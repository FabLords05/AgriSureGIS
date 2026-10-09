# Handoff — Blank Farmer Names in Spatial Analysis (Ingest Idempotency Fix)

**Branch:** `fabio/backend/farmer-name-backfill`
**Commit:** `32c79bc`
**Date:** 2026-10-09
**Status:** Test suite **PASSED** (20/20 new tests). Steps 2–5 below are **not yet run** —
database and UI verification is what remains.

Read this on the machine that has the database and the data files. Step 1 is already
done and recorded; **start at step 2.**

> **You need the data file for step 4.** `USTP CAPSTONE-20261008T140025Z-1-001/` is
> gitignored (it holds real farmer and insurance records), so it does not arrive with
> this push. Ask Fabio for
> `INSURANCE RECORDS/PCIC10 GPX 11-05-2025 WITH EXISTING IC AFFECTED BY TY.csv`.

---

## 1. What this branch fixes, and why it broke

Farmer names rendered as **empty cells** in Spatial Analysis → Farm Records for every
farm from the newer PABS export, even though the upload reported success.

**The parser was never at fault** — replaying its name logic against the real CSV gives
0 blank names out of 1,114 rows. Three things had to line up:

1. **The CSV was uploaded once before commit `9547564`**, when `prepare_row_payload()`
   had no `FARMER NAME` / `CIC NO` / `AREA` aliases. `tbl_farmers_profile.last_name`
   and `first_name` are `NOT NULL`, so the `or ""` fallback stored **empty strings**
   instead of failing. Nothing errored. The same gap stored `policy_no = ''`,
   `area_size = 0`, `amount_cover = 0`.
2. **Ingestion was not idempotent.** `_ingest_row()` resolved an existing farmer/farm
   purely as a lookup and threw the parsed payload away, so re-uploading the corrected
   file matched those broken rows by `farmers_id` and changed nothing. **Re-uploading
   could never have fixed it** — that is the actual defect, now fixed by
   `_backfill_blank_fields()`.
3. **The API returned `""`, not `null`.** The frontend's `farmer_name ?? "—"` only
   substitutes on null/undefined, so a blank rendered as a visually empty cell instead
   of a dash — which is why this hid in plain sight rather than looking like a failure.

**Side effect of the double upload:** the duplicate guard is `(policy_no, farm_id)`. The
pre-fix rows hold `policy_no = ''` while the re-upload supplied the real `CIC NO`, so the
guard did not match and a **second `tbl_insurance_records` row was inserted per farm**,
each with its own `tbl_risk_assessment` seed. Step 3 cleans that up.

The repair rule is **blank-only**: fill a field that is empty, never overwrite a value
that is really there. Settled with Fabio 2026-10-09 — the newer export derives the farmer
from one combined `FARMER NAME` field, so letting it win outright would let a split value
clobber the legacy export's three discrete columns.

---

## 2. Step 1 — test suite (ALREADY DONE, for reference)

Run by Fabio 2026-10-09: **passed.** All 20 new tests green; the only failures were the
10 pre-existing `test_farms_api.py` ones (same `_ChainableQuery`/`.join` harness error
that fails on `develop` too).

If you want to re-run it on your machine:

```bash
cd backend && JWT_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))") python -m pytest tests/ -v
```

Two things that will bite you here:

- **`python -m pytest`, not bare `pytest`.** There is no `pytest.ini` or `conftest.py`,
  so the console script won't put cwd on `sys.path` and `import app` fails.
- **The inline `JWT_SECRET_KEY` is not optional** unless you already have a
  `backend/.env`. `app/core/security.py:28` hard-fails without it, which
  collect-errors every test module that imports an API router. `DATABASE_URL` has a
  fallback (`app/core/database.py:15`) and the suite is fully mocked, so **no database
  is needed for this step.**

---

## 3. Step 2 — confirm the damage counts (READ-ONLY)

Do this before deleting anything. The migration file in step 3 runs its own diagnostic,
but it then deletes in the same pass — so look at the numbers here first.

```bash
psql -U agrisure_admin -d agrisure_db -c "
SELECT 'blank policy_no (TO DELETE)' AS check_name, COUNT(*) AS n FROM tbl_insurance_records WHERE policy_no = ''
UNION ALL SELECT 'real policy_no (KEEP)', COUNT(*) FROM tbl_insurance_records WHERE policy_no <> ''
UNION ALL SELECT 'nameless farmers', COUNT(*) FROM tbl_farmers_profile WHERE COALESCE(TRIM(last_name),'')='' AND COALESCE(TRIM(first_name),'')=''
UNION ALL SELECT 'farms with area_size 0', COUNT(*) FROM tbl_farms WHERE area_size IS NULL OR area_size = 0;"
```

Expected on a database that received both uploads:

| check_name | expected |
|---|---|
| `blank policy_no (TO DELETE)` | ~1,100 |
| `real policy_no (KEEP)` | ~1,100 |
| `nameless farmers` | 952 |
| `farms with area_size 0` | ~1,100 |

### Decision gate — read this before continuing

| What you see | What it means | What to do |
|---|---|---|
| Roughly the table above | Both uploads happened. Diagnosis confirmed. | Continue to step 3. |
| **`real policy_no (KEEP)` = 0** | The corrected CSV was never re-uploaded. The blank-policy rows are your **only** copy of this data. | **Skip step 3 entirely** — deleting would throw away all 1,100 records, not a duplicate set. Go straight to step 4. |
| `blank policy_no` = 0 | No pre-fix upload on this database, so no junk to remove. | **Skip step 3.** If `nameless farmers` is also 0, there is nothing to fix here at all. |
| `nameless farmers` = 0 but names still blank in the UI | Something other than this bug. | Stop and report — the diagnosis does not fit your database. |

---

## 4. Step 3 — remove the shadow insurance records

Only if step 2's gate said to.

```bash
psql -U agrisure_admin -d agrisure_db -f backend/migrations/2026-10-09_prefix_ingest_cleanup.sql
```

The file is diagnostic-first: it prints every affected count, deletes inside a single
`BEGIN`/`COMMIT`, then re-prints to verify. It is safe to re-run — a second pass reports
0 and deletes nothing.

What it deletes: `tbl_insurance_records WHERE policy_no = ''`. One statement is enough —
`tbl_risk_assessment` and `tbl_insurance_usage` both reference that FK
`ON DELETE CASCADE`, so the orphan crop-stage seeds go with them.

What it deliberately does **not** delete: the farmers and the farms. Their blank names and
zero areas are repaired in place by step 4. Deleting them would cascade into the *good*
insurance records and discard the `location_geom` already loaded from the `.gpkg`.

**Why `policy_no = ''` is a safe fingerprint:** nothing else writes a blank policy number.
`seed_database.py` inserts real values, `seed_active_insurance.py` prefixes `POL-SEED-`,
and `app/api/upload.py` only produces `''` when the source CSV had no recognizable
policy-number column at all — i.e. exactly the pre-fix run.

Expected output: `insurance records with blank policy_no (expect 0)` → **0**, and
`orphaned crop-stage seeds (expect 0)` → **0**.

---

## 5. Step 4 — re-upload the CSV

**This is the step that actually repairs the names.** The code fix only takes effect when
a row is ingested again.

You need the backend running, which needs a real `backend/.env` (the throwaway secret from
step 1 won't do). Per `.claude/ENV_GUIDE.md`:

```bash
cd backend && cp .env.example .env
# then edit .env: set DATABASE_URL, and
#   JWT_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
```

Then start the backend and frontend as usual (see `.claude/LOCAL_SERVER_SETUP.md`) and
upload `PCIC10 GPX 11-05-2025 WITH EXISTING IC AFFECTED BY TY.csv` through the UI.

Expected result: **~1,100 inserted / ~14 skipped / 0 failed.**

- If you ran step 3, the insurance records are re-created cleanly.
- If you skipped step 3 because the records already existed with a real `policy_no`,
  expect **~1,100 skipped / 0 inserted** instead — that is correct. The duplicate guard
  matches, so no row inserts, but **the names and areas are still backfilled**: the
  backfill runs before the duplicate check, and savepoints commit on `skipped` too
  (`app/api/upload.py:695`).

Watch the backend log for the new lines confirming the repair is firing:

```
Backfilled last_name, first_name, middle_name on existing farmer farmers_id=29136
Backfilled area_size=1 on existing farm csv_farm_reference=365827
```

**Do not re-upload the `.gpkg`** for this fix. It only ever updates `location_geom` and
never creates or renames a farmer, so it has no bearing on the names.

---

## 6. Step 5 — verify

### In SQL

```bash
psql -U agrisure_admin -d agrisure_db -c "
SELECT 'nameless farmers (expect 0)' AS check_name, COUNT(*) AS n FROM tbl_farmers_profile WHERE COALESCE(TRIM(last_name),'')='' AND COALESCE(TRIM(first_name),'')=''
UNION ALL SELECT 'farms area_size 0 (expect ~0)', COUNT(*) FROM tbl_farms WHERE area_size IS NULL OR area_size = 0
UNION ALL SELECT 'blank policy_no (expect 0)', COUNT(*) FROM tbl_insurance_records WHERE policy_no = '';"
```

Spot-check a known farmer — row 1 of the CSV is `ABANES, ALFONSO F.`, `FARMERSID` 29136:

```bash
psql -U agrisure_admin -d agrisure_db -c \
  "SELECT farmers_id, last_name, first_name, middle_name FROM tbl_farmers_profile WHERE farmers_id = '29136';"
```

Expect `29136 | ABANES | ALFONSO | F`.

### In the UI

1. Spatial Analysis → Farm Records.
2. **Turn "Active Insurance Only" OFF and search a municipality — e.g. `MAINIT`.**
   This matters: this CSV's policies expired `02/28/2026`, so with the toggle on
   **these farms do not appear at all** and you will think the fix failed. The toggle
   also requires a municipality or farmer scope before it can be turned off.
3. The **Farmer** column should be populated. A farmer genuinely missing a name now
   shows `—` rather than an empty cell.
4. Type `ABANES` into the farmer search box — a suggestion should appear. A farmer with
   no name on file is labelled `(unnamed farmer #<id>)` so the gap stays visible and
   still selectable.
5. Click a farm with a boundary on the map — the popup should show the name instead of
   "Unknown farmer".

---

## 7. Gotchas, ranked by how likely they are to waste your time

1. **"Active Insurance Only" hides every farm from this CSV.** Expired `02/28/2026`.
   See step 5.2. This is the single most likely reason to wrongly conclude the fix
   didn't work.
2. **`backend/.env` may not exist.** `JWT_SECRET_KEY` is required with no fallback and
   the backend refuses to start without it.
3. **`python -m pytest`, not `pytest`.** Already documented at `FUNCTION_CHANGES.md:859`.
4. **The frontend needs a rebuild** to pick up the `??` → `||` change in
   `SpatialAnalysisModule.tsx` / `GISLeafletMap.tsx`. A running dev server hot-reloads;
   a built bundle does not.
5. **10 `test_farms_api.py` tests fail on this branch and on `develop`.** Pre-existing,
   not caused by this work — `list_farms()` is called without `municipality`/`farmer_id`,
   so FastAPI's truthy `Query(None)` default reaches the `.join()` branch that
   `_ChainableQuery` doesn't implement. See §8.

---

## 8. Known gap worth closing separately

Because those 10 `test_farms_api.py` tests never execute, **`list_farms()`'s response
shape — including this branch's `farmer_name` change — has no automated coverage.** The
cause is a one-line harness gap (give `_ChainableQuery` a `.join`, or have the tests pass
explicit `municipality=None, farmer_id=None`). Small, self-contained, and would make the
test file that covers the changed function actually run. Deliberately left out of this
branch to keep the diff on the reported bug.

---

## 9. Not changed here — please don't re-litigate

| Decision | Why |
|---|---|
| `nullable=False` kept on `last_name`/`first_name` | Making them nullable would surface this bug class earlier, but it is a schema change touching every consumer. Its own task. |
| Backfill is blank-only, not "CSV always wins" | Fabio, 2026-10-09. See §1. |
| `panicle initiation/booting` → `crop_stage_no = NULL` | Unchanged from `HANDOFF_2026-10-09_CSV_CROP_STAGE.md` §4. Waiting on PCIC for a days-after-transplanting threshold, not on code. |
| The payout export's `'ABANES, ALFONSO. F.'` shape | Trailing period after the first name predates this work. The column format is PCIC-facing, so it is preserved exactly. |
| `/gpkg` untouched | Only ever updates `location_geom`; never creates or renames a farmer. |

---

## 10. Rollback

The code change is additive and safe to revert (`git revert 32c79bc`) — reverting
restores the old non-idempotent behaviour but does not undo a repair already written to
the database.

Step 3's delete is **not** reversible. If you want a safety net, take a dump first:

```bash
pg_dump -U agrisure_admin -d agrisure_db -t tbl_insurance_records -t tbl_risk_assessment \
  -f pre_cleanup_$(date +%F).dump
```

`*.dump` is already gitignored.
