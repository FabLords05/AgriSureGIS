# AgriSureGIS - API Contract

**Base URL:** `/api/`

## Conventions (current, as implemented)
- Request/response bodies: JSON.
- **Error shape:** FastAPI's default `{"detail": "<message>"}` on non-2xx responses — there is no custom error envelope in the codebase.
- **Pagination:** not implemented on any list endpoint yet.
- **Authentication:** not implemented in code yet. The Authentication section below (`/api/auth/login/`, `/api/auth/logout/`) describes the *planned* contract — no JWT/auth code exists in `backend/app/` today, and no endpoint currently enforces a role check.
- **Response envelope is currently inconsistent** — e.g. `GET /api/assessments` returns `{"status": "success", "data": [...]}`, while `GET /api/bulletins/` returns a bare array. This is a known gap, not a standard to copy.

## 1. Authentication
* **POST `/api/auth/login/`** - Authenticate user and return JWT tokens.
* **POST `/api/auth/logout/`** - Blacklist JWT refresh token.

## 2. Spatial Data & Profile Ingestion
* **POST `/api/upload/csv`**
  - **Description:** Bulk upload farmer and policy records.
  - **Payload:** Multipart Form (CSV file).
  - **Row handling:** Each row is processed in its own SAVEPOINT — a row that fails (e.g. no PSGC code on file for its province/municipality/barangay) is rolled back and recorded individually; it does not abort the rest of the batch. Response includes `rows_failed` (count) and `failures` (up to 50 entries: `{row, policy_no, error}`), alongside the existing `rows_processed`/`rows_inserted`/`rows_skipped`.
* **POST `/api/upload/gpx`**
  - **Description:** Upload GPX track files to build farm boundary geometries.
  - **Payload:** Multipart Form (GPX file, optional `farmer_id`, `farm_id`).
  - **Matching:** If `farmer_id`/`farm_id` are both omitted, the farmer/farm is auto-detected from the uploaded filename (pattern `TAB_<LASTNAME> , <FIRSTNAME> <MI>._<ID1>_<ID2>_<DATE>.gpx`) via `GpxFarmerMatcherService` — ID-based match first, normalized-name fallback. Returns 404/400 with no DB change if no match (or an ambiguous name match) is found; the caller falls back to supplying both IDs manually. Providing exactly one of the two IDs is a 400.
* **POST `/api/upload/gpkg`**
  - **Description:** Upload a GeoPackage holding many farm boundary polygons (one feature per walked farm) and attach each to its existing farm. Update-only — no farmer/farm/policy records are created.
  - **Payload:** Multipart Form (`.gpkg` file). Layer(s) must be EPSG:4326; Polygon and MultiPolygon features accepted.
  - **Matching:** Per feature, `GpxFarmerMatcherService.match_parsed` using the feature's `FARMERSID` (as id1), `FARMID` (as id2) and `FARMER NAME` attributes — same rules as GPX auto-detect. Duplicate FARMIDs: latest walk date (from `file_name`) wins. Each feature runs in its own SAVEPOINT; unmatched/ambiguous/bad-geometry features are reported, not fatal.
  - **Response:** `{status, message, features_total, features_updated, features_failed, duplicates_skipped, failures: [{feature, file_name, farm_reference, error}] (≤200)}`. 400 if the file isn't a readable GeoPackage, has no feature layer, or isn't EPSG:4326.

## 3. PAGASA Bulletin Monitoring
* **GET `/api/bulletins/`** - List all parsed tropical cyclone bulletins.
* **POST `/api/bulletins/parse`**
  - **Description:** Trigger scraper to check PAGASA portal, download PDF, and parse details.
  - **Response:** `{ "status": "success", "bulletin_id": 12, "typhoon_name": "Leon" }`
* **GET `/api/typhoons/{typhoon_id}/progress`**
  - **Description:** Where one typhoon is in the workflow, for the Monitoring dashboard's progress strip. Read-only counts; triggers no compute. `in_par` is `Typhoon.is_active` (still listed on PAGASA's status page).
  - **Response:** `{ "status": "success", "typhoon_id": 7, "typhoon_name": "OPONG", "in_par": false, "bulletin_count": 23, "final_bulletin": { "bulletin_count": 23, "issued_at": "..." }, "exposure_areas": 5, "assessed_farms": 20, "exported_policies": 0, "exported_at": null }`
* **GET `/api/typhoons/{typhoon_id}/track`**
  - **Description:** For the Spatial Analysis typhoon track overlay (2026-10-12). One point per bulletin center in issue order (bulletins with no center, or the parser's 0.0/0.0 fallback, are skipped), the latest bulletin's forecast positions, and the PAR outline. `in_par` here is geometric (latest center inside PAR), `null` if no center; radii are `null` when the bulletin didn't state them.
  - **Response:** `{ "status": "success", "typhoon_id": 7, "typhoon_name": "OPONG", "year": 2026, "is_active": true, "par_polygon": [[25, 120], ...], "points": [ { "tcb_id": 410, "bulletin_count": 9, "is_final": false, "issued_at": "...", "category": "Typhoon", "max_sustained_winds": 120, "lat": 14.3, "lng": 120.9, "wind_radius_km": 500, "storm_force_radius_km": 150, "inside_par": true } ], "forecast": [ { "label": "12-Hour Forecast 2:00 AM", "lat": 15.0, "lon": 117.8, "location": "...", "inside_par": true } ], "in_par": true }`
* **GET `/api/system/status`**
  - **Description:** For the Monitoring dashboard's System Status panel: the PAGASA polling job's last/next run (last run is in memory, `null` until the first run after a restart), the newest bulletin, and whether SMTP email alerts are configured.
  - **Response:** `{ "status": "success", "parser": { "interval_minutes": 15, "last_run_at": "...", "scrape_ok": true, "status_sync_ok": true, "next_run_at": "..." }, "last_bulletin": { "tcb_id": 432, "bulletin_count": 23, "is_final": true, "typhoon_name": "OPONG", "issued_at": "..." }, "email_alerts": { "configured": true } }`

## 4. Parametric Assessments
* **POST `/api/assessments/calculate`**
  - **Description:** Compute exposure hours, yield loss, and claim payouts for all active policies in the typhoon-affected area. At the end of the run, each assessed policy's insurance is marked used/unused for that specific typhoon in `tbl_insurance_usage` (see `AssessmentService._sync_insurance_usage`) — scoped per typhoon so a different typhoon's assessment isn't affected.
  - **Payload:** `{ "typhoon_id": 1, "bulletin_id": 12 }`
* **GET `/api/assessments/`** - Search and filter calculated risk assessments. Each row includes `typhoon_id` and `insurance_used` (`true`/`false`/`null` if no usage row exists yet for that typhoon).
* **GET `/api/assessments/export`**
  - **Description:** Download payout-ready PCIC-formatted CSV file.
* **GET `/api/assessments/pabs-summary`** / **POST `/api/assessments/export-pabs`**
  - **Description:** Combined PABS-format rows (JSON preview / CSV download; the POST also locks exported policies as used). Columns: `FARMER_NAME, FARMERID, FARMID, AREA, TYPHOON_NAME, PERIOD_OF_EXPOSURE, WIND_VELOCITY, DATE_FILED, DATE_OF_OCCURRENCE, P, S, AC, FINAL_INDEMNITY_PAYMENT, REMARKS`. No IRID (2026-10-12). `FINAL_INDEMNITY_PAYMENT` is blank until the revised payout calculation lands. `P` is always `"1.0"` (100% prevalence); `S` is the RECSAP estimated yield loss as a fraction (`"0.3"` = 30%); `REMARKS` is PCIC's fixed sentence. `WIND_VELOCITY` is the TCWS signal number.

## 4b. Farms (Farm Records)
* **GET `/api/farms/`** and **GET `/api/farms/geometry`**
  - **`active_only=true`:** farms with a policy inside its coverage dates today **and not locked as used** by a final PABS export (2026-10-12).
  - **`typhoon_id`:** farms whose policy was locked as used for that typhoon; overrides `active_only`.
* **GET `/api/farms/used-typhoons`**
  - **Description:** Typhoons with at least one policy locked as used by a final export, for the Farm Records typhoon filter.
  - **Response:** `{ "status": "success", "data": [ { "typhoon_id": 7, "name": "OPONG", "year": 2026, "farm_count": 20 } ] }`

## 5. Insurance
* **GET `/api/insurance/summary`** - Counts date-window-active vs. total policies.
* **GET `/api/insurance/usage`**
  - **Description:** Per-typhoon insurance usage status from `tbl_insurance_usage`. Optional `typhoon_id` and `insurance_records_id` query filters. Without `typhoon_id`, returns every typhoon a policy has been assessed against — the same policy can be used for one typhoon and unused for another, tracked independently.\n