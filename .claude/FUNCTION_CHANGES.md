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

## [2026-07-27] - Local Environment Setup: DATABASE_URL Wiring + Windows Fixes

**Branch:** `fabio/backend/env-based-db-config` (committed locally, not pushed, no PR open yet).

Set up PostgreSQL, the Python venv, and npm from scratch on Fabio's machine (first real local run this project has had — every prior changelog entry notes "never run against a live database"). This surfaced and fixed real, previously-latent bugs that only appear when actually running the app, not just reading the code.

### 1. File: `backend/app/core/database.py`
* `SQLALCHEMY_DATABASE_URL` was hardcoded directly in source (`postgresql://agrisure_admin:agrisure_password@localhost:5432/agrisure_db`), never actually reading `DATABASE_URL` from `.env` despite `.claude/ENV_GUIDE.md` documenting exactly that pattern. Now reads `os.getenv("DATABASE_URL", <same value as before>)` via `python-dotenv`'s `load_dotenv()` — existing setups keep working unchanged (same fallback default), but a local `backend/.env` can now actually override it, matching the documented behavior for the first time.

### 2. File: `backend/seed_database.py`
* Had its own, separate hardcoded `DB_CONFIG` dict (port 5432), completely independent of `database.py`'s connection setup — discovered when seeding failed against a differently-configured local instance even after `database.py` was fixed. Replaced with the same `DATABASE_URL` env-var pattern (psycopg2 natively accepts a full DSN string, so no dict-parsing needed), keeping the two files' DB config in sync.

### 3. File: `backend/.env.example` (new)
* Documents `DATABASE_URL` per `ENV_GUIDE.md`'s existing convention — previously referenced by that guide but never actually created. Safe to commit (unlike `backend/.env`, which stays gitignored).

### 4. File: `backend/requirements.txt`
* `uvloop==0.22.1` was pinned unconditionally — `uvloop` does not support Windows at all (confirmed via the actual pip build error: `RuntimeError: uvloop does not support Windows at the moment`), so `pip install -r requirements.txt` couldn't complete on any Windows machine. Changed to `uvloop==0.22.1; sys_platform != "win32"` — still installed (and still speeds up `uvicorn`) on Linux/Mac, silently skipped on Windows where `uvicorn` just falls back to its default asyncio event loop.

### Status / Next Steps
* Local setup used a self-owned PostgreSQL data directory (`C:\Users\User\pgdata`, port 5433) rather than the Windows-service-managed default instance (port 5432) — the Windows service's `postgres` superuser password was unknown/unrecoverable, and this machine's UAC elevation is non-functional in a way that blocked every service-control/config-reload workaround (confirmed via `whoami /groups` showing "Group used for deny only" on the Administrators SID even inside windows labeled "Administrator"). This is environment-specific to this machine, not a code issue — another teammate's default Windows-service Postgres install on port 5432 should work fine with the same `DATABASE_URL` fallback default.
* The old, stuck Windows service (`postgresql-x64-17`, port 5432, unknown password) is still installed and running on this machine, unused. Not cleaned up — out of scope, and Fabio may want to deal with it separately (e.g. once genuine admin access is sorted out).
* Full local smoke test passed: `pytest` suite green, `npm run build` clean, backend (`uvicorn app.main:app --reload`) and frontend (`npm run dev`) both start and serve real seeded data end-to-end in the browser.

