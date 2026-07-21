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

