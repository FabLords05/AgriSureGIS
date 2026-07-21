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

