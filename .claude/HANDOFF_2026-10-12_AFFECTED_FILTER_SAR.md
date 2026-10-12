# Handoff — "Affected Only" Filter + SAR `isPlanted` Spec (2026-10-12)

Context for continuing this work on another machine. Written at the end of
the session that produced branch `fabio/frontend/affected-only-sar-filter`.

---

## 1. What Fabio asked for

> "Create a filter where in spatial analysis, a button where it only shows
> affected insurances so that the specialist can check farms visually via SAR."

Clarified across the conversation into two separate things:

1. **The filter** (built, unverified) — a toolbar button in Spatial Analysis
   that narrows the Farm Records table *and* the map to the insured farms a
   typhoon actually hit.
2. **The SAR method** (specified only, not implemented) — what the Specialist
   then does with those polygons.

Fabio's own framing of the SAR step, verbatim:

> "The sar will Only check the affected polygons then is manually check by
> gis specialist and check the color."
> "the condition was just is planted."

So: SAR is requested **only for the filtered polygons** (bounds GEE/EEC
spend, per FR 2.4), the check is **planted vs. not planted** (FR 3.4), and
the verdict is **the Specialist's eye on the colour** — no automated
classification, no auto approve/reject.

## 2. Decisions already made (don't relitigate)

**"Affected" = inside the selected bulletin's TCWS signal >= 2 areas.**
Explicitly *not* "has a completed RiskAssessment". Reason: the planted-check
is validation *before* payout, so the filter must work the moment a bulletin
is parsed, before Calculate Assessment has run. The alternative
(assessment-based) was considered and rejected on that basis.

**Signal floor is 2**, matching the assessment engine's real eligibility rule
(`>= 2`, not `== 2`).

**It AND's with the other filters**, unlike `typhoon_id` which overrides
`active_only`. "Affected" and "active" are independent questions — a hit farm
can still hold usable cover.

**A toggle, not a second dropdown.** The bulletin is already selected in the
header and it's the same storm whose signals the map draws. Also keeps the
toolbar from carrying two near-identical typhoon dropdowns on a 1366x768
panel.

## 3. Known limitation, stated deliberately

Matching is **text-based, municipality-granular** — the same
`(province, municipality)` join `ExposureCalculatorService` already uses
against `tbl_tcb_signals`. PAGASA publishes TCWS areas as named municipality
lists, not radii, so **there is no wind-footprint polygon to intersect**.
Every farm in a listed municipality counts as affected.

This is fine for gating a visual check. It is **not** a geometric
intersection and must not be described as one in the manuscript.

## 4. State of the work

### Built, NOT verified
Backend (`farms.py`, `farms_cache.py`), frontend (`App.tsx`,
`SpatialAnalysisModule.tsx`, `GISLeafletMap.tsx`, `api.ts`,
`useFarmsData.ts`), tests, `API_CONTRACT.md`, `FUNCTION_CHANGES.md`.
Full per-file breakdown is in `.claude/FUNCTION_CHANGES.md` under the
2026-10-12 "Affected Only" entry — not duplicated here.

Only `python -m py_compile` was run. **The test suite has never executed.**

### Specified, not built
`docs/SAR_ISPLANTED_METHOD.md` — the `isPlanted` method, grounded in two
peer-reviewed Philippine papers Fabio supplied (Gutierrez et al. 2019 on the
rice planting window; Villano et al. 2019 on TP/DS separability, both
PhilGEOS x GeoAdvances 2019, IRRI/PhilRice). No GEE code exists anywhere in
the repo.

## 5. Blocker to resolve first on the new machine

`backend/.env` **does not exist**, so `JWT_SECRET_KEY` is unset and
`pytest` dies at import:

```
RuntimeError: JWT_SECRET_KEY is not set.
```

Fix (Fabio's own environment, per `.claude/ENV_GUIDE.md`):

```bash
cp backend/.env.example backend/.env
python -c "import secrets; print(secrets.token_urlsafe(48))"
# paste the output into JWT_SECRET_KEY= in backend/.env
```

Then the verification that was never run:

```bash
cd backend && python -m pytest tests/test_farms_api.py -v
cd frontend && npm run build        # TypeScript check on the 5 touched files
```

## 6. Pre-existing bug fixed in passing — verify this specifically

Commit `ef9265e` (the `typhoon_id` filter) broke **all 12** direct
`list_farms()` calls in `backend/tests/test_farms_api.py`.

Calling the endpoint as a plain function leaves an unpassed param bound to
the raw `fastapi.params.Query` marker object, which is **not `None`** — so
every one of those tests was silently taking the `typhoon_id is not None`
branch and asserting against filters it never expected. Confirmed:

```python
>>> from fastapi import Query
>>> Query(None) is None
False
```

`test_active_only_false_no_regression` already documents the correct
convention for `active_only`; the typhoon filter just didn't follow it. All
12 calls now pass `typhoon_id=None, affected_bulletin_id=None` explicitly.

**Expectation to confirm once the suite runs:** those tests were failing
before this branch. If they were somehow passing, the diagnosis above is
wrong and needs rechecking.

## 7. Next steps, in order

1. Create `backend/.env`, run the test suite, run the frontend build (§5).
2. Click through it: select a bulletin → toggle **Affected Only** → confirm
   the record count drops and the map polygons match the table.
3. Open the PR into `develop` per `.claude/GITHUB_WORKFLOW.md` Phase 4.
4. **Then** decide on the GEE/SAR layer — it is a separate build (service
   account auth, tile/map-id endpoint, EEC budgeting, calibration). The spec
   is written; nothing is implemented.

## 8. Loose ends

- Two research PDFs sit **untracked in the repo root**
  (`SEPARABILITY_OF_TRANSPLANTED_...pdf`,
  `THE_RICE_PLANTING_WINDOW_...pdf`). Not gitignored, not committed. Decide:
  move to `docs/`, or add to `.gitignore`.
- `webgis-pcic-dec4384c9f43.json` (the GEE service-account key) is in the
  repo root and **is** correctly gitignored via `webgis-pcic-*.json`. It is a
  live credential — keep it out of any commit.
- `TCB_PARSER_HANDOFF_2026-10-11.txt` is still untracked at the root from a
  previous session.
- Thresholds in `docs/SAR_ISPLANTED_METHOD.md` §6 are literature ballparks
  and **must be calibrated locally** before any of them ship.
