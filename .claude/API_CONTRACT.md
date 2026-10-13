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
  - **Description:** For the Monitoring dashboard's System Status panel: the PAGASA polling job's last/next run (last run is in memory, `null` until the first run after a restart), the newest bulletin, whether SMTP email alerts are configured, and (2026-10-12) the Google Earth Engine connection (`gee`, read-only -- the key never leaves the server; a failed sign-in is retried at most every 5 minutes).
  - **Response:** `{ "status": "success", "parser": { "interval_minutes": 15, "last_run_at": "...", "scrape_ok": true, "status_sync_ok": true, "next_run_at": "..." }, "last_bulletin": { "tcb_id": 432, "bulletin_count": 23, "is_final": true, "typhoon_name": "OPONG", "issued_at": "..." }, "email_alerts": { "configured": true }, "gee": { "configured": true, "connected": true, "project_id": "webgis-pcic", "service_account": "agrisure-ee@webgis-pcic.iam.gserviceaccount.com", "last_error": null } }`

## 4. Parametric Assessments
* **POST `/api/assessments/calculate`**
  - **Description:** Compute exposure hours, yield loss, and claim payouts for all active policies in the typhoon-affected area. At the end of the run, each assessed policy's insurance is marked used/unused for that specific typhoon in `tbl_insurance_usage` (see `AssessmentService._sync_insurance_usage`) — scoped per typhoon so a different typhoon's assessment isn't affected.
  - **Payload:** `{ "typhoon_id": 1, "bulletin_id": 12 }`
* **GET `/api/assessments/`** - Search and filter calculated risk assessments. Each row includes `typhoon_id` and `insurance_used` (`true`/`false`/`null` if no usage row exists yet for that typhoon).
* **GET `/api/assessments/export`**
  - **Description:** Download payout-ready PCIC-formatted CSV file.
* **GET `/api/assessments/pabs-summary`** / **POST `/api/assessments/export-pabs`**
  - **Description:** Combined PABS-format rows (JSON preview / CSV download; the POST also locks exported policies as used). JSON row keys (PCIC's final order, 2026-10-12): `FARMER_NAME, FARMERID, FARMID, IRID, CIC_NO, AREA, TYPHOON_NAME, PERIOD_OF_EXPOSURE, WIND_VELOCITY, AC, FINAL_INDEMNITY_PAYMENT, P, S, REMARKS`. The CSV writes them under PCIC's exact "final output" headers: `FARMER NAME, FARMERSID, FARMID, IRID, CIC NO, AREA, TYPHOON_NAME, PERIOD_OF_EXPOSURE, WIND_VELOCITY, AC, FINAL_INDEMNITY_PAYMENT, P, S, REMARKS`. `FARMID` is PCIC's own farm ID (`csv_farm_reference`); the JSON also carries non-exported `crop_stage`. `IRID` is always blank (no source yet). `CIC_NO` is the insurance record's `policy_no`. `FINAL_INDEMNITY_PAYMENT` is the assessment's stored payout. `P` is always `"1.0"` (100% prevalence); `S` is the RECSAP estimated yield loss as a fraction (`"0.3"` = 30%); `REMARKS` is PCIC's remark for the assessment's RECSAP cell (signal, crop stage, exposure; signal 5 uses signal 4's table), blank when none. `WIND_VELOCITY` is the typhoon's highest bulletin `max_sustained_winds` (km/h, storm-wide). The JSON rows also carry `wind_signal` (TCWS signal number, not exported) for the on-screen table.

## 4b. Farms (Farm Records)
* **GET `/api/farms/`** and **GET `/api/farms/geometry`**
  - **`active_only=true`:** farms with a policy inside its coverage dates today **and not locked as used** by a final PABS export (2026-10-12).
  - **`typhoon_id`:** farms whose policy was locked as used for that typhoon; overrides `active_only`.
  - **`affected_typhoon_id`:** farms inside that typhoon's TCWS signal >= 2 areas in **any** of its bulletins (2026-10-12; per typhoon, replacing the earlier per-bulletin `affected_bulletin_id`) — the Spatial Analysis "Affected by" dropdown. Matching is the same `(province, municipality)` text join `ExposureCalculatorService` uses against `tbl_tcb_signals`, so it is municipality-granular, **not** a geometric intersection with a wind footprint. Unlike `typhoon_id` (already exported/locked as used) it works as soon as a bulletin is parsed, before any assessment run, and it AND's with `active_only`/`municipality`/`farmer_id` rather than overriding them. Signals with no `province` recorded (pre-2026-08-20 rows) are skipped. The filtered set is the AOI for the SAR planted check — see `docs/SAR_ISPLANTED_METHOD.md`.
* **GET `/api/farms/used-typhoons`**
  - **Description:** Typhoons with at least one policy locked as used by a final export, for the Farm Records typhoon filter.
  - **Response:** `{ "status": "success", "data": [ { "typhoon_id": 7, "name": "OPONG", "year": 2026, "farm_count": 20 } ] }`

## 4c. SAR Planted Verification (Verify Farm Planted, 2026-10-12)
Phase 1 of `docs/SAR_ISPLANTED_METHOD.md`: a visual layer plus the GIS Specialist's recorded verdict. The verdict is **never** read by the assessment or the PABS/PCIC export.
* **POST `/api/sar/layer`**
  - **Payload:** `{ "typhoon_id": 7 }`
  - **Description:** Pre-event Sentinel-1 VV/VH-ratio tile layer from Google Earth Engine, clipped (20 m inward buffer) to the typhoon's affected farm polygons -- the `affected_typhoon_id` set on `GET /api/farms/`, narrowed to farms insured when it hit (see the planted check below), GPX-surveyed farms only, capped at 5,000. Window: the 24 days before the typhoon's first bulletin; descending IW scenes from the single most frequent relative orbit; colour stretch 4.5-7.5 dB. Cached server-side for 1 hour.
  - **Response:** `{ "status": "success", "data": { "tile_url": "https://earthengine.googleapis.com/.../{z}/{x}/{y}", "scene_dates": ["2026-09-06", "2026-09-18"], "relative_orbit": 105, "window_start": "2026-09-01", "window_end": "2026-09-24", "min_db": 4.5, "max_db": 7.5, "palette": ["#14532d", "#22c55e", "#d2b48c", "#7c4a1e"], "typhoon_id": 7, "event_date": "2026-09-25", "farm_count": 120, "capped": false, "skipped_no_geom": 3 } }`
  - **Errors:** 404 unknown typhoon or no bulletins; 503 Earth Engine not configured; 422 no affected polygons or no pre-event scenes; 502 Earth Engine failure.
* **GET `/api/sar/verifications?typhoon_id=7`** -- `{ "status": "success", "data": [ { "farm_id": 5, "typhoon_id": 7, "is_planted": true, "verified_by": "Juan Dela Cruz", "verified_at": "...", "notes": null } ] }`
* **PUT `/api/sar/verifications/{farm_id}`** -- payload `{ "typhoon_id": 7, "is_planted": false, "notes": "bare soil" }`; creates or replaces the verdict for that farm and typhoon (`tbl_planted_verification`, unique per farm + typhoon). 404 unknown farm.
* **DELETE `/api/sar/verifications/{farm_id}?typhoon_id=7`** -- back to unchecked; `{ "status": "success", "deleted": 1 }`.
* The three `/verifications` endpoints are no longer called by the frontend (2026-10-12; replaced by the automatic check below). They stay so verdicts already recorded remain readable.

### Automatic planted check (Phase 2, 2026-10-12)
Method doc §3: every affected farm comes back GREEN `planted` (all five conditions pass, no field visit) or YELLOW `field_verify` (anything else). SAR never returns "not planted" on its own. Results are **never** read by the assessment or the PABS/PCIC export.
* **POST `/api/sar/check`**
  - **Payload:** `{ "typhoon_id": 7 }`
  - **Description:** Classifies every farm in the typhoon's `affected_typhoon_id` set (signal 2+ in any of its bulletins) that was **insured when it hit**: a policy in force on the first-bulletin date and not already spent on a different typhoon by a final export (a policy exported for this same typhoon still counts). Uninsured farms are never sent to Earth Engine and get no result, using the 150 days before the typhoon's first bulletin. Farms with no GPX polygon (`no_boundary`), or nothing left after the 20 m inward buffer (`too_small`), are yellow without an Earth Engine call. The per-farm, per-scene polygon-mean VV/VH is cached in `tbl_sar_observation`. Earth Engine is only queried for farms whose window isn't already covered (`tbl_sar_fetch_coverage`) or whose boundary changed. A fully cached re-run works even with Earth Engine unconfigured. The run replaces any earlier result for the typhoon (`tbl_sar_planted_check`, unique per farm + typhoon). This is synchronous, and a first run on a large typhoon can take minutes.
  - **Response:** `{ "status": "success", "data": { "summary": { "typhoon_id": 7, "window_start": "2025-04-27", "window_end": "2025-09-23", "checked_at": "...", "checked": 148, "planted": 97, "field_verify": 51, "reasons": [ { "code": "no_canopy_closure", "label": "No canopy closure (C3)", "count": 19 } ], "fetched_from_gee": 140, "from_cache": 0 }, "results": [ { "farm_id": 5, "status": "planted", "reason_code": "all_conditions_met", "reason": "All 5 conditions met", "t0_date": "2025-06-15", "tp_date": "2025-08-14", "vh_rise_db": 3.0, "ratio_drop_db": 1.9, "relative_orbit": 105, "scene_count": 13 } ] } }`
  - **Reason codes:** `all_conditions_met`, `no_boundary`, `too_small`, `too_few_scenes`, `no_flood_minimum` (C1), `crop_too_young`, `no_biomass_rise` (C2), `no_canopy_closure` (C3), `vv_vh_disagree` (C4), `outside_planting_window` (C5).
  - **Errors:** 404 unknown typhoon or no bulletins; 422 no affected farms; 503 Earth Engine needed but not configured; 502 Earth Engine failure.
* **GET `/api/sar/checks?typhoon_id=7`** -- the stored result, in the same `{ summary, results }` shape without `fetched_from_gee`/`from_cache`. `summary` is `null` if the check has never been run for that typhoon.

## 5. Insurance
* **GET `/api/insurance/summary`** - Counts active policies (inside their effectivity/expiry window today **and** `is_used = false`, 2026-10-12) vs. total policies.
* **GET `/api/insurance/usage`**
  - **Description:** Per-typhoon insurance usage status from `tbl_insurance_usage`. Optional `typhoon_id` and `insurance_records_id` query filters. Without `typhoon_id`, returns every typhoon a policy has been assessed against — the same policy can be used for one typhoon and unused for another, tracked independently.\n