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

