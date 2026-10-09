# Handoff — Second PABS/GPX CSV Layout + Crop-Stage Translation

**Branch:** `fabio/backend/csv-crop-stage-mapping`
**Date:** 2026-10-09
**Status:** ⚠️ **CODE COMPLETE, COMPLETELY UNVERIFIED — nothing has been executed.**

Written for whoever picks this up on the backend machine. Everything below was
authored on Fabio's laptop, which has no working Python environment for this repo
(no `.venv` existed; one was created but the suite was never run) and no database
to point at. Treat every claim here as "intended behaviour", not "observed
behaviour".

> **You will not get the data files from this push.**
> `USTP CAPSTONE-20261008T140025Z-1-001/` is gitignored (it holds real farmer and
> insurance records). Steps 4–5 below need those files copied across separately —
> ask Fabio for the `INSURANCE RECORDS/*.csv` and `GPX/*.gpkg`. **Step 1, the test
> suite, needs none of them** and is the part that most needs running.

---

## 1. What this branch does

The client's newer export —
`USTP CAPSTONE/INSURANCE RECORDS/PCIC10 GPX 11-05-2025 WITH EXISTING IC AFFECTED BY TY.csv`
(42 columns, 1,114 rows) — could not be ingested. Only 9 of its headers match the
legacy export after normalization. It calls the policy number `CIC NO`, AreaInsured
`AREA`, carries the farmer as one combined `FARMER NAME` field, and gives the crop
stage as free text (`Dough Stage`) where the legacy file gives an integer `Stage No.`.

Mapping that stage column surfaced **a live bug in the existing pipeline**, which this
branch also fixes. `Stage No.` is PCIC's own 0–9 agronomic code, but
`prepare_row_payload()` wrote it straight into `tbl_risk_assessment.crop_stage_no`,
which `AssessmentService` reads as the Table 11 scale (1=Booting, 2=Flowering,
3=Maturity). Two different scales. On the legacy file that meant **41 of 100 rows
passed the eligibility gate with every one mis-staged**, while the genuinely eligible
rows — code 4 (Booting) and code 7 (Dough) — fell outside `{1,2,3}` and were silently
dropped.

Both CSV layouts now go through one pipeline. `/gpkg` is untouched.

---

## 2. Run this, in order

The environment on Fabio's machine was created but never exercised, so **step 0 may
need redoing** on yours.

```bash
# 0. Environment (skip if you already have a working .venv)
cd backend && python3 -m venv .venv && source .venv/bin/activate \
  && pip install --upgrade pip && pip install -r requirements.txt

# 1. Test suite — START HERE. Fully mocked, needs no database.
cd backend && python -m pytest tests/ -v
```

`python -m pytest`, **not** bare `pytest`. There is no `pytest.ini` or `conftest.py`,
so the console script won't put cwd on `sys.path` and `import app` fails. This is
already documented in `FUNCTION_CHANGES.md:859`.

Only once the suite is green:

```bash
# 2. Schema. DESTRUCTIVE — init_schema.sql DROPs every table.
psql -U agrisure_admin -d agrisure_db -f backend/init_schema.sql

# 3. Confirm the new lookup seeded (expect 17 rows)
psql -U agrisure_admin -d agrisure_db -c \
  "SELECT source_code, source_label, crop_stage_no, stage_group FROM tbl_crop_stage_mapping ORDER BY source_code NULLS LAST, source_label;"

# 4. Start the backend, upload the NEW csv through the UI, then:
psql -U agrisure_admin -d agrisure_db -c \
  "SELECT crop_stage, crop_stage_no, stage_group, COUNT(*) FROM tbl_risk_assessment GROUP BY 1,2,3 ORDER BY 4 DESC;"

# 5. Upload the .gpkg (USTP CAPSTONE/GPX/PCICX GPX_...11-05-2025.gpkg)
#    Expect 1,100 farms updated, 13 duplicates skipped, 0 unmatched.
```

**If you are NOT resetting your database**, use the migration instead of step 2 — it
is idempotent and additive:

```bash
psql -U agrisure_admin -d agrisure_db -f backend/migrations/2026-10-09_crop_stage_mapping.sql
```

### Expected ingestion result for the new CSV

| | |
|---|---|
| rows inserted | ~1,100 (1,114 rows, 14 duplicate `(CIC NO, FARMID)` pairs) |
| rows failed | **0** |
| `crop_stage_no IS NULL` | 312 rows — 176 `Panicle Initiation/Booting` + 122 `Harvested` + 14 `Vegetative/Tillering` |

Those 312 ingest successfully and are simply never assessed. That is correct, not a
bug — see §4.

---

## 3. Where it is most likely to break

Ranked by my own estimate of risk. None of this has run.

1. **`backend/tests/test_upload_csv_ingestion.py`** — highest risk. All 14 of its
   tests were *already dead on `develop`*: they call `upload_csv(file=..., db=mock_db)`
   but `upload_csv()` has taken only `file` since the row loop moved into
   `_run_csv_ingestion()` with its own `SessionLocal`. Every one was raising
   `TypeError`. I rewrote the harness (`_dataframe()` + `_run_ingestion()`, patching
   `SessionLocal`, `upload_jobs`, `invalidate_farms_cache`,
   `refresh_farm_latest_insurance_view`). **This rewrite has never executed.** If
   something here is wrong it is pre-existing breakage plus my fix, not a regression
   in the feature itself.
2. **`backend/tests/test_crop_stage_resolver.py`** (new) — uses
   `assertNoLogs`, which needs Python ≥ 3.10. The codebase already uses `X | None`
   syntax throughout so 3.10+ is implied, but it has not been confirmed.
3. **The fake-DB filter shim.** `CropStageResolver.load()` issues
   `.filter(CropStageMapping.is_active.is_(True))`. `_extract_filter()` in the test
   harness was written for `==`, `func.upper(...) ==` and `.in_(...)`. I believe `is_`
   falls through correctly (operator name `is_`, not `in_op`, so it compares by
   equality against `True`, and the seeded fixtures set `is_active=True`) — but this
   is reasoning, not a passing test.
4. **`toast.warning` in `frontend/src/app/App.tsx`.** Verified present in
   `sonner@2.0.3`'s type definitions. The frontend was never built or run.

---

## 4. Decisions already made — please don't re-litigate these

Settled with Fabio on 2026-10-08/09, sourced from
`USTP CAPSTONE/RECSAP-From-IRR.pptx` (Tables 1, 7a/7b, 9, 10, 11) and the manuscript's
worked example (p. 53). The slides are table screenshots; open the pptx to see them.

| Decision | Source |
|---|---|
| Milking Stage → `crop_stage_no` 2 (Flowering row) | PCIC pairs `FS/MS` as one unit in Tables 9 and 10 |
| Booting's group: Late Vegetative → **Reproductive** | PABS export labels it `4 - Booting Stg. (REPRODUCTIVE)`; the resulting 5-group assignment leaves none unused. The old value was flagged in `init_schema.sql` as inferred and unconfirmed |
| `crop_stage_no` and `stage_group` resolved **independently** | Milking and Flowering share `crop_stage_no` 2 but sit in different Table 1 groups — a derived mapping cannot express it |
| `Panicle Initiation/Booting` left **unmapped** | Table 11 Note 1 excludes PI from wind damage but BS is eligible, and **no PCIC document gives a days-after-transplanting threshold to split them** |

PCIC's full 9-stage sequence, from the Table 7a/7b column headers:
`MnTl | MxTl | PI | BS | FS | MS | SD | HD | YR` (with `S/T` preceding them as code 0
in the legacy export's numbering).

Resulting group assignment — note it leaves no group unused, which is the main reason
to trust it:

```
Early Vegetative   = S/T, MnTl
Late Vegetative    = MxTl
Reproductive       = PI, BS, FS
Late Reproductive  = MS
Maturity           = SD, HD, YR
```

### The one open item

`panicle initiation/booting` is **deliberately** left with `crop_stage_no = NULL`.
176 rows (15.8%) ingest and never pay out. **This is waiting on PCIC**, not on code.
When they supply a days-per-stage table, enabling it is one statement:

```sql
UPDATE tbl_crop_stage_mapping
   SET crop_stage_no = 1, stage_group = 'Reproductive'
 WHERE source_label = 'panicle initiation/booting';
```

The row's `notes` column says this too. Do not hard-code a day threshold without
PCIC confirming it — day 66 was floated (there is a natural gap in the data there)
and explicitly rejected as a guess.

---

## 5. Files changed

**New**
- `backend/app/services/crop_stage_resolver.py` — the translation layer
- `backend/migrations/2026-10-09_crop_stage_mapping.sql` — for DBs that aren't reset
- `backend/tests/test_crop_stage_resolver.py`

**Modified**
- `backend/app/api/upload.py` — header aliases, `FARMER NAME` split, stage resolution
  moved into `_ingest_row()`; `prepare_row_payload()` stays DB-free
- `backend/app/core/indemnity_calc.py` — `stage_group` parameter;
  `CROP_STAGE_TO_INDEMNITY_GROUP` demoted to fallback, Booting entry changed
- `backend/app/services/assessment_service.py` — threads `stage_group` through
- `backend/app/services/gpx_farmer_matcher.py` — `parse_farmer_name()` keeps compound
  first names (`'ACERO, ANNA MARIE S.'` was losing `MARIE`; 131 of 1,114 rows affected)
- `backend/app/models/models.py`, `backend/init_schema.sql` — `tbl_crop_stage_mapping`,
  `tbl_risk_assessment.stage_group`
- `backend/tests/test_csv_upload.py`, `test_upload_csv_ingestion.py`,
  `test_assessment_service.py`, `test_gpx_farmer_matcher.py`
- `frontend/src/app/App.tsx` — CSV per-row failures now reach the existing
  `UploadFailuresModal` (they were being dropped silently)
- `docs/RECSAP_MATRIX_SCHEMA.md`, `.claude/FUNCTION_CHANGES.md`

---

## 6. Background worth knowing

- **The `.gpkg` is a superset of the new CSV.** It carries all 42 CSV columns *plus*
  polygon geometry, and reconciles 1:1 with the CSV on `(CIC NO, FARMID)` — 1,100
  distinct keys each, zero orphans either direction. `/gpkg` reads only 6 fields
  (`fid`, `file_name`, `FARMERSID`, `FARMID`, `FARMER NAME`, `geom`) and ignores the
  other 39 attribute columns. **Order matters: CSV first, then GPKG** — `/gpkg` only
  updates `location_geom` on farms that already exist and creates nothing.
- **Columns in the new CSV that look useful but aren't:** `NORTH`/`EAST`/`WEST`/`SOUTH`
  are adjacent landowners' *names*, not coordinates. `PHASE` is `105` on all 1,114 rows
  and `PERIOD OF EXPOSURE, HRS` is `SN3_12` on all of them — both constant, no
  information.
- **`AMOUNT OF COVER` is the area-inclusive total** in both layouts (verified: 1,091 of
  1,114 new rows sit at a flat ₱20,000/ha), which matches `calculate_final_payout()`'s
  deliberately area-free formula `I = (AC / 1000) × IF`.
- `_parse_decimal` already strips thousands separators, so `"20,000.00"` parses fine
  and `"-"` (the new file's null marker) yields `None`. No change was needed there.
