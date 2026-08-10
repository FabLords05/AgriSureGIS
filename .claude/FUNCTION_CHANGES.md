# AgriSureGIS — Function & Model Changelog

This file tracks granular, function-level modifications made in the codebase, documenting what was changed and why for each file update.

---

## [2026-07-17] - Sprint 1 Completion

### 1. File: `backend/app/models/models.py`
* **Changes to Classes/Structures:**
  * Updated **`AdminBoundary`**: Added `psgc_code` column (`String(10)`, unique, non-nullable) to support official administrative referencing.
  * Added **`SystemUser`**: Mapped `tbl_system_users` for account authentication and user details.
  * Added **`Typhoon`**: Mapped `tbl_typhoons` to model storm events.
  * Added **`TropicalCycloneBulletin`**: Mapped `tbl_tropical_cyclone_bulletins` including the spatial `center_geom` (`Point` geometry) to represent bulletin updates.
  * Added **`TcbSignal`**: Mapped `tbl_tcb_signals` to model local storm warning assignments.
  * Added **`AreaExposureSummary`**: Mapped `tbl_area_exposure_summary` to capture duration and maximum wind signals per boundary.

### 2. File: `backend/seed_database.py`
* **Changes to Functions:**
  * Refactored **`run_setup()`**:
    - Removed the automatic schema drop/recreation DDL queries to avoid overwriting the `init_schema.sql` template.
    - Added boundary uniqueness pre-checks to prevent PSGC duplicates.
    - Implemented unique `psgc_code` generation (`PH10XXXX`) for admin boundaries seeded from the CSV.
    - Updated `tbl_insurance_records` and `tbl_risk_assessment` insertion queries to align with the relational constraints (e.g. mapping `Stage No.` to `crop_stage_no` as an integer and adding `final_indemnity_payment` values).

### 3. File: `backend/pabs_results.csv`
* **Changes to Data Structure:**
  * Populated the file with sample agricultural policies, boundaries (Claveria, Misamis Oriental and Talakag, Bukidnon), and crop stages to support database seeding verification.

---

## [2026-07-18] - Sprint 2 Implementation

### 1. File: `backend/app/services/bulletin_parser.py`
* **Changes to Functions (Class: `BulletinParserService`):**
  * Added **`fetch_active_bulletin_links()`**: Asynchronously scrapes the PAGASA active bulletins index page using BeautifulSoup to detect and return PDF links.
  * Added **`download_bulletin_pdf()`**: Asynchronously downloads bulletin PDFs from the PAGASA portal, saving them to a local temporary archive.
  * Added **`parse_bulletin_text()`**: Utilizes `pdfplumber` to extract text from a downloaded PDF and parses it using regular expressions to extract the typhoon name, issue dates, wind/gust speeds, eye coordinates, and segment signal wind hazard text blocks.
  * Added **`save_bulletin_to_db()`**: Normalized and saved parsed bulletin data into `tbl_typhoons`, `tbl_tropical_cyclone_bulletins` (storing spatial `center_geom`), and parsed Signal levels/municipalities into `tbl_tcb_signals`.

### 2. File: `backend/app/api/bulletins.py`
* **Changes to API Routes:**
  * Added **`list_bulletins()`** (`GET /api/bulletins/`): Lists all parsed bulletins alongside typhoon names and metadata.
  * Added **`trigger_pagasa_scrape()`** (`POST /api/bulletins/parse`): Runs the scraper/parser workflow on current PAGASA active PDF links.
  * Added **`upload_bulletin_pdf()`** (`POST /api/bulletins/upload`): Serves as a fallback route allowing manual PDF upload and parsing when the online portal is unreachable.
  * Added **`get_bulletin_signals()`** (`GET /api/bulletins/{tcb_id}/signals`): Returns signal assignments and affected municipalities.

### 3. File: `backend/app/main.py`
* **Changes to Configurations:**
  * Registered the new `bulletins_router` router under the prefix `/api`.

### 4. File: `backend/tests/test_bulletin_parser.py`
* **Changes to Tests (Class: `BulletinParserTests`):**
  * Added **`test_parse_bulletin_text_extracts_correct_metadata()`**: Uses unit test mock patches to assert that the parser correctly extracts metadata and signal areas from mock PDF bulletin layouts.

---

## [2026-07-21] - Recsap Matrix Persistence & Sprint 1 Audit

**Branch:** `fabio/backend/recsap-matrix-table` (committed locally, not pushed, no PR open yet).

### Sprint 1 vs. Manuscript Audit Findings
Checked Sprint 1's "[Done]" items in `.claude/DEVELOPMENT_PLAN.md` against `.claude/Revised AgriSureGIS Manuscript.pdf` (database dictionary, pp.36-47; functional requirements, p.23-24):
* `tbl_recsap_matrix` was specified in the manuscript's ERD but missing from the actual schema — the yield-loss/indemnity lookup existed only as hardcoded Python dicts. Fixed by this entry (see below).
* Table naming mismatch: manuscript specifies `tbl_insurance_record` (singular); actual schema has `tbl_insurance_records` (plural). Not changed — flagging for awareness since the ERD diagram may still show the singular form.
* `/api/health` is marked "[Done]" in the dev plan but does not exist anywhere in `backend/app/`. Not built as part of this entry.
* The frontend dashboard's four modules (Home/Spatial/Assessment/Settings) structurally match the manuscript's spec, but have zero `fetch`/`axios` calls anywhere — a disconnected static mockup, despite being marked "[Done]".

### 1. File: `backend/init_schema.sql`
* **Changes to Schema:**
  * Added **`tbl_recsap_matrix`**: `matrix_id` (PK), `crop_stage_no`, `wind_signal_tcws`, `exposure_hours`, `estimated_yield_loss`, `indemnity_factor`, `is_active` — per the manuscript's dictionary, with an added `exposure_hours` column since the manuscript's 2-key schema (`crop_stage_no` + `wind_signal_tcws`) doesn't account for the exposure-duration dimension the payout formula actually needs (matches the manuscript's own flowchart, p.48, which brackets exposure into 6/12/24-hour tiers).
  * Wired `tbl_risk_assessment.matrix_id` to a real `REFERENCES tbl_recsap_matrix(matrix_id) ON DELETE SET NULL` (previously a bare, unconstrained `INT`).

### 2. File: `backend/app/models/models.py`
* **Changes to Classes/Structures:**
  * Added **`RecsapMatrix`**: Mapped `tbl_recsap_matrix`.
  * Updated **`RiskAssessment`**: `matrix_id` now a `ForeignKey("tbl_recsap_matrix.matrix_id", ondelete="SET NULL")`, with a new `matrix` relationship.

### 3. File: `backend/app/core/indemnity_calc.py`
* **Changes to Functions (Class: `ParametricAssessment`):**
  * Refactored to take a SQLAlchemy `Session` and query `tbl_recsap_matrix` directly, replacing the old hardcoded `indemnity_factors` dict and the two-step `determine_yield_loss()` / `get_indemnity_factor()` lookup.
  * Added **`get_matrix_rule()`**: buckets raw exposure hours down to the matrix's discrete brackets (6/12/24), then queries by `(crop_stage_no, wind_signal_tcws, exposure_hours)` for a single matching active row.
  * **`calculate_final_payout()`** signature changed from free-text growth-stage strings (`matrix_stage`, `broad_stage` — e.g. `BOOTING`, `EARLY VEGETATIVE`) to `crop_stage_no: int`, matching what real ingested CSV data already uses (`Stage No.` column in `pabs_results.csv`) and the manuscript's schema. No other code called the old methods (`ParametricAssessment` had zero production call sites — only its own interactive `__main__` CLI test block), so this was a clean swap.

### Status / Next Steps
* `tbl_recsap_matrix` is schema-only — **no seed data yet**. Blocked on Fabio providing the real PCIC "Table 11" damage-matrix values (Table 11: *Damage Matrix for Parametric Insurance, Typhoon-Induced Strong Winds (Rice)*, referenced in the manuscript's flowchart, p.48, but not reproduced in the dictionary).
* Branch is **not pushed** and has **no PR open** — needs review before merging into `main`.
* Bug found in passing, **not fixed**: `backend/app/api/upload.py` passes `adjuster_calculation=...` into `models.RiskAssessment(...)`, but that column doesn't exist on the model — `/api/upload/csv` will raise a `TypeError` on any real upload.

---

## [2026-07-21] - Workflow Documentation Update

### 1. File: `.claude/CLAUDE.md`
* **Changes to Documentation:**
  * Added a **Changelog Requirement** section: before handing off any commit for Fabio to push, this file (`FUNCTION_CHANGES.md`) must be updated in the same commit with an entry documenting what changed and why, following the existing dated/sprint-grouped format. Applies to every commit destined for push, not just sprint-completion milestones.

### 2. File: `.claude/TEAM.md`
* **Changes to Documentation:**
  * Added a **Tooling** bullet under Fabio Joseph Tugonon's entry noting his use of Claude Code as an AI pair-programming assistant for implementation, documentation, and workflow tasks in this repository.

---

## [2026-07-21] - Branch Model: `develop` as Integration Branch

**Branch:** `develop` (new, cut from `main` at `3dfc695`; committed locally, not pushed yet).

### 1. File: `.claude/GITHUB_WORKFLOW.md`
* **Process/doc change, no code touched.** Restructured the branch model from "feature branches → PR directly into `main`" to a three-tier model, per Fabio's direction that `main` should stay untouched until final, release-ready code:
  * `main`: now frozen — only receives merges from `develop`, and only at a deliberate release point.
  * `develop` (new): integration branch. All feature branches now branch off `develop` (not `main`) and PR back into `develop` (Phase 1, Phase 2's rebase step, and Phase 4 all updated accordingly).
  * Added **Phase 7 — Release to `main`**: describes the `develop` → `main` PR at a release milestone, same review bar as Phase 5.
  * Added a **Setup Note** flagging that GitHub branch protection for `main`/`develop` (blocking direct pushes, requiring PR review) must be configured by Fabio in the GitHub repo settings — not achievable from the local git CLI.
* Existing in-flight branch `cristian/backend/sprint3-gpx-exposure` (already pushed, based on `main`) retargets to merge into `develop` going forward per Fabio's decision, rather than being treated as an exception into `main`.

### 2. File: `.claude/TEAM_RESPONSIBILITIES.md`
* Updated the "Review and Merging Workflow" bullet: PR approval requirement now targets merging into `develop`, with a note that `main` only receives merges from `develop` at a release point.

### Status / Next Steps
* `develop` branch is **not pushed** — needs Fabio to push it himself (no stored GitHub credentials in this environment) before the team can start branching off it or retargeting open PRs.
* GitHub branch protection rules for `main` and `develop` still need to be configured by Fabio via the GitHub web UI — this doc change only updates the *documented* workflow, it does not enforce it on GitHub.

---

## [2026-07-21] - Sprint 3 Backend: GPX Parser & Exposure Calculation (+ Sprint 2 Fixes)

**Branch:** `cristian/backend/sprint3-gpx-exposure` (committed locally, not pushed, no PR open yet).

### Sprint 2 Fixes
### 1. File: `backend/app/services/bulletin_parser.py`
* **Bug fix:** Added the missing `from sqlalchemy import func` import. `save_bulletin_to_db()` called `func.lower(...)` without it, so every DB-save attempt raised `NameError` — this code path had never actually run successfully since Sprint 2 was marked "Done."
* **Changes to Functions:**
  * `parse_bulletin_text()`: added `issued_at` extraction (regex for PAGASA's typical "Issued at HH:MM AM/PM, DD Month YYYY" phrasing), returned in the parsed-data dict. Falls back to `None` if not found — no bulletin sample exists in the repo/tests to validate the exact real-world phrasing yet, so this needs validation against a real PAGASA bulletin before being fully trusted.
  * `save_bulletin_to_db()`: now uses the parsed `issued_at` when available, falling back to `datetime.now(timezone.utc)` only if parsing failed. `expires_at` is unchanged (still a placeholder — PAGASA bulletins don't reliably state their own expiry).
* **Audit finding, not changed:** the `island_group = 2` hardcode is not a bug — the platform is scoped to PCIC Region X (Northern Mindanao) only (`PROJECT_CONTEXT.md`), so every `AdminBoundary` row in this dataset is Mindanao by definition. Left as-is rather than inventing an unfounded Luzon/Visayas mapping.

### 2. File: `backend/tests/test_bulletin_parser.py`
* **Changes to Tests:**
  * Added `test_parse_bulletin_text_extracts_issued_at()` and `test_parse_bulletin_text_issued_at_missing_defaults_to_none()`.
  * Added new class `BulletinParserSaveToDbTests` with `test_save_bulletin_to_db_creates_bulletin_and_signals()` — a regression test for the `func` import bug (mocked `Session`, dispatches `db.query(Model)` per model class). Previously only `parse_bulletin_text()` was tested; `save_bulletin_to_db()` had zero coverage.

### Sprint 3 Backend: GPX Boundary Parser
### 3. File: `backend/app/services/gpx_parser.py` (new)
* Added **`GpxParserService.parse_gpx_to_polygon()`**: parses an uploaded `.gpx` file with `gpxpy`, builds a Shapely `Polygon` from track points (falls back to route points if no tracks), auto-closes the ring, and returns a `WKTElement` (`MULTIPOLYGON`, SRID 4326) matching the geometry pattern `bulletin_parser.py` already uses for `center_geom`.

### 4. File: `backend/app/api/upload.py`
* **Changes to API Routes:**
  * Added **`upload_gpx()`** (`POST /api/upload/gpx`): accepts a multipart GPX file + `farmer_id` + `farm_id` per `API_CONTRACT.md` §2, parses it via `GpxParserService`, and updates that `Farm.location_geom`.

### 5. File: `backend/tests/test_gpx_parser.py` (new)
* Added `GpxParserServiceTests` covering: a valid closed-ring track, route-only fallback, and a `ValueError` for files with fewer than 3 points.

### Sprint 3 Backend: Exposure-Hours Calculation
### 6. File: `backend/app/services/exposure_calculator.py` (new)
* Added **`ExposureCalculatorService.compute_for_typhoon()`**: walks a typhoon's `TropicalCycloneBulletin` rows in `issued_at` order, matches each `TcbSignal.area_name` against `AdminBoundary.municipality` (same text-matching approach Sprint 2 already uses — no schema change), and upserts per-boundary `start_time`/`end_time`/`max_signal_level`/`total_exposure_hours`/`is_eligible_6hr` (≥6h threshold) into `tbl_area_exposure_summary`.
  * Deliberately does **not** model a circular "signal radius" geometry — PAGASA publishes TCWS signal areas as named municipality/province lists per bulletin, not a radius around the storm center, so exposure is a time-series aggregation over named areas rather than a spatial buffer intersection. Confirmed against `docs/ERD.drawio.png` (`tbl_area_exposure_summary` has `start_time`/`end_time`/`total_exposure_hours`, no radius/geometry column).

### 7. File: `backend/app/api/bulletins.py`
* **Changes to API Routes:**
  * Added **`compute_exposure()`** (`POST /api/bulletins/{tcb_id}/compute-exposure`). This is **not** the documented `POST /api/assessments/calculate` contract — that endpoint bundles in yield-loss/payout output which depends on Sprint 4's `RecsapMatrix`/`RiskAssessment` work, not built yet. Sprint 4 can add the real `/api/assessments/calculate` on top of this later.

### 8. File: `backend/tests/test_exposure_calculator.py` (new)
* Added `ExposureCalculatorServiceTests` covering: multi-bulletin aggregation (exposure hours + max signal level across two bulletins), a single-bulletin case (0 hours, not eligible), and no-bulletins (empty result).

### 9. File: `backend/requirements.txt`
* Added `gpxpy==1.6.2`, `geopandas==1.1.4`, `shapely==2.1.2`, `pyproj==3.7.2` for this sprint's GPX/exposure work.
* Also added `beautifulsoup4==4.15.0` and `pdfplumber==0.11.10` — these were already imported by Sprint 2's `bulletin_parser.py` but were missing from `requirements.txt` entirely (a pre-existing gap; `backend/venv` had nothing installed beyond `pip` itself when this branch started). Also added `pytest==9.1.1` to actually run the test suite (existing tests use stdlib `unittest`, no runner was previously pinned).

### Status / Next Steps
* **Flagging for Fabio, not built:** `docs/ERD.drawio.png` shows `tbl_tcb_signals` should have a `boundary_id` FK to `tbl_admin_boundaries`, and `tbl_admin_boundaries` should have a `geom` column. Neither exists in `models.py`/`init_schema.sql` today — Sprint 2 stores `area_name` as free text instead, and this branch's exposure calculator matches on that same text field. Adding the FK/geom columns would make the matching robust and align the schema with the ERD, but it's a DB structure change and needs to be proposed to Fabio per `GITHUB_WORKFLOW.md`, not done unilaterally here.
* `issued_at` regex parsing (Sprint 2 fix above) is unvalidated against a real PAGASA bulletin — only tested against a hand-written sample string.
* Frontend Leaflet map integration for Sprint 3 (visualizing farm boundaries and typhoon path overlaps) is out of scope for this branch — that's James's (Frontend Developer) piece per `TEAM_RESPONSIBILITIES.md`.
* Adjacent, out of scope: `upload.py`'s pre-existing `adjuster_calculation` bug (passed into `RiskAssessment` where no such column exists — flagged in the 2026-07-21 "Recsap Matrix Persistence" entry above, still unfixed). Not touched here since it's Sprint 1/CSV path, unrelated to GPX/exposure.
* Branch is **not pushed** and has **no PR open** — needs review before merging into `main`.

---

## [2026-07-21] - PAGASA Scraper Fix: Dead Index URL & Overly-Strict PDF Filter

**Branch:** `cristian/backend/sprint3-gpx-exposure` (committed locally, not pushed, no PR open yet).

### 1. File: `backend/app/services/bulletin_parser.py`
* **Bug fix:** `PAGASA_INDEX_URL` changed from `.../tamss/weather/bulletin.html` to `.../tamss/weather/bulletin/` — the `.html` path was not the live directory-listing endpoint. The trailing slash is required, not stylistic: `fetch_active_bulletin_links()` derives the base URL via `PAGASA_INDEX_URL.rsplit("/", 1)[0]`, which only strips the correct (empty) trailing segment when the constant ends in `/`; without it, `rsplit` would strip the real `bulletin` path segment and misresolve every relative link.
* **Bug fix:** Removed the `"bulletin" in href.lower()` condition from `fetch_active_bulletin_links()`'s link filter (now just `href.endswith(".pdf")`). Real PAGASA filenames follow a `TCB#<n>_<stormname>.pdf` pattern (e.g. `TCB#10_francisco.pdf`) with no literal "bulletin" substring, so the old filter silently matched zero links against the live server. Verified against the live index: 0 links found before the fix, 55 found after.

### Status / Next Steps
* Verified against the live PAGASA server only (`fetch_active_bulletin_links()`); `download_bulletin_pdf()` / `parse_bulletin_text()` / `save_bulletin_to_db()` were not exercised against a real downloaded PDF as part of this fix.
* Branch is **not pushed** and has **no PR open** — needs review before merging into `main`.

---

## [2026-07-21] - CLAUDE.md: Handoff Rules for DB/sudo and Frontend Commands

**Branch:** `cristian/backend/sprint3-gpx-exposure` (committed locally, not pushed, no PR open yet).

### 1. File: `.claude/CLAUDE.md`
* **Process/doc change, no code touched.** Added two new sections following the existing "Git Command Execution" / "Python Environment (venv) Execution" pattern, closing gaps found while auditing the codebase for commands that require Fabio's own terminal/credentials:
  * **`Database Command Execution (sudo / psql)`**: `sudo systemctl start postgresql`, `sudo -iu postgres psql`, `CREATE USER`/`CREATE DATABASE`, and applying `backend/init_schema.sql` via `psql -f` must be handed to Fabio, one command at a time, confirmed via AskUserQuestion — same handoff pattern as `git push`, since these need his `sudo` access and DB superuser credentials.
  * **`Frontend Local Environment Execution`**: `npm i`/`npm install`, `npm run dev`, `vite build` (see `frontend/package.json` scripts) must likewise be handed off rather than run via tool call, since they install into and run against Fabio's local `frontend/node_modules`.
* Companion memory entries were added outside the repo (`feedback_db_command_handoff.md`, `feedback_frontend_handoff.md` in the Claude Code memory store) so future sessions apply this immediately instead of rediscovering it.

---

## [2026-07-21] - Sprint 4: Parametric Payout Engine & CSV Export

**Branch:** `fabio/backend/sprint4-payout-engine` (based on `cristian/backend/sprint3-gpx-exposure`, since eligibility depends on that branch's `AreaExposureSummary`/`tbl_area_exposure_summary` work; committed locally, not pushed, no PR open yet).

### Two assumptions this entry depends on (confirmed with Fabio before writing code)
1. **Crop growth stage source:** the schema has no live-updated place tracking a policy's current crop stage — `crop_stage_no`/`crop_stage` only exist on `tbl_risk_assessment`, populated once at legacy CSV-import time (`pabs_results.csv`'s `Stage No.`/`Stage` columns). The payout engine reuses each policy's most recent existing `RiskAssessment` row for this value. This is a real architecture gap, not a new abstraction invented here — flagging for whoever eventually builds real crop-stage tracking.
2. **`tbl_recsap_matrix` placeholder data:** real PCIC "Table 11" values are still not available (blocked since the "Recsap Matrix Persistence" entry above). Seeded 36 placeholder rows instead so the engine has something to compute against.

### 1. File: `backend/init_schema.sql`
* Appended a `-- PLACEHOLDER` seed block: 36 `tbl_recsap_matrix` rows (`crop_stage_no` 1–3 × `wind_signal_tcws` 2–5 × `exposure_hours` 6/12/24), made-up but monotonically increasing yield-loss/indemnity values. `crop_stage_no` 2=Flowering and 3=Maturity are confirmed against `pabs_results.csv`; 1=Booting is inferred from `MASTER_DEVELOPMENT_CONTEXT.md`'s stage ordering, not independently confirmed. **Replace this entire block** once real Table 11 values are available.

### 2. File: `backend/app/services/assessment_service.py` (new)
* Added **`AssessmentService.calculate_for_bulletin()`**: given `(typhoon_id, bulletin_id, db)`, re-runs `ExposureCalculatorService.compute_for_typhoon()`, filters to boundaries meeting eligibility (`max_signal_level >= 2` and `total_exposure_hours >= 6`), finds each eligible boundary's active policies via `Farm.boundary_id` (the same text-matched boundary linkage Sprint 3 uses — no boundary geometry column exists to spatially intersect against, so this stands in for the "typhoon path overlay" step), filters further by crop stage (Booting/Flowering/Maturity per assumption #1 above), looks up the matrix rule and computes the payout via the existing `ParametricAssessment` (`indemnity_calc.py`, untouched), and upserts one `RiskAssessment` row per `(insurance_records_id, summary_id)` pair.
* "Active policy" is determined by `InsuranceRecord.effectivity_date <= bulletin.issued_at.date() <= expiry_date` — evaluated as of the typhoon event, not "today".

### 3. File: `backend/app/api/assessments.py` (new)
* Added **`POST /api/assessments/calculate`**: thin wrapper around `AssessmentService.calculate_for_bulletin()`, matching the documented `.claude/API_CONTRACT.md` contract (`{typhoon_id, bulletin_id}` payload).
* Added **`GET /api/assessments/`**: lists `RiskAssessment` rows with optional `typhoon_id` (via an explicit join on `summary_id` — `tbl_risk_assessment.summary_id` is a bare `INT`, not an FK, so there's no relationship to join through) and `policy_no` filters.
  * **Known duplication, not resolved here:** `backend/app/main.py` already has an ad hoc `GET /api/assessments` (no trailing slash) doing a similar but simpler join. Left untouched since something (possibly the frontend) may already call it and this wasn't in scope to audit; FastAPI treats the two paths as distinct routes, so both coexist without conflict, but this is worth cleaning up later.
* Added **`GET /api/assessments/export`**: streams a CSV matching `pabs_results.csv`'s original column layout with computed columns (`Wind Signal (TCWS)`, `Period of Exposure (Hours)`, `Final Indemnity Payment`, `Assessment Date`) appended, per the manuscript's "append to original row layouts" spec. Only includes rows this engine computed (`matrix_id IS NOT NULL`) — excludes the legacy CSV-imported rows, which have no `matrix_id`.
* Registered `assessments_router` in `backend/app/main.py` under the `/api` prefix.

### 4. File: `backend/tests/test_assessment_service.py` (new)
* Added `AssessmentServiceTests` covering: a full eligible-policy payout calculation (asserts the exact `I = (AC/1000) × IF × Area` result and `estimated_damage`), a policy skipped for an ineligible crop stage, a boundary skipped for wind signal below threshold, and a `ValueError` when the bulletin isn't found. Mocks `ExposureCalculatorService.compute_for_typhoon()` directly rather than its internals, since that method already has its own test coverage in `test_exposure_calculator.py`.

### Status / Next Steps
* **Not merged anywhere** — sits on top of `cristian/backend/sprint3-gpx-exposure`, which itself isn't merged into `develop` yet. This branch inherits that same blocker.
* `GET /api/assessments/` vs. the pre-existing `GET /api/assessments` duplication (noted above) should be cleaned up in a follow-up, ideally by whoever owns the frontend's existing call site.
* Real PCIC Table 11 values still needed before any of this is production-usable — everything downstream of `tbl_recsap_matrix` is placeholder-driven until then.
* Not run against a live database — verified by reading the code and the new unit tests only; Fabio needs to run the test suite and a real `/api/assessments/calculate` call himself (per `CLAUDE.md`'s venv-handoff rule).

---

## [2026-07-21] - Sprint 3 & Sprint 4 Merged into develop

Both branches above are now on `develop`, closing out the "not merged" status noted in their respective entries:
* `cristian/backend/sprint3-gpx-exposure` → `develop`: merged via PR, commit `9f7c2cf`.
* `fabio/backend/sprint4-payout-engine` → `develop`: merged locally (`--no-ff`) on top of the updated `develop`, commit `6227ec2`, then pushed. Merge was clean (verified with `git merge-tree --write-tree` before merging) aside from an auto-mergeable append conflict in this file.

Outstanding items from both entries above (Table 11 placeholder data, `GET /api/assessments/` duplication, live-DB verification, `boundary_id`/`geom` FK gap) are unchanged by the merge and still need follow-up.

---

## [2026-07-21] - Real PCIC Table 11 Data: Recsap Matrix Split Into Two Lookups

Resolves the "Table 11 placeholder data" blocker noted in the two entries above. Fabio supplied the actual PCIC damage-matrix and Rice Indemnity Factor Table figures (screenshots transcribed from the manuscript). While wiring them in, found the real tables don't share one key structure the way the placeholder assumed — they're two chained lookups, not one flat table — and that `indemnity_factor`'s column precision couldn't have held the real values anyway.

### Two things confirmed with Fabio before writing code
1. **Growth-stage taxonomy mismatch:** the yield-loss matrix uses 3 stages (Booting, Flowering, Maturity — `tbl_recsap_matrix.crop_stage_no` 1/2/3), but the indemnity-factor table uses PCIC's own 5-stage taxonomy (Early Vegetative, Late Vegetative, Reproductive, Late Reproductive, Maturity). The manuscript's worked example only confirms Flowering → Reproductive. Fabio confirmed Booting → Late Vegetative; Maturity → Maturity by same name. Early Vegetative and Late Reproductive are consequently unreachable via the current 3-stage crop tracking, but per a follow-up request from Fabio all 5 stage-groups were seeded anyway for fidelity to the source table (see updated bullet 1 below).
2. **Data completeness:** the 3 screenshots are the complete source tables — yield loss ≤10% has no bracket (no payout) and 30-35% is the top bracket, not partial data.

### 1. File: `backend/init_schema.sql`
* **Schema:** `tbl_recsap_matrix` dropped its `indemnity_factor` column — it now only resolves step 1, `(crop_stage_no, wind_signal_tcws, exposure_hours) → estimated_yield_loss`.
* **Schema:** Added **`tbl_indemnity_factor_matrix`** for step 2: `(crop_stage_group, yield_loss_min, yield_loss_max) → indemnity_factor`. Brackets are exclusive-lower/inclusive-upper per the source table's ">10 to 15" style labels. `indemnity_factor` is `NUMERIC(7,2)`, not `NUMERIC(5,4)` — the old precision (max 9.9999) couldn't have stored real values like 392.00 or 560.00 even before this change; this was a latent bug in the Sprint 4 placeholder work, not something introduced by real data.
* **Schema:** `tbl_risk_assessment.indemnity_factor` widened to `NUMERIC(7,2)` to match; added `indemnity_matrix_id` FK to `tbl_indemnity_factor_matrix`, alongside the existing `matrix_id` FK to `tbl_recsap_matrix`.
* **Seed data:** Replaced the 36-row made-up placeholder block with the real transcribed values: 35 `tbl_recsap_matrix` rows (one cell, Maturity/signal-2/6h, reads "<10" with no exact figure in the source and was intentionally omitted rather than inventing a number — it resolves to $0 payout either way since the indemnity table's floor is >10%) and 25 `tbl_indemnity_factor_matrix` rows (5 yield-loss brackets × all 5 stage groups, per Fabio's follow-up request — only 3 of the 5 are reachable by the app today, see taxonomy note above). The source table's "TCWS No.04 (118-184 KPH) AND > 184 KPH" header groups wind signals 4 and 5 under identical values, so both were seeded identically.

### 2. File: `backend/app/models/models.py`
* Trimmed **`RecsapMatrix`**: removed `indemnity_factor`.
* Added **`IndemnityFactorMatrix`**: mapped `tbl_indemnity_factor_matrix`.
* Updated **`RiskAssessment`**: `indemnity_factor` widened to `Numeric(7, 2)`; added `indemnity_matrix_id` FK column and `indemnity_matrix` relationship.

### 3. File: `backend/app/core/indemnity_calc.py`
* Added **`CROP_STAGE_TO_INDEMNITY_GROUP`**: the 3-stage → 5-stage taxonomy mapping confirmed with Fabio above.
* Added **`ParametricRule`** dataclass: bundles both lookup steps' results (`matrix_id`, `indemnity_matrix_id`, `estimated_yield_loss`, `indemnity_factor`) so callers get one object instead of juggling two query results.
* Rewrote **`ParametricAssessment.get_matrix_rule()`**: now chains the two lookups — queries `tbl_recsap_matrix` for yield loss %, maps the crop stage to its indemnity-table stage group, then queries `tbl_indemnity_factor_matrix` for the bracket containing that yield loss %. Returns `None` (→ `$0` payout via the existing `calculate_final_payout()` path, unchanged) if either step has no match.

### 4. File: `backend/app/services/assessment_service.py`
* `calculate_for_bulletin()`: now also sets `existing.indemnity_matrix_id = rule.indemnity_matrix_id` alongside the existing `matrix_id` assignment.

### 5. File: `backend/tests/test_assessment_service.py`
* Updated `_build_mock_db()` and the eligible-policy test to mock both chained queries (`RecsapMatrix` then `IndemnityFactorMatrix`) instead of one flat `RecsapMatrix` row, and to use a real indemnity value (330.00, from the Reproductive/>20-25% bracket) instead of the old made-up `0.25` multiplier. Recomputed the expected payout accordingly (`(50000/1000) × 330.00 × 2.5 = 41250.0`, was `31.25`).

### 6. File: `docs/RECSAP_MATRIX_SCHEMA.md` (new)
* Added a text record of the new `tbl_recsap_matrix` / `tbl_indemnity_factor_matrix` / `tbl_risk_assessment` structure — column-by-column tables, the 3-stage→5-stage taxonomy mapping, and the full seeded source data (yield-loss and indemnity-factor tables) — per Fabio's request. `docs/ERD.drawio.png` is a static PNG exported from a `.drawio` source not checked into this repo, so it can't be regenerated here; this file is the interim text record until the visual diagram is updated separately.

### Status / Next Steps
* Not run against a live database or the test suite — Fabio needs to re-run `init_schema.sql` and the test suite himself (per `CLAUDE.md`'s DB/venv handoff rules) to confirm the migration and tests pass.
* `docs/ERD.drawio.png` itself is now stale (still shows the old single `tbl_recsap_matrix` shape) and needs a manual update in the drawio tool by whoever owns that source file — `docs/RECSAP_MATRIX_SCHEMA.md` is a stopgap, not a replacement.
* Merged locally (`--no-ff`) into `develop` on Fabio's instruction, matching the Sprint 3/4 merge precedent above — no PR opened for this one. Push to `origin/develop` still pending Fabio's own terminal.

---

## [2026-07-21] - Recsap Matrix Real-Data Branch Merged into develop

`fabio/backend/recsap-matrix-real-data` merged locally (`--no-ff`) into `develop`, closing out the "not yet pushed" status noted in the entry above. Clean merge, no conflicts. Not yet pushed to `origin/develop` — pending Fabio running the push himself.

Outstanding items from the entry above (live-DB/test-suite verification, stale `docs/ERD.drawio.png`) are unchanged by the merge and still need follow-up.

---

## [2026-07-21] - Frontend-Backend Wiring (Sprint 3)

Connected the static React frontend to the backend endpoints that already exist and match its data needs.

### 1. File: `frontend/src/lib/api.ts` (new)
* **Changes to Functions:**
  * Added **`uploadCsv()`** → routes to `POST /api/upload/csv`.
  * Added **`getBulletins()`** → routes to `GET /api/bulletins/`.
  * Added **`parseBulletins()`** → routes to `POST /api/bulletins/parse`.

### 2. File: `frontend/src/app/components/SpatialModule.tsx`
* **Changes to Functions/Behavior:**
  * Added **`handleCsvFileSelected()`**: wires the CSV dropzone's file input to `uploadCsv()`, with a success/error status banner.

### 3. File: `frontend/src/app/components/MonitoringModule.tsx`
* **Changes to Functions/Behavior:**
  * Added **`loadBulletins()`**: fetches the bulletin list from `getBulletins()` on mount, replacing the mock array.
  * Added **`handleParseLatest()`**: wires the "Parse Latest Bulletin" button to `parseBulletins()`, then reloads the list.

### 4. File: `frontend/tsconfig.json`
* **Changes to Configuration:**
  * Added `"ignoreDeprecations": "6.0"` to silence a TypeScript warning on `baseUrl` (still required for the `@/*` path alias).

### Status / Next Steps
* Not pushed yet — awaiting Fabio's push per the git workflow rules in `.claude/CLAUDE.md`.

---

## [2026-07-22] - High-Fidelity UI Adoption

Replaced the frontend's MUI-based screens with the team's high-fidelity Figma "Make" prototype design (formerly the untracked `High Fidelity Interactive Desktop/` folder, renamed to `ui-prototype/` — gitignored, not part of this commit). Re-applied the existing backend wiring from the 2026-07-21 entry into the new component structure. No backend files touched.

### 1. New files: `frontend/src/app/components/Header.tsx`, `LoginScreen.tsx`, `CalibrationModule.tsx`, `AOISARPanel.tsx`, `mockData.ts`, `SpatialAnalysisModule.tsx`
* Ported from the high-fidelity prototype as-is (Header nav/dark-mode/notifications, demo-credential Login/Registration, Calibration settings, SAR/GEE analysis panel, shared mock farmer/bulletin data). All fully client-side mock UI — no matching backend endpoints exist for GPX upload, `/api/assessments/calculate`, or GEE/SAR analysis, so these stay static per prior scope decisions.

### 2. New file: `frontend/src/app/components/GISLeafletMap.tsx`
* Real `react-leaflet` map (OpenStreetMap tiles) built to the same prop interface as the prototype's canvas-mockup `GISMap.tsx`, so it drops into `SpatialAnalysisModule.tsx` without further rework. Farms are plotted using real coordinates for the municipalities the prototype's data already names (Naga City, Pili, Libmanan, Sipocot, Goa, Lagonoy — Camarines Sur), spread into a small grid per municipality since the prototype's own farm coordinates were fake canvas pixels, not geographic.

### 3. File: `frontend/src/app/components/SpatialAnalysisModule.tsx` (new — replaces `SpatialModule.tsx`, which is left in place unused)
* CSV dropzone's `processFiles()` now calls `uploadCsv()` for `.csv` files (real `POST /api/upload/csv`) with a status banner; `.gpx` files still fake-process client-side (no backend endpoint).

### 4. File: `frontend/src/app/components/MonitoringModule.tsx` (overwritten — same filename as prototype)
* Bulletin table now sources from `getBulletins()` (`GET /api/bulletins/`) instead of mock data. Added **`handleSelectBulletin()`** and **`handleViewTCB()`**, both lazily calling the new **`getBulletinSignals()`** (`GET /api/bulletins/{tcb_id}/signals`) to derive real per-bulletin signal level and affected-area lists — the list endpoint alone doesn't carry these. **`handleParseLatest()`** wires the "Parse Latest Bulletin" action to `POST /api/bulletins/parse`, then reloads the list. Table columns/detail views were adjusted to only show fields the backend actually returns (`category`, `max_sustained_winds`, `gustiness`, `issued_at`) — dropped the prototype's fabricated `status`/`fileSize`/`version`/`windVelocityRange` fields, which have no backend equivalent. Growth-stage/signal/timeline charts remain mock (no assessment-history endpoint exists).

### 5. File: `frontend/src/app/components/AssessmentModule.tsx` (overwritten — same filename as prototype)
* Ported as-is from the prototype; remains fully mock per the 2026-07-21 decision, since `GET /api/assessments` has no field overlap with this UI.

### 6. File: `frontend/src/lib/api.ts`
* Added **`getBulletinSignals(tcbId)`** → routes to `GET /api/bulletins/{tcb_id}/signals`, plus the `TcbSignal` type.

### 7. File: `frontend/src/app/App.tsx`
* Replaced the MUI `ThemeProvider`/`DashboardLayout` shell with the prototype's `LoginScreen` → `Header` → module-switch structure (`monitoring` / `spatial` / `assessment` / `calibration`), plus `darkMode` and `coverageRatePerHa` state shared across modules. Old `DashboardLayout.tsx`, `Login.tsx`, `SettingsModule.tsx`, and the old `SpatialModule.tsx` are no longer imported anywhere — left in place unused, not deleted, per Fabio's call.

### 8. File: `frontend/src/styles/theme.css`
* Replaced the color tokens with the prototype's palette (`--primary: #166534` green / `--accent: #ca8a04` gold, plus dark-mode variants) — a full visual theme change, confirmed with Fabio beforehand. Removed the old `--green-*`/`--blue-*`/`--gold-*` tokens the now-unused MUI components relied on; harmless since those components no longer render.

### Status / Next Steps
* `npm run build` passes clean; verified both dev servers respond, but UI was not visually screenshotted (no browser-automation tool available in this environment) — Fabio should click through it locally before merging.
* Not pushed yet — awaiting Fabio's push per the git workflow rules in `.claude/CLAUDE.md`.

---

## [2026-07-23] - Real PSGC Codes + Region X Boundary Map Layer

Replaces the mock `tbl_admin_boundaries` PSGC codes with real ones, and adds a municipality-outline context layer to the Leaflet map. Scoped as "map layer only" per Fabio's decision — does **not** touch `tbl_admin_boundaries`'s schema or `ExposureCalculatorService`/`AssessmentService`'s existing text-matching logic (still no `geom` column, matching the gap already flagged in the 2026-07-21 Sprint 3 entry and `docs/ERD.drawio.png`'s stale divergence from the actual schema).

Source: `github.com/faeldon/philippines-json-maps` (2023 PSGC-current, derived from PSA/NAMRIA data via `altcoder/philippines-psgc-shapefiles`). The official HDX COD-AB page (`data.humdata.org/dataset/cod-ab-phl`) is the canonical source but returns HTTP 403 to automated fetches (Cloudflare bot protection) — this GitHub mirror was used instead since it's directly fetchable and traces back to the same PSA/NAMRIA lineage. Verified against `backend/pabs_results.csv`: only Bukidnon/Talakag and Misamis Oriental/Claveria are actually seeded today.

### 1. File: `backend/app/data/psgc_region10_boundaries.csv` (new)
* Real PSGC codes for every barangay in all 22 Bukidnon municipalities and all 25 Misamis Oriental municipalities (888 barangays total), per Fabio's follow-up request to cover both provinces in full rather than just Talakag/Claveria. Verified spot-checks: San Isidro (Talakag) = `1001320027`, Poblacion (Claveria) = `1004306020`.

### 2. File: `backend/seed_database.py`
* **Changes to Functions (`run_setup()`):**
  * Replaced the mock `psgc_code = f"PH10{idx:06d}"` generation with a real lookup against `app/data/psgc_region10_boundaries.csv` (loaded via pandas, indexed on `(province, municipality, barangay)`).
  * If a CSV row's boundary isn't found in the reference file, `run_setup()` now raises `ValueError` naming the missing boundary, instead of silently minting a fake code — surfaces data gaps rather than hiding them.

### 3. File: `frontend/public/data/region10-boundaries.geojson` (new)
* Merged, low-res municipality polygons for all 5 Region X provinces (Bukidnon, Camiguin, Lanao del Norte, Misamis Occidental, Misamis Oriental — 91 municipalities, ~55KB), each feature carrying `psgc_province`, `psgc_municipality`, `province`, `municipality`. Served as a static asset (Vite `public/`) — no backend endpoint, since this data doesn't change at runtime.

### 4. File: `frontend/src/app/components/GISLeafletMap.tsx`
* **Changes to Functions/Behavior:**
  * Added a `GeoJSON` react-leaflet layer (`regionXBoundaries` state, fetched from `/data/region10-boundaries.geojson` on mount) rendering Region X municipality outlines — dashed green, no fill, `bindTooltip` on hover showing `municipality, province`. Presentation-only; not read by any calculation.
  * Changed `MapContainer`'s default `center`/`zoom` from `[13.68, 123.2]`/`10` (Camarines Sur) to `[8.38, 124.84]`/`9` (Region X, centered between Talakag and Claveria) so the new layer is actually visible on load.

### Status / Next Steps
* **Not fixed, flagged only:** the map's mock farmer data (`mockData.ts`, ~20 rows) and the typhoon-track/signal-ring mock overlays (`GISLeafletMap.tsx`'s `MUNICIPALITY_CENTERS`/`TYPHOON_TRACK`/`SIGNAL_WIND_RINGS`) are still all Camarines Sur/Bicol coordinates (per the 2026-07-22 "High-Fidelity UI Adoption" entry). After this change, those will render far outside the new Region X default viewport. Fabio decided to leave this as-is for now rather than expand scope — replacing the mock farmer data with real Region X placeholders is a separate follow-up task.
* Two Region X cities — Cagayan de Oro and Iligan (independent/highly-urbanized, administratively separate from any province) — aren't in the source repo's province-level files and weren't chased down further: not in `pabs_results.csv`, and PCIC insures rice farms rather than urban cores. Flagging in case boundary coverage there is wanted later.
* Not run against a live database or `npm run build` — Fabio needs to re-run `seed_database.py` (per `CLAUDE.md`'s venv-handoff rule; will only succeed on a fresh/re-seeded `tbl_admin_boundaries`, since existing rows with mock `PH10######` codes won't be overwritten by the `SELECT ... WHERE province/municipality/barangay` existence check) and view the frontend locally.
* Not pushed yet — awaiting Fabio's push per the git workflow rules in `.claude/CLAUDE.md`.

---

## [2026-07-23] - Sprint 3 Close-Out: Wire Real Farm/Bulletin Data into the Spatial UI

**Branch:** `cristian/backend/wire-real-data-sprint3` (cut from `develop`; committed locally, not pushed, no PR open yet).

Rechecked Sprint 3 after the Sprint 3/4 backend work, real recsap matrix data, and the high-fidelity frontend UI had all merged into `develop`, and found none of Sprint 3's backend deliverables (GPX parser, exposure calculator) were actually reachable from the UI: the GPX dropzone faked uploads with a `setTimeout`, `GISLeafletMap.tsx` rendered 100% hardcoded/mock data, and there was no `GET /api/farms/` endpoint at all — so the frontend had no way to fetch real farm data even if it tried. This entry closes that gap end-to-end.

### 1. File: `backend/app/api/farms.py` (new)
* Added **`list_farms()`** (`GET /api/farms/`): lists all farms with farmer name, province/municipality/barangay, area size, and `location_geom` serialized to GeoJSON via `geoalchemy2.shape.to_shape()` + `shapely.geometry.mapping()` (`None` if no GPX has been uploaded yet). Response envelope: `{"status", "data": [...]}`, matching `assessments.py`'s convention.

### 2. File: `backend/app/api/bulletins.py`
* `list_bulletins()`: added `center_lat`/`center_lng` (derived from `TropicalCycloneBulletin.center_geom` via `to_shape()`) to each row, so the frontend can place a real typhoon marker instead of a hardcoded one. Bare-array envelope left unchanged.

### 3. File: `backend/app/api/assessments.py`
* `list_assessments()`: added `farm_id` (via `a.insurance_record.farm_id`) to each row — previously assessments were only keyed by `policy_no`, with no way to trace a computed assessment back to a specific farm. This is the join key the frontend now uses to attach real wind-signal/exposure/payout data onto the real farm table.

### 4. File: `backend/app/main.py`
* Registered `farms_router` under the `/api` prefix.

### 5. File: `frontend/src/lib/api.ts`
* Added **`uploadGpx(file, farmerId, farmId)`** → `POST /api/upload/gpx`, **`getFarms()`** → `GET /api/farms/`, **`getAssessments(typhoonId?, policyNo?)`** → `GET /api/assessments/`. Added `Farm`, `GeoJsonMultiPolygon`, `Assessment`, `UploadGpxResult` types; extended `Bulletin` with `center_lat`/`center_lng`.

### 6. File: `frontend/src/app/components/SpatialAnalysisModule.tsx`
* **Replaced the `mockFarmers`-driven table with real data** (`getFarms()` + `getAssessments()`, joined client-side by `farm_id`) — this went beyond the originally-scoped "minimal dropdown" approach per an explicit decision to do the bigger rework instead. Columns not backed by any real field (`plantingDate`, mock `growthStage` taxonomy) were dropped rather than faked; wind signal / exposure / payout columns show "Not yet assessed" / "—" when no matching `RiskAssessment` exists for that farm — **expect most/all rows to show this initially**, since the payout engine has never been run against a live database. This is expected, not a bug.
* GPX upload targeting: since the table is now real, **selecting a table row is the upload target** (no separate dropdown needed) — `processFiles()`'s `.gpx` branch now calls `uploadGpx()` for real against the selected row's `farmer_id`/`farm_id`, replacing the previous fake `setTimeout`-only placeholder. Re-fetches `getFarms()` afterward so the map picks up the new geometry immediately.
* Municipality filter options are now derived from real farm data instead of a hardcoded Camarines Sur town list.

### 7. File: `frontend/src/app/components/GISLeafletMap.tsx`
* **Deviates from the plan's "additive layer, keep mock untouched" wording** — since the table driving selection is now fully real (per item 6), keeping the old `FarmerRecord`-based mock layer as a second, disconnected, unselectable layer would have been confusing (clicking a real table row wouldn't highlight anything in it, and its farms don't correspond to any table row anymore). Instead, the component's farm layer is now fully real-data-driven: farms with `location_geom` render as real `<GeoJSON>` boundary polygons; farms without one yet render as small `<CircleMarker>` dots at an approximate municipality-center placement (reusing the old grid-spread logic, just for placement, not as a fake boundary shape) so they stay visible/selectable as GPX upload targets. Confirmed via grep this component has no other callers, so the prop-signature change is safe.
* Removed `TYPHOON_TRACK`/`TYPHOON_EYE`/`SIGNAL_WIND_RINGS` (hardcoded, explicitly commented "Simulated") entirely. Replaced with a real `<Marker>` at the selected bulletin's `center_lat`/`center_lng` (custom inline-SVG `L.divIcon`, sidestepping the well-known Vite/Webpack "missing default Leaflet marker icon" asset-resolution issue rather than fixing that separately) plus a real affected-municipality list via the already-working `getBulletinSignals()`, both in the marker's popup. No polygon/radius overlay — that geometry doesn't exist (see the new schema proposal, item 9).

### 8. Files: `frontend/src/app/App.tsx`, `frontend/src/app/components/MonitoringModule.tsx`
* Lifted `selectedBulletin` state from `MonitoringModule` up to `App.tsx` (passed down as `selectedBulletin`/`onSelectBulletin` props to both `MonitoringModule` and `SpatialAnalysisModule`), so one typhoon-event selection is shared app-wide instead of `SpatialAnalysisModule` needing its own independent, duplicate bulletin picker. `MonitoringModule.handleSelectBulletin()` now calls the passed-down setter instead of owning local state; its own signal-list fetching logic is otherwise unchanged.

### 9. File: `docs/PROPOSAL_boundary_geometry.md` (new)
* Drafted (not implemented) a proposal for Fabio: add `tbl_admin_boundaries.geom` (municipal boundary polygon) and `tbl_tcb_signals.boundary_id` (FK, replacing today's fragile `area_name` text-matching). This is the real blocker for ever rendering a true "typhoon path crosses this municipality" polygon overlay — reconfirmed against `docs/ERD.drawio.png`, which already shows both fields in the intended design. No schema change made; awaiting Fabio's review per the DB Admin approval rule in `CLAUDE.md`.

### Status / Next Steps
* Not run against a live database or the frontend dev server — I can no longer run venv/pytest/npm commands myself (per `CLAUDE.md`'s handoff rules); Fabio needs to run the backend test suite, exercise the three endpoints via Swagger UI, and click through the frontend (`npm run dev`) himself to confirm end-to-end.
* `location_geom`'s GeoJSON shape is passed to react-leaflet's `<GeoJSON data={...}>` with an `as any` cast (its prop type expects the `geojson` package's `GeoJsonObject`, which our hand-rolled `GeoJsonMultiPolygon` interface structurally matches but isn't declared as) — flagging in case `npm run build`'s type-check is stricter than expected; not verified since I can't run the build myself.
* `frontend/src/app/components/mockData.ts`'s `mockFarmers` is still used elsewhere (`MonitoringModule.tsx`'s dashboard stats, `AssessmentModule.tsx`) — untouched, out of scope for this entry.
* Branch is **not pushed** and has **no PR open** — needs review before merging into `develop`.

---

## [2026-07-23] - Merge Conflict Resolution: Region X Boundary Layer + Sprint 3/4 Real-Data Rewrite

Merging `cristian/backend/wire-real-data-sprint3` into `develop` produced a genuine structural conflict in `frontend/src/app/components/GISLeafletMap.tsx` — `develop`'s "Real PSGC Codes + Region X Boundary Map Layer" entry (above) added a municipality-outline `GeoJSON` layer on top of the *old* mock-farmer-driven component, while the Sprint 3 entry completely rewrote the same component for real farm/typhoon data. Resolved by hand rather than picking a side: kept the Sprint 3 rewrite's structure (real `GeoJSON` farm boundaries, real typhoon marker, `CircleMarker` fallback placement) and merged in the Region X boundary layer feature (`regionXBoundaries` state/fetch, `styleBoundary()`/`labelBoundary()`, the `<GeoJSON>` outline layer) on top of it.

While reconciling, corrected a latent bug the Sprint 3 rewrite had carried over unnoticed: `MUNICIPALITY_CENTERS` (used to place farms without a GPX boundary yet) still listed the old mock UI's Camarines Sur towns (Naga City, Pili, etc.), which don't match any real seeded data. Replaced with the two municipalities actually seeded per `pabs_results.csv` (Talakag, Bukidnon and Claveria, Misamis Oriental), and changed `DEFAULT_CENTER`/zoom to Region X (matching the boundary-layer commit's map view) instead of the leftover Camarines Sur default.

### Status / Next Steps
* Not verified with a build/dev server — same handoff situation as both merged entries; Fabio needs to run `npm run build`/`npm run dev` to confirm the reconciled component compiles and renders both the real farm/typhoon layers and the Region X boundary outline together correctly.

---

## [2026-07-23] - Sprint 4 Close-Out: Wire Real Payout/Export Data into AssessmentModule

**Branch:** `cristian/backend/wire-real-data-sprint4`, stacked on top of the still-unmerged `cristian/backend/wire-real-data-sprint3` (committed locally, not pushed, no PR open yet).

An audit found Sprint 4 (parametric payout engine + real PCIC Table 11 data + CSV export) had the exact same pattern as Sprint 3's original gap: a correct, real-data backend, completely unwired from the frontend. Worse than Sprint 3's gap — `AssessmentModule.tsx`'s "calculation" was a fully scripted fake progress bar with an invented SAR/GEE failure narrative ("Sentinel-1 tile coverage gap detected") that has nothing to do with the real backend (no SAR/GEE dependency exists anywhere in this calculation), plus a hardcoded "Signal 2 only" scope that contradicts the real eligibility rule (signal ≥ 2, not signal = 2), a 4-stage growth taxonomy that doesn't match the real 3-stage `crop_stage_no`, and a per-farm coverage-rate override feature with no real backend equivalent (`InsuranceRecord.amount_cover` is fixed at CSV-import time). This entry removes the fabricated simulation and wires the module to the real engine.

### 1. File: `backend/app/api/bulletins.py`
* `list_bulletins()`: added `typhoon_id` to each row (the query already resolved `Typhoon` by this ID to get `typhoon_name` — it just never returned the ID itself). Needed so the frontend can call `POST /api/assessments/calculate` (which requires a `typhoon_id`) directly from a selected bulletin.

### 2. File: `backend/app/api/assessments.py`
* `list_assessments()`: added `amount_cover` (via `a.insurance_record.amount_cover`, a real Sum Insured value) and `indemnity_factor` (previously only returned by `/calculate`'s response, not the persistent `GET /`, so it disappeared on page reload).
* `export_assessments_csv()`: added an optional `typhoon_id` query filter (same `AreaExposureSummary` join pattern `list_assessments()` already uses), so the export can be scoped to one typhoon instead of always returning every computed assessment ever. Backward compatible — omitting the param keeps the old unscoped behavior.

### 3. File: `frontend/src/lib/api.ts`
* Added `typhoon_id` to `Bulletin`; added `amount_cover`/`indemnity_factor` to `Assessment`.
* Added `CalculateAssessmentsResult` type and `calculateAssessments(typhoonId, bulletinId)` → `POST /api/assessments/calculate` (the file's first JSON-body POST — existing POSTs all use `FormData`, so `Content-Type: application/json` is set explicitly at the call site).
* Added `getAssessmentsExportUrl(typhoonId)` — returns a plain URL string rather than a typed fetch-blob helper, since no `api.ts` function anywhere sets auth headers; the CSV modal opens this URL directly (`window.open`) and lets the browser handle the download.

### 4. File: `frontend/src/app/App.tsx`
* `AssessmentModule` now receives the same lifted `selectedBulletin`/`onSelectBulletin` props as `MonitoringModule`/`SpatialAnalysisModule` (one shared typhoon-event selection app-wide). Its `coverageRatePerHa` prop was removed — `CalibrationModule` keeps owning that value for whatever else uses it, but `AssessmentModule` no longer has a use for it (see below).

### 5. File: `frontend/src/app/components/AssessmentModule.tsx` (near-total rewrite)
* Replaced all `mockFarmers`/`mockBulletins` usage with `getBulletins()` (grouped client-side by `typhoon_name` for the folder UI — same interaction shape as before, real data underneath), and `getAssessments(typhoonId)` + `getFarms()` joined by `farm_id` for the results table (same join pattern as `SpatialAnalysisModule`).
* Selecting a bulletin now calls the real `calculateAssessments()`. Replaced the fake `setInterval` progress/failure simulation with real `isCalculating`/`calcError` state — `calcError` surfaces the actual thrown error (e.g. a real 404), not fabricated SAR/GEE text. Removed `lastSuccessfulTCB` rollback-to-previous-bulletin logic entirely (it only existed to serve the fake failure path). Added an explicit **honest zero-result state** ("0 assessments computed — no policies met eligibility criteria...") since that's a normal, expected real outcome, not an error.
* Removed: per-farm coverage-rate override editing (pencil icon/inline input/override map — no real backend concept), the 4-stage growth-stage taxonomy and `windVelocityMin`/`windVelocityMax` range display (real data is a single signal number), the hardcoded "Signal 2 Only" default filter and footer summary panel (the real eligibility rule is already enforced server-side at calculate time), the per-typhoon-folder signal badge (no real per-bulletin signal on the list endpoint, not worth an N+1 fetch just for a badge), and the "Damage Factors" reference table (4-stage taxonomy/percentages don't correspond to the real `tbl_recsap_matrix`/`tbl_indemnity_factor_matrix` values, which are a 3-key lookup, not a simple stage×signal table — no cheap real replacement without a new backend endpoint).
* CSV export: simplified from a two-modal preview→confirm flow to one modal (preview table + a "Download CSV" button linking to the new `typhoon_id`-scoped export URL) — the original two-step flow was preserved in spirit, just consolidated, since the download is now a real server-generated file (nothing left to "confirm" client-side beyond reviewing the same rows about to download).
* "Indemnity by Municipality" bar chart kept, re-sourced from real filtered/joined assessment rows grouped by `Farm.municipality` (clean real-data path existed for this one).

### Status / Next Steps
* Not run against a live database or the frontend dev server — same handoff situation as the Sprint 3 entry: Fabio needs to run the backend test suite, exercise the three modified endpoints via Swagger UI, and click through the frontend himself.
* An uncommitted, unrelated change was already present in the working tree when this branch was created: `.claude/DEVELOPMENT_PLAN.md`'s Sprint 4 formula was edited from `I = (AC / 1000) * IF * Area` to `I = (AC / 1000) * IF` (dropping `* Area`). This was not made by this work and contradicted the actual formula used everywhere in the real code (`indemnity_calc.py`, `PROJECT_CONTEXT.md`) at the time — flagged to the user, who chose to keep and include it in this branch rather than revert it. **Resolved by the entry below**, which confirmed this was correct per PCIC and fixed the rest of the codebase to match.
* Branch is **not pushed** and has **no PR open**, and depends on `cristian/backend/wire-real-data-sprint3` merging first (stacked branch) — needs review before merging into `develop`.

---

## [2026-07-23] - Formula Correction: Drop `* Area` from the Indemnity Payout Calculation

**Branch:** `cristian/backend/wire-real-data-sprint4` (same branch as the entry above; committed locally, not pushed, no PR open yet).

Fabio confirmed the correct PCIC formula is `I = (AC / 1000) * IF` — farm area is **not** a factor. This corrects a bug: the payout engine had been computing `I = (AC / 1000) * IF * Area` this entire session (matching what `.claude/PROJECT_CONTEXT.md`/`MASTER_DEVELOPMENT_CONTEXT.md` documented at the time, which was itself wrong), silently over/under-paying every farm proportional to its area. Every prior changelog entry describing the old formula is left as historical record, not rewritten.

### 1. File: `backend/app/core/indemnity_calc.py`
* `ParametricAssessment.calculate_final_payout()`: dropped the `area_hectares` parameter and the `* area_hectares` term — now `payout = (amount_of_cover / 1000) * float(rule.indemnity_factor)`. Updated the docstring and the interactive `__main__` CLI testing block (no longer prompts for area).

### 2. File: `backend/app/services/assessment_service.py`
* `calculate_for_bulletin()`: removed the now-unused `area = float(insurance.farm.area_size)` local and stopped passing it to `calculate_final_payout()`. `estimated_damage`'s calculation (`amount_cover * yield_loss% / 100`) was never area-dependent and is unchanged.

### 3. File: `backend/tests/test_assessment_service.py`
* Recomputed the eligible-policy test's expected payout: `(50000/1000) * 330.00 = 16500.0` (was `41250.0`, which included the now-removed `* 2.5` area factor).

### 4. Files: `.claude/PROJECT_CONTEXT.md`, `.claude/MASTER_DEVELOPMENT_CONTEXT.md`
* Both updated from `I = (AC / 1000) * IF * Area` to `I = (AC / 1000) * IF`, matching `.claude/DEVELOPMENT_PLAN.md`'s already-corrected version and the fixed code.

### Status / Next Steps
* Not run against a live database — same handoff situation as every other entry in this file; Fabio needs to run the test suite himself to confirm.
* This changes real computed payout amounts. If any assessments were ever computed against a live database using the old formula (unlikely given the repeated "never run against a live database" notes above, but worth confirming), those `RiskAssessment.final_indemnity_payment` values would need recomputing.

---

## [2026-07-24] - PABS CSV Ingestion Fix, GPX Filename Auto-Matching, and `farmers_id` Schema Proposal

**Branch:** `fabio/db/pabs-ingestion-gpx-matching` (committed locally, not pushed, no PR open yet).

Prompted by two new real files dropped in `docs/`: `Rice Risk Exposure Region X 04-15-2026.csv` (a fresh PABS export, 23,917 rows — intended as the recurring source-of-truth format the GIS specialist will keep exporting) and `TAB_ABAO , JONEL  J._120961_1148107_2024-08-06.gpx` (a real farm-boundary walk). Investigating whether the database could actually ingest the CSV, and whether a GPX file's farmer could be auto-detected from its filename, surfaced that **`POST /api/upload/csv` was completely broken for any CSV, old or new format** — before touching anything else — plus a design trap that would have made things worse.

### 0. The trap: `RiskAssessment` at CSV-import time looked removable, but isn't
`upload_csv()`'s previous per-row `RiskAssessment(..., adjuster_calculation=...)` insert crashed on every real upload (`adjuster_calculation` is not a column on that model — confirmed via grep, only referenced in this one call site and its own unit test). The obvious fix looked like "delete that insert entirely." That would have been wrong: `AssessmentService.calculate_for_bulletin()` (the real payout engine) reads each policy's crop growth stage from its **most recent existing `RiskAssessment` row** (`assessment_service.py`'s own docstring says so explicitly, and `test_assessment_service.py` mocks exactly this `prior` row in every eligibility test). Deleting the insert would have made every CSV-ingested policy permanently un-assessable — silently, since `calculate_for_bulletin()` just skips policies with no prior row. `backend/seed_database.py` (the separate, legacy ingestion script) already depends on this same mechanism, seeding a `RiskAssessment` row with `final_indemnity_payment` set equal to `estimated_damage` as a placeholder. `export_assessments_csv()` already filters `WHERE matrix_id IS NOT NULL` specifically to exclude these placeholder rows from "real" results. Fix keeps this seed row, narrowed to only the fields the CSV actually provides (crop stage + estimated damage), matching `seed_database.py`'s existing placeholder convention (confirmed with Fabio).

### 1. File: `docs/PROPOSAL_farmers_id_column.md` (new)
* Proposal for adding `tbl_farmers_profile.farmers_id VARCHAR(20) UNIQUE` — PABS's own per-farmer ID. Empirically (full 23,917-row pass of the real CSV): `FarmersID` is 100% populated vs. `RSBSA No.`'s 71.3% (6,862 blank rows — legitimate for non-RSBSA program types like `APCP`/`AGRISENSO PROGRAM`). Includes the exact `init_schema.sql`/`models.py` diffs. Approved by Fabio (concept-level) before this commit; **the live database does not have this column until Fabio applies it** — see Status below.

### 2. File: `backend/init_schema.sql`
* **Changes to Schema:** Added `tbl_farmers_profile.farmers_id VARCHAR(20) UNIQUE` per the proposal above. Not yet applied to any live database.

### 3. File: `backend/app/models/models.py`
* **Changes to Classes/Structures:** `FarmerProfile` gained `farmers_id = Column(String(20), unique=True)`. Also fixed `rsbsa_no` from `nullable=False` to nullable — it was already nullable in both the live DDL and the manuscript's own dictionary (p.37: "UNIQUE, NULLABLE"); only the SQLAlchemy model contradicted reality. Needed so the CSV fix below can insert a genuine `NULL` for the ~29% of real rows with no RSBSA number.

### 4. File: `backend/app/services/gpx_farmer_matcher.py` (new)
* Added **`GpxFarmerMatcherService.parse_filename(filename)`**: regex-parses the `TAB_<LASTNAME> , <FIRSTNAME> <MI>._<ID1>_<ID2>_<DATE>.gpx` filename convention. ID/date suffix and name portion are parsed independently so a malformed name doesn't lose the IDs (or vice versa).
* Added **`GpxFarmerMatcherService.match(filename, db)`**: matching precedence is ID1 → `farmers_id` (once applied), then ID2 → `Farm.csv_farm_reference`, then normalized (last name + first name) match, with middle name/initial used **only** as a tiebreaker between multiple name candidates — never a hard requirement. This is deliberate: the real sample file's filename middle initial ("J.") disagrees with its own in-file `<trk><name>` middle name ("BEBERRENO"), proving the two can genuinely disagree. Returns an explicit "ambiguous" result (populated `candidates`) or an empty result (no match at all) rather than guessing — confirmed against the real sample file, which matches **nothing** in the new CSV/XLSX by name or ID (independently-sourced files), so "no match" had to be a first-class, gracefully-handled outcome, not an edge case.
* `gpx_parser.py` (geometry parsing) is untouched — filename/identity matching is a separate concern with its own file, consistent with this codebase's one-concern-per-service pattern.

### 5. File: `backend/app/api/upload.py`
* **Changes to Functions:**
  * Added **`_normalize_header(key)`**: collapses a CSV header to bare alphanumerics so `"Farm ID"` (legacy `pabs_results.csv` layout) and `"FARMID"` (the new PABS export's actual header — no space) resolve to the same lookup. This was the exact bug that would have collapsed every farm across a 23,917-row import onto a single DB row: the old code read `data.get("Farm ID")` literally, which always returned `None` against the new file's `FARMID` column, and the get-or-create farm lookup matched on that `None`/blank value rather than refusing to match on it.
  * Added **`_stringify_id(value)`**: coerces a pandas-inferred numeric ID column (`FARMID`/`FarmersID` are pure-digit columns pandas reads as int64/float64) to text before it reaches a `VARCHAR` column.
  * Rewrote **`prepare_row_payload(row)`**: now header-normalized (see above); added `farmers_id` (farmer) and `product_name` (insurance — was silently read nowhere despite `InsuranceRecord.product_name` existing on the model and being `NOT NULL` in the manuscript's dictionary, p.39); renamed the `"assessment"` sub-dict to `"crop_stage_seed"` and dropped `adjuster_calculation` entirely (the field that crashed every upload); kept `risk_exposure_amount` only for a runtime cross-check, never persisted (confirmed numerically identical to `EstimatedDamage` across all 23,917 real rows — logged as a warning if a future file ever disagrees, not silently ignored). Blank `rsbsa_no` now normalizes to `None`, not `""` — the root cause of the farmer-side collapse bug (matching on `""` treated "no RSBSA number" as a real, shared identity).
  * Rewrote **`upload_csv()`**: (a) added an encoding fallback (`utf-8-sig` → `cp1252`) — the real export is ISO-8859-1/cp1252-encoded (e.g. surnames like "SEÑERES"), and the old code had no encoding handling at all; (b) farmer get-or-create now prefers `farmers_id` over `rsbsa_no`, and — like the farm lookup — never matches an existing row when the key is blank/`None`, only when it's a real value; (c) removed the broken `RiskAssessment(..., adjuster_calculation=...)` call, replaced with the narrowed crop-stage-seed insert described in item 0 above (`final_indemnity_payment` seeded from `estimated_damage`, per Fabio's explicit instruction to pull this from the CSV's own figures rather than a fabricated placeholder); (d) fixed two bugs found in passing in this same function: `InsuranceRecord.farmer_id` was never set on CSV-uploaded records (silently broke `export_assessments_csv()`'s farmer-name lookup for any non-`seed_database.py` data), and `product_name` was read but never persisted.
  * Updated **`upload_gpx()`**: `farmer_id`/`farm_id` are now optional (`Form(default=None)`). Omitting both auto-detects via `GpxFarmerMatcherService.match()` on the uploaded filename; providing both keeps the exact previous manual behavior (backward compatible); providing exactly one is a 400. Auto-detect failure (no match, or an ambiguous name match) returns 404/400 with no DB change — falls back to the existing manual UI selection, never guesses. Response now includes `matched_by` and `farmer_name`.

### 6. File: `.claude/API_CONTRACT.md`
* Synced the `POST /api/upload/gpx` entry to document the now-optional `farmer_id`/`farm_id` and the auto-detect/ambiguous/no-match behavior.

### 7. File: `.claude/CLAUDE.md`
* Fixed a stale pointer: the manuscript link pointed at `.claude/Revised AgriSureGIS Manuscript.pdf`, but that file actually lives at `docs/Revised AgriSureGIS Manuscript.pdf` (confirmed via direct listing — it isn't in `.claude/` at all, and isn't an untracked/moved file per `git status`, so this drift predates this session). Updated the reading-order link to point at the real location. Not rewriting historical changelog entries that cite the old path (e.g. the `[2026-07-21]` Sprint 1 audit entry) — those are left as an accurate record of what was true when written, same convention as the formula-correction entry above.

### 8. Files: `frontend/src/lib/api.ts`, `frontend/src/app/components/SpatialAnalysisModule.tsx`
* `api.ts`: `uploadGpx()`'s `farmerId`/`farmId` params are now optional; added `matched_by`/`farmer_name` to `UploadGpxResult`.
* `SpatialAnalysisModule.tsx`: dropping a `.gpx` file with no table row pre-selected now calls `uploadGpx(file)` (auto-detect) instead of hard-erroring with "select a farm row first". On success, the success banner reports the matched farmer/method and the matched row is auto-highlighted (reusing the table's existing row-selection styling — no new UI surface). A pre-selected row still takes priority and behaves exactly as before (manual override unchanged). Dropzone hint text updated to mention auto-matching.

### 9. Files: `backend/tests/test_csv_upload.py`, `backend/tests/test_upload_csv_ingestion.py` (new), `backend/tests/test_gpx_farmer_matcher.py` (new), `backend/tests/test_upload_gpx_api.py` (new)
* `test_csv_upload.py`: updated for the renamed `crop_stage_seed` payload shape; added a test using the new export's exact real header spellings (`FARMID`, `Product Name`, `FarmersID`, `RiskExposureAmount`, `DistinctCount`), and a test proving blank `RSBSA No.`/`FARMID` normalize to `None` (not `""`).
* `test_upload_csv_ingestion.py`: new DB-integration-level tests against a small in-memory fake-table `db` mock (value-matched, not sequence-scripted, so it behaves like a real get-or-create across multiple rows in one upload) — direct regression tests for the farmer/farm blank-collapse bug, farmer reuse when `farmers_id` matches, the `InsuranceRecord.farmer_id`/`product_name` fixes, the crop-stage-seed shape, the `RiskExposureAmount` mismatch warning, and the cp1252 encoding fallback with a real accented surname.
* `test_gpx_farmer_matcher.py`: filename-parsing tests against the exact real sample filename (including the "missing IDs still recovers name" and "missing name still recovers IDs" tolerance cases), and `match()` tests covering every precedence branch, the middle-initial tiebreaker, the ambiguous-candidates case, and the genuine no-match case modeled on the real sample file.
* `test_upload_gpx_api.py`: `upload_gpx()` auto-detect success/no-match/ambiguous, manual-mode regression (unchanged behavior), and the exactly-one-ID-provided 400 case. No `TestClient` introduced — tested as plain function calls with a mocked `db`, consistent with how every other test in this suite already calls service/API functions directly.

### Manuscript Audit Findings (verified directly against `docs/Revised AgriSureGIS Manuscript.pdf` — footer pp.23-25 Functional/Non-Functional Requirements, p.37 `tbl_farmers_profile` dictionary, p.38 `tbl_farms` dictionary)
* **CSV column layout:** the manuscript requires CSV import (footer p.23: "allow the specialist to import the existing risk exposure report... via CSV file") but specifies no column layout for it. The new export's `FarmersID`, `FARMID` (vs. legacy `Farm ID`), `RiskExposureAmount`, `DistinctCount`, and `Product Name` are all real-world extensions the manuscript never enumerated — a gap-fill, not a conflict.
* **GPX farmer linkage — an actual deviation, not just a gap:** the manuscript's `tbl_farms` dictionary (p.38) states `location_geom` is "Populated via spatial join with the georef_id." In practice, `Georef ID` is blank on 99.8% of real CSV rows, and the real GPX file carries no `georef_id` anywhere inside it at all — only a farmer name (in a non-standard `<metadata><farmer><name>` block gpxpy doesn't surface, and in the standard `<trk><name>` it does) plus two numeric IDs in the *filename*. Filename-based matching is a necessary, pragmatic replacement for a documented mechanism that the real data can't actually support — worth stating plainly rather than softening it as mere silence.
* **`farmers_id`:** no such field exists anywhere in the manuscript's `tbl_farmers_profile` dictionary (p.37) — a pure additive extension, motivated by `farmers_id`'s 100% real-world coverage vs. `rsbsa_no`'s 71.3%.
* **Corroboration:** FR (footer p.23) explicitly requires the system to automate "matching the crop growth stage" as part of the payout calculation — independently validates item 0's finding that a crop-stage source must survive CSV ingestion. `tbl_farms.georef_id`'s dictionary example value, `"R10-13-16-012-000016"` (p.38), exactly matches the format of real populated `Georef ID` values seen in the CSV — confirms that mapping is correct where it does apply.
* **Unrelated, pre-existing divergence noted for the record only (not touched by this change):** the manuscript's `tbl_risk_assessments` dictionary (p.40) describes `final_indemnity_payment` as `amount_cover * indemnity_factor` — no `/1000`. This differs from the actual formula `(amount_cover / 1000) * indemnity_factor`, which Fabio already confirmed correct and which the `[2026-07-23]` "Formula Correction" entry above already fixed in code. Flagging only because this audit was already reading that page; no action taken.

### Status / Next Steps
* **The live database does not have the `farmers_id` column yet.** Any upload that hits the `farmers_id`-matching branch will raise `UndefinedColumn` until Fabio applies `docs/PROPOSAL_farmers_id_column.md`'s DDL. Everything else in this entry (encoding fix, header normalization, blank-collapse fix via `rsbsa_no` alone, `product_name`/`InsuranceRecord.farmer_id` fixes, the crop-stage-seed rework, and GPX matching via `farm_reference`/name) has no DDL dependency and works against the current live schema.
* Backend test suite run by Fabio (`pytest tests/ -v`): 36/43 passed on the first pass; the 7 failures were all in `test_upload_csv_ingestion.py` and all traced to the same root cause (a gap in that test file's own mock harness, not production code — see the follow-up entry directly below). Not yet re-run since the fix; not run against a live database or the frontend dev server.
* Branch is **not pushed** and has **no PR open** — needs review before merging into `develop`.

---

## [2026-07-24] - Test Fix: `RiskAssessment` Inserts in the CSV Ingestion Fake-DB Harness

Follow-up to the entry directly above, found by Fabio's first `pytest` run against it.

### 1. File: `backend/tests/test_upload_csv_ingestion.py`
* **Changes to Tests:** `_build_mock_db()`'s `add_side_effect()` only tracked the four get-or-create models (`AdminBoundary`/`FarmerProfile`/`Farm`/`InsuranceRecord`) in its fake PK-tracking table. `upload_csv()` also calls `db.add()` on a `RiskAssessment` instance (the crop-stage seed row, item 0 in the entry above) — a model the harness never queries back, so it was never added to that table, and `tables[RiskAssessment]` raised `KeyError: <class 'app.models.models.RiskAssessment'>` on every test, caught by `upload_csv()`'s broad `except Exception` and re-surfaced as a 500. Fixed by only running the PK-assignment bookkeeping for models actually present in the tracking table, while still recording every added instance (including `RiskAssessment`) in the flat `added_instances` list the tests assert against.

### Status / Next Steps
* This was a test-harness-only bug. All 36 other tests (the updated `test_csv_upload.py`, `test_gpx_farmer_matcher.py`, `test_upload_gpx_api.py`, and the rest of the existing suite) passed on the first run, meaning the actual production code from the entry above (`upload.py`, `gpx_farmer_matcher.py`, `models.py`) was already correct.
* Fabio re-ran `pytest tests/ -v`: all 43 tests passed.

---

## [2026-07-24] - CSV Ingestion: PSGC Boundary Lookup and Case-Insensitive Matching

Found by Fabio actually exercising `/api/upload/csv` end-to-end in the browser against the real `docs/Rice Risk Exposure Region X 04-15-2026.csv` — the first genuine live-DB test of this endpoint. Two real, pre-existing bugs surfaced (neither introduced by the entry above; the boundary-creation code was untouched by it):

1. **`AdminBoundary` creation never set `psgc_code`.** `tbl_admin_boundaries.psgc_code` is `NOT NULL UNIQUE`, but `upload_csv()` only ever passed `province`/`municipality`/`barangay` when creating a new boundary row. Every row whose exact boundary didn't already exist in the DB hit `psycopg2.errors.NotNullViolation` (Fabio's actual error: `null value in column "psgc_code"... Failing row contains (3, null, Agusan del Norte, REMEDIOS T. ROMUALDEZ, POBLACION II)`).
2. **The PSGC reference file only covered 2 of the CSV's 8 provinces.** `backend/app/data/psgc_region10_boundaries.csv` (888 rows) covered Bukidnon and Misamis Oriental only; the real CSV spans Agusan del Norte, Agusan del Sur, Bukidnon, Camiguin, Dinagat Islands, Misamis Oriental, Surigao del Norte, and Surigao del Sur.
3. **Case mismatch, independent of the above:** the reference file and `pabs_results.csv` both use Title Case province/municipality/barangay names, but the new CSV export uses ALL CAPS for municipality/barangay (e.g. `Bukidnon,BAUNGON,LIBORAN`). Exact-string matching (both the `AdminBoundary` get-or-create query and the new PSGC lookup) would have silently failed for nearly every row, including Bukidnon/Misamis Oriental rows that were supposedly already "covered."

### 1. File: `backend/app/data/psgc_region10_boundaries.csv`
* Appended 1,369 barangay-level rows (78 municipalities/cities) covering the 6 previously-missing provinces, sourced from `https://psgc.gitlab.io/api/` (a PSA/NAMRIA-derived PSGC API — the same class of source as the original Bukidnon/Misamis Oriental data, per the `[2026-07-23]` "Real PSGC Codes" entry). Cross-checked against the existing file before trusting it: two known entries (`Balintad` under both Baungon, Bukidnon and Manticao, Misamis Oriental) matched exactly, including the full 10-digit PSGC code. File now covers all 8 provinces the real CSV spans (2,257 total rows).
* One finding worth recording: `REMEDIOS T. ROMUALDEZ` (flagged in Fabio's error above, and initially suspected as a shifted/malformed CSV column) is confirmed to be a **real, official Agusan del Norte municipality** — not a data error. It resolves correctly once case-insensitive matching (below) is in place.
* Cities required special handling: barangays under a **city** (e.g. City of Butuan, City of Bislig) reference a `cityCode` field in the source API rather than `municipalityCode` — missed on the first extraction pass (caught 0 Butuan-area rows), fixed to check both fields.

### 2. File: `backend/app/api/upload.py`
* **Changes to Functions:**
  * Added **`_boundary_key(province, municipality, barangay)`**: normalizes (strip + uppercase) a boundary tuple for comparison, shared by both the PSGC lookup dict and the DB query below.
  * `_load_psgc_lookup()`: dict keys now built via `_boundary_key()` instead of raw CSV text, so lookups are case-insensitive.
  * `upload_csv()`: the `AdminBoundary` get-or-create query now compares `func.upper(AdminBoundary.column) == payload_value.upper()` instead of exact equality, for the same reason. Boundary rows are still **stored** with whatever casing the source CSV used (no data rewritten) — only the comparison is case-insensitive.
  * Boundary creation now looks up `psgc_code` via `_load_psgc_lookup()` before constructing `AdminBoundary(...)`, raising a clear `ValueError` (`"No PSGC code on file for (...). Add it to app/data/psgc_region10_boundaries.csv..."`, matching `seed_database.py`'s existing message style) instead of letting a missing code reach the database as a cryptic constraint violation.

### 3. File: `backend/tests/test_upload_csv_ingestion.py`
* Added `test_missing_psgc_code_raises_clear_error_not_db_constraint_violation` — regression test for the exact failure Fabio hit.
* The fake-DB `_FakeQuery`/`_FakeTable` harness needed a real fix, not just a cosmetic one: it introspected filter criteria as plain `Model.column == value` expressions, but `func.upper(Model.column) == value` has a different shape (`.left` is the `Function`, not the `Column`). Without handling this, the harness would have silently stopped matching on province/municipality/barangay at all (every row would appear to create a brand-new boundary instead of reusing one) rather than failing loudly — fixed to detect the `func.upper(...)` wrapper, pull the real column name from its wrapped argument, and apply the same uppercase transform to the stored value before comparing.
* `_FAKE_PSGC_LOOKUP`'s key updated to the uppercase-normalized form `_boundary_key()` now produces (was previously keyed by the raw Title-Case text, which no longer matches).

### Status / Next Steps
* Not yet re-verified against a live database — Fabio needs to re-attempt the CSV drop in the browser to confirm the real file now ingests (or fails only on genuinely bad rows, e.g. a `Surigao del Norte,DDINAGAT` typo spotted in passing — looks like a real source-data typo, not something to silently "correct").
* **Resolved by the entry below:** whether the whole 23,917-row import should abort on the first bad row, or isolate failures per-row. Fabio chose per-row isolation.

---

## [2026-07-24] - CSV Ingestion: Per-Row Failure Isolation

Follow-up to the entry above. `upload_csv()` previously wrapped the *entire* row loop in one try/except with a single `db.commit()` at the end — any row's exception (e.g. the PSGC lookup failure two entries up, or a genuine data-quality row like the `DDINAGAT` typo) rolled back the whole batch, discarding every other already-processed row. Given a 23,917-row real export is not going to be perfectly clean, Fabio confirmed per-row isolation is wanted over all-or-nothing.

### 1. File: `backend/app/api/upload.py`
* **Changes to Functions:**
  * Extracted **`_ingest_row(payload, db)`**: the per-row boundary/farmer/farm/insurance/crop-stage-seed logic, unchanged in behavior, pulled out of `upload_csv()`'s loop body into its own function. Returns `"inserted"` or `"skipped"`; raises on any unrecoverable problem (missing PSGC code, etc.) for the caller to handle.
  * `upload_csv()`: each row now runs inside its own SQLAlchemy SAVEPOINT (`db.begin_nested()`). On success, the savepoint is committed (still pending in the outer transaction, not yet durable) and the loop continues; on failure, only that row's savepoint is rolled back — every previously-processed row in the same upload is unaffected — the row is counted in a new `rows_failed`, and `{row, policy_no, error}` is appended to a new `failures` list (capped at 50 entries in the response to avoid a pathological response size if the PSGC data or CSV itself turns out to be more broken than expected; `rows_failed` itself is always the true total). The outer try/except is kept for genuinely unexpected failures (e.g. the final `db.commit()` itself failing) — that still aborts and rolls back everything, since at that point something is wrong beyond a single row's data.
  * Response `message` now says `"CSV data ingested with N row(s) skipped due to errors."` when `rows_failed > 0`, instead of always claiming full success.

### 2. Files: `frontend/src/lib/api.ts`, `frontend/src/app/components/SpatialAnalysisModule.tsx`
* `api.ts`: added `UploadCsvRowFailure` type and `rows_failed`/`failures` to `UploadCsvResult`.
* `SpatialAnalysisModule.tsx`: CSV upload success banner now appends `", N failed"` when `rows_failed > 0` (previously only showed inserted/skipped counts). No new UI surface for browsing individual failures yet — `result.failures` is available on the response for a future "view details" affordance if wanted, but the *count* was the priority for the GIS specialist to at least know something needs attention.

### 3. File: `backend/tests/test_upload_csv_ingestion.py`
* Renamed/updated `test_missing_psgc_code_raises_clear_error_not_db_constraint_violation` → `test_missing_psgc_code_is_reported_as_a_row_failure_not_a_raised_exception`: with per-row isolation, this case no longer raises out of `upload_csv()` at all — it's now a normal 200 response with the failure captured in `result["failures"]`.
* Added `test_one_bad_row_does_not_abort_the_rest_of_the_batch`: two rows, one with an unmappable boundary — asserts the good row's `FarmerProfile`/`InsuranceRecord` are still present and counted, and the bad row is isolated in `failures` rather than wiping out the batch.

### 4. File: `.claude/API_CONTRACT.md`
* Documented the per-row SAVEPOINT behavior and the new `rows_failed`/`failures` response fields for `POST /api/upload/csv`.

### Status / Next Steps
* Awaiting Fabio's re-run of `pytest tests/ -v`, then a re-attempt of the real CSV drop in the browser — expecting the bulk of the 23,917 rows to now ingest successfully, with any remaining genuine data-quality rows (e.g. `DDINAGAT`) reported in `failures` rather than blocking everything else.
* No mechanism yet to *fix* a reported bad row and re-run just that one — re-uploading the same CSV after a fix is safe (already-inserted policies are skipped via the existing `policy_no` uniqueness check), just not surgical. Not building that now — flagging in case it's wanted later.
* **Superseded in part by the entry below:** Fabio tried the real 23,917-row CSV and the request never returned within several minutes — this entry's per-row SAVEPOINTs, on top of the pre-existing per-row SELECT queries, meant far more DB round trips per row than before, with no caching of repeated lookups within the same upload.

---

## [2026-07-24] - CSV Ingestion: Cache Repeated Boundary/Farmer/Farm Lookups Within One Upload

Fabio reported the real CSV upload appeared to hang (waited several minutes, backend terminal showed no activity). Root cause: the real file's 23,917 rows span far fewer distinct boundaries/farmers than rows — the same barangay repeats across roughly 10-20 rows on average, and the same farmer across ~1.2 rows — but every row was independently re-querying the database for its boundary/farmer/farm via `SELECT`, on top of the new per-row SAVEPOINT overhead from the entry above. Nothing had actually deadlocked; it was just doing many times more DB round trips than necessary. Since the whole upload is one outer transaction that only commits at the very end, nothing was lost by the wait — safe to just retry after this fix.

### 1. File: `backend/app/api/upload.py`
* **Changes to Functions:**
  * Added **`_IngestCaches`** (dataclass): four in-process dicts (`boundaries`, `farmers_by_farmers_id`, `farmers_by_rsbsa_no`, `farms_by_reference`) scoped to a single `upload_csv()` call. Populated by the caller **only after** a row's SAVEPOINT successfully commits — a rolled-back row's newly-created objects must never be cached for a later row to reuse, since the DB-level insert they'd point to no longer exists.
  * Added **`_RowIngestResult`** (dataclass): what `_ingest_row()` now returns (outcome, the resolved boundary/farmer/farm objects and their cache keys) so `upload_csv()`'s loop can update the caches after each successful commit.
  * Extracted **`_ingest_row(payload, db, caches)`**: same per-row logic as the entry above, now checking `caches` before issuing any `SELECT` for boundary/farmer/farm, only hitting the database on a cache miss.
* This is purely an internal optimization — no change to `upload_csv()`'s request/response contract, ingestion order, or the get-or-create/blank-matching rules from earlier entries.

### 2. File: `backend/tests/test_upload_csv_ingestion.py`
* `_build_mock_db()` now tracks `query_call_counts` per model, so tests can assert on query *volume*, not just correctness.
* Added `test_repeated_boundary_across_many_rows_is_only_queried_once` and `test_same_rsbsa_no_across_rows_is_only_queried_once` — direct regression tests for this exact problem, asserting the database is queried once per distinct boundary/farmer rather than once per row.

### Status / Next Steps
* The caching fix worked (request returned quickly instead of hanging), but Fabio's next attempt reported all 23,917 rows failed. **Resolved by the entry below**, a distinct bug this caching change wasn't responsible for.

---

## [2026-07-24] - CSV Ingestion: Coerce Every VARCHAR-Mapped ID to a String

Fabio's retry (fast this time, confirming the caching fix above worked) reported **every single row failing identically**: `psycopg2.errors.UndefinedFunction: operator does not exist: character varying = integer` on `WHERE tbl_insurance_records.policy_no = 1192155`. Root cause: `Policy No.` in the real PABS export is purely numeric (e.g. `1192155`), so pandas infers that whole column as `int64` — `prepare_row_payload()` only ever coerced `FARMID`/`FarmersID` to text via `_stringify_id()`, not `Policy No.` (or `RSBSA No.`/`Georef ID`, which have the same latent risk even though the current file's values happen to be dash-formatted). This bug predates this session entirely — the original `upload_csv()` had the identical `_normalize_value(data.get("Policy No.")) or ""` line — it just never surfaced because nobody had run it against a live database with a real, purely-numeric Policy No. column before now. None of this session's own tests caught it either, since every test fixture used a non-numeric policy number like `"POL-1"`, which never exercises pandas' numeric type inference at all.

### 1. File: `backend/app/api/upload.py`
* **Changes to Functions:**
  * `prepare_row_payload()`: `policy_no`, `rsbsa_no`, and `georef_id` are now all passed through `_stringify_id()`, same as `farmers_id`/`csv_farm_reference` already were. All five are VARCHAR-mapped identifiers that PABS could plausibly export as pure digits in some file even if the current one only demonstrates it for `Policy No.`.
  * `_stringify_id()`'s docstring updated to reflect it's a general "every ID column read from this CSV" helper, not FARMID/FarmersID-specific.

### 2. Files: `backend/tests/test_csv_upload.py`, `backend/tests/test_upload_csv_ingestion.py`
* Added `test_purely_numeric_policy_no_is_coerced_to_string` (`test_csv_upload.py`) — parses a **real CSV string** through `pd.read_csv()` (not a hand-built `pd.DataFrame([...])`, which never exercises pandas' own type inference) with an all-digit Policy No., confirming it comes out of `prepare_row_payload()` as `str`.
* Added `test_purely_numeric_policy_no_ingests_successfully_end_to_end` (`test_upload_csv_ingestion.py`) — same scenario through the full `upload_csv()` call, asserting `rows_failed == 0` and the stored `InsuranceRecord.policy_no` is a string.
* Neither existing test suite caught this originally because every fixture used letters in its policy numbers (`"POL-001"`, `"POL-1"`, etc.) — worth remembering when writing CSV-ingestion test fixtures going forward: use realistic, purely-numeric IDs where the real PABS data is purely numeric, not letter-prefixed placeholders that accidentally dodge pandas' type inference.

### Status / Next Steps
* Awaiting Fabio's re-run of `pytest tests/ -v`, then a fresh CSV upload attempt — this should be the last blocker for a full, successful end-to-end ingestion of the real 23,917-row file (modulo any genuinely bad individual rows like the `DDINAGAT` typo, which will now report cleanly in `failures` instead of blocking anything).

---

## [2026-07-26] - Sample Ingestion Assets Added to `docs/`

No backend/frontend code touched. Fabio dropped four real-world sample artifacts into `docs/` for GPX-matching/ingestion work on this branch; a replacement flowchart export also lands here (the old `docs/Flowchart.drawio.png` stays as-is, unrelated to this branch's revert).

### 1. File: `docs/Rice Risk Exposure Region X 04-15-2026.csv` (new)
* Trimmed from the original ~23,918-row PABS export down to 100 lines (header + 99 rows) at Fabio's request, so it's usable as a lightweight test fixture instead of the full file.
* The naive first-100-rows slice was 94/99 `RSBSA` `Program Type` rows (only 5 non-`RSBSA`), which isn't representative — the full file's `Program Type` column has 8 distinct values (`RSBSA`, `APCP`, `ACEF PROGRAM`, `AGRI-PUHUNAN PROGRAM`, `RSBSA - ARB`, `AGRISENSO PROGRAM`, `ANYO PROGRAM`, `OTHER - LI LC`), and non-`RSBSA` rows are only 437 of 23,917 total, sparse and scattered throughout the file. Rebuilt as: the first 92 `RSBSA` rows (original order) + the first occurrence of each of the 7 non-`RSBSA` program types, merged back into original row order — giving a 100-line sample that exercises every program type instead of being effectively all-`RSBSA`.

### 2. File: `docs/TAB_ABAO , JONEL  J._120961_1148107_2024-08-06.gpx` (new)
* Real farmer GPX boundary track sample for this branch's GPX-matching work.

### 3. File: `docs/RICE_Insured-Farms_with-PPI-Polygon_02-09-2026.xlsx` (new)
* Real insured-farms reference workbook with PPI polygon data.

### 4. File: `docs/Parametric_Indemnity_Process_Flowchart.drawio.png` (new)
* Updated flowchart export. Added alongside (not replacing) the existing `docs/Flowchart.drawio.png`, which an earlier revert on this branch restored to its committed state.

### Status / Next Steps
* Committed on `fabio/db/pabs-ingestion-gpx-matching`, which has never been pushed to `origin` before now — this is the branch's first push, needs `git push -u origin fabio/db/pabs-ingestion-gpx-matching` (no upstream configured yet).

---

## [2026-07-27] - Automated PAGASA TCB Ingestion (Background Scheduler + In-App Notification)

TCB ingestion was 100% manual: a GIS specialist had to click "Parse Latest Bulletin" to trigger `POST /api/bulletins/parse`. Per Fabio's decisions (scraping + in-app pop-up only, no email; in-process APScheduler, no OS cron; wire the interval to the existing mock "TCB Polling Interval" Calibration field rather than hardcoding it), this entry automates the scrape/parse/save pipeline and makes the interval live-configurable. Schema change proposed and approved per `docs/PROPOSAL_parser_settings_table.md` — **not yet applied to any live database**, that's Fabio's `psql -f init_schema.sql` to run.

### 1. File: `backend/app/services/bulletin_parser.py`
* Added **`BulletinParserService.scrape_and_save_all(db, temp_dir="temp_bulletins")`**: extracts the fetch→download→parse→save loop previously inlined in `trigger_pagasa_scrape`. Pure refactor, no behavior change — but unlike the HTTP route, this method never raises on an empty/all-failed result, since the new scheduled job needs "nothing new found" to be a quiet, normal outcome rather than an error.

### 2. File: `backend/app/api/bulletins.py`
* `trigger_pagasa_scrape` (`POST /parse`) is now a thin wrapper: still raises `404` if no links are found (unchanged HTTP contract for the manual button), then delegates to `scrape_and_save_all`.
* Added **`GET /settings`** / **`PUT /settings`** (→ `/api/bulletins/settings`), backed by the new `ParserSettings` model: `GET` returns the current polling interval (get-or-create a default row if missing); `PUT` validates `1-24` via a new inline `ParserSettingsUpdate(BaseModel)` (matching this file's existing convention from `assessments.py` — no `app/schemas/` module exists in this codebase), persists the new value, and reschedules the **live** APScheduler job via `request.app.state.scheduler`.

### 3. File: `backend/app/models/models.py`
* Added **`ParserSettings`**: maps the new `tbl_parser_settings` single-row config table (`polling_interval_hours`, `updated_at`).

### 4. File: `backend/init_schema.sql`
* Added `tbl_parser_settings` (+ drop, + seed row `polling_interval_hours = 3`, matching the frontend's existing default). See `docs/PROPOSAL_parser_settings_table.md` (new) for the full proposal — this is the one schema change in this entry.

### 5. File: `backend/app/core/scheduler.py` (new)
* Added **`build_scheduler(initial_interval_hours)`**: registers a `BackgroundScheduler` job (`id="pagasa_bulletin_poll"`, `max_instances=1` to guard against overlapping runs if a scrape outlasts the interval).
* Added **`run_scheduled_scrape()`**: the APScheduler job target. Opens/closes its own `SessionLocal()` session (no FastAPI request context exists in a background job, so `Depends(get_db)` isn't usable here), drives the async `scrape_and_save_all` via `asyncio.run(...)`, and never lets an exception escape the job (logs instead) so one bad scrape can't kill the scheduler thread.
* Added **`reschedule_bulletin_job(scheduler, new_interval_hours)`**: used by the `PUT /settings` route to reconfigure the already-running job in place.
* Used `BackgroundScheduler` (thread-based), not `AsyncIOScheduler` — the job mixes `await httpx` calls with sync SQLAlchemy/pdfplumber work, so it's simpler to drive the async call via `asyncio.run(...)` inside a plain scheduler thread than to integrate with uvicorn's own event loop.
* **Known limitation, not engineered around:** this repo's documented dev setup is single-worker `uvicorn --reload`, so exactly one scheduler runs at a time. A hypothetical multi-worker deployment would start one independent scheduler per worker, all polling redundantly — harmless (saves are idempotent per `(typhoon_id, bulletin_count)`) but wasteful. Out of scope.

### 6. File: `backend/app/main.py`
* Replaced `app = FastAPI(...)` with a `lifespan` async context manager: on startup, reads the persisted interval from `tbl_parser_settings` (defaults to 3 if missing), builds and starts the scheduler, stashes it on `app.state.scheduler`, and logs the interval; on shutdown, `scheduler.shutdown(wait=False)`. Everything else in `main.py` is unchanged.

### 7. File: `backend/requirements.txt`
* Added `APScheduler==3.11.0`.

### 8. File: `frontend/src/lib/api.ts`
* Added **`ParserSettings`** interface + **`getParserSettings()`** / **`updateParserSettings(hours)`**, following the existing `request<T>()` wrapper pattern.

### 9. File: `frontend/src/app/App.tsx`
* Added a `useEffect` (gated on `currentUser`) polling `getBulletins()` every 60s, tracking the highest `tcb_id` seen in a `ref`. First poll after login only records the baseline — it does not notify about bulletins that already existed. When a higher `tcb_id` appears (i.e. the background scheduler parsed something new with no button click involved), pushes a real `AppNotification` (matching `mockData.ts`'s existing interface/wording) onto the `notifications` state already wired to `Header`'s bell dropdown, and fires a `sonner` `toast.success(...)` (the `<Toaster>` was already mounted).
* Changed the initial `notifications` state from `useState(mockNotifications)` to `useState([])`, since it's now populated by real events. `mockData.ts` itself is untouched — `mockNotifications` isn't imported anywhere else.
* No WebSockets/SSE — plain polling of the existing list endpoint, matching this project's synchronous-HTTP-only style.

### 10. File: `frontend/src/app/components/CalibrationModule.tsx`
* `parserInterval` stays local `useState` (no `App.tsx` prop-drilling needed — nothing else in the app needs this value client-side) but is now backed by a `useEffect` that calls `getParserSettings()` on mount, and `handleSave()` now also calls `updateParserSettings(parserInterval)` alongside its existing local "Settings saved" banner. No JSX/layout changes — same input, same styling.

### 11. Files: `backend/tests/test_bulletin_parser.py`, `backend/tests/test_parser_settings_api.py` (new), `backend/tests/test_scheduler.py` (new)
* `test_bulletin_parser.py`: added `ScrapeAndSaveAllTests` (`unittest.IsolatedAsyncioTestCase`, this repo's first async test) — empty-links returns `[]` without raising; a failing link is skipped while the rest still process; happy-path dict shape.
* `test_parser_settings_api.py`: get-or-create default row; existing-value read; update persists + calls `reschedule_bulletin_job` (mocked); Pydantic `ge=1,le=24` rejects out-of-range values via direct `ParserSettingsUpdate` construction — matches this suite's existing convention of calling route functions directly with a mocked `db`/fake `request`, never `TestClient`.
* `test_scheduler.py`: `build_scheduler`/`reschedule_bulletin_job` register/update the job with the right interval. Deviates slightly from the original plan (which assumed `get_job()` works without `.start()`) — APScheduler keeps unstarted jobs in a pending queue not visible to `get_job()`, so these tests `.start()` then immediately `.shutdown(wait=False)` in a `finally` block. Since the interval is always in hours (minimum 1h), the job cannot actually fire within a test's lifetime — no real network/DB activity occurs. Confirmed safe more broadly: no test in this suite imports `app` from `main.py` (all call functions/services directly), so `lifespan` — and the real scheduler/network calls — never run during `pytest` collection.

### Status / Next Steps
* **Schema not yet applied** — `tbl_parser_settings` doesn't exist on any live database yet. `GET/PUT /api/bulletins/settings` and the scheduler's startup read will raise `UndefinedTable` until Fabio re-runs `init_schema.sql` (or applies the equivalent `CREATE TABLE`/`INSERT` from `docs/PROPOSAL_parser_settings_table.md`).
* `APScheduler` needs `pip install -r requirements.txt` in Fabio's venv before the backend will start.
* Not run against a live database or `pytest` — Fabio needs to run the test suite himself, then the manual end-to-end verification (scheduler starts with logged interval; changing/saving the Calibration interval reschedules the live job per a log line, without restarting `uvicorn`; a simulated new bulletin — e.g. via the existing `/api/bulletins/upload` fallback — shows up as a toast/bell notification within ~60s with no manual "Parse Latest Bulletin" click).
* No email/SMTP notification (out of scope per Fabio's decision) — only the in-app toast/bell.

---

## [2026-07-27] - Fix: `ParserSettings` Mapper Crash + Typhoon Name/Grouping Bugs

Fabio's first `pytest` run after the entry above hit 10 collection errors (`ModuleNotFoundError: No module named 'app'` — fixed by running `python -m pytest` instead of bare `pytest`, since the `pytest` console-script doesn't add cwd to `sys.path` and this repo has no `pytest.ini`/`conftest.py` to do it another way), then a second run surfaced 18 real test failures. Root cause of nearly all of them: one stray line I introduced.

### 1. File: `backend/app/models/models.py`
* **Bug fix:** Removed a stray `boundary = relationship("AdminBoundary")` line accidentally left on the new `ParserSettings` model (added in the entry above) — `ParserSettings` has no `boundary_id` column at all. SQLAlchemy configures every mapper in the registry together on first use; this one broken relationship (`NoForeignKeysError: ... between 'tbl_parser_settings' and 'tbl_admin_boundaries'`) cascaded into totally unrelated test failures across `test_assessment_service.py`, `test_bulletin_parser.py`, `test_exposure_calculator.py`, and all of `test_upload_csv_ingestion.py` (the last of these especially misleadingly — `upload_csv()`'s per-row try/except silently caught the resulting `InvalidRequestError` on every row and recorded it as a row failure instead of raising, so the symptom looked like a CSV-ingestion regression rather than a models.py typo). Verified fixed via a standalone `configure_mappers()` check before handing back to Fabio to re-run the full suite.

### 2. File: `backend/app/services/bulletin_parser.py`
Separately, while looking at the Monitoring module's "Typhoon Events" list, Fabio spotted duplicate-looking entries — "Typhoon KIYAPO" next to "Typhoon KIYAPO Issued at", etc.
* **Bug fix — `parse_bulletin_text()`:** the typhoon-name capture group `[A-Z\s\-]+` had no upper bound and, with `re.IGNORECASE`, happily consumed through a following word (since `\s` matches the space between words, and even newlines) whenever the source PDF didn't wrap the name in quotes — e.g. `TYPHOON GARDO Issued at 5:00 PM...` parsed as name `"GARDO Issued at"` instead of `"GARDO"`. Tightened to `[A-Z][A-Z\-]*` — a single word, matching the Philippine local-name convention — so it stops at the first space.
* **Changed `save_bulletin_to_db()`'s "Get or Create Typhoon" step**, per Fabio's decision: group bulletins under the same `Typhoon` row by name (case-insensitive) **and** recency — a bulletin only joins an existing typhoon if that typhoon has some bulletin issued within the last 30 days (`reference_time = parsed_data["issued_at"] or now`; `window_start = reference_time - 30 days`; query joins `Typhoon` to `TropicalCycloneBulletin`, filters `issued_at >= window_start`, orders by `issued_at desc`). Previously it matched by name + current calendar-year only (`Typhoon.year == datetime.now().year`), which had two problems: (a) it used *today's* year rather than the bulletin's own year, so a bulletin from a prior year processed later would misfile; (b) PAGASA's local-name list rotates and reuses names across separate seasons, so a bare name match had no time bound at all and could wrongly merge unrelated storms. Any bulletin number for an ongoing typhoon (bulletin No. 10, 20, ...) still lands well inside the 30-day rolling window since real bulletins for one event are issued every few hours, not weeks apart — per Fabio's confirmation.
* New `Typhoon` rows now get `year=reference_time.year` (the bulletin's own issued year) instead of `datetime.now().year`.

### 3. File: `backend/cleanup_typhoon_names.py` (new)
* One-off script (not run automatically, not wired to any endpoint) to fix `Typhoon` rows already corrupted by the name-regex bug before this fix landed: derives each row's "clean" name using the same single-word rule, then either merges the corrupted row's bulletins into an existing clean-named row and deletes the corrupted row, or renames the corrupted row in place if no clean counterpart exists yet.

### 4. File: `backend/tests/test_bulletin_parser.py`
* Added `test_parse_bulletin_text_name_does_not_swallow_trailing_issued_at` — regression test for the regex fix.
* Added `test_reuses_existing_typhoon_when_a_bulletin_is_within_30_days` and `test_creates_new_typhoon_when_no_bulletin_within_30_days` — cover both branches of the new grouping logic.
* Updated `_build_mock_db()`'s Typhoon-query mock to match the new `.join(...).filter(...).order_by(...).first()` chain (previously just `.filter(...).first()`), with a new `existing_typhoon` parameter so tests can control the "found within window" vs. "not found" outcome.

### Status / Next Steps
* Fabio needs to re-run `python -m pytest tests/ -v` from `backend/` to confirm all failures are now resolved (not yet re-run since these fixes).
* **`cleanup_typhoon_names.py` has not been run against the live database** — needs Fabio to run it himself (`python cleanup_typhoon_names.py` from `backend/`, in his venv) to fix the corrupted rows already visible in his screenshot. Existing `TcbSignal` rows pointing at a to-be-deleted corrupted `Typhoon` are unaffected (they key off `tcb_id`, not `typhoon_id`).

---

## [2026-07-27] - Bulletin Parsing Rewrite: Bulletin Number, Category, Coordinates, Real TCWS Table

Fabio provided a real sample bulletin (`docs/TCB#11_kiyapo.pdf` — Tropical Storm KIYAPO, Bulletin NR. 11) and pointed at the `pagasa-parser` project (github.com/pagasa-parser) as a reference implementation. Running our existing `parse_bulletin_text()` against this real file (not a hand-typed mock) surfaced four concrete bugs beyond the name-regex fix from the entry above. Fixes below are modeled on `@pagasa-parser/source-pdf`'s regex approach (confirmed via its published source: `Tropical Cyclone Bulletin N[ro]\. (\d+)` for the bulletin number, a title-line-anchored category/name/international-name pattern, and `([0-9.]+)°([NS]),\s?([0-9.]+)°([WE])` for coordinates) and its use of real PDF table extraction (`tabula-java` in their Node.js stack) for the TCWS signal table, rather than regex-scanning flattened prose.

### 1. File: `backend/app/services/bulletin_parser.py`
* **Bug fix — bulletin number:** real bulletins abbreviate to `"BULLETIN NR. 11"`, not `"Bulletin No. 11"`. Regex widened to `N[ro]\.` (matches both). Against the real sample, this was silently defaulting to `1` for every bulletin.
* **Bug fix — category:** replaced the old `"Typhoon" if "typhoon" in text.lower() else "Tropical Storm"` substring check — which false-positived whenever the word "typhoon" appeared anywhere else in the bulletin's forecast prose (e.g. "may be upgraded... reach typhoon category") — with extraction directly from the title line itself (e.g. `"Tropical Storm KIYAPO (NOUL)"`), via one regex anchored to line-start (`^\s*(TYPHOON|TROPICAL STORM|...)`) that also captures the name and, as a bonus, the international name in parentheses. Against the real sample this was misreporting a Tropical Storm as a "Typhoon".
* **New field:** `parsed_data["international_name"]` (e.g. `"NOUL"` for KIYAPO) — captured for free by the same title-line regex. Not yet wired into `save_bulletin_to_db()`/the `Typhoon` model; available for future use.
* **Bug fix — coordinates:** real phrasing is a parenthesized `"(18.8°N, 122.0°E)"` pair with a full clause between the word "at" and the actual numbers (`"...data at over the coastal waters of ... (18.8°N, 122.0°E)"`), and the old fallback regex was missing the `°` symbol entirely — so neither of the two old patterns matched, and every real bulletin silently got `latitude=0.0, longitude=0.0`. Replaced both with one pattern, `([0-9.]+)\s*°\s*([NS]),\s*([0-9.]+)\s*°\s*([EW])`, matched anywhere in the text.
* **Rewrite — signal/area extraction:** PAGASA bulletins contain the signal-area data as an actual table (`TCWS No. | Luzon | Visayas | Mindanao`, one row per signal level, `"-"` where a column doesn't apply, confirmed against the real sample's actual `page.extract_tables()` output) — not free prose. The old approach regex-scanned the flattened text for any "Signal No. X" occurrence, which had no way to tell the real table apart from a narrative sentence merely *mentioning* a signal (e.g. "The hoisting of Wind Signal No. 3 is not ruled out should KIYAPO intensify...") — against the real sample this fabricated phantom signals `{1, 2, 3}` from unrelated narrative text. Now uses `page.extract_tables()` (already available via `pdfplumber`, already a dependency — no new library needed, unlike `pagasa-parser`'s Java/tabula-java requirement), locates the table row containing "Mindanao" in its header, and reads only that column per signal level (this project is scoped to PCIC Region X/Mindanao per `PROJECT_CONTEXT.md`, so Luzon/Visayas columns are intentionally not extracted). `signals_data` keeps its original `{level: text}` shape, so `save_bulletin_to_db()` needed no changes.
* Note: the real sample (KIYAPO) only has Luzon areas — its Mindanao column is `"-"` for every signal level — so `signals == {}` is the **correct** result for this file, not a remaining bug.

### 2. File: `backend/tests/test_bulletin_parser.py`
* Added a `_mock_pdf(text, tables=None)` helper (every mock page now sets both `extract_text` and `extract_tables`, since the production code now reads both).
* Added `test_parse_bulletin_text_extracts_bulletin_number_with_nr_abbreviation`, `test_parse_bulletin_text_category_is_not_fooled_by_the_word_elsewhere_in_the_text`, `test_parse_bulletin_text_extracts_coordinates_with_degree_symbol_and_no_at_prefix`, `test_parse_bulletin_text_extracts_mindanao_signals_from_table` (mocked table matching the real sample's shape, including a "Warning lead time" continuation row with a blank first cell that must stay attributed to the running signal level, and a Signal 1 row whose Mindanao cell is `"-"` and must be excluded).
* Added `test_parse_bulletin_text_against_real_sample_pdf` — a true end-to-end regression test that opens `docs/TCB#11_kiyapo.pdf` directly (no mocks) and asserts the exact real values (name, international name, bulletin number, category, winds, coordinates, issued-at, and the correct empty `signals`).
* Updated the existing metadata/issued-at tests to use the new `_mock_pdf` helper (previously missing `extract_tables`, which would now raise `TypeError` since the new code always iterates it).

### Status / Next Steps
* Verified directly (regex/table logic hand-run against both mocks and the real PDF) before handing back, but **not yet run through the actual `pytest` suite** — needs Fabio's `python -m pytest tests/ -v` re-run, same as the entry above.
* `international_name` is parsed but not persisted anywhere yet — flag for later if Fabio wants it stored on `tbl_typhoons`.
* Did not port `pagasa-parser`'s full `AreaExtractor` (directional-qualifier parsing like "eastern portion of X" into structured province/part/municipality JSON) — our `TcbSignal`/`AdminBoundary` matching only needs municipality-level substring matching today, so this was intentionally left out as bigger scope than asked; flagging in case finer-grained (barangay/partial-area) signal data is wanted later.

---

## [2026-07-27] - Final-Bulletin Detection: Auto-Close Typhoon + Auto-Run Exposure Summary

Fabio confirmed PAGASA's real signal for "no more bulletins will follow" is a trailing `F` on the bulletin number itself (e.g. `"NR. 21F"` for Francisco's last bulletin) — not any particular closing-sentence wording (which we have no real sample of). Per Fabio's decision, a detected final bulletin now auto-closes the typhoon and auto-runs the exposure summary; it deliberately stops short of the assessment/payout calculation, which stays a separate manual step.

### 1. File: `backend/app/services/bulletin_parser.py`
* **`parse_bulletin_text()`:** bulletin-number regex widened to `N[ro]\.\s+(\d+)([A-Za-z]?)`, capturing an optional trailing letter. New `parsed_data["is_final"]` = `True` when that letter is `"F"`/`"f"`. Verified against both the real KIYAPO sample (`bulletin_count=11, is_final=False` — it explicitly says "next bulletin at 5:00 PM today") and a synthetic Francisco `"NR. 21F"` case (`bulletin_count=21, is_final=True`).
* **`save_bulletin_to_db()`:** when `is_final` is set and the resolved `Typhoon.is_active` is still `True`, flips it to `False` and commits — the first code path that ever sets this existing-but-previously-unused column.
* **`scrape_and_save_all()`:** added `from app.services.exposure_calculator import ExposureCalculatorService`; after a final bulletin is saved, calls `ExposureCalculatorService.compute_for_typhoon(bulletin.typhoon_id, db)` inline (inside the existing per-link try/except, so a failure here doesn't crash the rest of the scrape loop). Since both the manual `POST /api/bulletins/parse` route and the new scheduled job funnel through this one shared method, this trigger applies to both without duplicating logic. `bulletins_created` dict entries now also include `"is_final"`.

### 2. File: `backend/tests/test_bulletin_parser.py`
* Added `test_parse_bulletin_text_detects_final_bulletin_marker` (the `"NR. 21F"` case) and an `is_final` assertion on the existing NR./real-sample tests.
* Added `test_save_bulletin_to_db_marks_typhoon_inactive_when_final` — uses a real `Typhoon(...)` instance (not a `MagicMock`) as `existing_typhoon` so `.is_active`'s actual before/after state can be asserted directly.
* Added `test_final_bulletin_triggers_exposure_summary` and `test_non_final_bulletin_does_not_trigger_exposure_summary` to `ScrapeAndSaveAllTests`, patching `app.services.bulletin_parser.ExposureCalculatorService.compute_for_typhoon` to assert it's called with the right `typhoon_id` only in the final case.
* Updated `test_returns_created_bulletin_dicts_on_happy_path`'s exact-dict assertion to include the new `"is_final"` key.

### Status / Next Steps
* Verified directly (hand-run against both the auto-trigger and typhoon-inactive scenarios) before handing back; not yet run through `pytest` — needs Fabio's re-run, same as the two entries above.
* The assessment/payout calculation (`AssessmentService.calculate_for_bulletin()`) intentionally still requires a manual `POST /api/assessments/calculate` call even after a final bulletin — per Fabio's explicit scope decision, not an oversight.
* Only real-world confirmation of the `F`-suffix convention is Fabio's own domain knowledge (Francisco's `"NR. 21F"`) — no real *final* bulletin PDF was available to verify end-to-end the way `docs/TCB#11_kiyapo.pdf` verified the other parsing fixes. Worth dropping a real final-bulletin sample into `docs/` later if one becomes available.

---

## [2026-07-27] - Active-Typhoon Reconciliation Against PAGASA's Current Listing

Fabio asked for a way to cross-check whether the typhoons we have on file are still actually "active" per PAGASA, since the "F" final-bulletin marker (previous entry) is only a signal PAGASA sometimes sends — it doesn't cover a storm that simply stops getting new bulletins without one. Per Fabio's decisions: this runs automatically as part of the existing scheduler/scrape cycle (not a separate on-demand endpoint), and closing a stale typhoon does the same thing the final-bulletin path does (mark inactive + auto-run the exposure summary).

### 1. File: `backend/app/services/bulletin_parser.py`
* **New `PagasaScrapeError` exception** + **behavior change in `fetch_active_bulletin_links()`**: previously swallowed *any* failure (bad HTTP status or a network exception) into a bare `return []`, identical to a successful check that genuinely found nothing active. Now raises `PagasaScrapeError` for real failures; `[]` is returned only for a confirmed-successful check with zero links. This distinction matters because the new reconciliation step (below) treats an empty result as "PAGASA confirms nothing is active — close everything still marked active," which would have been actively dangerous to trigger off of a transient network hiccup instead of a real empty check.
* **New `ACTIVE_LINK_NAME_RE`** (module-level): `TCB#\d+[A-Za-z]?_([A-Za-z]+)\.pdf` — parses the storm name out of a real PAGASA bulletin filename (e.g. `"TCB#11_kiyapo.pdf"` → `KIYAPO`). Tolerates an optional trailing letter on the bulletin number (`"TCB#21F_francisco.pdf"`) since Fabio confirmed the same "F" final-bulletin marker can appear in the filename's own number, not just inside the PDF text.
* **New `_reconcile_active_typhoons(active_links, db)`**: for every `Typhoon` row still marked `is_active=True`, checks whether its name appears among the storm names parsed from `active_links`; if not, closes it (`is_active=False` + `ExposureCalculatorService.compute_for_typhoon(...)`) — same action as an explicit final bulletin, just triggered by absence from PAGASA's list instead. An empty-but-successful `active_links` list correctly means "close everything."
* **`scrape_and_save_all()`**: calls `_reconcile_active_typhoons(links, db)` once, after the per-link download/parse/save loop, using the same `links` already fetched at the top of the method. Since the initial `links = await cls.fetch_active_bulletin_links()` call is *not* wrapped in the per-link try/except, a `PagasaScrapeError` here propagates straight out of `scrape_and_save_all()` — skipping the loop and reconciliation entirely — and is caught by the scheduler job's own top-level try/except (`backend/app/core/scheduler.py`'s `run_scheduled_scrape()`), so a failed PAGASA check just gets logged and retried next cycle rather than closing anything.

### 2. File: `backend/app/api/bulletins.py`
* `trigger_pagasa_scrape()` now catches `PagasaScrapeError` from its own initial `fetch_active_bulletin_links()` check and returns the same existing `404 "No active bulletin PDFs found on PAGASA portal."` response as a genuinely empty result — no visible behavior change for the manual-trigger button, just an internal distinction that only matters for reconciliation.

### 3. File: `backend/tests/test_bulletin_parser.py`
* New `FetchActiveBulletinLinksTests` (mocking `httpx.AsyncClient`): non-200 response and a network exception both raise `PagasaScrapeError`; a successful zero-link response still returns `[]`.
* New `ReconcileActiveTyphoonsTests`: closes a stale typhoon absent from the active-links list; leaves one present in the list untouched; correctly matches a name despite the filename's own `"21F"`-style final suffix; closes everything when `active_links` is empty.
* New `test_propagates_pagasa_scrape_error_and_skips_reconciliation` on `ScrapeAndSaveAllTests` — confirms a fetch failure isn't swallowed and never reaches the exposure-summary call.

### Status / Next Steps
* Verified directly (hand-run against all of the above scenarios, including confirming existing `scrape_and_save_all` tests still pass unmodified — a bare `MagicMock()`'s `.all()` iterates as empty by default, so the new reconciliation step doesn't interfere with tests that don't care about it) before handing back; not yet run through `pytest` — needs Fabio's re-run.
* Name-matching is filename-based only (same assumption `GpxFarmerMatcherService` already relies on for GPX filenames) — a PAGASA filename that doesn't follow the `TCB#<n>[F]_<name>.pdf` convention would fail to match and could cause a false closure. No real-world counterexample has been seen; flagging as a known limitation, not engineered around further.

---

## [2026-07-28] - Fix Map Attribution Links Kicking Users Back to Login

**Branch:** `fabio/db/pabs-ingestion-gpx-matching` (James's frontend edit, per Fabio's request to use this branch — committed locally, not pushed yet).

James found that clicking the Leaflet/OpenStreetMap attribution links at the bottom-right of the map (Spatial Analysis screen) navigated the whole browser tab away to `leafletjs.com`/`openstreetmap.org`. Since this SPA has no URL routing, pressing Back afterward doesn't restore the app's prior state — it reloads the app from scratch, which drops the user (all state is in-memory `useState`, including `currentUser`) back on the Login screen instead of wherever they were.

### 1. File: `frontend/src/app/components/GISLeafletMap.tsx`
* **Changes to Functions/Behavior:**
  * Added `target="_blank" rel="noopener noreferrer"` to the `TileLayer`'s custom OpenStreetMap copyright attribution string.
  * Added a `mapWrapperRef` + `useEffect` with a `MutationObserver` that patches every link inside `.leaflet-control-attribution` (including Leaflet's own auto-injected "Leaflet" credit link, which isn't reachable via a react-leaflet prop) to also open in a new tab. The observer is needed because Leaflet renders its attribution control after mount, not as part of React's initial render.

### Status / Next Steps
* Verified in-browser by James: clicking both attribution links now opens a new tab instead of navigating the app away.
* Not pushed yet.

---

## [2026-07-28] - GeoServer Integration (Schema, Backfill, Frontend WFS/WMS)

Fabio asked to wire up GeoServer, the 2nd-tier spatial layer server shown in
`docs/system architecture.png` but never actually implemented (confirmed zero
references anywhere in the codebase prior to this change). Scoped after finding that
`tbl_farms`' interactive click/popup layer can't move to WMS without losing
interactivity (WMS returns raster, not clickable features), and that
`tbl_admin_boundaries` had no geometry column at all — so region boundaries were a
static bundled file, not something GeoServer could serve from PostGIS. Fabio chose:
farm layer stays additive-only (existing FastAPI-sourced interactive layer untouched,
new optional WMS overlay added), and to add the missing geometry column so region
boundaries can move to a live GeoServer WFS source. GeoServer itself installs
natively (no Docker) — actual install/publish steps are a runbook for Fabio, not
run by Claude, per `.claude/CLAUDE.md`'s DB/venv execution rules.

### 1. File: `backend/init_schema.sql`
* **`tbl_admin_boundaries`**: added `boundary_geom GEOMETRY(MultiPolygon, 4326)` column and
  `idx_admin_boundaries_boundary_geom` GIST index, so GeoServer has a real PostGIS
  geometry to publish for the region-boundaries layer. Backfilled from
  `frontend/public/data/region10-boundaries.geojson` (see backfill script below), not
  used in any exposure calculation — `ExposureCalculatorService` still matches on
  province/municipality/barangay text.

### 2. File: `backend/app/models/models.py`
* **`AdminBoundary`**: added `boundary_geom = Column(Geometry(geometry_type="MULTIPOLYGON", srid=4326))`
  to match the schema change above.

### 3. File: `backend/backfill_admin_boundary_geom.py` (new)
* **`run_backfill()`**: one-off script reading `region10-boundaries.geojson` and
  `UPDATE`-ing `tbl_admin_boundaries.boundary_geom` for every row matching a
  feature's `(province, municipality)` — matched on text, not `psgc_code`, since the
  geojson's `psgc_municipality` codes are municipality-level and don't correspond to
  any single barangay's `psgc_code`. Prints unmatched municipalities (expected for
  ones with no seeded farms yet, not an error). Not run yet — needs Fabio, per venv
  execution rules.

### 4. File: `frontend/src/app/components/GISLeafletMap.tsx`
* **Changes to Functions/Behavior:**
  * Added `GEOSERVER_URL`/`GEOSERVER_PROXY_BASE`/`REGION_X_BOUNDARIES_WFS_URL`/
    `FARMS_WMS_LAYER`/`FARMS_WMS_URL` constants. `VITE_GEOSERVER_URL` is only used to
    decide *whether* GeoServer is configured (shows/hides the overlay toggle, gates
    the WFS attempt); actual requests are built against the `/geoserver-proxy` path
    (see `vite.config.ts` below), not the raw `VITE_GEOSERVER_URL`, so the browser
    never makes a cross-origin request.
  * The `regionXBoundaries` fetch effect now tries GeoServer WFS
    (`agrisuregis:tbl_admin_boundaries`, GeoJSON output) first and falls back to the
    existing static `region10-boundaries.geojson` fetch if `VITE_GEOSERVER_URL` is
    unset or the WFS request fails — same rendering/tooltip code (`styleBoundary`,
    `labelBoundary`) either way, so this changes only the data source, not behavior.
  * Added `showFarmsWmsOverlay` state and a new checkbox control (top-right,
    only rendered when `VITE_GEOSERVER_URL` is set) toggling a `<WMSTileLayer>` for
    `agrisuregis:tbl_farms`, rendered as a semi-transparent overlay alongside —
    not replacing — the existing interactive per-farm `<GeoJSON>` layer, so
    click-to-select/popups are unaffected.

### 5. File: `frontend/vite.config.ts`
* **Changes to Config:** switched `defineConfig({...})` to the function form
  `defineConfig(({ mode }) => {...})` so it can `loadEnv()` and read
  `VITE_GEOSERVER_URL` at dev-server-config time (not just client-side via
  `import.meta.env`). Added `server.proxy['/geoserver-proxy']` forwarding to
  `VITE_GEOSERVER_URL` with `changeOrigin: true`, only registered when that env var
  is set. This exists specifically to avoid needing CORS configured on GeoServer —
  see the incident note below.

### 6. File: `.claude/GEOSERVER_SETUP.md` (new)
* Runbook for Fabio: native GeoServer install (no Docker), applying the schema
  change to the live DB, running the backfill script, creating the `agrisuregis`
  workspace + PostGIS datastore, publishing `tbl_farms`/`tbl_admin_boundaries` as
  WMS/WFS layers, and a written incident note steering away from editing GeoServer's
  `web.xml` for CORS (see below).

### 7. File: `.claude/ENV_GUIDE.md`
* Documented new `VITE_GEOSERVER_URL` variable.

### 8. File: `frontend/.env.example` (was empty)
* Populated with `VITE_API_BASE_URL` (pre-existing var, was missing from this file)
  and the new `VITE_GEOSERVER_URL`, per `ENV_GUIDE.md`'s rule to keep this file in
  sync with what the code reads.
* **Follow-up correction**, found while testing: initially set
  `VITE_API_BASE_URL=http://localhost:8000/api`, copying `ENV_GUIDE.md`'s documented
  default verbatim without checking it against `frontend/src/lib/api.ts` — every path
  there already includes its own leading `/api/...` (e.g. `request('/api/bulletins/')`),
  so that combination produced `/api/api/bulletins/` and 404'd every core feature
  (bulletins, farms, assessments, CSV upload) once Fabio copied it into a real `.env`.
  Corrected to `http://localhost:8000` (no suffix) in both this file and
  `ENV_GUIDE.md`. GeoServer's own requests were unaffected (they go through
  `/geoserver-proxy`, not `API_BASE_URL`), which is what made this identifiable as a
  separate bug rather than a GeoServer regression.

### 9. Files: `.claude/PROJECT_CONTEXT.md`, `.claude/MASTER_DEVELOPMENT_CONTEXT.md`, `docs/README.md`
* Added GeoServer to the written architecture descriptions, matching what
  `docs/system architecture.png` already showed but the text docs omitted.

### Incident: GeoServer outage from a bad CORS fix attempt
While testing, the frontend's WFS call to GeoServer hit a CORS error (expected —
GeoServer doesn't send CORS headers by default). The Jetty-bundled GeoServer
distribution ships a *Tomcat*-specific `CorsFilter` block in `web.xml`, commented
out; its own comment says "enable CORS in Tomcat," which doesn't apply to this
Jetty-based install. Uncommenting it anyway threw `ClassNotFoundException:
org.apache.catalina.filters.CorsFilter` and crashed the entire GeoServer webapp
(503 on everything, including the admin UI). A follow-up attempt to hand-revert the
comment markers over chat left the XML malformed (unclosed `<web-app>` tag),
crashing it a second way. Recovered by extracting a clean `web.xml` from Fabio's
original downloaded archive rather than continuing to hand-patch it. Fabio then
deleted and re-extracted the whole GeoServer folder to get a guaranteed-clean state,
which also reset `data_dir` (workspace/datastore/published layers) back to
out-of-the-box defaults, requiring the workspace/datastore/publish steps to be
redone. Final fix avoids `web.xml` entirely — see `vite.config.ts` above. Runbook
updated with an explicit warning against editing that file for CORS.

### Status / Next Steps
* **Verified working end-to-end by Fabio**: schema applied, database reseeded,
  `boundary_geom` backfilled, GeoServer installed (JDK 11 — JDK 17 hit a separate
  `NoClassDefFoundError`/Marlin-renderer incompatibility on WMS `GetMap`/rendering
  operations), workspace/datastore/layers republished after the folder
  re-extraction reset them, frontend restarted with corrected env vars. Core app
  features (bulletins, farms, assessments, CSV upload) and the GeoServer WFS
  boundary layer + WMS farm overlay toggle all confirmed working in-browser.
* Pushed (`fabio/db/pabs-ingestion-gpx-matching`).

---

## [2026-07-28] - Windows Setup Guide

Fabio asked for a Windows-specific setup walkthrough. Written by checking actual
code behavior rather than trusting existing docs at face value, since the
GeoServer work earlier the same day surfaced two cases (`DATABASE_URL`,
`VITE_API_BASE_URL`) where `.claude/ENV_GUIDE.md` described env-var behavior the
code doesn't actually implement — confirmed via `grep` that nothing in
`backend/app/` imports `python-dotenv` or reads `os.environ`/`os.getenv` at all,
despite the package being listed in `requirements.txt`; `DATABASE_URL` and
`PAGASA_SCRAPE_URL` are both hardcoded in source
(`backend/app/core/database.py`, `backend/app/services/bulletin_parser.py`)
instead.

### 1. File: `docs/WINDOWS_SETUP.md` (new)
* Full walkthrough: prerequisites (Git, Python 3.11+, Node 20 LTS, PostgreSQL+PostGIS
  via the EDB installer/Stack Builder, optional JDK for GeoServer), DB
  user/database/extension creation matching the hardcoded credentials in
  `database.py` (flagged as a doc/code mismatch rather than silently "fixed"),
  backend venv/pip/uvicorn steps (PowerShell-specific execution-policy note for
  venv activation), frontend npm/`.env` steps (repeats the `VITE_API_BASE_URL`
  no-`/api`-suffix warning from the GeoServer work), and an optional GeoServer
  section (Windows paths/`startup.bat`/`JAVA_HOME` via PowerShell, same JDK 17
  Marlin-renderer warning, explicit "don't edit `web.xml` for CORS" warning
  referencing the incident from the same day's GeoServer entry, and a pointer to
  `.claude/GEOSERVER_SETUP.md` §5–6 for the OS-independent workspace/datastore/
  publish steps rather than duplicating them).

### 2. File: `README.md`
* Added a link to `docs/WINDOWS_SETUP.md` under Contents.

### Status / Next Steps
* Not verified on an actual Windows machine — written from the codebase's actual
  behavior (grepped, not assumed) plus the Linux setup already verified the same
  day, but no Windows hardware available to test the walkthrough end-to-end.
* Not pushed yet.

---

## [2026-07-29] - Assessment & Reporting: PABS-Format Combined Summary + Exposure Summary Mock

**Branch:** `fabio/db/pabs-ingestion-gpx-matching` (James's frontend work + supporting backend fix, per Fabio's request to use this branch — committed locally, not pushed yet).

Restructured the Assessment & Reporting screen around the PABS-mandated combined-CSV format (all typhoons together, not scoped to one bulletin/typhoon), then iterated through several rounds of Fabio's feedback (relayed through James) on how the computation trigger and its result table should actually be shaped.

### 1. File: `backend/app/api/assessments.py`
* Added **`_build_pabs_rows()`**: shared row-builder joining `RiskAssessment` → `InsuranceRecord` → `Farm` → `FarmerProfile`, and `RiskAssessment` → `AreaExposureSummary` → `Typhoon`, filtered to `matrix_id IS NOT NULL` (real computed assessments only, excludes legacy CSV-import seed rows). `IRID`, `P`, `S` have no known schema equivalent and are left `None`; `REMARKS` is a manually-inputted field per the source format's own legend, also left `None`.
* Added **`GET /pabs-summary`** (JSON) and **`GET /export-pabs`** (CSV) using that shared builder.
* `DATE_FILED` / `DATE_OF_OCCURRENCE` now formatted `MM/DD/YYYY` (previously raw datetimes) to match the reference format (`pabs_format_mockup.csv`) exactly.
* `export_assessments_pabs_csv()`: added `float_format="%.2f"` so `AC`/`AREA` come out as e.g. `"16542.00"`, matching the reference CSV's decimal style instead of pandas' default float printing (`16542.0`).

### 2. File: `frontend/src/lib/api.ts`
* Added `PabsAssessmentRow` type, `getAssessmentsPabsSummary()`, `getAssessmentsExportPabsUrl()`.
* Added `AreaExposureSummary` type, `ComputeExposureResult` type, `computeExposure()` — supports Monitoring's new TCB Exposure Summary modal (see `MonitoringModule.tsx` entry below).

### 3. File: `frontend/src/app/App.tsx`
* `AssessmentModule` no longer receives `selectedBulletin`/`onSelectBulletin` — Assessment stopped needing shared bulletin-selection state once it moved to the always-combined summary view.

### 4. File: `frontend/src/app/components/AssessmentModule.tsx`
* Net rewrite of the screen. In order, per successive rounds of feedback:
  * Replaced the mock/prototype table with the real PABS-format combined summary (`getAssessmentsPabsSummary()`), sortable/filterable by municipality and wind signal, plus a "Review & Export CSV" modal previewing exactly what `/export-pabs` will download.
  * Added a temporary `TEMP_PREVIEW_ROWS` hardcoded fallback so James could see the table populated before any real assessment existed — removed once real backend wiring was confirmed working (a 0-row real result is a legitimate outcome, not a bug, per `AssessmentService.calculate_for_bulletin()`'s eligibility rules).
  * Added, then removed, a per-bulletin "Compute Assessments" trigger (`calculateAssessments()`) — removed per Fabio's correction that computation must combine a typhoon's whole TCB range into one result, not run per individual bulletin.
  * Sidebar iterated through several shapes on Fabio's/his teammate's feedback: per-typhoon folders (too many, including duplicate names from a `typhoon_id` bulletin-title-parsing bug) → a single flat "All Bulletins" list → a typhoon list deduped by `typhoon_name` (not `typhoon_id`, to actually fix the duplicate-name display) → finally reference-only (no selection at all), since Fabio's final direction was that Compute always combines every typhoon into one result, matching the farmer-level table's own "all typhoons combined" behavior.
  * Added a mocked "Exposure Summary — All Typhoons Combined" panel (Typhoon / Areas / Signal Number / Exposure (h) / Start Time / End Time columns, per Fabio's exact spec) behind a "Compute Exposure Summary" button in the top bar — explicitly marked "Mock preview — pending backend wiring" since Fabio said he's wiring the real combined endpoint himself.
  * Added **`formatPabsCell()`** so the CSV preview modal's on-screen `AREA`/`AC` values match the CSV export's `float_format="%.2f"` exactly (the modal claims "exactly what the downloaded CSV will contain" — now genuinely true).

### 5. File: `frontend/src/app/components/MonitoringModule.tsx`
* Added **`ExposureSummaryModal`** + **`handleViewExposure()`**: a per-bulletin view (`POST /{tcb_id}/compute-exposure` via the new `computeExposure()`) showing affected areas, max signal, start/end time, exposure hours, and 6h+ eligibility — a real-data view, separate from Assessment's new mocked all-typhoons panel above.

### Status / Next Steps
* Assessment's Exposure Summary panel is frontend-mocked only (`MOCK_EXPOSURE_ROWS`) — Fabio said he'll wire it to a real combined-TCB backend endpoint himself; the frontend only needs `handleComputeExposure()` swapped to call it once that endpoint exists.
* `IRID`, `P`, `S` columns remain undefined/blank in the PABS output — still no schema/doc source, deferred per earlier agreement with Fabio ("we will deal about it later").
* `MonitoringModule.tsx` still uses `mockFarmers` for its stat cards (`totalFarms`, etc.) in this diff — a separate mock-data-removal pass noted elsewhere is not reflected in this file's current working-tree state; flagging so it isn't assumed done.
* Two mockup CSVs were created outside the repo for manual testing (not part of this commit): `C:\Users\User\Desktop\pabs_format_mockup.csv` (reference PABS-format sample) and `C:\Users\User\Desktop\mockup_assessment_test_data.csv` (uploadable via `/api/upload/csv`, Talakag/Claveria boundaries, for testing real Compute Assessments end-to-end).
* Not pushed yet — awaiting Fabio's/James's own push per `CLAUDE.md`'s git-handoff rules.

---

## [2026-07-29] - Merge: Summary-Tcb-Pabs-format into pabs-ingestion-gpx-matching

Merged `origin/Summary-Tcb-Pabs-format` (PABS-format Assessment/Exposure Summary work,
entry above) into `fabio/db/pabs-ingestion-gpx-matching`, per Fabio's request to
consolidate the two branches. `origin/Summary-Tcb-Pabs-format` is being deleted on
the remote after this merge is pushed.

* Clean merge on all files except this one — both branches had independently
  appended a changelog entry at the same location; resolved by keeping both,
  in chronological order.
* Not pushed yet.

---

## [2026-07-29] - Assessment & Reporting: Per-Typhoon Exposure Summary (replaces combined mock)

Per Fabio's direction, replaced the mocked "Compute Exposure Summary — All Typhoons
Combined" panel with a real, per-typhoon summary driven by clicking a typhoon in the
sidebar, which was previously reference-only. Reuses the already-computed
`tbl_area_exposure_summary` rows (populated once a typhoon's bulletins are done, not
per-TCB) rather than triggering a new computation on click.

### 1. File: `backend/app/api/bulletins.py`
* Added **`GET /bulletins/typhoon/{typhoon_id}/summary`**: reads `AreaExposureSummary`
  rows for a typhoon and returns `typhoon_name`, `areas_hit` (province/municipality/
  max_signal_level/start_time/end_time/total_exposure_hours per boundary), overall
  `max_signal_level`, overall `start_time`/`end_time` (min/max across areas), a derived
  `exposure_duration_hours` (`end - start`, in hours), and `people_hit` — a count of
  distinct farmers (`Farm.farmer_id`) whose `boundary_id` falls in one of the typhoon's
  affected boundaries, regardless of whether a payout assessment has been computed for
  them yet (per Fabio: "people hit" = spatial exposure, not assessment eligibility).
  Does not trigger `ExposureCalculatorService.compute_for_typhoon()` — read-only.

### 2. File: `frontend/src/lib/api.ts`
* Added `TyphoonSummaryArea` and `TyphoonSummary` types, and `getTyphoonSummary()`
  calling the new endpoint.

### 3. File: `frontend/src/app/components/AssessmentModule.tsx`
* Removed `MOCK_EXPOSURE_ROWS`, `ExposureSummaryRow`, `handleComputeExposure()`, and the
  "Compute Exposure Summary" button/mock table (all frontend-only, per the 2026-07-29
  PABS-format entry above).
* Typhoon sidebar is no longer reference-only: cards are now buttons; clicking one
  selects/deselects it (`selectedTyphoonId`) and fetches its summary via
  `getTyphoonSummary()`. The `typhoons` memo now also carries a representative
  `typhoon_id` per deduped name (first bulletin seen for that name), inheriting the
  same known limitation as the existing name-based dedup if a typhoon's bulletins got
  split across more than one `typhoon_id` by the bulletin-title parsing bug.
* Added the new summary panel: stat tiles (Areas Hit, People Hit, Max Signal Number,
  Exposure Time, Start, End) plus a per-area breakdown table, shown when a typhoon is
  selected; states covered: loading, error, and "not computed yet" (empty
  `areas_hit`). Added `formatDateTime()` helper for the ISO timestamps.
* The farmer-level PABS combined table/badge/export below is unchanged — still
  intentionally all-typhoons-combined, per Fabio's earlier direction; only the
  typhoon-scoped exposure panel was in scope here.

### Status / Next Steps
* Not tested end-to-end yet (Fabio's local venv/frontend, per `CLAUDE.md`'s execution
  rules) — needs `AreaExposureSummary` rows to actually exist for a typhoon (via
  Monitoring's existing "Compute Exposure" action) to see a non-empty panel.
* Not pushed yet.

---

## [2026-07-29] - Mock Data for Assessment & Reporting Usability Testing (Talakag + Claveria)

Per Fabio's request, added standalone mock/test fixtures to exercise the Assessment &
Reporting module (including the per-typhoon panel above) end-to-end without touching
real data. `docs/Rice Risk Exposure Region X 04-15-2026.csv` was used only as the
format reference for the CSV columns — none of its actual data was reused. Also
re-added a "Compute Assessments" trigger (removed in the 2026-07-29 PABS-format entry
above) since there was otherwise no way to turn the mock exposure data into real
`RiskAssessment` payouts from the UI.

### 1. New file: `backend/mock_data/mock_farmers_talakag_claveria.csv`
* 12 fake farmer/policy rows (6 Talakag/San Isidro, 6 Claveria/Poblacion), matching
  the CSV-upload column format read by `backend/app/api/upload.py`'s
  `prepare_row_payload()` exactly (`Province, Municipality, Barangay, FarmersID,
  RSBSA No., Surname, Firstname, Middlename, FARMID, Georef ID, AreaInsured,
  Policy No., Program Type, Product Name, Effectivity Date, Expiry Date,
  AmountofCover, Stage No., Stage, EstimatedDamage, RiskExposureAmount`).
  `Effectivity Date`/`Expiry Date` (06/01/2026–12/31/2026) deliberately bracket the
  mock typhoon's bulletin dates below. `Stage No.` cycles through 1/2/3
  (Booting/Flowering/Maturity) so all three `RecsapMatrix` crop-stage rows are
  reachable. Intended for upload via the existing Data Ingestion module's CSV
  uploader (`POST /api/upload/csv`) — no code changes needed to use it.

### 2. New files: `backend/mock_data/gpx/*.gpx` (12 files)
* One small rectangular polygon boundary per mock farm, filenames following
  `GpxFarmerMatcherService`'s `_TAIL_RE` pattern (`..._<FarmersID>_<FARMID>_<date>.gpx`)
  so each auto-matches its corresponding CSV row's farmer/farm on upload via
  `POST /api/upload/gpx`. Coordinates are approximate/illustrative points spread out
  around Talakag and Claveria — not surveyed real boundaries.

### 3. New file: `backend/mock_data/seed_mock_typhoon.py`
* One-off script (raw `psycopg2`, same connection pattern as
  `backend/backfill_admin_boundary_geom.py`) that inserts a fictional typhoon
  ("MARISOL", 2026 — clearly not a real PAGASA name) with two
  `TropicalCycloneBulletin` rows 12 hours apart and `TcbSignal` rows for Talakag
  (signal 3) and Claveria (signal 2) on each, so
  `ExposureCalculatorService.compute_for_typhoon()` has real bulletin/signal data to
  aggregate into a 12-hour exposure window for both municipalities (matches
  `tbl_recsap_matrix`'s 12h bucket). Deliberately does not insert
  `AreaExposureSummary`/`RiskAssessment` rows itself — those come from running the
  app's own "Compute Exposure Summary" (Monitoring) and new "Compute Assessments"
  (Assessment & Reporting, see below) actions afterward, so the rest of the pipeline
  is exercised for real. Safe to re-run (skips if the typhoon already exists).
  Requires `tbl_admin_boundaries` rows for Talakag/Claveria to already exist (i.e.
  `seed_database.py` already run).

### 4. File: `frontend/src/lib/api.ts` / `frontend/src/app/components/AssessmentModule.tsx`
* Re-added a **"Compute Assessments"** button (calls the existing `calculateAssessments()`
  / `POST /assessments/calculate`), now inside the per-typhoon exposure panel added
  above rather than the top bar — shown only once a typhoon's exposure summary has
  at least one area hit. Picks that typhoon's latest bulletin (highest
  `bulletin_count`) to pass as `bulletin_id`; per `AssessmentService.calculate_for_bulletin()`
  this only affects the "as of" eligibility date, since the actual computation already
  combines the whole typhoon's exposure data internally — unaffected by which bulletin
  is passed, consistent with the original removal reason from the PABS-format entry
  above. On success, refreshes the main PABS table via the existing `loadSummary()`.

### Status / Next Steps
* Not run/tested yet — per `CLAUDE.md`'s DB/venv/frontend execution rules, Fabio needs
  to run the seed script and upload the CSV/GPX files himself; see chat for the exact
  step-by-step handoff.
* Mock data is intentionally isolated (fake IDs `900001–900012`, fictional typhoon name)
  so it can be identified and deleted later without touching real records.
* Not pushed yet.

---

## [2026-07-30] - Monitoring/Spatial/Calibration Real-Data Pass, Auto-Assessment on Parse

**Branch:** `fabio/db/pabs-ingestion-gpx-matching` (James's frontend work + supporting backend changes, committed locally, not pushed yet). Does **not** touch `AssessmentModule.tsx` — that file was independently reworked by Fabio's own `425e129` commit on this branch (real per-typhoon exposure panel + `GET /bulletins/typhoon/{typhoon_id}/summary`), merged in separately from this entry.

### 1. File: `backend/app/api/insurance.py` (new)
* Added **`GET /insurance/summary`**: counts `InsuranceRecord` rows currently within their `effectivity_date`–`expiry_date` window against the total policy count. Backs Monitoring's new "Active Insurance Policies" stat card.

### 2. File: `backend/app/main.py`
* Registered `insurance_router` under `/api`.

### 3. File: `backend/app/api/farms.py`
* `list_farms()`: now also looks up each farm's most recent `InsuranceRecord` (by `effectivity_date desc`) and returns `policy_no`, `effectivity_date`, `expiry_date` (formatted `MM/DD/YYYY`) alongside the existing fields — backs the new "Effective Date"/"Expiry Date" columns in Spatial Analysis's Farm Records table.

### 4. File: `backend/app/services/bulletin_parser.py`
* **Behavior change, overrides an earlier explicit decision:** `scrape_and_save_all()` now calls `AssessmentService.calculate_for_bulletin(bulletin.typhoon_id, bulletin.tcb_id, db)` after **every** successfully parsed bulletin (previously only `ExposureCalculatorService.compute_for_typhoon()` ran, and only for a detected *final* bulletin). Since `calculate_for_bulletin()` already recomputes the exposure summary internally before checking payout eligibility, this is a strict superset of the old behavior, not just an addition.
  * `_reconcile_active_typhoons()` updated the same way: on closing a typhoon that dropped off PAGASA's active list, it now looks up that typhoon's most recent bulletin and runs the same assessment computation (falling back to the old exposure-only call if no bulletin is found, which shouldn't happen in practice).
  * **Why this overrides the prior decision:** the 2026-07-27 entry ("Final-Bulletin Detection") explicitly recorded Fabio's call to keep assessment/payout calculation a separate manual step even after auto-closing a typhoon. This entry reverses that — confirmed directly with the user, not done unilaterally — so that clicking "Parse Latest Bulletin" (or the scheduled background scrape) now makes results appear in Assessment & Reporting without an extra manual `POST /api/assessments/calculate` call. **Flagging for Fabio's review**, since he made the original manual-only call and may want it reverted or handled differently.

### 5. File: `frontend/src/lib/api.ts`
* Added `InsuranceSummary` type + `getInsuranceSummary()`.
* `Farm` interface: added `policy_no`, `effectivity_date`, `expiry_date`.

### 6. File: `frontend/src/app/components/MonitoringModule.tsx`
* Removed remaining `mockFarmers`/`FarmerRecord` usage entirely (the 2026-07-29 entry above already flagged this file as not actually cleaned up despite an earlier todo item claiming it was):
  * "Affected Farms" / "Est. Total Indemnity" stat cards now computed from real `getFarms()`/`getAssessments()`, counting only farms with a real computed assessment (`wind_velocity` set — excludes legacy CSV-import seed rows).
  * "Growth Stage Distribution", "Farms by Signal Number", and "TCB Download Timeline" charts now computed from real crop-stage/signal/bulletin-date data instead of hardcoded arrays, each with an honest empty state.
  * The "Farmers Under Signal No. X" list feeding `SARQuickViewModal` is now real farm data; the SAR *imagery* itself remains a simulated canvas render (no real Google Earth Engine integration exists anywhere in this codebase) — `SARQuickViewModal` reworked to take a `FarmRow` instead of the mock `FarmerRecord`.
* Added a 5th stat card, **"Active Insurance"** (`X/Y` from the new `/insurance/summary` endpoint).
* Removed the "System Status" panel (moved to Calibration & Settings, see below).
* **Layout change:** root container changed from `overflow-auto` (whole-page scroll) to a bounded `flex flex-col overflow-hidden` — the page itself no longer scrolls. The PAGASA TCB Bulletins list is the only element that scrolls now (`flex-1 min-h-0 overflow-auto`, sticky header), instead of growing unbounded and pushing the charts below off-screen.

### 7. File: `frontend/src/app/components/CalibrationModule.tsx`
* Added a new **"System Status"** section (moved from Monitoring), showing a real Backend API connected/unreachable status — piggybacks on the `getParserSettings()` call this screen already makes on mount rather than firing an extra request just for a health check.

### 8. File: `frontend/src/app/components/SpatialAnalysisModule.tsx`
* Removed the "Data Import" CSV/GPX drag-drop panel entirely (per explicit confirmation that this removes the only upload UI in the app — CSV/GPX ingestion is still possible via the API directly, e.g. Swagger docs).
* The former "Export Period of Exposure" button (client-side CSV download) is now an **"Upload CSV"** button in its place — opens a native file picker, uploads via the existing `uploadCsv()` API. The client-side export feature itself is gone from this screen.
* "Filter map" changed from a `<select>` dropdown to a type-ahead search box: typing narrows a suggestion list of municipalities (prefix match), clicking one applies the filter; clearing the box resets to "All."
* Added two new Farm Records table columns: "Effective Date", "Expiry Date" (from the `farms.py` change above).
* Passes `focusMunicipality` to `GISLeafletMap` so picking a municipality also flies the map to it (see below).

### 9. File: `frontend/src/app/components/GISLeafletMap.tsx`
* Added **`FlyToSelectedFarm`**: flies the map to whichever farm is selected (real GPX polygon bounds if surveyed, else its approximate marker position) — covers both clicking a farm on the map and clicking its row in the Farm Records table.
* Added **`FlyToMunicipality`**: flies to a searched/selected municipality's real boundary outline (from the existing `region10-boundaries.geojson` context layer), floored at zoom 12 so it never pulls back further than that even for a large/sprawling municipality shape.
* Removed the click-`Popup` on both surveyed (GPX polygon) and unsurveyed (approximate marker) farms — redundant with the existing "Selected Farm Info Panel" overlay, which already shows the same (and more) detail.
* Clicking a farm now visibly highlights it with a real fill-color change (amber `#f59e0b`), not just a border-color/weight tweak as before.

### 10. File: `backend/requirements-win.txt`
* Added `APScheduler==3.11.0` — was present in `requirements.txt` but missing from the Windows-specific file entirely, causing `ModuleNotFoundError: No module named 'apscheduler'` on a fresh Windows venv setup (surfaced when moving the project to a new drive location and reinstalling).

### Status / Next Steps
* Merged into `fabio/db/pabs-ingestion-gpx-matching` on top of `425e129` (Fabio's per-typhoon exposure summary + mock test data). The predicted `api.ts` conflict auto-merged cleanly (both sides only added new types/functions); the only manual resolution needed was combining a `react-leaflet` import line in `GISLeafletMap.tsx` (both sides added a different new import — `WMSTileLayer` for Fabio's GeoServer overlay, `useMap` for this entry's fly-to-farm/fly-to-municipality) and this changelog file itself.
* Auto-assessment-on-parse (item 4 above) needs Fabio's explicit sign-off — implemented per direct user request during testing, not per his own decision.
* Not pushed yet — awaiting the user's own push per `CLAUDE.md`'s git-handoff rules.

---

## [2026-07-30] - Wire Up GPX Upload UI (Spatial Analysis module)

Fabio found only CSV upload in the live UI when trying to load the mock GPX boundary
files from the Talakag/Claveria test data. Investigation found `uploadGpx()` in
`frontend/src/lib/api.ts` had zero callers anywhere in the frontend — the only GPX
file input that ever existed was a `<input type="file" accept=".gpx">` in the unused,
never-imported `frontend/src/app/components/SpatialModule.tsx` (superseded by
`SpatialAnalysisModule.tsx`, which `App.tsx` actually mounts), and even that dead
input had no `onChange` handler wired to anything.

### 1. File: `frontend/src/app/components/SpatialAnalysisModule.tsx`
* Added an **"Upload GPX"** button in the map toolbar, right next to the existing
  "Upload CSV" one, with its own hidden `<input type="file" accept=".gpx" multiple>`.
* Added **`handleGpxFilesSelected()`**: uploads each selected file sequentially (not
  in parallel, so a large batch doesn't hammer the backend at once) via the existing
  `uploadGpx()` — farmer/farm auto-detected from filename by
  `GpxFarmerMatcherService`, same as before. Reuses the existing `uploadStatus`
  banner, reporting a combined success/failure count across the batch, and calls
  `refreshFarms()` afterward so the "GPX Boundary" column reflects newly-attached
  geometry immediately.

### Status / Next Steps
* Not tested end-to-end yet (Fabio's local frontend, per `CLAUDE.md`'s execution
  rules) — next step is uploading the 12 mock GPX files from
  `backend/mock_data/gpx/` through this new button.
* Not pushed yet.

---

## [2026-07-30] - Fix: policy_no Unique Constraint Wrongly Excluded Batch-Policy Farmers

Fabio noticed some farmers from `docs/Rice Risk Exposure Region X 04-15-2026.csv`
showed a blank crop stage in the app UI. Traced to `tbl_insurance_records.policy_no`
being `UNIQUE` — but that CSV has one Policy No. legitimately covering many different
farmers (e.g. Policy No. `1761604` spans 10 distinct farmers across rows 4-13,
`1761606` spans 14 across rows 82-95): a batch/program policy, not one-farmer-one-policy.
Confirmed with Fabio: this is real, not a source-data error. The old
`_ingest_row()` duplicate check treated "policy_no already exists" as "already
ingested, skip" — so only the *first* farmer under each shared Policy No. ever got an
`InsuranceRecord` (and therefore the crop-stage-seeding `RiskAssessment` right after
it); every other farmer sharing that Policy No. silently got a Farm/Farmer row with no
Insurance/RiskAssessment at all, reported only as a `rows_skipped` count with no
indication why.

### 1. File: `backend/app/models/models.py`
* `InsuranceRecord.policy_no`: removed `unique=True`. Added
  `__table_args__ = (UniqueConstraint("policy_no", "farm_id", name="uq_insurance_records_policy_no_farm_id"),)`
  — the real per-row unique identity is (policy_no, farm_id), not policy_no alone.

### 2. File: `backend/init_schema.sql`
* `tbl_insurance_records.policy_no`: `VARCHAR(50) UNIQUE NOT NULL` → `VARCHAR(50) NOT NULL`,
  with a new table-level `CONSTRAINT uq_insurance_records_policy_no_farm_id UNIQUE (policy_no, farm_id)`.

### 3. File: `backend/app/api/upload.py`
* `_ingest_row()`'s duplicate-detection query now filters on both `policy_no` AND
  `farm_id == farm.farm_id`, not `policy_no` alone — different farmers sharing a
  policy number now each get their own `InsuranceRecord`/`RiskAssessment` instead of
  being silently skipped after the first.

### 4. File: `backend/seed_database.py`
* `ON CONFLICT (policy_no) DO NOTHING` → `ON CONFLICT (policy_no, farm_id) DO NOTHING`
  — required to match the new composite constraint; the old target no longer exists
  once the schema changes, and `ON CONFLICT` errors if its target doesn't match an
  actual constraint.

### Status / Next Steps
* Fabio applying a non-destructive `ALTER TABLE` himself (per `CLAUDE.md`'s DB-command
  handoff rule) rather than a full `init_schema.sql` rewipe, to preserve existing data
  (MARISOL typhoon, mock CSV/GPX farmers already loaded) — see chat for the exact
  command handed to him.
* After the ALTER TABLE, re-uploading `docs/Rice Risk Exposure Region X...csv` should
  backfill `InsuranceRecord`/`RiskAssessment` (crop stage) for every farmer who was
  previously silently skipped — their Farm/Farmer rows already exist from the earlier
  upload, so nothing needs deleting first.
* Not pushed yet.

---

## [2026-08-03] - Login Page Static Layout

### 1. File: `frontend/src/app/components/LoginScreen.tsx`
* Root container (`LoginScreen`) changed from `min-h-screen` to `h-screen overflow-hidden` — the login page no longer grows taller than the viewport and scrolls; it's now fixed to viewport height.

### Status / Next Steps
* Cherry-picked directly onto `develop` from `fabio/db/pabs-ingestion-gpx-matching` at the user's request.


## [2026-08-03] - Typhoon-Wide TCB Summarization Gated on "F" Marker + is_active Decoupled from TCB Parsing

Two related decisions from Fabio: (1) farms must be cross-referenced against one
typhoon-wide summary once a typhoon's bulletins are confirmed complete, not
re-cross-referenced after every single TCB — reverting the 2026-07-30 "Auto-
Assessment on Parse" entry's "run on every bulletin" behavior back to the
original 2026-07-27 "only on the final bulletin" design, this time all the way
through to the farm/payout assessment step, not just the exposure summary.
(2) `Typhoon.is_active` ("is there a current typhoon") must no longer be decided
by TCB parsing at all (neither the "F" marker nor reconciliation against
PAGASA's bulletin-PDF index) — it's now driven exclusively by a new scraper
reading PAGASA's public severe-weather-bulletin status page
(https://www.pagasa.dost.gov.ph/tropical-cyclone/severe-weather-bulletin) for a
recognized cyclone-category word. The "F" marker's only remaining job is
gating when the exposure summary/assessment computation runs.

### 1. File: `backend/app/services/bulletin_parser.py`
* `scrape_and_save_all()`: the auto-run of `AssessmentService.calculate_for_bulletin()`
  is now gated on `parsed_data.get("is_final")` — only a trailing-"F" bulletin
  triggers it, not every parsed bulletin. Removed the `cls._reconcile_active_typhoons(links, db)`
  call at the end of the method entirely (see below).
* Removed `_reconcile_active_typhoons()` and its `ACTIVE_LINK_NAME_RE` filename
  regex — both fully superseded by `PagasaStatusService` (new file, below), which
  reads PAGASA's own status page instead of inferring activity from which TCB
  PDFs happen to be listed.
* `save_bulletin_to_db()`: no longer flips `Typhoon.is_active` on a final ("F")
  bulletin. The "Get or Create Typhoon" block is extracted into a new
  `get_or_create_typhoon(name, reference_time, db)` classmethod (same 30-day-
  window name-matching logic, unchanged), reused by `PagasaStatusService` so
  both the TCB side and the status-page side of PAGASA agree on which `Typhoon`
  row a given name refers to. A newly-created `Typhoon` now defaults to
  `is_active=False` (was `True`) — `PagasaStatusService` is the sole source of
  truth for that flag now and typically confirms/sets it `True` moments later
  in the same scrape cycle.
* `PagasaScrapeError`'s docstring generalized (it's now raised by, and shared
  with, `PagasaStatusService` too) — no behavior change.

### 2. File: `backend/app/services/pagasa_status_scraper.py` (new)
* Added **`PagasaStatusService`**: `fetch_active_storm_names()` fetches
  PAGASA's severe-weather-bulletin status page and returns the uppercased
  name of every cyclone currently listed there. Scoped specifically to
  `<a class="swb">` tab-label elements (confirmed against the live page —
  each active cyclone is a tab, e.g. `<a class="swb">Tropical Depression
  &quot;Luis&quot;</a>`) rather than scanning the whole page text, so a stray
  "typhoon" mention elsewhere (nav/footer/unrelated article) can't cause a
  false positive — the same failure mode `bulletin_parser.py`'s own category
  regex was previously rewritten to avoid. Category word list includes
  "Super Typhoon" (bulletin_parser.py's TCB-title regex doesn't have this
  case — no real sample bulletin carrying it was available when that regex
  was written). Raises `PagasaScrapeError` on an unreachable page, same
  distinction `fetch_active_bulletin_links()` already makes.
  `sync_active_typhoons(active_names, db)` sets `Typhoon.is_active = True`
  for each resolved name (via the shared `get_or_create_typhoon`) and `False`
  for every other currently-active `Typhoon` — an empty list is a real signal
  that correctly closes everything.

### 3. File: `backend/app/api/bulletins.py`
* `POST /parse`: after `scrape_and_save_all()`, now also calls
  `PagasaStatusService.fetch_active_storm_names()` +
  `.sync_active_typhoons()` in its own try/except (a status-page failure
  doesn't hide a successful bulletin parse, or vice versa).

### 4. File: `backend/app/core/scheduler.py`
* `run_scheduled_scrape()`: now also runs the `PagasaStatusService` status
  sync after the TCB scrape, in its own try/except block, so a failure in
  either step doesn't skip or hide the other.

### 5. File: `backend/app/api/typhoons.py` (new)
* Added **`GET /typhoons/active`**: returns every `Typhoon` currently
  `is_active=True` (per `PagasaStatusService`) as
  `{typhoon_id, name, year}`. No `typhoons` router existed before this.
  Registered in `backend/app/main.py`.

### 6. File: `frontend/src/lib/api.ts`
* Added `ActiveTyphoon`/`ActiveTyphoonsResult` types and `getActiveTyphoons()`
  calling the new endpoint.

### 7. File: `frontend/src/app/components/MonitoringModule.tsx`
* The "Active Typhoon" stat card previously showed `bulletins[0]?.typhoon_name`
  (the typhoon owning whichever bulletin row had the highest `bulletin_count`
  ever ingested — not actually "active" in any meaningful sense, and unrelated
  to `Typhoon.is_active`, which nothing in the frontend read at all). Now
  fetches `getActiveTyphoons()` on load and after "Parse Latest Bulletin",
  and shows the real active-typhoon name(s) (joined by ", ", or "—" if none).

### 8. Files: `backend/tests/test_bulletin_parser.py`, `backend/tests/test_pagasa_status_scraper.py` (new)
* `test_bulletin_parser.py`: updated `test_creates_new_typhoon_when_no_bulletin_within_30_days`
  to assert `is_active=False` on the freshly-created row. Replaced
  `test_save_bulletin_to_db_marks_typhoon_inactive_when_final` with
  `test_save_bulletin_to_db_does_not_touch_is_active_even_when_final` (asserts
  the opposite of the old behavior). Renamed/repointed
  `test_final_bulletin_triggers_exposure_summary` →
  `test_final_bulletin_triggers_assessment_calculation` and
  `test_non_final_bulletin_does_not_trigger_exposure_summary` →
  `test_non_final_bulletin_does_not_trigger_assessment_calculation` to patch
  `AssessmentService.calculate_for_bulletin` (what the code now actually
  gates) instead of `ExposureCalculatorService.compute_for_typhoon`. Removed
  `ReconcileActiveTyphoonsTests` entirely (tested the now-deleted
  `_reconcile_active_typhoons`). These three renamed/patched tests were
  asserting pre-2026-07-30 behavior that the code had already stopped
  matching (the unconditional-call change never updated them) — they were
  almost certainly red before this entry; this both fixes and repurposes them.
* `test_pagasa_status_scraper.py` (new): covers `fetch_active_storm_names()`
  (HTTP/network error handling, `.swb`-tab extraction, multiple concurrent
  tabs, "Super Typhoon", and the false-positive guard for a category word
  appearing outside a `.swb` tab) and `sync_active_typhoons()` (activates a
  matched name, closes unmatched typhoons, leaves an already-active match
  untouched and excluded from the closing pass, closes everything on an
  empty list).

### Status / Next Steps
* Not run against Fabio's venv yet — needs `pytest` for
  `test_bulletin_parser.py` and the new `test_pagasa_status_scraper.py`, and
  `npm run build`/`npm run dev` to confirm the frontend changes compile and
  the Active Typhoon card renders correctly against a live backend.
* The severe-weather-bulletin page's exact markup when **no** cyclone is
  active is unconfirmed — a live fetch during this work only showed the
  active-storm case (Tropical Depression "Luis" was genuinely active at the
  time). `fetch_active_storm_names()`'s keyword-presence design is robust to
  this (no `.swb` tabs / no recognized category word → `[]`, same as "nothing
  active"), but it's worth Fabio double-checking the card shows "—" correctly
  the next time PAR has no active system.
* Not pushed yet.


## [2026-08-03] - Mock Farm Data: Realistic Polygons + Spread Across More of Region X

Fabio flagged the 12 mock farm GPX boundaries as inaccurate: each was a perfect
uniform 0.0030°×0.0030° axis-aligned square (~11 ha, identical for all 12,
marching in a diagonal grid) rather than an irregular real-world plot shape, and
all 12 sat in just two municipalities (Talakag, Claveria). Cross-checking against
the real boundary polygons in `frontend/public/data/region10-boundaries.geojson`
also surfaced that farms 900001-900006's old square centers weren't even inside
the real Talakag polygon at all -- a second, independent inaccuracy beyond shape.

### 1. Files: `backend/mock_data/gpx/*.gpx` (all 12 rewritten)
* Every farm's boundary is now an irregular quadrilateral (randomly jittered
  corners, trapezoid-like -- not a uniform square) instead of the old identical
  squares. Each polygon's area now roughly matches that farm's real
  `AreaInsured` value from the CSV (1.2-3.0 ha) instead of the old uniform
  ~11 ha. Every polygon's centroid is verified (via Shapely, against the real
  municipality polygons in `region10-boundaries.geojson`) to actually fall
  inside its claimed municipality -- confirmed the old Talakag placements did
  not. Farms `900004`/`900005`/`900006` relocated from Talakag to Manolo
  Fortich (Bukidnon), and `900010`/`900011`/`900012` from Claveria to City of
  Gingoog (Misamis Oriental), per Fabio's request to spread the mock dataset
  across more of Region X rather than just the original two municipalities --
  both are real, already-seeded municipalities (`psgc_region10_boundaries.csv`).
  Coordinates were computed via a one-off scratch script (not committed --
  pure geometry/area-matching math, no app or DB dependency) and hand-verified
  valid/simple/in-boundary before being written; not run through the actual
  upload pipeline yet.

### 2. File: `backend/mock_data/mock_farmers_talakag_claveria.csv`
* Rows for FarmersID `900004`-`900006` and `900010`-`900012`: `Municipality`/
  `Barangay` updated to match the GPX relocation above (`Talakag`/`San Isidro`
  → `Manolo Fortich`/`Alae`; `Claveria`/`Poblacion` → `City of Gingoog`/
  `Agay-ayan`); `Province` unchanged (both new municipalities are in the same
  province as their old one). `Georef ID`'s embedded location code updated to
  match (`R10-BUK-TAL-*` → `R10-BUK-MFO-*`, `R10-MIS-CLV-*` → `R10-MIS-GIN-*`)
  so it doesn't keep referencing the old municipality. All other columns
  (AreaInsured, AmountofCover, Stage, policy/RSBSA/farm IDs, etc.) untouched.
  Filename kept as-is despite no longer being Talakag/Claveria-only, to avoid
  a disruptive rename across every reference to it.

### 3. File: `backend/mock_data/seed_mock_typhoon.py`
* `BULLETINS[0]["signals"]` and `BULLETINS[1]["signals"]`: added a
  `"Manolo Fortich"` entry alongside each existing `"Talakag"` entry (same
  signal_level=3) and a `"City of Gingoog"` entry alongside each `"Claveria"`
  entry (same signal_level=2), so farms relocated in #1/#2 above still get
  exposure/assessment test coverage. Docstring and closing print statements
  updated to mention both new municipalities instead of just the original two.

### Status / Next Steps
* Not run against Fabio's venv/DB yet. To pick this up: reset the DB (see
  `.claude/BACKEND_DATABASE_WORKFLOW.md` §4), re-run `seed_database.py` +
  `backfill_admin_boundary_geom.py`, re-upload the CSV + all 12 GPX files
  (Data Ingestion module), run `mock_data/seed_mock_typhoon.py`, then
  Monitoring → Compute Exposure Summary and Assessment & Reporting → Compute
  Assessments for typhoon MARISOL -- same sequence as before, just now
  spanning 4 municipalities instead of 2.
* Not pushed yet.

---

## [2026-08-03] - Fix: PAGASA Bulletin "Issued At" Timestamp Mislabeled as UTC

Fabio flagged that bulletin issue times were showing wrong values in the
Monitoring module. Root cause: PAGASA states every bulletin's "Issued at"
time in Philippine Standard Time (PHT/UTC+8), but `parse_bulletin_text()`
labeled the parsed wall-clock value as `timezone.utc`, shifting the stored
absolute instant 8 hours away from the real one. `TropicalCycloneBulletin`'s
`issued_at`/`expires_at` columns were also mapped as timezone-naive
`DateTime` in the ORM despite the DB schema (`init_schema.sql`) defining them
as `TIMESTAMPTZ`. Separately, the frontend was rendering the raw ISO string
(with its `+08:00` offset) directly instead of a formatted local time.

### 1. File: `backend/app/services/bulletin_parser.py`
* Added module-level `PHT = timezone(timedelta(hours=8))` constant (the
  Philippines observes no DST, so a fixed offset is correct).
* `parse_bulletin_text()`: the "Issued at" datetime is now tagged
  `tzinfo=PHT` instead of `tzinfo=timezone.utc`, so the stored `issued_at`
  represents the correct absolute instant.

### 2. File: `backend/app/models/models.py`
* `TropicalCycloneBulletin.issued_at` / `.expires_at`: changed from
  `Column(DateTime, ...)` to `Column(DateTime(timezone=True), ...)` to match
  the actual `TIMESTAMPTZ` columns in `init_schema.sql`.

### 3. File: `backend/tests/test_bulletin_parser.py`
* Imports `PHT` from `bulletin_parser` instead of using bare `timezone.utc`.
* `test_parse_bulletin_text_against_real_sample_pdf()`: updated the expected
  `issued_at` value's tzinfo from `timezone.utc` to `PHT` to match the fix.

### 4. File: `frontend/src/app/components/MonitoringModule.tsx`
* Added `formatIssuedAt()`: formats an `issued_at` ISO string via
  `Intl.DateTimeFormat` (`timeZone: "Asia/Manila"`) into a readable local
  date/time string, returning `"Unknown"` for null/invalid input.
* Replaced all 6 raw `bulletin.issued_at` / `b.issued_at` /
  `selectedBulletin.issued_at` render sites (TCB viewer modal header/detail
  grid, bulletin list table row, selected-bulletin detail panel, and both
  `.txt` export builders) with `formatIssuedAt(...)` calls. Left the
  timeline-bucketing logic (`bulletinTimelineData`, which slices the raw ISO
  string by day) untouched -- that's data grouping, not display.

### Status / Next Steps
* Verified: `python -m pytest tests/test_bulletin_parser.py -v` -- 23 passed.
* Frontend visual check still pending (needs `npm run dev`).
* Not pushed yet.

---

## [2026-08-03] - Bulletin List: Chronological Ordering + Sortable Columns

Fabio flagged that the PAGASA TCB Bulletins table was ordered by "download
stack" (insertion/bulletin_count order) rather than chronologically, and
asked for it to be sortable.

### 1. File: `backend/app/api/bulletins.py`
* `list_bulletins()`: changed `ORDER BY` from `bulletin_count.desc()` to
  `issued_at.desc()`. `bulletin_count` resets to 1 per typhoon, so ordering
  by it interleaved typhoons out of true chronological order (e.g. an old
  typhoon's bulletin #21 would outrank a newer typhoon's #3 issued more
  recently). Newest-issued-first remains the default direction.

### 2. File: `frontend/src/app/components/MonitoringModule.tsx`
* Added `BulletinSortField` / `SortDir` types and `bulletinSortField`
  (default `"issued_at"`) / `bulletinSortDir` (default `"desc"`) state,
  matching the default chronological order now returned by the backend.
* Added `sortedBulletins` (`useMemo`): client-side stable sort over
  `bulletin_count`, `typhoon_name`, `issued_at` (parsed via `Date.parse`,
  not string comparison), `category`, `max_sustained_winds`, or `gustiness`.
  Kept separate from the raw `bulletins` array so sorting the table doesn't
  change what `latestBulletin = bulletins[0]` refers to.
* Added `handleBulletinSort()`, `BulletinSortIcon`, and `bulletinSortableCols`,
  and made the bulletin table's column headers (`Bulletin`, `Typhoon`,
  `Issued`, `Category`, `Max Winds`, `Gust`) clickable to toggle sort
  field/direction -- mirrors the existing clickable-header +
  `ChevronUp`/`ChevronDown` pattern already used in `AssessmentModule.tsx`
  and `SpatialAnalysisModule.tsx`, not a new UI pattern. The bulletin table
  body now renders `sortedBulletins` instead of `bulletins`.

### Status / Next Steps
* Not run against Fabio's venv/frontend dev server yet -- needs a visual
  check in the Monitoring module (click each column header, confirm asc/desc
  toggle and icon state).
* Not pushed yet.

---

## [2026-08-03] - Remove Duplicate `GET /api/assessments` Route

Long-flagged known issue (first noted in the Sprint 3/4 merge entries, "known
duplication, not resolved here"): `backend/app/main.py` had an ad hoc
`GET /api/assessments` (no trailing slash) alongside the real
`GET /api/assessments/` route in `backend/app/api/assessments.py`. FastAPI
treated them as distinct paths so both coexisted without erroring, but they
returned different response shapes from different queries.

### 1. File: `backend/app/main.py`
* Removed `get_all_assessments()` and its `@app.get("/api/assessments")`
  route. Confirmed dead code first: grepped `frontend/`, `backend/`, `docs/`,
  and `.claude/` for any caller of the bare path or the function name --
  `frontend/src/lib/api.ts` only ever calls the trailing-slash router route
  (`/api/assessments/`, `/api/assessments/calculate`, etc.), and nothing else
  in the repo referenced the ad hoc one. `models` import left in place --
  still used elsewhere in the file (`models.ParserSettings`, `models.Farm`
  in `test_database_connection()`).

### Status / Next Steps
* Pure deletion, no behavior change for any working code path -- no test
  suite run needed to verify.
* Not pushed yet.

---

## [2026-08-03] - Login Page Static Layout

### 1. File: `frontend/src/app/components/LoginScreen.tsx`
* Root container changed from `min-h-screen` to `h-screen overflow-hidden` --
  the login page no longer grows taller than the viewport and scrolls; it's
  fixed to viewport height.
* Trimmed vertical spacing throughout (header padding, logo/title margins,
  demo-credentials box, register link, footer note) so the full card fits
  within typical viewport heights without clipping -- flagged by Fabio after
  the initial `overflow-hidden` change cut off the bottom of the card on his
  screen.
* Removed the "A" logo square above the "AgriSureGIS" title entirely (kept
  just the text) -- per Fabio's explicit request, both to match his intended
  look and to free up more vertical space.
* Center content wrapper (`flex-1 min-h-0 overflow-y-auto`) is a safety net
  for unusually short viewports -- normally the trimmed spacing means it
  fits without any scrolling at all.

### Status / Next Steps
* Verified working directly with the user -- full card (through Demo
  Credentials and the Register link) renders without clipping and without a
  page scrollbar.
* Pushed to `develop`.

---

## [2026-08-03] - Login Page: Viewport-Relative Spacing (Fabio Feedback Round 2)

Fabio reported the previous fixed-spacing fix still showed a scrollbar on his
screen ("e flexible kay lahi ug result sa lahi nga screen res" -- fixed
pixel/rem spacing gives different results across different screen
resolutions).

### 1. File: `frontend/src/app/components/LoginScreen.tsx`
* Replaced fixed padding/margin values throughout the login card (top bar,
  title block, card header, role selector, form fields, submit button, demo
  hint, register link, footer note) with `clamp(min, Nvh, max)` arbitrary
  values -- spacing now scales with viewport height instead of being tuned
  for one specific screen size, so it compresses automatically on shorter
  screens rather than triggering the `overflow-y-auto` scroll fallback.

### Status / Next Steps
* Not yet re-verified on Fabio's actual screen -- needs his confirmation
  after this change.
* Pushed to `develop`.

---

## [2026-08-03] - Spatial/Data Import: "Active Insurance Only" Filter

### 1. File: `frontend/src/app/components/SpatialAnalysisModule.tsx`
* Added `activeInsuranceOnly` state and a toggle button ("Active Insurance
  Only", `ShieldCheck` icon) in the Farm Records table header, styled to
  match the existing SAR/GEE toggle button convention.
* Added `isActiveInsurance()` helper: client-side filter mirroring the exact
  "active" definition already used by `GET /api/insurance/summary`
  (`backend/app/api/insurance.py`) -- today's date falls within
  `effectivity_date`-`expiry_date`, inclusive, both non-null. No backend
  change needed since `Farm` rows already carry both date fields.
* `filteredFarms` now also filters on `activeInsuranceOnly` alongside the
  existing municipality filter, before sorting.
* Dates from the API are formatted as `MM/DD/YYYY` (`backend/app/api/farms.py`
  lines 49-50), not ISO -- initial version of `isActiveInsurance()` wrongly
  compared them as ISO strings and silently matched nothing. Fixed by adding
  `parseMDY()` to parse into `Date` objects before comparing, catchable only
  by testing against live data (flagged by Fabio).

### Status / Next Steps
* Verified working directly with the user against the live `/api/farms/`
  data -- correctly isolates farms whose policy window covers today.
* Investigated (read-only, no changes made) a ~15-month effectivity-to-expiry
  span on farm_id 19's policy that looked suspicious for a per-season
  typhoon product -- traced to unvalidated CSV import pass-through
  (`backend/app/api/upload.py`, `_parse_date()`/`prepare_row_payload()` have
  no duration sanity check), not a bug in this filter or in date parsing.
  Fabio deferred adding import validation to a separate future task.
* Not yet pushed.

---

## [2026-08-03] - Assessment & Reporting: "View Areas Affected" Modal

### 1. File: `frontend/src/app/components/AssessmentModule.tsx`
* Added `AreasAffectedModal` component: fetches `getBulletinSignals(tcbId)` for
  every TCB belonging to the selected typhoon and merges them into a unique,
  all-areas list (by highest signal level) -- unlike the pre-existing
  `typhoonSummary.areas_hit` (backed by `tbl_area_exposure_summary`), this
  does not drop areas whose name failed to match an `AdminBoundary` row in
  `ExposureCalculatorService` (`backend/app/services/exposure_calculator.py:44-47`
  silently `continue`s on unmatched names). Where a computed exposure match
  exists it's shown (hours/start/end); where not, the area still appears with
  its signal level and `--` for exposure fields.
* Replaced the always-inline typhoon exposure summary card
  (previously `AssessmentModule.tsx:353-433`) with a compact bar shown on
  typhoon selection, holding a new "View Areas Affected" button (opens the
  modal) alongside the existing "Compute Assessments" button -- keeps the
  main assessment table uncluttered by default per Fabio's request to
  "isolate it to [a] window."
* No backend or API changes -- reuses the existing
  `GET /api/bulletins/{tcb_id}/signals` and
  `GET /api/bulletins/typhoon/{typhoon_id}/summary` endpoints.

### Status / Next Steps
* Verified working directly with the user -- button and modal render and
  open correctly.
* Investigated (read-only, no changes made) why the modal shows "no areas
  listed" for the typhoons Fabio tested: confirmed via live API that
  `tbl_tcb_signals` has zero rows for all 80 bulletins currently in the dev
  DB. Root cause: `AdminBoundary` (used for province+municipality substring
  matching in `bulletin_parser.py:342-365`) is seeded for Bukidnon +
  Misamis Oriental only, while the PAGASA scraper pulls bulletins
  nationwide -- storms that never track through Region X correctly produce
  zero signal rows (matches a checked-in real test case,
  `docs/TCB#11_kiyapo.pdf`, a Luzon-only storm asserting `signals == {}`).
  This is a pre-existing scope/matching limitation in the bulletin parser,
  not a bug introduced by this modal. Fabio deferred further investigation
  (e.g. checking a real bulletin's raw text for a genuine matching miss) to
  a separate future task.
* Not yet pushed.

---

## [2026-08-03] - Nationwide TCB Signal Extraction & Per-Level Areas Display

Fabio's follow-up to the "View Areas Affected" modal: the modal was correctly
scoped to Region X only (per the original parser design), but Fabio wants a
GIS specialist to see a typhoon's full national footprint regardless of
whether it reaches Mindanao. Separately, testing this surfaced a real display
bug in the existing TCB Viewer modal (Monitoring module) where areas under
different signal levels were merged into one misleading list.

### 1. File: `backend/app/services/bulletin_parser.py`
* `parse_bulletin_text()`: TCWS table extraction (section 5) now reads all
  three island columns (Luzon, Visayas, Mindanao), not just Mindanao. Return
  shape of `signals` changed from `dict[level, str]` to
  `dict[level, dict[island_group, str]]` (island_group 0=Luzon, 1=Visayas,
  2=Mindanao).
* Added `_split_named_areas()`: best-effort split of a TCWS cell's free-text
  area list into province/region-level phrases for Luzon/Visayas (no
  `AdminBoundary` data exists to validate matches outside Region X) — strips
  parenthetical municipality detail and the fixed "Warning lead time: .../
  Range of wind speeds: .../ Potential impacts of winds: ..." boilerplate
  block that follows every cell (found via live-testing against a real
  PAGASA scrape — it was leaking into the split as bogus "area" entries),
  then splits on commas. Caps each phrase at 100 chars to fit
  `TcbSignal.area_name`'s existing `varchar(100)` — no schema change needed.
* `save_bulletin_to_db()`: Mindanao (`island_group=2`) matching against
  `AdminBoundary` is unchanged (still feeds exposure/indemnity calculations,
  stays precise). Luzon/Visayas now get `TcbSignal` rows too, via
  `_split_named_areas()`, informational only.
* Verified end-to-end against a live PAGASA scrape (after Fabio reset
  `tbl_tcb_signals`/`tbl_tropical_cyclone_bulletins`/`tbl_typhoons` and
  re-ran `POST /api/bulletins/parse` twice — once to catch the boilerplate
  bug, once after the fix): KIYAPO Bulletin NR. 11 (`docs/TCB#11_kiyapo.pdf`,
  tcb_id 167) produced clean Luzon area names matching the source PDF exactly
  (e.g. "Batanes", "the northern portion of Cagayan including Babuyan
  Islands", "Isabela", "Quirino", ...).

### 2. File: `backend/tests/test_bulletin_parser.py`
* Updated `test_parse_bulletin_text_extracts_mindanao_signals_from_table`
  (renamed `..._extracts_signals_from_all_island_columns`) and
  `test_parse_bulletin_text_against_real_sample_pdf` for the new nested
  `signals` shape — KIYAPO's real Luzon text is now asserted present
  (previously asserted as an empty dict, which was correct under the old
  Mindanao-only scope but no longer reflects what the parser captures).
  Updated `test_save_bulletin_to_db_creates_bulletin_and_signals` similarly.
* Added `test_split_named_areas_strips_parens_and_splits_on_commas`,
  `test_split_named_areas_strips_warning_lead_time_boilerplate` (regression
  test for the boilerplate leak found via live testing), and
  `test_save_bulletin_to_db_creates_best_effort_luzon_visayas_signals`.
* Not yet run by Fabio against this exact final version — verified instead
  via the live end-to-end scrape described above.

### 3. File: `frontend/src/app/components/AssessmentModule.tsx`
* `AreasAffectedModal`: merge key now includes `island_group` (not just
  `area_name`) so same-named phrases on different islands can't collide.
  Exposure-match lookup restricted to `island_group === 2` (Mindanao) only,
  since exposure/indemnity data never exists for Luzon/Visayas. Added an
  "Island Group" column to the table and an `ISLAND_GROUP_LABELS` lookup.
  Info banner text updated to explain Luzon/Visayas areas are
  situational-awareness only, not tied to insurance eligibility.

### 4. File: `frontend/src/app/components/MonitoringModule.tsx`
* `TCBViewerModal` previously computed one `highestSignal` (max across all
  signal rows) and merged every area from every signal level into one flat
  list shown under that single header — a Signal No. 1 area and a Signal
  No. 3 area for the same bulletin looked identical. Found while showing
  Fabio the FRANCISCO TCB No. 7 example (which genuinely only had Signal
  No. 1 data — not a bug, just prompted the review that found this one).
* Added `groupAreasBySignalLevel()` and `signalLevelColor()` helpers. Areas
  are now grouped into one section per signal level actually present in the
  data, sorted highest-to-lowest, each with its own "Signal No. X" header
  and color. Also fixes a latent color bug where signal levels 4/5 fell
  through to the default (green, "low severity") color since the old ternary
  only special-cased levels 2 and 3.
* `handleDownloadTCB()`'s exported `.txt` summary updated to the same
  grouped-by-level structure for consistency.
* The top headline box (category + highest signal + winds/gusts) is
  unchanged — kept as an at-a-glance bulletin-level summary.

### Status / Next Steps
* Verified working directly with the user in the browser for both the
  Assessment "View Areas Affected" modal (island group column) and the
  Monitoring "TCB Viewer" modal (per-level grouping).
* Pushed to `develop`.

---

## [2026-08-04] - Bulletin Title Parsing: Missing Categories & Smart Quotes

Fabio asked why the app "does not parse the latest bulletins." Root cause
traced by fetching PAGASA's live bulletin index directly and inspecting the
actual PDF behind the newest bulletin the app had misfiled: LUIS weakened
into a Low Pressure Area, and its final bulletin's title
("Low Pressure Area (formerly "LUIS")") didn't match any of the four
category keywords `parse_bulletin_text()` recognized, so it silently fell
back to a literal `"UNKNOWN"` typhoon name/category — forking that and any
other similarly-titled bulletin onto one fake shared "UNKNOWN" Typhoon row
instead of reuniting with the real one. The bulletin *was* being fetched and
numbered correctly; it just became invisible under the real typhoon's name
in the UI.

### 1. File: `backend/app/services/bulletin_parser.py`
* `parse_bulletin_text()`: added `SUPER TYPHOON` to the recognized category
  alternation (a real PAGASA category above Typhoon, previously missing
  entirely).
* Added a fallback `lpa_match` regex (tried only when the main category
  regex doesn't match) for the `Low Pressure Area (formerly "NAME")` title
  format PAGASA uses on a storm's final bulletin once it weakens below
  tropical depression strength — extracts `NAME` as the typhoon name so it
  reunites with the storm's existing Typhoon row, with category set to
  `"Low Pressure Area"`.
* First version of this fix used a `["']?` quote character class and still
  silently failed against the real bulletin -- confirmed via `pdftotext`
  that PAGASA renders Unicode "smart quotes" (`“`/`”`), not straight ASCII
  quotes, around the former name. Broadened the quote class (shared `QUOTES`
  constant, used in both the main title regex and the new LPA fallback) to
  cover straight and curly single/double quotes (straight `"`/`'` plus their
  curly counterparts).
* Verified end-to-end via a live PAGASA scrape (after Fabio reset
  `tbl_tcb_signals`/`tbl_tropical_cyclone_bulletins`/`tbl_typhoons` twice —
  once per fix iteration): all 83 bulletins now group under their real
  typhoon names with zero `UNKNOWN`/garbled entries. LUIS went from stuck at
  12 bulletins to the correct 13 (its real final "Low Pressure Area"
  bulletin); JOSIE went from 2 to the correct 3; BAVI (previously entirely
  missing) now appears correctly as "Super Typhoon".

### 2. File: `backend/tests/test_bulletin_parser.py`
* Added `test_parse_bulletin_text_extracts_super_typhoon_category`,
  `test_parse_bulletin_text_recognizes_low_pressure_area_formerly_title`
  (uses real Unicode smart quotes, matching the actual PDF — a straight-quote
  version of this same test would have passed against the first, still-buggy
  fix and missed the regression),
  `test_parse_bulletin_text_recognizes_low_pressure_area_with_straight_quotes`,
  and `test_parse_bulletin_text_unrecognized_title_still_falls_back_to_unknown`
  (keeps the `UNKNOWN` fallback covered for genuinely unparseable titles).
* Not yet run by Fabio against this exact final version — verified instead
  via the live end-to-end scrape described above.

### Status / Next Steps
* Only affects newly parsed bulletins going forward; already-mis-filed
  historical data required the two reset+rescrape cycles performed during
  this session to clean up (done).
* Pushed to `develop`.

---

## [2026-08-04] - Mock Data: Typhoon ALBRITCH + Bukidnon Farmers

Fabio asked for a self-contained mock dataset for testing: a fictional
typhoon with 10 bulletins seeded directly (no PAGASA scraping), plus 3
farmers/10 farms in real Bukidnon locations. Follows the existing
`mock_farmers_talakag_claveria.csv` / `seed_mock_typhoon.py` precedent.

### 1. File: `backend/mock_data/mock_farmers_albritch_bukidnon.csv`
* 10 rows in the same PABS export column format as the existing mock CSV.
  Real Bukidnon municipalities/barangays confirmed against
  `app/data/psgc_region10_boundaries.csv`: Karylle Maagad (2 farms,
  Lantapan), Fabio Tugonon (3 farms, Impasug-ong), James Gayla (5 farms,
  2 in City of Malaybalay + 3 in Maramag). Policy numbers
  `POL-MOCK-92001`-`92010`, farmers_id shared per farmer across their
  multiple farm rows. Effectivity 06/01/2026-12/31/2026 (matches the
  existing mock CSV's ~7-month window, deliberately not the ~15-month span
  flagged as a data-quality issue earlier this session).
* Uploaded via `POST /api/upload/csv` -- all 10 rows inserted successfully
  (`farm_id` 580-589).

### 2. File: `backend/mock_data/seed_mock_typhoon_albritch.py`
* Same pattern as `seed_mock_typhoon.py` (direct psycopg2 insert, bypasses
  `BulletinParserService`/the PAGASA scrape pipeline entirely per Fabio's
  "skip the scraping" request). Creates Typhoon "ALBRITCH" (2026) + 10
  bulletins at 6-hour intervals, tracking westward across Bukidnon with a
  realistic TD -> TS -> STS -> Typhoon (peak, 155 km/h) -> STS -> TS -> TD
  -> Low Pressure Area intensity arc -- the final bulletin's title/category
  mirrors the real "Low Pressure Area (formerly ...)" pattern found in
  `TCB#13_luis.pdf` earlier this session. Signals cover Lantapan,
  Impasug-ong, City of Malaybalay, and Maramag (the same 4 municipalities
  as the mock farmers CSV) with `island_group=2` (Mindanao) -- corrects a
  placeholder value of `3` used in the older `seed_mock_typhoon.py`, which
  predates the real island_group convention established in
  `bulletin_parser.py` this session.
* Run by Fabio in his venv (`python mock_data/seed_mock_typhoon_albritch.py`)
  -- created typhoon_id 51, tcb_id 409-418.
* Verified end-to-end: `POST /api/bulletins/{tcb_id}/compute-exposure` ->
  all 4 municipalities show Signal 4, 42-48h exposure, `is_eligible_6hr`.
  `POST /api/assessments/calculate` -> 4 of 10 policies got a computed
  indemnity payout (assessment_id 590-593, ₱10,752-₱17,920); the other 6
  hit a pre-existing gap in `tbl_recsap_matrix`/`tbl_indemnity_factor_matrix`
  seed coverage (not every crop-stage x signal x 24h-bucket combination has
  a matrix row) -- flagged to Fabio, not fixed, since it's a real data gap
  unrelated to this mock scenario and out of scope for what was asked.

### Status / Next Steps
* Not yet pushed.

---

## [2026-08-04] - Assessment Table Now Actually Filters by Selected Typhoon

Fabio caught this using the new ALBRITCH mock data: selecting "Typhoon LUIS"
in the left sidebar left ALBRITCH's already-computed rows showing in the
main table, with no indication they belonged to a different typhoon --
confusing for a GIS specialist trying to tell what's actually affected by
which storm.

### 1. File: `frontend/src/app/components/AssessmentModule.tsx`
* Root cause: `filtered` (the main table's row source) was never filtered
  by `selectedTyphoonId` at all -- the left sidebar's typhoon selection only
  ever scoped the "View Areas Affected" modal and "Compute Assessments"
  button, never the table itself, despite visually looking like a table
  filter.
* Added `selectedTyphoonName` (resolved from `typhoons` by id) and a new
  `.filter(r => selectedTyphoonName === null || r.TYPHOON_NAME ===
  selectedTyphoonName)` step in `filtered`. Matches by name (a plain string
  field on `PabsAssessmentRow`) rather than typhoon_id, consistent with how
  `typhoons` itself is already deduped by name to route around the known
  bulletin-title-parsing quirk that can split one real typhoon across
  multiple `typhoon_id` rows.
* Top badge now reads "Typhoon {name} only" instead of always "All typhoons
  combined" when a typhoon is selected.
* Added a distinct empty-state message ("No assessments computed yet for
  Typhoon {name}") for the case where a typhoon is selected but has zero
  matching rows, instead of silently falling through to a zeroed-out table.
* CSV export/preview (`CSVPreviewModal`) already consumes `filtered`, so it
  automatically respects the same typhoon scoping now too.

### Status / Next Steps
* Verified working directly with the user in the browser.
* Not yet pushed.

---

## [2026-08-07] - Environment Recheck: uvloop Marker, DB Config Wiring

Fabio asked for a recheck that Postgres/venv/npm are set up correctly.
Read-only inspection found: `.venv` already has all `requirements-win.txt`
packages installed (Postgres port 5432 reachable; GeoServer port 8080 is
not, which is expected/optional per `.claude/ENV_GUIDE.md`); frontend
`node_modules` already installed. Found two real gaps, fixed here.

### 1. File: `backend/requirements.txt`
* Fabio had already changed `uvloop==0.22.1` to
  `uvloop==0.22.1; sys_platform != "win32"` (uvloop doesn't support Windows;
  `backend/requirements-win.txt` already excluded it entirely). Committing
  it now — confirmed it matches the actual `.venv` (no uvloop installed).

### 2. File: `backend/app/core/database.py`
* `SQLALCHEMY_DATABASE_URL` was fully hardcoded in source, including a
  plaintext password, despite `.claude/ENV_GUIDE.md` documenting a
  `DATABASE_URL` env var and its own "Key Security Rule" saying never to put
  DB passwords in the codebase. `python-dotenv` was already installed
  (listed in both requirements files) but never imported anywhere in the
  backend.
* Added `load_dotenv()` + `os.getenv("DATABASE_URL", <old hardcoded value>)`
  so `backend/.env` (once Fabio creates one) overrides the connection
  string; the previous hardcoded value stays as the fallback default so
  behavior is unchanged until `.env` exists.

### 3. File: `backend/.env.example` (new)
* Did not exist on disk at all — `.claude/ENV_GUIDE.md` instructs copying
  it to `backend/.env` but there was nothing to copy. Added placeholders
  for `DATABASE_URL`, `PAGASA_SCRAPE_URL`, `SMTP_HOST`, `SMTP_USER`,
  `SMTP_PASSWORD` (the backend-side vars from `ENV_GUIDE.md`'s table — the
  `VITE_*` frontend vars already have their own `frontend/.env.example`).

### Status / Next Steps
* Not yet pushed. Fabio still needs to create `backend/.env` himself with
  the real `DATABASE_URL` (and confirm the `agrisure_db`
  database/`agrisure_admin` user/PostGIS extension actually exist — not
  verifiable from this environment, needs his `psql` access).

---

## [2026-08-07] - CSV Ingestion Performance Fix (Stall on Large Files)

Reported symptom: CSV ingestion "takes an unusually long time" and "appears
to stall before finishing," evidenced by a Network-tab screenshot where the
`csv` upload request sat Pending indefinitely while unrelated background
requests (the 60s bulletin poll in `App.tsx`) kept completing normally --
proving the backend process itself wasn't hung, just the ingestion request.

**Root cause:** `tbl_farms.csv_farm_reference` and
`tbl_admin_boundaries (province, municipality, barangay)` had no DB index,
but `upload_csv()`'s per-row loop queried them on every row not already in
its in-process cache. Since `csv_farm_reference` is normally unique per
row, almost every row triggered a full sequential scan of `tbl_farms` --
and that table grows by one row for every farm this same upload has
already inserted, making a large, mostly-new-farms CSV import an
effectively O(n²) scan. On the real ~23,917-row PABS export this is what
actually produced the "stall"; on top of that, the loop did up to ~10 DB
round trips per row (SAVEPOINT + up to 4 SELECTs + up to 4 flushes +
RELEASE) with zero logging anywhere, so a merely-slow ingest and a truly
dead one looked identical from the outside.

### 1. File: `backend/app/api/upload.py`
* Added **`_prefetch_caches()`**: bulk-loads everything the upload's rows
  are going to look up *before* the per-row loop starts -- the whole
  `tbl_admin_boundaries` table (small, bounded by one PSGC region) in one
  query, plus `tbl_farmers_profile`/`tbl_farms` rows matching the CSV's own
  `farmers_id`/`rsbsa_no`/`csv_farm_reference` values via chunked
  `WHERE ... IN (...)` queries (`_PREFETCH_CHUNK_SIZE = 1000` per chunk, via
  new helper **`_chunked()`**). `_ingest_row()` itself is unchanged -- it
  already checked the cache before falling back to a per-row `SELECT`, so
  pre-populating that same cache is what removes the scan from the hot path
  without touching row-level insert/skip/dedup semantics.
* **`upload_csv()`**: now parses every row into a payload up front (a
  parse-only failure is recorded immediately, with no SAVEPOINT spent on
  it), calls `_prefetch_caches()` once, then runs the existing per-row
  SAVEPOINT/insert/skip loop against the pre-populated caches. Added
  `logger.info` at ingestion start (filename + row count), prefetch
  completion (counts per cache), every 1000 rows during the loop (elapsed
  time, rows/sec, running inserted/skipped/failed counts,
  `_PROGRESS_LOG_EVERY`), and at completion (total elapsed time + final
  counts); added `logger.warning` per failed row and `logger.exception` on
  an unhandled-exception rollback. Response shape (`UploadCsvResult`) is
  unchanged.

### 2. File: `backend/init_schema.sql`
* Added `idx_farms_csv_farm_reference` and
  `idx_admin_boundaries_province_municipality_barangay` indexes (fresh-install
  schema only -- see Status/Next Steps for the live-DB command).

### 3. File: `backend/tests/test_upload_csv_ingestion.py`
* Extended the mocked-DB test harness (`_FakeTable`, `_FakeQuery`,
  `_extract_filter`) to also support `.all()` and `.filter(Model.column.in_(...))`,
  since `_prefetch_caches()` now issues those in addition to the
  `.filter(...).first()` calls the harness already simulated.
* Updated `test_repeated_boundary_across_many_rows_is_only_queried_once` and
  `test_same_rsbsa_no_across_rows_is_only_queried_once`: expected DB query
  count changed from 1 to 2 (one upfront prefetch call + one real per-row
  fallback on the first genuinely-new value) -- still asserts the count
  doesn't scale with the number of repeated rows, just with a different
  constant.
* Added **`test_large_file_all_rows_accounted_for_with_no_duplicates()`**:
  ingests 1,550 rows (1,500 distinct + 50 exact re-uploads of earlier rows)
  to exercise the chunked prefetch across multiple `_PREFETCH_CHUNK_SIZE`
  batches and confirm row accounting (`processed == inserted + skipped +
  failed`) and dedup/no-duplication behavior still hold at that scale.

### Status / Next Steps
* **Fabio, DB Admin action needed:** the two new indexes only apply to a
  fresh `init_schema.sql` run. To speed up ingestion against the database
  that already exists, run this directly (non-destructive, safe to run
  regardless of order relative to anything else):
  ```sql
  CREATE INDEX IF NOT EXISTS idx_farms_csv_farm_reference ON tbl_farms (csv_farm_reference);
  CREATE INDEX IF NOT EXISTS idx_admin_boundaries_province_municipality_barangay
      ON tbl_admin_boundaries (province, municipality, barangay);
  ```
* **Verified by Fabio (2026-08-07):** `pytest backend/tests/test_upload_csv_ingestion.py
  backend/tests/test_csv_upload.py -v` → **19 passed**. The mocked-DB harness
  changes were written by reasoning through SQLAlchemy's expression internals
  (`Column.in_()` → `BinaryExpression.operator is sqlalchemy.sql.operators.in_op`,
  confirmed by reading the installed SQLAlchemy source) rather than by
  executing them, since this environment can't run Python against the
  project -- Fabio's run is what actually confirms they're correct.
* **Measured (Fabio, 2026-08-07, local dev machine, indexes applied):**
  `backend/scripts/benchmark_csv_ingestion.py --rows 24000` → all 24,000 rows
  brand-new (no pre-existing farmers/farms to hit the prefetch cache, i.e. the
  worst case for row-by-row insert overhead) → **272.2s, 88.2 rows/sec,
  24,000 inserted / 0 skipped / 0 failed**. No true "before" (pre-fix, no
  index) number was captured -- reverting the code/index to measure it
  wasn't worth the risk on a real environment -- but this confirms the
  process now runs to completion in minutes rather than hanging/stalling on
  a file at the real ~23,917-row PABS export's scale, with correct,
  complete, non-duplicated row accounting throughout.
* First benchmark attempt failed for an unrelated reason worth recording:
  the script's synthetic `FarmersID` values initially exceeded
  `tbl_farmers_profile.farmers_id`'s `VARCHAR(20)` limit, so Postgres
  correctly rejected all 24,000 rows with `StringDataRightTruncation` --
  fixed by shortening the generated IDs. Notably, that all-failure run still
  completed in 69.9s (343 rows/sec) with zero hang, since a rejected insert
  is just a cheap per-row SAVEPOINT rollback.
* Remaining limitation: 88.2 rows/sec is still one-row-at-a-time
  SAVEPOINT+INSERT+flush, just no longer with an O(n²) unindexed scan on
  top. If CSVs grow substantially past ~25k rows, the next lever is
  switching per-row inserts to `bulk_insert_mappings`/`COPY`, which would
  require redesigning the per-row-failure-isolation architecture the
  existing tests depend on -- left out of scope for this fix.

---

## [2026-08-07] - Farm Records table: fix N+1 query + smooth loading UX

### 1. File: `backend/app/api/farms.py`
* **Changes to Functions:**
  * Rewrote **`list_farms()`**: replaced the per-farm `InsuranceRecord` query
    (plus lazy-loaded `Farm.farmer`/`Farm.boundary`, which also default to
    one query per row) with `joinedload(Farm.farmer)`/`joinedload(Farm.boundary)`
    on the initial query and a single bulk `InsuranceRecord` fetch reduced to
    "most recent per farm" in Python via `dict.setdefault()` on a
    `farm_id, effectivity_date DESC`-ordered result set. Cuts the endpoint
    from ~1 + up to 3-per-farm queries (~1,770 for the current 589 farms) to
    2 queries total, regardless of farm count. Response shape (`{"status",
    "data"}`) and every field are unchanged.

### 2. File: `frontend/src/app/components/SpatialAnalysisModule.tsx`
* **Changes to Functions/Rendering:**
  * Added a `visibleRowCount` state + `useEffect` that grows the number of
    rendered Farm Records rows in `ROW_BATCH_SIZE` (50) increments via
    `requestAnimationFrame`, re-triggered on `filteredFarms.length` changes.
    The table now paints its first ~50 rows immediately after data loads and
    fills in the rest across a few frames instead of mounting all rows (589
    currently) in one blocking paint. The full dataset is fetched in one
    call as before (unchanged) — needed since the map (`GISLeafletMap`),
    municipality filter, and sort all read from the same `farmRows`/
    `filteredFarms` arrays and require the complete set to stay correct;
    only the row *paint* is staggered, not the fetch.
  * Replaced the empty `<tbody>` shown while `isLoadingFarms` is true with
    `SKELETON_ROW_COUNT` (10) placeholder `<tr>` rows using the
    previously-unused `Skeleton` primitive (`ui/skeleton.tsx`), one per
    column (`TABLE_COLUMN_COUNT` = 12), instead of a blank table body with
    only the header pill reading "Loading…".
* **Why:** the "Active Typhoon"/"Farm Records" screen would sit blank/frozen
  until the entire (previously N+1-slow) farms response arrived, then mount
  all rows in a single React commit. Fixing the backend query removes the
  actual wait; the frontend batching/skeleton changes smooth out the
  remaining paint so the table doesn't visibly block even on a fast
  response. Considered true pagination/infinite-scroll first, but rejected
  it — it would've left the map and municipality/sort filters incomplete
  until the user finished scrolling the table, since they all read the same
  in-memory farm list.

---

## [2026-08-07] - Farm Records table: revert row-reveal animation

### 1. File: `frontend/src/app/components/SpatialAnalysisModule.tsx`
* **Changes to Functions/Rendering:**
  * Removed the `visibleRowCount` state and its `requestAnimationFrame`
    growth effect added earlier the same day; the table body now renders
    `filteredFarms` directly again (no `.slice(0, visibleRowCount)`), and
    the now-unused `ROW_BATCH_SIZE` constant was removed with it.
  * The `isLoadingFarms` skeleton placeholder rows (`SKELETON_ROW_COUNT`,
    `TABLE_COLUMN_COUNT`, `ui/skeleton.tsx`) are unchanged and still shown
    while the initial fetch is in flight.
* **Why:** Fabio reported the batch-reveal animation itself was visible as
  rows "moving" every time the screen opened. The animation was meant to
  smooth out mounting hundreds of `<tr>`s at once, but for this dataset size
  the visible motion it introduced was worse than the jank it was solving —
  reverted to a single static render once data arrives, keeping only the
  backend N+1 fix and the loading-state skeleton from the prior entry.

---

## [2026-08-07] - Farm Records table: remove loading skeleton too

### 1. File: `frontend/src/app/components/SpatialAnalysisModule.tsx`
* **Changes to Functions/Rendering:**
  * Removed the `isLoadingFarms` skeleton `<tr>` block (`SKELETON_ROW_COUNT`,
    `TABLE_COLUMN_COUNT`, the `Skeleton` import from `ui/skeleton.tsx`) added
    two entries above. The table body now renders only `filteredFarms.map(...)`
    — an empty `<tbody>` while loading (with the header pill reading
    "Loading…", unchanged), then the full table in one static pass once data
    arrives. This is now functionally identical to the file's pre-2026-08-07
    rendering; the only surviving change from today is the backend N+1 fix
    in `farms.py`.
* **Why:** the right-aligned numeric columns (Area (ha), Exp (h), Est.
  Payment) render a full-width skeleton bar while loading vs. short
  right-anchored text once loaded, which read as text jumping from left to
  right on every screen open — the same "I want it static" complaint as the
  row-reveal animation. Rather than patch the skeleton's alignment per
  column, removed the skeleton loading state entirely to guarantee no visual
  motion between the loading and loaded states.

---

## [2026-08-07] - Farm Records table: no header-over-blank-body loading state

### 1. File: `frontend/src/app/components/SpatialAnalysisModule.tsx`
* **Changes to Rendering:**
  * Wrapped the `<table>` (header + body) in `{isLoadingFarms ? (...) : (...)}`
    inside the scrollable panel `<div>`. While loading, that panel now shows
    a single centered "Loading farm records…" message instead of the table
    shell; the `<table>` (with its `<thead>`/`<tbody>`) only mounts once
    `isLoadingFarms` is false, fully populated.
* **Why:** even with no skeleton or animation, the green `<thead>` was still
  rendering immediately with an empty `<tbody>` beneath it while loading —
  visually indistinguishable from a broken/empty table, and a different
  "shape" than the loaded state. Fabio compared the before/after screenshots
  directly and wanted them structurally consistent: no header sitting over
  blank rows. Swapping the whole table for a loading message (rather than
  showing a partial table) removes that mismatched mid-state entirely — one
  atomic swap from "loading" to "fully loaded table," nothing in between.

---

## [2026-08-07] - Monitoring stat card: fix "Active Typhoon" wrapping to two lines

### 1. File: `frontend/src/app/components/MonitoringModule.tsx`
* **Changes to Rendering (Fabio's own edit, logged here for the record):**
  * `statCards`: the "Active Typhoon" card's fallback value changed from
    `"—"` to `"N/A"`, and its icon shrunk from `size={18}` to `size={14}`, so
    the fallback text fits on one line within the card instead of wrapping.

### 2. File: `.claude/settings.json`
* **New file:**
  * Adds `{"permissions": {"defaultMode": "bypassPermissions"}}` as the
    project-level Claude Code permission default.

---

## [2026-08-08] - Farm Records: paginated first load with infinite scroll +
## default active-insurance-only filter

Reported symptom (screenshot): opening the Spatial Analysis screen blocks
the whole "Farm Records" panel behind a single "Loading farm records…"
message until the entire `GET /api/farms/` response has arrived, with
nothing visible in the meantime -- Fabio wanted the table to show *some*
real data immediately and load the rest as the user scrolls, rather than
one all-or-nothing fetch.

This directly follows the three same-day reverts logged under
`[2026-08-07] - Farm Records table: ...` above -- those attempts only
re-staggered the *paint* of an already-fully-fetched array (row-reveal
animation, then skeleton rows) and were reverted for visible layout jank.
This entry changes how much data is actually in flight over the network
instead, which is why it lands differently.

### 1. File: `backend/app/api/farms.py`
* **Changes to Functions:**
  * `list_farms()` gains three optional query params: `limit: int | None`
    (`Query(None, ge=1, le=1000)`), `offset: int` (`Query(0, ge=0)`), and
    `active_only: bool` (`Query(False)`).
  * **Backward compatibility (required):** `MonitoringModule.tsx` also calls
    `getFarms()` with no args and expects the full unpaginated array back.
    Omitting `limit` runs the exact same unmodified query as before -- no
    `.offset()`/`.limit()`, no extra `COUNT` query -- so that caller sees
    zero behavior change.
  * When `limit` is given: `.offset(offset).limit(limit)` is applied to the
    existing farms query, plus one additional `COUNT` query for `total`. The
    bulk `InsuranceRecord` fetch is left structurally unchanged -- it already
    scopes to `farm_ids` from whichever `farms` list resulted, so it
    naturally becomes page-scoped. Still 2 real query executions per page
    (farms + insurance), a 3rd (`COUNT`) only when paginated -- no N+1
    reintroduced.
  * When `active_only=True`: restricts the farms query to farms with at
    least one `InsuranceRecord` currently bracketing today
    (`effectivity_date <= today <= expiry_date`, via a
    `Farm.farm_id.in_(subquery)` filter) -- the same "active" definition
    `SpatialAnalysisModule.tsx`'s `isActiveInsurance()` already applies
    client-side, now pushed into the query so an all-inactive farm is never
    fetched at all. The subquery is embedded in the farms query's WHERE
    clause (not separately executed), so it doesn't add a real query
    round-trip.
  * Response gains `total`, `limit`, `offset`, `has_more` fields (additive --
    existing callers only read `.data`). `has_more = offset + len(data) <
    total` when paginated; unpaginated responses get `total=len(data)`,
    `limit=None`, `offset=0`, `has_more=False` for shape consistency.
  * Docstring updated to describe the new params and restate the
    "2 (+1 COUNT) queries per page" guarantee.

### 2. File: `frontend/src/lib/api.ts`
* **Changes to Functions:**
  * `getFarms()` now takes an optional `{ limit?, offset?, active_only? }`
    param and returns the widened `GetFarmsResult` (adds `total`/`limit`/
    `offset`/`has_more`). Called with no args, as `MonitoringModule.tsx`
    still does, it hits `/api/farms/` with no query string -- unchanged
    behavior.

### 3. File: `frontend/src/app/components/SpatialAnalysisModule.tsx`
* **Changes to Functions/Rendering:**
  * Added **`mergeFarmsPage()`**: upserts a freshly-fetched page into the
    existing `farms` array by `farm_id` (new ids appended, existing ids
    updated in place) instead of replacing the array outright. This is what
    lets pagination grow the table incrementally *and* lets a CSV/GPX- or
    filter-triggered refetch update stale rows without the visible row count
    ever dropping mid-refresh -- old rows simply stay until fresh data for
    that same farm arrives.
  * Added **`fetchNextPage(reason)`**: the single place (besides the initial
    page-1 call) that issues a `GET /api/farms/` request, guarded by a
    shared `fetchInFlightRef`/`nextOffsetRef` pair so the scroll trigger and
    the background-completion loop never double-request the same page.
    Tracks a `generationRef` counter so a page fetch already in flight when a
    restart happens (CSV/GPX upload, or the Active-Insurance toggle) is
    discarded on resolve instead of corrupting the new sequence's cursor.
  * Added **`runBackgroundCompletion()`**: after page 1 lands, keeps fetching
    subsequent pages at a deliberately unhurried pace (`sleep(300ms)`
    between pages) so `GISLeafletMap`'s markers and the municipality filter's
    suggestion list become complete shortly after first paint, without
    competing for bandwidth/DB load against a user actively scrolling.
  * Added **`loadFarmsFromStart(reason)`**: (re)starts the fetch sequence
    from page 1 -- used on mount, on CSV/GPX upload (`refreshFarms()`, now a
    thin wrapper around this), and whenever the Active-Insurance toggle
    changes. Existing `farms` data is left untouched; `mergeFarmsPage` folds
    new pages in, so the table never blanks or shrinks mid-refresh.
  * Infinite scroll: a sentinel `<tr>` (spans all 12 columns, fixed height,
    shows "Loading more…" only while `isFetchingNextPage`) is appended after
    the table body while `hasMore`, observed via `IntersectionObserver`
    rooted at the table's existing scroll container -- fetches the next page
    once scrolled near the bottom. Chosen over a hand-rolled scroll-position
    listener since it's the first infinite-scroll implementation in the
    codebase and doesn't require reasoning about exact scroll geometry.
  * Loading-state split into three flags, replacing the old single
    `isLoadingFarms`: **`isLoadingFirstPage`** (nothing loaded yet -- the one
    case where the whole table panel still swaps to the "Loading farm
    records…" message, unchanged from the 2026-08-07 revert's end state),
    **`isRefreshing`** (a CSV/GPX/toggle-triggered refetch is in flight --
    header pill reads "Refreshing…", table stays fully visible throughout,
    no blank state), and **`isFetchingNextPage`** (scroll-triggered next-page
    fetch in flight -- drives only the small sentinel-row indicator).
  * `activeInsuranceOnly` now **defaults to `true`** (was `false`) and is
    threaded into every paginated fetch via `active_only`, not just the
    existing client-side filter on `filteredFarms` (left in place unchanged,
    as a harmless safety net). Toggling it calls `loadFarmsFromStart` to
    restart pagination under the new filter value; farms fetched under a
    prior filter state are never purged from the cache, they're just
    correctly hidden/shown by the existing client-side filter -- so
    switching back doesn't require re-fetching farms already seen once.
  * Accepted, explicitly-flagged side effect: for a non-default sort (e.g.
    by "Farmer"), rows can visibly reorder as background pages land -- real
    data changing, not animation, matching what was already accepted for the
    table growing during first load.

### 4. File: `backend/tests/test_farms_api.py` (new)
* Added `ListFarmsUnpaginatedTests`, `ListFarmsPaginationTests`,
  `ListFarmsActiveOnlyTests`, `ListFarmsResponseShapeTests` -- direct-call
  tests against `list_farms()` using a purpose-built `_ChainableQuery` fake
  (mirrors the `.options()/.order_by()/.filter()/.offset()/.limit()` chain
  the endpoint actually uses, with `.all()`/`.count()` call counters), same
  direct-call-with-mocked-`Session` style as `test_upload_gpx_api.py`.
  Covers: unpaginated backward compatibility (no `.offset()`/`.limit()`, no
  extra `COUNT`), pagination applying `.offset()`/`.limit()` correctly,
  `has_more` at the start/middle/last page, the insurance bulk-fetch staying
  scoped to the current page's `farm_ids` only, exactly 2 (+1 `COUNT` when
  paginated) query executions, `active_only` filtering by the
  effectivity/expiry date bracket and being a no-op when omitted, and the
  existing "most recent insurance record per farm" reduction still working
  after the refactor. FastAPI's `Query(..., ge=..., le=...)` bound
  validation is Pydantic/routing-layer behavior and isn't exercised by these
  direct-call tests -- consistent with the rest of this test suite, which
  has no `TestClient`-based tests anywhere.

### Status / Next Steps
* **Bug found and fixed via Fabio's first test run (2026-08-08):**
  `Farm.farm_id.in_(active_farm_ids)` raised `sqlalchemy.exc.ArgumentError`
  ("IN expression list, SELECT construct, or bound parameter object
  expected") -- in SQLAlchemy 2.x, a bare ORM `Query` object (what
  `db.query(InsuranceRecord.farm_id).filter(...).distinct()` returns) is not
  a valid `.in_()` operand; it must be converted to a `ScalarSelect` first.
  Fixed by appending `.scalar_subquery()` to `active_farm_ids` in
  `farms.py`. This would have failed on every real `active_only=true`
  request, not just the tests -- caught before this ever reached Fabio's
  running dev server. `test_farms_api.py`'s active-only tests were updated
  to match: the `InsuranceRecord.farm_id` branch of the test's fake
  `db.query()` router now returns a real, unbound (`session=None`)
  SQLAlchemy `Query` (needed for `.scalar_subquery()` to produce a genuine
  construct `Farm.farm_id.in_(...)` will accept) instead of the test's own
  `_ChainableQuery` fake, and the date-bracket assertion compiles the
  resulting filter criterion to SQL text (`literal_binds=True`) rather than
  introspecting the fake chain's call log.
* **Verified by Fabio (2026-08-08):** `pytest backend/tests/test_farms_api.py -v`
  → all 10 tests pass after the `.scalar_subquery()` fix above.
* Not run against a live database or the frontend yet -- Fabio still needs
  to click through the Spatial Analysis screen locally (fresh load,
  scroll-to-bottom, leave it idle to watch background completion, toggle
  Active Insurance Only, and a CSV/GPX upload) to confirm the UX matches the
  plan's verification checklist.
* `PAGE_SIZE = 100` and the 300ms background-completion delay are fixed
  constants for this pass (not configurable), per Fabio's direction.
* The municipality filter's suggestion list intentionally has no "still
  loading full list…" indicator -- it silently grows as background pages
  land, consistent with how the table itself grows silently, per Fabio's
  direction.

---

## [2026-08-08] - Farm Records: lift the fetch to app-level, shared with
## Monitoring's stats

Follow-up to the entry directly above, raised by Fabio during the frontend
walkthrough: farm records should start loading the moment the app opens
(right after login), not wait until the user navigates into the Spatial
Analysis tab. `SpatialAnalysisModule` only mounts when `activeModule ===
"spatial"` (`App.tsx`), so the whole pagination pipeline built above never
even started until then.

This surfaced a real conflict worth recording: `MonitoringModule` (the
actual default landing tab) already ran its own separate, unpaginated
`getFarms()` call on mount, and its stat cards (Total Farms, Affected Farms,
Total Area, Total Indemnity, per-signal distribution) need the *complete*
farm dataset to be correct. Naively sharing SpatialAnalysisModule's
`active_only`-gated fetch as-is would have made those stats silently
undercount whenever the Spatial screen's toggle was left on its new default.
Resolved (confirmed with Fabio) by making the shared fetch always walk to
100% completion in two phases -- active-insurance farms first, then
everything else -- so Monitoring's stats are always eventually accurate and
Spatial's toggle becomes a pure client-side display filter with no fetch
behind it at all.

### 1. File: `frontend/src/lib/useFarmsData.ts` (new)
* Added **`useFarmsData(enabled)`**: the shared farms data source, lifted out
  of `SpatialAnalysisModule.tsx`'s previous self-contained implementation.
  Starts fetching once `enabled` flips true (App.tsx passes `!!currentUser`,
  so it starts right after login, before any tab-specific module mounts) and
  keeps running regardless of which tab is active.
  * Fetches in two phases via a `phaseRef` (`"active" | "all" | "done"`):
    phase `"active"` pages through `active_only=true` first (fast, matches
    what the Spatial table's default view needs); once that's exhausted,
    phase `"all"` restarts pagination from offset 0 with `active_only=false`
    to fill in the remainder. The two phases' offsets aren't directly
    comparable (different WHERE clauses shift what falls at a given offset),
    so phase `"all"` does re-fetch farms phase `"active"` already merged in
    -- harmless no-ops via `mergeFarmsPage`'s upsert semantics, traded for
    not needing to track which specific farm_ids were already seen.
  * Kept **`mergeFarmsPage()`** (moved from `SpatialAnalysisModule.tsx`,
    unchanged) and the same shared-lock/generation-counter pattern
    (`fetchInFlightRef`, `generationRef`) from the entry above, now scoped to
    this hook instead of one component.
  * Returns `{ farms, isLoadingFirstPage, isRefreshing, isFetchingMore,
    hasMore, isComplete, loadError, refresh, requestMore }` --
    `isComplete` is new (true once phase `"all"` exhausts, i.e. the complete
    dataset has landed) for any future consumer that wants to know when
    aggregate stats are guaranteed fully accurate; not consumed yet.
  * `isFetchingNextPage` (Spatial-only naming) collapsed into
    **`isFetchingMore`**, since the reason a page fetch is happening (scroll
    vs. background pace) no longer needs separate UI treatment once shared
    across screens -- both drive the same "Loading more…" sentinel.

### 2. File: `frontend/src/app/App.tsx`
* **Changes to Functions:**
  * Added `const farmsData = useFarmsData(!!currentUser)`, called
    unconditionally above the `if (!currentUser) return <LoginScreen/>`
    early-return (required -- hooks can't be called conditionally), so the
    fetch starts the instant `currentUser` is set by `handleLogin()`.
  * Passes `farmsData` as a new prop to both `<MonitoringModule>` and
    `<SpatialAnalysisModule>`.

### 3. File: `frontend/src/app/components/MonitoringModule.tsx`
* **Changes to Functions/Rendering:**
  * Removed its own `farms` state and the `getFarms()` call from its mount
    effect; `farms` is now `farmsData.farms`, read from the new required
    `farmsData: FarmsData` prop. `totalFarms`/`affectedFarms`/`totalArea`/
    `totalIndemnity` and the signal-distribution chart are otherwise
    unchanged -- they already just read from `farms`/`farmRows`, so they now
    grow live as the shared background completion progresses, same
    "silently grows" philosophy already accepted for the Spatial table.
  * `assessments`/`insuranceSummary`/`activeTyphoons` fetching is unchanged
    (out of scope for this entry -- only the farms fetch was duplicated).

### 4. File: `frontend/src/app/components/SpatialAnalysisModule.tsx`
* **Changes to Functions/Rendering:**
  * Removed everything the entry above added for its *own* fetch/pagination
    machinery (`farms`/`isLoadingFirstPage`/`isRefreshing`/
    `isFetchingNextPage`/`hasMore` state, `nextOffsetRef`/`hasMoreRef`/
    `fetchInFlightRef`/`activeOnlyRef`/`generationRef`, `fetchNextPage()`,
    `runBackgroundCompletion()`, `loadFarmsFromStart()`, `mergeFarmsPage()`,
    the `PAGE_SIZE`/`BACKGROUND_FETCH_DELAY_MS` constants) -- all of it now
    lives in `useFarmsData.ts` instead. This component now takes a required
    `farmsData: FarmsData` prop and destructures `farms`, `isLoadingFirstPage`,
    `isRefreshing`, `isFetchingMore`, `hasMore`, `loadError`,
    `refresh` (aliased to the existing local name `refreshFarms`, so the
    CSV/GPX upload handlers didn't need to change), and `requestMore` from it.
  * The infinite-scroll `IntersectionObserver` effect now calls
    `requestMore()` instead of a local `fetchNextPage("scroll")` --
    `requestMore` is deliberately excluded from the effect's dependency
    array (it's a fresh function identity on every `useFarmsData` state
    change, i.e. every page fetch, which would otherwise tear down/rebuild
    the observer constantly for no behavioral difference).
  * `activeInsuranceOnly` (still defaults to `true`) is now **purely a
    client-side display filter** on `filteredFarms`, same as it always was
    structurally, but no longer triggers a fetch restart when toggled -- the
    `useEffect(() => { loadFarmsFromStart(...) }, [activeInsuranceOnly])`
    from the entry above is gone entirely, since `useFarmsData` already
    fetches every farm (active-first, then the rest) regardless of this
    toggle's state. Toggling now re-filters the already-loaded/loading
    shared array instantly, with no network request -- strictly better UX
    than the previous design's "restart pagination on toggle" behavior.

### Status / Next Steps
* **Verified by Fabio (2026-08-08):** fresh `npm run dev` + login walkthrough
  confirmed -- farm records populate on the Monitoring tab immediately after
  login (before ever clicking into Spatial), the Spatial tab shows data
  immediately/near-immediately on first visit, the Active-Insurance toggle
  re-filters instantly with no new network request, and scrolling/idle
  background completion/CSV/GPX upload refresh all behave as expected.
* `isComplete` is returned by `useFarmsData` but not yet consumed by either
  screen (e.g. as a "still finishing up…" affordance on Monitoring's stat
  cards) -- left unused/available for a future request rather than adding
  UI surface that wasn't asked for.

---

## [2026-08-08] - Persist login session across page refresh

Reported symptom: refreshing the page always redirected back to the login
screen. Root cause: `LoginScreen.tsx` has no real backend auth (checks
against hardcoded `DEMO_ACCOUNTS` client-side, issues no token/session --
registration is similarly fake, just a `setTimeout` before showing a
"submitted for approval" message) and `App.tsx`'s `currentUser` was purely
in-memory React state, which a full page reload always wipes.

Confirmed with Fabio: persist across full browser restarts (not just
same-tab refresh), with no automatic time-based expiry -- the session lasts
until the user explicitly logs out.

### 1. File: `frontend/src/lib/authStorage.ts` (new)
* Added **`CurrentUser`** interface (`{ name, role, email }` -- the same
  shape `LoginScreen.tsx`'s `onLogin()` already passed, now the single
  source of truth instead of a duplicate inline interface in `App.tsx`).
* Added **`loadPersistedUser()`**: reads/parses the persisted user from
  `localStorage` (key `agrisuregis_current_user`), with shape-validation on
  the parsed JSON and a try/catch fallback to `null` (not logged in) for
  corrupt/unparseable storage or a storage-unavailable environment (private
  browsing, quota, disabled) -- fails safe rather than crashing app load.
* Added **`persistUser(user)`** / **`clearPersistedUser()`**: write/remove
  that same key, each independently try/caught so a storage failure doesn't
  break login/logout itself, just the "survives a refresh" behavior.

### 2. File: `frontend/src/app/App.tsx`
* **Changes to Functions:**
  * `currentUser` state now initialized via `useState<CurrentUser | null>
    (loadPersistedUser)` -- a lazy initializer, so it reads `localStorage`
    synchronously on the very first render and never flashes the login
    screen before rehydrating.
  * `handleLogin()`: now also calls `persistUser(user)` alongside the
    existing `setCurrentUser(user)`.
  * Added **`handleLogout()`**: `setCurrentUser(null)` + `clearPersistedUser()`,
    replacing the inline `onLogout={() => setCurrentUser(null)}` prop that
    never cleared storage.
  * Removed the local `interface CurrentUser` (moved to `authStorage.ts`,
    imported instead).
* **Side effect worth noting, not a regression:** `useFarmsData(!!currentUser)`
  (from the entry above) now effectively also starts on refresh instead of
  only on a fresh login, since `currentUser` is populated synchronously on
  first render whenever a persisted session exists -- consistent with the
  rest of the app now staying "logged in" across a refresh.

### Status / Next Steps
* **Verified by Fabio (2026-08-08):** login persists across refresh and full
  browser restarts, and explicit logout correctly clears the session (see
  the follow-up entry directly below for the companion farms-cache fix found
  during this same walkthrough).
* No expiry timer exists by design (per Fabio's direction) -- the persisted
  session is only ever cleared by an explicit logout. If a future request
  wants automatic expiry, `authStorage.ts` would need a stored timestamp and
  an expiry check in `loadPersistedUser()`.
* This persists to `localStorage`, which is per-browser-profile, not a real
  server-side session -- since there is still no backend auth endpoint,
  logging in on a second device/browser is a separate, independent "session"
  with no shared server-side state. Flagging in case real backend
  authentication is wanted later; out of scope for this fix.

---

## [2026-08-08] - Farm records cache: seed instantly on refresh instead of
## restarting the fetch from page 1

Follow-up to the login-persistence entry directly above. Fabio's first
walkthrough of that fix reported the login screen correctly stopped
reappearing on refresh, but the Farm Records table/map still visibly reset
and re-fetched from scratch on every refresh -- because `useFarmsData.ts`'s
progress (the `farms` array, and which pages had already been fetched) only
ever lived in React state, which a full page reload always wipes regardless
of whether `currentUser` itself now survives it.

Considered a "true resume" (persist exactly which offsets/pages were already
fetched and pick up from there) vs. "seed instantly, then revalidate in the
background" -- confirmed with Fabio: the latter, since it's simpler and
self-correcting (no risk of stale data lingering if something changed
server-side between sessions), at the cost of re-requesting some pages a
true resume could have skipped.

### 1. File: `frontend/src/lib/useFarmsData.ts`
* Added **`loadCachedFarms()`** / **`persistFarmsCache()`**: read/write the
  farms list to `localStorage` (key `agrisuregis_farms_cache`), each
  independently try/caught (corrupt/unparseable cache, storage unavailable,
  or quota exceeded all fail safe -- worst case, this cache is skipped and
  the hook behaves exactly as it did before this entry, a cold-start fetch).
* `farms` state now initialized via `useState<Farm[]>(loadCachedFarms)` (a
  lazy initializer, reads `localStorage` synchronously on first render) --
  instead of starting empty on every mount.
* Added a `useEffect` that persists `farms` to the cache on every change
  (i.e. after every merged page), so the *next* refresh seeds from
  up-to-date data, not just whatever was cached at the start of the current
  session. Skips persisting an empty array so a transient early error can't
  wipe out a previously good cache.
* `hasLoadedOnceRef` (already existed, drives the `isLoadingFirstPage` vs.
  `isFetchingMore` distinction in `fetchNextPage()`) now initializes to
  `farms.length > 0` instead of unconditionally `false` -- when `farms`
  started from a non-empty cache, the mount fetch is treated as a quiet
  background revalidation from the very first page, so the full-panel
  "Loading farm records…" blocker never reappears on a refresh where cached
  data already exists. No other logic changed: the same two-phase fetch
  sequence (active-first, then complete) still runs in full on every mount,
  it just does so behind already-visible cached rows instead of a blank
  loading state, merging real data back over the seed via the existing
  `mergeFarmsPage()` as it lands.
* **Deliberately not cleared on logout** (unlike the login session itself in
  `authStorage.ts`): farm records are shared, global data, not user-specific
  or per-account -- both demo accounts see the same underlying dataset, and
  the cache is never rendered without a valid session anyway (`App.tsx`
  gates all screens behind `currentUser`). Leaving it in place across a
  logout/re-login cycle is a free speed-up for the next login, not a
  data-exposure risk.

### Status / Next Steps
* **Verified by Fabio (2026-08-08):** fresh `npm run dev` walkthrough
  confirmed -- farm records appear immediately on refresh (no "Loading farm
  records…" blocker), the background-completion sequence quietly re-runs
  behind them, and the login-persistence behavior from the entry above still
  holds (refresh, browser restart, and explicit logout all behave as
  expected).
* Very large datasets (the benchmarked ~24k-row CSV ingestion ceiling) could
  approach `localStorage`'s typical ~5-10MB per-origin limit -- not a
  concern at today's ~589-row scale, but `persistFarmsCache()`'s try/catch
  means this fails safe (cache silently stops updating) rather than
  breaking the app if that ceiling is ever hit.

---

## [2026-08-08] - Farm records: true resume instead of re-walking the whole
## fetch on every refresh

Follow-up to the entry directly above. The "very large datasets" note in its
Status/Next Steps turned out to already be Fabio's actual situation: his dev
DB apparently still carries the ~24,000 synthetic rows from the CSV
ingestion benchmark run (`FUNCTION_CHANGES.md`, 2026-08-07), on top of the
original ~589 -- Monitoring's "Affected Farms" stat card showed `0/25700`.
At that real scale, "seed instantly, then fully revalidate the entire
two-phase sequence in the background" (the entry above) meant every single
refresh re-issued 250+ paginated requests at the deliberately-unhurried
300ms/page background pace -- 75+ seconds of visible churn every reload,
which Fabio reported as the page/backend "getting stuck" and "doing it again
from the start." Confirmed with Fabio: switch to true resume.

### 1. File: `frontend/src/lib/useFarmsData.ts`
* Added **`loadCachedProgress()`** / **`persistProgress()`**: read/write
  `{ phase, activeOffset, allOffset }` to `localStorage` (key
  `agrisuregis_farms_progress`, separate key from the farms data cache
  itself), with the same shape-validated-with-fallback-to-fresh pattern as
  `loadCachedFarms()`/`persistFarmsCache()`.
* `phaseRef`/`activeOffsetRef`/`allOffsetRef` now initialize from this
  cached progress instead of always `"active"`/`0`/`0`. `hasMore`/
  `isComplete` state likewise initialize from `cachedProgress.phase` instead
  of always `true`/`false`.
* `fetchNextPage()`'s success branch now calls `persistProgress()` after
  every merged page (and after any phase transition), so the persisted
  progress always reflects exactly how far the sequence has gotten.
* Added **`resume()`**: the new mount-time entry point (replaces calling
  `start(false)` on mount). Unlike `start()`, it does **not** reset
  `phaseRef`/the offset refs -- it continues `fetchNextPage()` from
  whatever they already are. If a previous session had already reached
  phase `"done"`, `resume()` is a complete no-op: zero requests, the cached
  `farms` (already seeded, per the entry above) is simply left as-is.
* `start(isRefresh)` (still used only by `refresh()`, i.e. a CSV/GPX
  upload) is unchanged in behavior -- a real restart, resetting both the
  in-memory cursors *and* the persisted progress via
  `persistProgress(FRESH_PROGRESS)`, so a refresh that happens mid-upload
  resumes from that fresh sequence rather than stale pre-upload progress.

### Status / Next Steps
* Not yet verified by Fabio -- needs a walkthrough at his actual (large)
  dataset scale: let the background sequence reach `isComplete` once, then
  refresh -- confirm `farms` display instantly *and* the Network tab shows
  no new `/api/farms/` requests at all (full resume, not just fast display).
  Then try refreshing mid-sequence (before it completes) -- confirm it
  continues from roughly where it left off rather than restarting at
  `offset=0`.
* Real corollary of true resume (called out when this tradeoff was first
  offered, now the active choice): a farm that changes server-side (e.g.
  insurance status flips) won't be reflected in the cached copy until
  something eventually re-fetches its specific page -- once `isComplete` is
  reached, that may never happen again automatically. No staleness
  invalidation exists yet (e.g. re-running phase "all" periodically, or
  after some elapsed time) -- flagging as a possible follow-up if stale data
  becomes a real problem in practice, not built here since it wasn't asked
  for.
* `agrisuregis_farms_progress` is left uncleared on logout, same reasoning
  as `agrisuregis_farms_cache` in the entry above (not user-specific data,
  never rendered without a valid session).

---

## [2026-08-08] - Farm records: move the farms cache from localStorage to
## IndexedDB (root cause of the "stuck at 16800" bug)

Follow-up to the entry directly above. Fabio's walkthrough of "true resume"
found it stuck: "Affected Farms" showed `0/16800`, unchanging across
refreshes, with confirmed zero new backend requests (`curl` checks against
`GET /api/farms/` directly proved the backend was completely healthy --
`total: 48588`, `has_more: true` even at `offset=16795`; the real
`tbl_farms` count via `psql` also confirmed `48588`).

**Root cause, found via browser console:** `localStorage.getItem
('agrisuregis_farms_progress')` returned `{"phase":"done","activeOffset":39,
"allOffset":48588}` -- the fetch sequence had genuinely, correctly walked
all 48,588 rows and correctly detected completion. But `JSON.parse
(localStorage.getItem('agrisuregis_farms_cache')).length` was only `16800`.
`localStorage` has a hard ~5-10MB per-origin quota (flagged as a risk in the
entry above, but the actual failure mode wasn't yet understood). Once the
serialized `farms` array grew past what ~16,800 real farm records encode to,
every subsequent `persistFarmsCache()` call started throwing
`QuotaExceededError` -- silently, since it's caught and treated as
"best-effort, skip on failure." Meanwhile `persistProgress()`'s payload
(`{phase, activeOffset, allOffset}`, a few dozen bytes) never came close to
the quota and kept succeeding all the way to `"done"`. The two caches
desynced: progress said "fully done," the farms cache silently froze at its
last successful write. Every later `resume()` correctly trusted the
(accurate) "done" progress marker and skipped fetching entirely -- but
`farms` had seeded from the (stale, truncated) cache, so the UI stayed stuck
at 16,800 forever with no way to notice.

Confirmed with Fabio: move the (potentially large) farms array cache to
IndexedDB, which doesn't have `localStorage`'s small quota ceiling. The tiny
progress marker stays in `localStorage`, since it's the whole reason the two
caches were distinguishable enough to diagnose this at all.

### 1. File: `frontend/src/lib/useFarmsData.ts`
* Replaced `loadCachedFarms()`/`persistFarmsCache()`'s `localStorage`
  implementation with an `IndexedDB`-backed one (`openFarmsDb()` +
  a single-record object store, db name `agrisuregis`, store
  `farms_cache`). Both are now `async` (`IndexedDB`'s API is inherently
  asynchronous, unlike `localStorage`), with the same fail-safe-on-any-error
  philosophy as before (unavailable/disabled storage → treated as "nothing
  cached" / "skip this write," never throws into calling code).
* Added a one-time, unconditional `localStorage.removeItem
  ('agrisuregis_farms_cache')` at module load -- the old cache key is now
  orphaned dead weight, and since it was written right up to the quota
  wall, leaving it in place risked *other* small `localStorage` writes
  (the progress marker, `authStorage.ts`'s session) failing too.
* `PROGRESS_CACHE_KEY` renamed to `agrisuregis_farms_progress_v2`. Without
  this, the very first load after this fix would read the *old* progress
  key's `"done"` state (persisted by the previous version of this hook)
  against the *new*, empty IndexedDB cache -- reproducing this exact bug
  immediately (progress says done, cache has nothing, farms render
  permanently empty). Versioning the key forces one real walk instead.
* Because the farms cache read is now async, `farms` state can no longer be
  seeded synchronously via `useState`'s lazy initializer (`useState(() =>
  ...)`, what the previous entry used) -- it now starts `[]` and is
  populated inside the mount `useEffect`, after `await loadCachedFarms()`
  resolves. `isLoadingFirstPage`'s default flipped from `false` to `true`
  to cover this brief async gap (previously: default `false`, since a
  synchronous `localStorage` read meant `farms` was correct from the very
  first render) -- and is explicitly cleared after the cache read if
  `phaseRef.current === "done"`, since in that case `fetchNextPage()`
  (which normally clears it) never runs at all.
* `hasLoadedOnceRef`'s initial value changed from `farms.length > 0`
  (readable synchronously before) to unconditionally `false`, now set
  `true` inside the mount effect once the async cache read resolves with
  data, or by a successful `fetchNextPage()` -- same purpose as before
  (distinguishing "nothing to show yet" from "quiet background top-up"),
  just triggered from the new async path instead of the constructor-time
  value.

### Status / Next Steps
* Tested by Fabio: the walk itself ran to real completion (progress marker
  correctly reached `{"phase":"done",...,"allOffset":48588}`), but a reload
  right around that point landed in the exact race this entry's own "Residual
  risk" note below had already flagged -- see the next entry
  (`[2026-08-08] - Farm records: close the IndexedDB write race behind
  "done"`) for the follow-up fix and why the predicted risk turned out not to
  be narrow enough to skip.

## [2026-08-08] - Farm records: close the IndexedDB write race behind "done"

Follow-up to the entry directly above. Fabio reloaded mid-testing (per that
entry's own instructions, to check "does a second reload show zero new
requests") and hit a fresh symptom: two stat cards on Monitoring disagreed on
the farm total at the same moment (`Affected Farms: 0/48488` vs.
`Active Insurance: 39/48588`) -- diagnosed as unrelated to this bug (they
read from two independent sources, `farms.length` vs. a one-shot
`GET /api/insurance/summary` `COUNT(*)`, explained and confirmed as a
red herring). The real symptom, confirmed with Fabio afterward: the count
climbed live, then permanently stopped at `48488` -- 100 rows (one page)
short -- even though nothing on screen indicated loading was still in
progress (neither `MonitoringModule.tsx` nor `SpatialAnalysisModule.tsx`
gate any indicator on `isComplete`, only on `isLoadingFirstPage`, which
clears after just the first page).

**Root cause, confirmed via evidence at each step:**
* `curl -sS "http://localhost:8000/api/farms/?limit=100&offset=48488&active_only=false"`
  returned `total: 48588`, `has_more: false`, `len(data): 100`, farm_ids
  `48489`-`48588` -- proving the backend was completely healthy and this was
  the true, correct final page. Backend ruled out.
* Browser console: `localStorage.getItem('agrisuregis_farms_progress_v2')`
  returned `{"phase":"done","activeOffset":39,"allOffset":48588}` -- the
  fetch sequence genuinely, correctly completed all 48,588 rows.
* Browser console (reading the IndexedDB record directly): the cached
  `farms` array held only `48488` entries -- matching the stuck on-screen
  count exactly.
* Fabio confirmed a reload happened between watching the count climb and it
  landing on 48488. That reload is what exposed the bug: the tiny
  `agrisuregis_farms_progress_v2` marker (`localStorage`) is written
  *synchronously*, the instant a page's fetch resolves; the (much larger)
  `IndexedDB` farms-array write was, until this fix, fired from a *separate*
  `useEffect` keyed on `farms`, async and unawaited -- "best-effort," same
  philosophy as the localStorage-quota-era version. The reload landed in the
  gap: progress had already persisted `"done"` for the completing page, but
  that page's IndexedDB write hadn't flushed yet. The new mount seeded
  `farms` from the still-truncated (48488-row) cache, saw progress already
  `"done"`, and `resume()` correctly no-op'd on `"done"` -- permanently
  stuck, no further requests ever made. Same failure shape as the
  `localStorage`-quota bug two entries above, different mechanism: a race
  window instead of a hard wall. This is exactly the "residual risk" flagged
  (but left unbuilt) in that entry's Status/Next Steps.

### 1. File: `frontend/src/lib/useFarmsData.ts`
* Added `farmsRef`, a ref mirroring `farms` state synchronously. Needed
  because `setFarms(prev => mergeFarmsPage(prev, res.data))`'s updater isn't
  guaranteed to have run yet by the time the code right after it needs the
  merged array (React 18 batches state updates) -- `farmsRef.current` is
  always the true current merged array, readable immediately.
* `fetchNextPage()`: on the page that finishes the walk (`!res.has_more` in
  phase `"all"`), now `await persistFarmsCache(mergedFarms)` *before* setting
  `phaseRef.current = "done"` and before `persistProgress()` runs. This is
  the actual fix -- it guarantees the complete farms array is durably in
  IndexedDB before the progress marker is ever allowed to claim `"done"`, closing
  the race a reload could land in. Every other (non-final) page keeps a
  fire-and-forget `persistFarmsCache()` call, unchanged in spirit from
  before -- a reload catching one of *those* mid-flight just resumes
  normally via the persisted (non-`"done"`) progress and re-fetches whatever
  the cache is missing, so only the final page's write needed to become
  blocking.
* Removed the separate `useEffect(() => { if (farms.length > 0)
  persistFarmsCache(farms); }, [farms])` that previously drove all cache
  writes -- superseded by the inline writes above (fire-and-forget mid-walk,
  awaited on completion), which also avoids opening a fresh `IndexedDB`
  connection on every single render-triggered `farms` change independent of
  whether a fetch actually completed.
* Mount effect: added a self-heal guard, checked right after seeding `farms`
  from the IndexedDB cache. If loaded progress says `phase: "done"` but
  `farmsRef.current.length !== allOffsetRef.current` (the "all" phase's
  cumulative row count when it finished, which must equal the cached array's
  length if that completing page's write truly landed), the `"done"` is
  treated as unverifiable: falls back to `phaseRef.current = "all"`,
  `allOffsetRef.current = 0`, `hasMore`/`isComplete` reset, and persists that
  corrected progress immediately. Re-walking the `"all"` phase from scratch
  is safe and idempotent (`mergeFarmsPage` dedupes by `farm_id`). This is
  also what self-heals Fabio's already-stuck browser tab on its next
  reload -- no manual cache-clearing needed -- and guards against any other
  future cause of the same desync shape, not just this specific race.

### Status / Next Steps
* Verified by Fabio (2026-08-08): reload converged from 48488 to the true
  48588, and a subsequent reload showed the count instantly with no further
  `/api/farms/` requests.
* The two stat-card totals reading from independent sources
  (`farms.length` vs. `GET /api/insurance/summary`'s `COUNT(*)`) is a
  pre-existing, separate characteristic, not touched by this fix -- flagged
  during this investigation as a possible future inconsistency (most visible
  transiently, mid-load, at real dataset scale) but out of scope here since
  Fabio confirmed the frozen-count symptom, not the transient mismatch, was
  the actual problem.

## [2026-08-08] - Dev data: seed 1000 additional active InsuranceRecord rows

Requested by Fabio directly (not tied to the Farm Records work above) so the
dev DB's "active insurance" set is large enough to meaningfully exercise the
app beyond the real dataset's tiny 39-farm active count -- e.g. testing the
`useFarmsData` "active" phase (previously a single ~39-row page) against
something closer to a realistic multi-page volume.

### 1. File: `backend/seed_active_insurance.py` (new)
* Standalone one-off script, same `psycopg2` connection style as the
  existing `backend/seed_database.py` -- but unlike that script (which is
  driven entirely by `pabs_results.csv` and isn't parameterized), this one
  is a targeted, repeatable "add N active records" utility with no CSV
  dependency.
* `run()`: selects up to `TARGET_NEW_ACTIVE_RECORDS` (1000) farms at random
  from `tbl_farms` via `NOT EXISTS (... WHERE effectivity_date <= today AND
  expiry_date >= today)` -- i.e. farms with zero currently-active coverage,
  the same "active" definition already used by
  `backend/app/api/farms.py`'s `active_only` filter and
  `backend/app/api/insurance.py`'s summary endpoint. Inserts one new
  `InsuranceRecord` per selected farm:
  * `policy_no = f"POL-SEED-{farm_id}"` -- deliberately distinct from both
    the real dataset's plain numeric `policy_no` (e.g. `"1192155"`) and the
    existing large synthetic batch's `"POL<digits>"` convention (e.g.
    `"POL10483323900"`), so this batch stays trivially identifiable/
    greppable (`WHERE policy_no LIKE 'POL-SEED-%'`) and reversible later
    without touching real or previously-seeded rows.
  * `program_type = "Rice Parametric"`, `amount_cover = area_size *
    ₱25,000/ha` (rounded to 2dp) -- matches `pabs_results.csv`'s template
    row convention (2.50 ha -> ₱62,500.00 `InsuredAmountofCover`) rather
    than a flat amount, so the new rows don't stand out from real ones by
    coverage size alone.
  * `effectivity_date` = a random day within the last 30 days (not a single
    shared date, so the batch doesn't read as obviously bulk-inserted),
    `expiry_date` = `effectivity_date + 365 days` (standard annual policy
    duration).
  * `ON CONFLICT (policy_no, farm_id) DO NOTHING`, matching the existing
    `uq_insurance_records_policy_no_farm_id` constraint's semantics.

### Status / Next Steps
* Run by Fabio via his own venv (`python seed_active_insurance.py` from
  `backend/`) -- not run by Claude, per the repo's DB/venv command-handoff
  rules. Reported inserting ~1000 rows.
* Verified via `GET /api/insurance/summary`: `active_count` went `39` ->
  `1039` (exactly +1000), `total_count` (total `InsuranceRecord` rows, not
  farms) went `48588` -> `49588` (also exactly +1000) -- confirms the script
  only added new rows and didn't touch or duplicate any existing ones.
* Committed directly to `develop` (Fabio's choice) rather than behind a
  feature branch, since it's a standalone dev-tooling/data script with no
  application behavior change -- same category as `seed_database.py`.

## [2026-08-09] - Farm Records: "most recent insurance per farm" NULLS-FIRST bug, then a 6-part farms-listing performance pass

Two rounds of follow-up work in the same session, both triggered by testing
`seed_active_insurance.py`'s output (see the entry above).

### Round 1: NULLS FIRST bug in "most recent InsuranceRecord per farm"

Fabio reported the Farm Records table (Active Insurance Only) stuck at 39-54
records while Monitoring's Active Insurance stat card correctly showed
~1036-1039. Root-caused: `GET /api/farms/?active_only=true` correctly
*included* the 1000 newly-seeded farms (has an active record), but
*displayed* the wrong record for ~949 of them -- `effectivity_date`/
`expiry_date: null` instead of the new active dates.

**Root cause:** `backend/app/api/farms.py`'s "most recent per farm"
resolution (`order_by(InsuranceRecord.farm_id, InsuranceRecord.effectivity_date.desc())`,
first-seen-per-farm_id wins) assumed Postgres sorts NULLs last in `DESC`
order. It doesn't -- Postgres's default is NULLS FIRST for `DESC`, so a
farm's old record with no dates set (common in the large synthetic batch)
sorted *ahead of* a real dated record, and `setdefault()` picked the wrong
one. Invisible until this session, since no farm had ever had 2+
InsuranceRecords before `seed_active_insurance.py`.

**Fix:** added `.nullslast()` to the ordering. Verified via curl against a
sample of the previously-broken farm_ids (651, 880, 894) -- all 1000/1000
rows in a full active_only=true page now correctly bracket today.

#### File: `backend/app/api/farms.py`
* `.order_by(InsuranceRecord.farm_id, InsuranceRecord.effectivity_date.desc().nullslast())`.

### Round 2: 6-part performance pass (Fabio: "apply 1-6")

Triggered by a side discussion about OFFSET pagination's cost profile --
measured empirically (curl timing) at 54ms (offset=0) / 151ms (offset=24000)
/ 264ms (offset=48000), confirming cost grows with depth. Fabio asked for
all of it applied at once.

#### 1. Keyset (cursor) pagination -- replaces OFFSET/LIMIT
* `backend/app/api/farms.py`: `offset: int` param replaced with
  `after_id: int` (0 = start). Filters `Farm.farm_id > after_id` instead of
  `.offset()`. `total` still only computed on `after_id == 0` (unchanged
  reasoning from the prior COUNT-skipping optimization); `has_more` no
  longer needs `total` at all under keyset pagination -- just `len(data) ==
  limit`.
* `frontend/src/lib/api.ts`: `GetFarmsResult.offset` -> `after_id`;
  `getFarms({ offset })` -> `getFarms({ after_id })`.
* `frontend/src/lib/useFarmsData.ts`: `activeOffsetRef`/`allOffsetRef`
  (OFFSET counters) replaced with `activeCursorRef`/`allCursorRef` (last-seen
  `farm_id`), advanced from the last row of each returned page rather than
  arithmetic on requested-offset + response-length. Added `allCountRef`, a
  plain cumulative row counter *decoupled* from the cursor -- needed because
  the mount effect's self-heal invariant (`farms.length` must equal the
  "all" phase's total when `phase: "done"`) previously relied on
  `allOffsetRef` doing double duty as both "resume position" and "count
  fetched so far," which a farm_id cursor value can't do on its own.
  `PROGRESS_CACHE_KEY` bumped `_v2` -> `_v3` (shape and semantics both
  changed; an old record's numeric offsets would be silently wrong read
  back as farm_id cursors).

#### 2. Bigger pages
* `PAGE_SIZE` (the "all" phase) raised from 100 to 1000 -- the backend's own
  max `limit`. Was `ACTIVE_PAGE_SIZE`, a separate constant already at 1000
  from the earlier active-phase speedup entry; now unified into one constant
  since both phases use the same value. Cuts the "all" phase's walk from
  ~486 requests to ~49.

#### 3. Index for the active_only filter
* `backend/app/models/models.py`: `InsuranceRecord.__table_args__` gained
  `Index("ix_insurance_records_active_lookup", "effectivity_date",
  "expiry_date", "farm_id")` -- a covering index (index-only scan) for
  `active_only=True`'s `WHERE effectivity_date <= today AND expiry_date >=
  today` / `DISTINCT farm_id` query.
* `backend/init_schema.sql`: matching `CREATE INDEX` added, for future fresh
  installs.
* `backend/migrations/2026-08-09_farms_perf.sql` (new): standalone
  `CREATE INDEX CONCURRENTLY` for Fabio's already-populated DB (re-running
  `init_schema.sql` wholesale would `DROP TABLE` everything).

#### 4. Optional Redis page-level cache
* `backend/app/core/farms_cache.py` (new): `get_cached_farms_page()`/
  `cache_farms_page()`/`invalidate_farms_cache()`. A no-op unless
  `REDIS_URL` is set -- deliberately not a forced dependency (not added to
  `requirements.txt`); degrades gracefully the same way the DB/venv/npm
  handoff rules in `.claude/CLAUDE.md` treat any new local infrastructure.
  Rationale: multiple real users each independently walking the same
  ~48,588-farm dataset would otherwise each cost the DB the same queries
  redundantly -- a shared cache means only the first request per page
  actually hits Postgres. (Client-side IndexedDB caching only helps repeat
  visits from the *same* browser, not a different user's first walk.)
* `backend/app/api/farms.py`: checks the cache first, populates it after a
  cache miss.
* `backend/app/api/upload.py`: `invalidate_farms_cache()` called after a
  successful CSV ingest and after a GPX boundary update (both change data
  the cache could be serving stale).
* `backend/seed_active_insurance.py`: also invalidates (best-effort, since
  it writes outside the app) after inserting.

#### 5. Materialized view for "most recent insurance per farm"
* `backend/app/core/farms_view.py` (new): `mv_farm_latest_insurance`
  precomputes what `list_farms()` otherwise resolves via bulk-fetch +
  Python reduction on every request. `materialized_view_available()` checks
  existence once and memoizes *only* a positive result -- a negative result
  is cheaply re-checked every call, so applying the migration mid-session
  is picked up by the very next request without restarting the backend
  (this needed a follow-up fix after Fabio ran the migration and the
  already-running process kept using the fallback path, having cached
  `False` from testing before the migration existed).
  `refresh_farm_latest_insurance_view()` uses `REFRESH ... CONCURRENTLY`
  (needs the view's unique index) and is called from the same write paths
  as `invalidate_farms_cache()` above.
* `backend/app/api/farms.py`: uses the view when available, falls back to
  the original bulk-fetch-and-reduce-in-Python path (with the Round 1
  `.nullslast()` fix preserved) otherwise.
* `backend/migrations/2026-08-09_farms_perf.sql`: `CREATE MATERIALIZED VIEW
  IF NOT EXISTS` + its required unique index, `DISTINCT ON (farm_id) ...
  ORDER BY farm_id, effectivity_date DESC NULLS LAST`.
* `backend/init_schema.sql`: matching statements added for future fresh
  installs.

#### 6. DB connection pooling
* `backend/app/core/database.py`: `create_engine(...)` gained explicit
  `pool_size=10, max_overflow=20` (up from SQLAlchemy's unstated defaults of
  5/10, sized for one local dev process, not concurrent real users),
  `pool_pre_ping=True` (transparently replaces a connection that went stale
  while idle instead of surfacing as a request failure), `pool_recycle=1800`
  (proactively retires connections older than 30 minutes).

### Status / Next Steps
* Migration applied by Fabio (`psql -U agrisure_admin -d agrisure_db -f
  migrations/2026-08-09_farms_perf.sql`) -- succeeded.
* Verified via curl: keyset pagination pages correctly (cursor advances,
  `has_more`/`total` semantics correct), materialized-view path returns the
  same correct data as the Python fallback did.
* Verified by Fabio: cleared frontend cache (`agrisuregis_farms_progress_v2`
  removed, IndexedDB `agrisuregis` deleted, per the `_v3` bump), reloaded --
  farms load correctly, counts reach the right totals, no errors.
* Redis caching (item 4) is written but not enabled -- would need `pip
  install redis`, a running Redis server, and `REDIS_URL` set in
  `backend/.env`, none of which Fabio has done yet. Everything works
  identically without it; enabling it is a future opt-in, not required.
* `backend/seed_active_insurance.py`'s changelog entry (the one directly
  above this one) is now slightly out of date in one respect: it predates
  the NULLS FIRST bug fix, so re-reading it without this entry would miss
  why the active-insurance data it seeds initially displayed incorrectly.

## [2026-08-10] - REDIS_URL documented; TCB polling interval moved to minutes

Two small follow-ups from the same day's remote-server-migration session.

### 1. `REDIS_URL` documented (`backend/.env.example`, `.claude/ENV_GUIDE.md`)
Fabio set up Redis locally (installed via `pacman`, started the service) to
actually activate the optional page cache from the 2026-08-09 performance
pass (`backend/app/core/farms_cache.py`). Added `REDIS_URL=` to
`.env.example` with a placeholder and a row to `ENV_GUIDE.md`'s variable
table, per that guide's own rule 4 ("add new variables to `.env.example` in
the same commit"). `backend/.env` itself (gitignored) was updated directly
with `REDIS_URL=redis://localhost:6379/0`, not part of this commit.

### 2. TCB polling interval: hours -> minutes
Fabio asked for the PAGASA bulletin scraper's polling interval to support
15-minute granularity ("every 15 mins checking"). The prior implementation
was hardcoded to whole hours at every layer (DB column, API validation,
scheduler calls) with a 1-hour minimum -- confirmed with Fabio that this
means the scraper hitting PAGASA's site up to 4x more often than that
previous floor, since this polls an external third-party site, before
implementing.

#### Files
* `backend/app/models/models.py`: `ParserSettings.polling_interval_hours`
  (Integer, default 3) -> `polling_interval_minutes` (Integer, default 180
  -- same real-world default of "every 3 hours," just expressed in minutes).
* `backend/app/api/bulletins.py`: `ParserSettingsUpdate.polling_interval_hours`
  (`ge=1, le=24`) -> `polling_interval_minutes` (`ge=15, le=1440` -- 1440 =
  24h, same upper bound as before, just in minutes). `GET`/`PUT
  /api/bulletins/settings` request/response bodies renamed to match.
* `backend/app/core/scheduler.py`: `build_scheduler()`/
  `reschedule_bulletin_job()` now pass `minutes=` to APScheduler instead of
  `hours=`.
* `backend/app/main.py`: reads `settings.polling_interval_minutes` (default
  180 if no row exists yet) instead of `polling_interval_hours` (default 3)
  when building the scheduler at startup.
* `frontend/src/lib/api.ts`: `ParserSettings.polling_interval_minutes`;
  `updateParserSettings(minutes)` (was `(hours)`).
* `frontend/src/app/components/CalibrationModule.tsx`: `parserInterval`
  state's default changed `3` -> `180`; the "TCB Polling Interval" input's
  label, `min`/`max`/`step` (`15`/`1440`/`15`), and helper text all updated
  to describe minutes instead of hours.
* `backend/tests/test_parser_settings_api.py`: updated field names/values
  and bound-rejection tests (`14`/`1441` instead of `0`/`25`).
* `backend/migrations/2026-08-10_polling_interval_minutes.sql` (new):
  `ALTER TABLE ... RENAME COLUMN polling_interval_hours TO
  polling_interval_minutes`, then `UPDATE ... SET polling_interval_minutes
  = polling_interval_minutes * 60` -- converts any already-persisted value
  (e.g. `3`) to the equivalent real-world interval in minutes (`180`)
  instead of silently reinterpreting it as 3 *minutes*, which would have
  made the scheduler run 60x more often than intended for anyone with a
  non-default saved interval.
* `backend/init_schema.sql`: matching column rename for future fresh installs.

### Status / Next Steps
* `*.dump` added to `.gitignore` -- the `pg_dump` output used to migrate
  data to the remote server (`agrisure_db.dump`, 1.7MB) is a data snapshot,
  not source, and can carry real farmer/insurance data.
* Not yet verified -- needs the migration applied and the backend restarted
  on whichever DB(s) still have the old `polling_interval_hours` column
  (both Fabio's local dev DB and the newly-provisioned remote server's DB).

## [2026-08-10] - Containerize backend + Redis for the remote mock server

Fabio's plan: run the backend and Redis (the optional page cache from the
2026-08-09 performance pass, still never confirmed working anywhere) as
Docker containers on the remote mock server (192.168.1.41), instead of the
bare `uvicorn --reload` process it runs today, so that a `redis:alpine`
sibling container finally activates `backend/app/core/farms_cache.py` for
real. Postgres stays native on that machine (already `pg_restore`'d with
~48,588 farms / 49,588 insurance records) -- only the backend app and
Redis move into containers. Chose Redis-as-a-container over the
earlier-discussed Memurai-on-bare-Windows alternative once Docker was
already going to be introduced for the backend anyway.

#### Files
* `backend/requirements.txt`: committed the `redis==8.1.0` line (added
  locally earlier but not yet committed) -- without this, `pip install -r
  requirements.txt` inside the image wouldn't install `redis`, and
  `farms_cache.py`'s `import redis` would fail silently inside its
  `except Exception` guard, reproducing the exact "caching never actually
  engages" gap this change exists to close.
* `backend/Dockerfile` (new): `python:3.13-slim` base (placeholder --
  must be confirmed against the remote venv's actual Python version before
  building), installs `requirements.txt`, copies `app/` (including the
  bundled `app/data/psgc_region10_boundaries.csv` PSGC lookup), no
  `--reload` (deployed service now, not live-edited -- a code change means
  `git pull` + `docker compose up --build`).
* `backend/docker-compose.yml` (new): `backend` service (builds from the
  Dockerfile, publishes `8000:8000`, reads `backend/.env` via `env_file:`
  rather than inlining secrets in a tracked file, `depends_on: redis`) +
  `redis` service (`redis:alpine`, named volume for restart persistence,
  port intentionally not published -- only `backend` talks to it over
  compose's internal DNS as `redis://redis:6379/0`).
* `backend/.dockerignore` (new): excludes `venv/`/`.venv/` (hundreds of MB
  with geopandas/numpy/pandas that would otherwise re-upload into the
  Docker build context on every build), `__pycache__/`, `.env`, etc.

#### Status / Next Steps
* Not yet deployed -- remote-box steps (Postgres `listen_addresses`/
  `pg_hba.conf`/firewall changes to let the container reach native
  Postgres via `host.docker.internal`, `backend/.env` edit, `docker
  compose build`/`up`, and updating `C:\Users\admin\check_backend.ps1`'s
  restart action from spawning bare `uvicorn` to `docker compose restart
  backend`) are all pending handoff to Fabio's own SSH session, one
  command at a time.
* Full plan: `/home/fabio/.claude/plans/so-this-is-the-happy-whisper.md`.
* Separately, Tailscale is being set up on the same remote box for
  outside-LAN SSH access -- independent of this containerization work,
  no code/repo changes involved.

## [2026-08-11] - Spatial Analysis tab: fix map ignoring the Active Insurance filter + add viewport culling

Fabio reported the "Spatial Analysis & Data Import" tab (one component,
despite the two-part label -- there's no separate Data Import module) is
slow to click into. Investigation (two parallel Explore passes) found the
farms data-fetching layer (`useFarmsData.ts`: shared, keyset-paginated,
IndexedDB-cached) is already well-optimized and NOT the cause -- the
slowness is entirely client-side map rendering:

1. A real bug: the farm-records table respects the "Active Insurance Only"
   toggle via `filteredFarms`, but the map was fed a separate, unfiltered
   `farmRows` expression -- so the map silently ignored that toggle and
   tried to render every farm in the shared cache (growing toward the full
   ~48,588 rows as `useFarmsData`'s background "all" phase completes).
2. No viewport limiting: `GISLeafletMap` gave every farm its own live
   Leaflet layer (`<GeoJSON>` polygon or `<CircleMarker>`) with no
   clustering and no bounds-based culling, so the map kept re-rendering
   with more layers as more farms streamed into the shared cache.

Fix direction chosen with Fabio: fix the filter bug, and add
viewport-based culling directly in `GISLeafletMap.tsx` (only render farms
currently within the visible map bounds) rather than adding a
marker-clustering npm dependency -- clustering libraries only help point
markers, not the polygon-heavy surveyed-farm case, and this needed no
`npm install` handoff.

#### Files
* `frontend/src/app/components/SpatialAnalysisModule.tsx`:
  `filteredFarms` (used by both the table and, now, the map) wrapped in
  `useMemo` -- needed once it also feeds the map, since an unmemoized
  version would hand `GISLeafletMap` a new array reference on every
  unrelated re-render (e.g. typing in the municipality search box),
  defeating the map's own memo chain. The `GISLeafletMap` `farms` prop
  changed from a separate unfiltered `farmRows`/`.filter(municipality)`
  expression to `filteredFarms` directly, so the map now respects
  `activeInsuranceOnly` exactly like the table does.
* `frontend/src/app/components/GISLeafletMap.tsx`:
  - `surveyedFarms`/`unsurveyedFarms` (the has-geometry/no-geometry split)
    wrapped in `useMemo` (was recomputed every render).
  - Added `computeGeoJsonBBox()`/`bboxIntersects()`/`pointInBounds()`
    helpers and a `surveyedBBoxByFarmId` cache (`useRef` Map, keyed by
    `farm_id`, incremental -- only recomputes bbox math for farms not
    already cached or whose `location_geom` reference changed).
  - Added `MapBoundsWatcher` (mounted inside `MapContainer`, uses
    react-leaflet's `useMapEvents`) reporting the map's current bounds on
    mount and on every `moveend`/`zoomend` -- Leaflet's own discrete
    end-of-gesture events, so no extra debounce timer was needed.
  - Added `visibleSurveyedFarms`/`visibleUnsurveyedFarms` -- viewport-
    culled subsets used only by the two `<GeoJSON>`/`<CircleMarker>`
    render loops. Deliberately kept as *additional* derived arrays rather
    than replacing `surveyedFarms`/`unsurveyedFarms`/`farms` in place,
    since `selectedFarm` (`farms.find(...)`), `approxPlacements`,
    `FlyToSelectedFarm`, and the legend all still need to resolve/operate
    against the full farm set regardless of current viewport (e.g.
    selecting an off-screen farm from the table must still fly to it).

#### Status / Next Steps
* Not yet verified end-to-end (frontend build/typecheck + manual browser
  check) -- handed off to Fabio per the frontend-local-environment rule.
* Full plan: `/home/fabio/.claude/plans/so-this-is-the-happy-whisper.md`.
* Deliberately not addressed: a duplicate `getAssessments()` call between
  `SpatialAnalysisModule` and `MonitoringModule` (each fetches
  independently on mount, unlike the shared `farmsData`) -- low-cost
  dataset, unrelated to the reported slowness, left for a separate cleanup
  if wanted later.

## [2026-08-11] - GeoServer setup rewritten for Docker on the remote mock server

`.claude/GEOSERVER_SETUP.md` previously documented a native/JDK GeoServer
install on Fabio's local machine. Rewritten to run GeoServer as a third
Docker service on the remote mock server (192.168.1.41), alongside the
`backend`/`redis` containers from the 2026-08-10/11 containerization work
-- colocating it with the native Postgres it queries (avoids a network hop
per internal PostGIS query GeoServer makes) and reusing the
`host.docker.internal` reachability + Docker-subnet `pg_hba.conf`/firewall
rules already set up for `backend`, rather than opening new surface area.
Chose `docker.osgeo.org/geoserver:3.0.x` (current stable line, released
June 2026) over the 2.x line, with a conservative `-Xms512m -Xmx1g` JVM
heap given this box already runs `backend`, `redis`, native Postgres, and
Docker Desktop itself.

#### Files
* `backend/docker-compose.yml`: added a `geoserver` service
  (`docker.osgeo.org/geoserver:3.0.x`, port `8080:8080`, `env_file: .env`
  for `GEOSERVER_ADMIN_USER`/`PASSWORD` -- kept out of this tracked file
  same as `DATABASE_URL`/`REDIS_URL` -- `GEOSERVER_DATA_DIR`,
  `EXTRA_JAVA_OPTS`, `SKIP_DEMO_DATA=true` to skip bundled demo layers) +
  a `geoserver-data` named volume for persistence across restarts.
* `.claude/GEOSERVER_SETUP.md`: full rewrite --
  - Prerequisites/install section now points at the existing Docker Desktop
    setup instead of a JDK, with an explicit note that building/pulling
    this image needs the physical console on 192.168.1.41 (the same
    Windows Credential Manager/DPAPI-over-SSH limitation hit building the
    `backend` image), while day-to-day `restart`/`logs`/`ps` work fine
    over SSH.
  - Schema-change/backfill steps (`ALTER TABLE`, `backfill_admin_boundary_geom.py`)
    changed from "your local venv" to "the remote box's venv over SSH,"
    since `agrisure_db` lives there now, not locally.
  - GeoServer's PostGIS datastore connection host changed from `localhost`
    to `host.docker.internal` (GeoServer-in-a-container reaching
    native Postgres, same indirection `backend`'s `DATABASE_URL` uses).
  - CORS section kept the existing "handled by the Vite dev proxy, not
    GeoServer" design (`CORS_ENABLED` is available on this image but
    deliberately left off) -- added a new step 8 documenting the
    `VITE_GEOSERVER_URL` value pointing at the remote box's LAN or
    Tailscale address instead of `localhost`.
  - All admin-UI/WMS/WFS URLs updated from `localhost:8080` to
    `192.168.1.41:8080`.

#### Status / Next Steps
* **Deployed and verified 2026-08-11.** `.env` credentials, firewall rule,
  `docker compose up -d` (needed the physical console the first time --
  hit the same Docker Desktop credential-helper/logon-session bug as the
  `backend` image, same fix), workspace/datastore, and both layers are
  all live. WMS/WFS endpoints confirmed responding; frontend confirmed
  loading boundaries from GeoServer with the overlay toggle working.
* Hit and worked around a `docker.osgeo.org/geoserver:3.0.x`-specific bug:
  "Compute from native bounds" corrupts the Lat/Lon Bounding Box (garbage
  `0`/`-1` values) even though native SRS is already EPSG:4326 and no real
  reprojection is needed. Workaround: use "Compute from data" only, then
  manually copy those same values into the Lat/Lon Bounding Box fields.
  `tbl_farms` also needed a real GPX uploaded first (this DB had zero
  farms with `location_geom`) before it had any geometry to compute a bbox
  from at all -- used a `backend/mock_data/gpx/` test file. See
  `project_geoserver_deployed` memory for full details.
* `frontend/.env`'s `VITE_GEOSERVER_URL` now set to
  `http://100.80.128.92:8080/geoserver` (Tailscale address, matching
  `VITE_API_BASE_URL`) -- gitignored, local-only change.

## [2026-08-11] - Spatial Analysis map: remove approximate-placement circle markers for unsurveyed farms

Fabio flagged solid gray blob shapes on the map (screenshot around
Manolo Fortich, Bukidnon) suspecting they weren't real farm locations.
Confirmed: `GISLeafletMap.tsx`'s `MUNICIPALITY_CENTERS` only defines real
coordinates for 2 municipalities (`Talakag`, `Claveria`); every farm in
any other municipality fell back to one shared `DEFAULT_CENTER` point.
With ~48,588 farms and only 1 having a real GPX boundary (see the
GeoServer deployment entry above), nearly the entire table collapsed onto
2-3 shared points, rendered as a small grid of `<CircleMarker>`s dense
enough to look like solid blobs rather than individual farm positions.

Confirmed with Fabio: remove the circle-marker rendering entirely rather
than improve the placement algorithm — the map now only shows farms with
real GPX-surveyed boundaries.

#### Files
* `frontend/src/app/components/GISLeafletMap.tsx`:
  - Removed the `visibleUnsurveyedFarms.map(...)` `<CircleMarker>` render
    loop (was the "click to select as an upload target" affordance for
    unsurveyed farms) and the now-unused `visibleUnsurveyedFarms` `useMemo`
    + `pointInBounds()` helper it alone depended on.
  - Kept `unsurveyedFarms`, `approxPlacements`, and `approximateFarmPosition()`
    intact -- selecting an unsurveyed farm via the farm-records table still
    flies the map to its approximate town-center position
    (`FlyToSelectedFarm`'s `approxPos` prop), just without drawing a marker
    there. Selecting one for GPX upload still works via the table's row
    click, unaffected by this change.
  - Removed the now-stale "Approximate (no GPX yet)" legend row and the
    `CircleMarker` import (both otherwise-unused after the above).

#### Status / Next Steps
* Verified 2026-08-11 -- circles gone, everything else (selection, GPX
  upload targeting) still works.

## [2026-08-11] - Fix backend Docker build needing physical console (pin FROM to a digest)

Fabio wants ordinary backend code updates buildable entirely over SSH,
without the physical-console requirement hit during the initial
containerization work ([[project_docker_containerization]]). Root cause
was more specific than first thought: it's not just about pulling a
*brand-new* image -- `docker images -a` on 192.168.1.41 showed
`python:3.13-slim` was never actually stored as its own locally-tagged
image at all (only the final `backend-backend:latest` image existed).
Without a local tag-to-digest mapping, BuildKit's `FROM python:3.13-slim`
step has to ask the registry "what does this tag currently point to?" on
*every* build, not just the first -- and that resolution call is what
hits the Windows Credential Manager/DPAPI-over-SSH limitation
(`error getting credentials ... A specified logon session does not
exist.`), independent of whether any actual layers end up needing to be
downloaded.

Fix: pin the Dockerfile's `FROM` to an exact digest instead of the
mutable `:3.13-slim` tag. A digest reference is immutable, so BuildKit
can match it against the local cache directly with no ambiguity to
resolve -- no registry contact needed at all once it's cached under that
exact digest.

#### Files
* `backend/Dockerfile`: `FROM python:3.13-slim` -> `FROM
  python:3.13-slim@sha256:69e18bd8d831d88e0ef70239dc7771ab7c28bc296ae78ac75cde71e60aa4434f`
  (linux/amd64, confirmed via Docker Hub's public API, not guessed).

#### Status / Next Steps
* **Verified 2026-08-11.** First build against the new digest ran at the
  console as expected (one-time cost); a second build immediately after,
  from an SSH session, succeeded with no credential error -- confirms
  ordinary backend code rebuilds are now fully SSH-workable. A genuinely
  new/updated base image (a real version bump, not this exact digest)
  would still need the console once, same reasoning as before.
* `redis:alpine` and `docker.osgeo.org/geoserver:3.0.x` are unaffected --
  those are `image:`-referenced (pulled, not built) in
  `backend/docker-compose.yml`, and `docker compose up`/`restart`'s
  default pull policy only contacts the registry if the tag isn't already
  present locally at all (it is, for both) -- no equivalent freshness-check
  behavior to BuildKit's build-time tag resolution applies to them.

