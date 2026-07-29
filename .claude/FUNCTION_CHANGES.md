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

