# AgriSureGIS - API Contract

**Base URL:** `/api/` (FastAPI app title `AgriSureGIS API`, version `1.0`).

Last reconciled against the code on **2026-10-18**. Every endpoint below was read
out of `backend/app/api/` — this file documents what exists, not what is planned.

## Conventions (current, as implemented)

- Request/response bodies: JSON. CSV exports stream back as `text/csv`.
- **Error shape:** FastAPI's default `{"detail": "<message>"}` on non-2xx responses — there is no custom error envelope in the codebase.
- **Authentication:** implemented (2026-08-16). Every router except the public
  endpoints below carries a router-level `Depends(get_current_user)`, so every
  request needs an `Authorization: Bearer <token>` header.
  - **Public (no token):** `POST /api/users/register`, `POST /api/users/login`, plus
    `GET /` and `GET /api/test-db`.
  - **Admin-only:** the whole `/api/activity-log` router, and `GET /api/users/`,
    `POST /api/users/`, `PATCH /api/users/{user_id}` — all via `require_admin`,
    which demands `role == "System Administrator"` and returns **403**
    `"Administrator access required."` otherwise.
  - **Token:** a stateless signed JWT (HS256, `JWT_SECRET_KEY`, see
    `backend/app/core/security.py`). There is **no server-side blocklist** — per
    Fabio's explicit direction, a token is invalidated by the client discarding it
    (explicit Logout, or `App.tsx`'s inactivity timer). `TOKEN_EXPIRY_HOURS = 24`
    is a safety-net upper bound, not the timeout mechanism.
  - `is_active` is re-checked on **every** request, so deactivating an account
    kills its existing token immediately.
  - 401 messages: `"Not authenticated."`, `"Session expired."`,
    `"Invalid session token."`, `"Account not found or deactivated."`.
- **Activity logging:** an HTTP middleware in `backend/app/main.py` records every
  **mutating** (`POST`/`PUT`/`PATCH`/`DELETE`) request, plus the two CSV export
  GETs, to `tbl_activity_log` as it finishes, attributed to
  `request.state.user`, with a detailed `remarks` sentence (see §2). `/api/users/login` and
  `/api/users/logout` are excluded there because they self-log a more specific
  `LOGIN`/`LOGOUT` action from inside their own route bodies.
- **Pagination:** keyset pagination exists on **`GET /api/farms/` only**
  (`limit` + `after_id`); omitting `limit` keeps the original unpaginated
  behaviour. No other list endpoint is paginated.
- **Response envelope is inconsistent** — most endpoints return
  `{"status": "success", ...}`, but `GET /api/bulletins/`,
  `GET /api/bulletins/{tcb_id}/signals` and the `/api/bulletins/settings` pair
  return bare arrays/objects, and `POST /api/upload/csv` returns a bare job
  object. This is a known gap, not a standard to copy.
- **CSV downloads:** filenames are set via `Content-Disposition` and name
  themselves after the typhoon + export time (`assessments._export_filename`).
  `main.py`'s CORS middleware must keep `expose_headers=["Content-Disposition"]`
  or the browser hides the header and every file saves under the fallback name.

## 1. Authentication & User Accounts (`/api/users`)

Note the prefix: it is **`/api/users/...`**, not `/api/auth/...`.

* **POST `/api/users/register`** *(public)*
  - **Description:** Self-registration from the Login screen's "Request System Access" form. Creates a **pending** account (`is_active = false`) awaiting administrator approval in Calibration & Settings.
  - **Payload:** `{ "full_name": "...", "email": "...", "employee_id": "...", "role": "...", "password": "...", "division": null }` (`password` min length 8; `role` must be `"GIS Specialist"` or `"System Administrator"`; `employee_id` becomes `username`).
  - **Response:** `{ "status": "success", "message": "Registration submitted. Pending administrator approval." }`. 400 on a bad role, 409 if the employee ID or email is taken.
* **POST `/api/users/login`** *(public)*
  - **Payload:** `{ "email": "...", "password": "..." }`
  - **Response:** `{ "status": "success", "token": "<jwt>", "user": { "name": "...", "role": "...", "email": "...", "session_timeout_minutes": 30 } }`
  - **Errors:** 401 `"Invalid credentials."`; 403 `"This account is pending administrator approval."` when `is_active = false`. Both are recorded in the activity log, as is a success.
  - Passwords are verified with bcrypt directly (not passlib — see the comment in `app/api/users.py`). `last_login` is stamped on success.
* **POST `/api/users/logout`** - Records a `LOGOUT` activity-log entry and returns `{"status": "success"}`. Does **nothing** to the token itself (stateless JWT, no blocklist).
* **GET `/api/users/`** *(admin)* - `{ "status": "success", "data": [ { "user_id", "name", "email", "role", "is_active", "last_login", "created_at", "session_timeout_minutes" } ] }`, ordered by `user_id`. Backs Calibration & Settings' User Account Management table.
* **POST `/api/users/`** *(admin)*
  - **Description:** Admin-created account ("Add User") — active immediately, no approval step. `username` is the email local-part (the form has no employee-ID field).
  - **Payload:** `{ "name": "...", "email": "...", "role": "...", "password": "..." }`
  - **Response:** `{ "status": "success", "data": { ...user... } }`. 409 if the email exists.
* **PATCH `/api/users/me`**
  - **Description:** Self-service Account Settings tab, for any authenticated user. Registered **before** `PATCH /{user_id}` so `/me` matches as a static path.
  - **Payload:** any of `{ "name", "email", "session_timeout_minutes" (0-120), "current_password", "new_password" }`. Changing the password requires a correct `current_password` (400 otherwise).
  - **Deliberately has no `role`/`is_active` fields at all**, so no payload shape can let a user promote or reactivate themselves.
* **PATCH `/api/users/{user_id}`** *(admin)*
  - **Description:** Admin edit / activate / deactivate.
  - **Payload:** any of `{ "name", "email", "role", "is_active", "session_timeout_minutes" }`. 404 unknown user, 400 bad role, 409 duplicate email.

## 2. Activity Log (`/api/activity-log`) — admin-only

* **GET `/api/activity-log/`**
  - **Query:** `limit` (default 200, 1-1000), `user_id` (optional, narrows to one account), `action_type` (optional, one label from `/filters`' `action_types`, e.g. `"Uploaded a CSV file"`; 400 if unknown).
  - **Description:** Every login, logout and mutating backend call, plus the two CSV export GETs (`/api/assessments/export`, `/api/sar/field-verify/export`), the background CSV ingestion's outcome (`action: "INGEST"`), and the scheduled PAGASA TCB ingestion (`action: "SYSTEM"`, `endpoint: "scheduler/pagasa-poll"`, no user). Newest first. Capped by `limit` because this table has no upper bound on growth.
  - **Response:** `{ "status": "success", "data": [ { "log_id", "user_id", "user_name", "user_email", "action", "endpoint", "summary", "remarks", "status_code", "created_at" } ] }`
  - `remarks` (2026-10-22) is a full sentence saying exactly what was done: which file or record, before → after values, how many rows were accepted, skipped or rejected and why, and, for a failed request, the error message the user saw (`Rejected: ...` / `Failed: ...`). Routes set it with `note_activity()` (`app/core/activity_log.py`). Passwords are never included.
  - `summary` is a human-readable label from `_ENDPOINT_SUMMARIES` in `app/api/activity_log.py` (e.g. `"Uploaded a CSV file"`, `"Logged in"`, `"Failed login attempt"`). A mutating route added without a matching entry falls through to the raw `"{ACTION} {endpoint}"` string, so nothing is ever hidden — but new routes should get an entry.
* **GET `/api/activity-log/filters`** (2026-10-22)
  - **Description:** Options for the Activity Log tab's User and Action dropdowns.
  - **Response:** `{ "status": "success", "data": { "users": [ { "user_id", "name", "email", "role" } ], "action_types": [ "Logged in", ..., "Uploaded a CSV file", ... ] } }`. `users` = every account with at least one log entry, admins included.

## 3. Spatial Data & Profile Ingestion (`/api/upload`)

* **POST `/api/upload/csv`**
  - **Description:** Bulk upload of farmer and policy records. **Asynchronous since 2026-08-16.** The file is validated and parsed synchronously (fast), then the slow row-by-row ingestion runs on a background thread.
  - **Payload:** Multipart Form (CSV file).
  - **Response (immediate):** `{ "status": "processing", "job_id": "<uuid>", "total_rows": 1113 }` — poll the status endpoint below for progress. An empty CSV returns the same shape with `total_rows: 0` and an already-completed job.
  - **Up-front rejection (2026-10-13):** 400 if the extension/content-type isn't CSV, if the file can't be decoded (UTF-8 with BOM tolerance first, then cp1252 — real PABS exports have arrived as ISO-8859-1/cp1252, e.g. names like `SEÑERES`), or if it is missing required PABS columns (`"This doesn't look like a PABS insurance export -- missing column(s): ... No rows were imported."`).
  - **Row handling:** each row is processed in its own SAVEPOINT — a row that fails (e.g. no PSGC code on file for its province/municipality/barangay) is rolled back and recorded individually; it does not abort the rest of the batch.
* **GET `/api/upload/csv/status/{job_id}`**
  - **Response:** `{ "status": "processing" | "done" | "error", "processed": 420, "total": 1113, "result": {...} | null, "error": null }`
  - On completion, `result` carries what the endpoint used to return synchronously: `{ status, message, rows_processed, rows_inserted, rows_skipped, rows_failed, failures: [{row, policy_no, error}] (<=50) }`.
  - **404** `"Unknown upload job (may have been since a backend restart)."` — jobs live in memory (`app/core/upload_jobs.py`), not in the database.
* **POST `/api/upload/gpx`**
  - **Description:** Upload GPX track files to build farm boundary geometries. Update-only: it sets `location_geom` on an existing farm.
  - **Payload:** Multipart Form (GPX file, optional `farmer_id`, `farm_id`).
  - **Matching:** If `farmer_id`/`farm_id` are both omitted, the farmer/farm is auto-detected from the uploaded filename (pattern `TAB_<LASTNAME> , <FIRSTNAME> <MI>._<ID1>_<ID2>_<DATE>.gpx`) via `GpxFarmerMatcherService` — ID-based match first, normalized-name fallback. Returns 404/400 with no DB change if no match (or an ambiguous name match) is found; the caller falls back to supplying both IDs manually. Providing exactly one of the two IDs is a 400. GPX must be UTF-8.
  - **Response:** `{ "status": "success", "message": "...", "farm_id": 5, "matched_by": "manual" | "<id|name>", "farmer_name": "..." }`
* **POST `/api/upload/gpkg`**
  - **Description:** Upload a GeoPackage holding many farm boundary polygons (one feature per walked farm) and attach each to its existing farm. Update-only — no farmer/farm/policy records are created.
  - **Payload:** Multipart Form (`.gpkg` file). Layer(s) must be EPSG:4326; Polygon and MultiPolygon features accepted.
  - **Matching:** Per feature, `GpxFarmerMatcherService.match_parsed` using the feature's `FARMERSID` (as id1), `FARMID` (as id2) and `FARMER NAME` attributes — same rules as GPX auto-detect. Duplicate FARMIDs: latest walk date (from `file_name`) wins. Each feature runs in its own SAVEPOINT; unmatched/ambiguous/bad-geometry features are reported, not fatal.
  - **Response:** `{status, message, features_total, features_updated, features_failed, duplicates_skipped, failures: [{feature, file_name, farm_reference, error}] (<=200)}`. 400 if the file isn't a readable GeoPackage, has no feature layer, or isn't EPSG:4326.

## 4. PAGASA Bulletin Monitoring (`/api/bulletins`)

* **GET `/api/bulletins/`**
  - **Description:** All parsed bulletins, **newest `issued_at` first**. Ordered by `issued_at` rather than `bulletin_count` — the latter resets to 1 per typhoon, so sorting by it interleaves typhoons out of chronological order.
  - **Response:** a **bare array** of `{ tcb_id, typhoon_id, title, bulletin_count, category, typhoon_name, max_sustained_winds, gustiness, issued_at, center_lat, center_lng, max_signal_level, tcws_areas, is_final }`.
* **POST `/api/bulletins/parse`**
  - **Description:** Trigger the scraper to check the PAGASA portal, download PDFs, and parse details. Then syncs active typhoons from PAGASA's severe-weather status page (an independent step — a failure there doesn't hide a successful parse), then sends the new-TCB email alert.
  - **Response:** `{ "status": "success", "parsed_count": 2, "bulletins": [...] }`
  - **404** `"No active bulletin PDFs found on PAGASA portal."` — returned both for a genuinely empty list and for a scrape failure (the distinction only matters internally; see `PagasaScrapeError`).
* **POST `/api/bulletins/upload`**
  - **Description:** Manual upload of a PAGASA bulletin PDF for when the scraping portal is offline. Also fires the new-TCB email alert (2026-10-13). Deliberately **not** preceded by a status sync, unlike `/parse` — this route exists precisely for when PAGASA is unreachable, and an empty status fetch would deactivate every typhoon.
  - **Payload:** Multipart Form (PDF file).
  - **Response:** `{ "status": "success", "message": "...", "bulletin": { "tcb_id", "title", "bulletin_count" } }`. 400 non-PDF, 500 on a parse failure.
* **GET `/api/bulletins/settings`** / **PUT `/api/bulletins/settings`**
  - **Description:** The persisted TCB polling interval in **minutes**, backing Calibration's "TCB Polling Interval" field. The PUT also reschedules the already-running APScheduler job, with no backend restart.
  - **Payload (PUT):** `{ "polling_interval_minutes": 15 }` (15-1440).
  - **Response:** a bare `{ "polling_interval_minutes": 15 }`.
  - **Caveat:** the background poll is started on `scheduler.FIXED_POLL_INTERVAL_MINUTES` at app startup, **not** on this stored value (see that constant's comment in `app/core/scheduler.py`). `GET /api/system/status` reports the fixed interval.
* **POST `/api/bulletins/{tcb_id}/compute-exposure`**
  - **Description:** Recomputes per-municipality exposure-duration summaries (`tbl_area_exposure_summary`) for the typhoon this bulletin belongs to, using all of that typhoon's bulletins parsed so far. Does not compute yield loss or payouts.
  - **Response:** `{ "status": "success", "typhoon_id", "boundaries_computed", "summaries": [ { summary_id, boundary_id, province, municipality, max_signal_level, start_time, end_time, total_exposure_hours, is_eligible_6hr } ] }`. 404 unknown bulletin.
* **GET `/api/bulletins/{tcb_id}/signals`**
  - **Description:** The parsed wind signals and affected municipalities for one bulletin.
  - **Response:** a **bare array** of `{ signal_id, signal_level, island_group, area_name, province }`.
* **GET `/api/bulletins/typhoon/{typhoon_id}/summary`**
  - **Description:** Per-typhoon exposure summary for the Assessment & Reporting module's typhoon panel. Reads `tbl_area_exposure_summary` as-is — it does **not** trigger a recompute. "People hit" is anyone whose farm falls in an affected boundary, whether or not a payout was assessed.
  - **Response:** `{ "status": "success", "typhoon_id", "typhoon_name", "areas_hit": [ { province, municipality, max_signal_level, start_time, end_time, total_exposure_hours } ], "max_signal_level", "start_time", "end_time", "exposure_duration_hours", "people_hit", "signal_1_only_people_hit" }`. `people_hit` counts farmers in municipalities that reached TCWS 2+; `signal_1_only_people_hit` counts farmers whose municipality only reached Signal 1 (2026-10-22). With no summaries yet, the same shape comes back with an empty `areas_hit` and nulls. 404 unknown typhoon.
  - Farmers are matched by `(province, municipality)`, not `boundary_id` — a summary's `boundary_id` is one barangay standing in for the whole municipality.

## 5. Typhoons (`/api/typhoons`)

* **GET `/api/typhoons/active`**
  - **Description:** Typhoon(s) PAGASA's severe-weather status page currently lists as active (`PagasaStatusService`), **not** derived from bulletin parsing. Backs the Monitoring dashboard's "Active Typhoon" card. Usually 0 or 1 entries; the status page can show more if several cyclones are in the PAR at once.
  - **Response:** `{ "status": "success", "active_typhoons": [ { "typhoon_id": 7, "name": "OPONG", "year": 2026 } ] }`
* **GET `/api/typhoons/{typhoon_id}/progress`**
  - **Description:** Where one typhoon is in the workflow, for the Monitoring dashboard's progress strip. Read-only counts; triggers no compute. `in_par` is `Typhoon.is_active` (still listed on PAGASA's status page). `assessed_farms` only counts `RiskAssessment` rows tied to this typhoon's exposure summaries, which leaves out CSV-seeded rows (`summary_id` NULL) that only carry crop stage.
  - **Response:** `{ "status": "success", "typhoon_id": 7, "typhoon_name": "OPONG", "in_par": false, "bulletin_count": 23, "final_bulletin": { "bulletin_count": 23, "issued_at": "..." }, "exposure_areas": 5, "assessed_farms": 20, "exported_policies": 0, "exported_at": null }`
* **GET `/api/typhoons/{typhoon_id}/track`**
  - **Description:** For the Spatial Analysis typhoon track overlay (2026-10-12). One point per bulletin center in issue order (bulletins with no center, or the parser's 0.0/0.0 fallback, are skipped), the latest bulletin's forecast positions, and the PAR outline. `in_par` here is geometric (latest center inside PAR), `null` if no center; radii are `null` when the bulletin didn't state them.
  - **Response:** `{ "status": "success", "typhoon_id": 7, "typhoon_name": "OPONG", "year": 2026, "is_active": true, "par_polygon": [[25, 120], ...], "points": [ { "tcb_id": 410, "bulletin_count": 9, "is_final": false, "issued_at": "...", "category": "Typhoon", "max_sustained_winds": 120, "lat": 14.3, "lng": 120.9, "wind_radius_km": 500, "storm_force_radius_km": 150, "inside_par": true } ], "forecast": [ { "label": "12-Hour Forecast 2:00 AM", "lat": 15.0, "lon": 117.8, "location": "...", "inside_par": true } ], "in_par": true }`. 404 unknown typhoon.

## 6. System Status (`/api/system`)

* **GET `/api/system/status`**
  - **Description:** For the Monitoring dashboard's System Status panel: the PAGASA polling job's last/next run (last run is in memory, `null` until the first run after a restart), the newest bulletin, whether SMTP email alerts are configured, and (2026-10-12) the Google Earth Engine connection (`gee`, read-only — the key never leaves the server; a failed sign-in is retried at most every 5 minutes).
  - **Response:** `{ "status": "success", "parser": { "interval_minutes": 15, "last_run_at": "...", "scrape_ok": true, "status_sync_ok": true, "next_run_at": "..." }, "last_bulletin": { "tcb_id": 432, "bulletin_count": 23, "is_final": true, "typhoon_name": "OPONG", "issued_at": "..." }, "email_alerts": { "configured": true }, "gee": { "configured": true, "connected": true, "project_id": "webgis-pcic", "service_account": "agrisure-ee@webgis-pcic.iam.gserviceaccount.com", "last_error": null } }`

## 7. Parametric Assessments (`/api/assessments`)

* **POST `/api/assessments/calculate`**
  - **Description:** Compute exposure hours, check payout eligibility (wind signal >= 2, exposure >= 6h, crop stage in Booting/Flowering/Maturity) and calculate indemnity for all active policies in the typhoon-affected area. At the end of the run, each assessed policy's insurance is marked used/unused for that specific typhoon in `tbl_insurance_usage` (`AssessmentService._sync_insurance_usage`) — scoped per typhoon, so a different typhoon's assessment isn't affected.
  - **Payload:** `{ "typhoon_id": 1, "bulletin_id": 12 }`
  - **Response:** `{ "status": "success", "typhoon_id", "bulletin_id", "assessments_computed", "assessments": [ { assessment_id, insurance_records_id, crop_stage, period_of_exposure, wind_velocity, indemnity_factor, estimated_damage, final_indemnity_payment } ] }`. 404 when the typhoon/bulletin can't be resolved.
* **GET `/api/assessments/`**
  - **Query:** `typhoon_id`, `policy_no` (both optional).
  - **Response:** `{ "status": "success", "data": [ { assessment_id, policy_no, farm_id, amount_cover, crop_stage, period_of_exposure, wind_velocity, indemnity_factor, estimated_damage, final_indemnity_payment, assessment_date, typhoon_id, insurance_used } ] }`, newest `assessment_date` first.
  - `insurance_used` is `true`/`false`/`null` — `null` means no `tbl_insurance_usage` row exists yet for that (policy, typhoon) pair, which is distinct from `false` ("assessed, but unused").
* **GET `/api/assessments/summary`**
  - **Description:** Server-side dashboard aggregates (2026-08-17/18), replacing what `MonitoringModule.tsx` used to reduce over the entire client-side farms array before the on-demand-pagination redesign. Raw SQL over a latest-assessment-per-farm CTE. Deliberately **not** scoped by municipality — it reflects the whole system, unlike `GET /farms/`.
  - **"Affected"** = a farm's most recent `RiskAssessment` (by `assessment_date`, across all its policies/typhoons) has `wind_velocity` set. `total_area`/`total_indemnity` are summed over that same affected set only.
  - **Response:** `{ "status": "success", "total_farms", "affected_farms", "total_area", "total_indemnity", "growth_stage_distribution": [ { "crop_stage": "...", "farm_count": 12 } ], "signal_breakdown": [ { "wind_velocity": 3, "farm_count": 8, "total_area": 14.2 } ] }`
  - `growth_stage_distribution` covers **all** farms, bucketing farms with no assessment at all into `"Not Assessed"`.
* **GET `/api/assessments/export`**
  - **Query:** `typhoon_id` (optional).
  - **Description:** Downloads a PCIC-formatted CSV: the original `pabs_results.csv` row layout with the computed columns appended. Only includes assessments this engine computed (`matrix_id` is not null) — excludes the legacy rows created at CSV import time, which have no `matrix_id`.
* **GET `/api/assessments/pabs-summary`** / **POST `/api/assessments/export-pabs`**
  - **Description:** Combined PABS-format rows (JSON preview / CSV download). The POST also locks every exported policy with a payout as used (`AssessmentService.finalize_exported_usage`) and invalidates the farms cache, so no later typhoon can reuse it — POST rather than GET because exporting changes data.
  - **JSON row keys** (PCIC's final order, 2026-10-12): `FARMER_NAME, FARMERID, FARMID, IRID, CIC_NO, AREA, TYPHOON_NAME, PERIOD_OF_EXPOSURE, WIND_VELOCITY, AC, FINAL_INDEMNITY_PAYMENT, P, S, REMARKS`.
  - **CSV headers** (PCIC's exact "final output" spelling): `FARMER NAME, FARMERSID, FARMID, IRID, CIC NO, AREA, TYPHOON_NAME, PERIOD_OF_EXPOSURE, WIND_VELOCITY, AC, FINAL_INDEMNITY_PAYMENT, P, S, REMARKS`. Numeric columns are written to 2 decimals.
  - `FARMID` is PCIC's own farm ID (`csv_farm_reference`); the JSON also carries non-exported `crop_stage`. `IRID` is always blank (no source yet). `CIC_NO` is the insurance record's `policy_no`. `FINAL_INDEMNITY_PAYMENT` is the assessment's stored payout. `P` is always `"1.0"` (100% prevalence); `S` is the RECSAP estimated yield loss as a fraction (`"0.3"` = 30%); `REMARKS` is PCIC's remark for the assessment's RECSAP cell (signal, crop stage, exposure; signal 5 uses signal 4's table), blank when none. `WIND_VELOCITY` is the typhoon's highest bulletin `max_sustained_winds` (km/h, storm-wide). The JSON rows also carry `wind_signal` (TCWS signal number, not exported) and the farm's `province`, `municipality` and `barangay` (not exported; `barangay` added 2026-10-13) for the on-screen table.

## 8. Farms / Farm Records (`/api/farms`)

* **GET `/api/farms/`**
  - **Query:** `limit` (1-1000, optional), `after_id` (keyset cursor, default 0), `active_only`, `municipality`, `farmer_id`, `typhoon_id`, `affected_typhoon_id`.
  - **Response:** `{ "status": "success", "data": [ { farm_id, farmer_id, farmer_name, province, municipality, barangay, area_size, csv_farm_reference, georef_id, has_geometry, policy_no, amount_cover, program_type, effectivity_date, expiry_date, used_for_typhoon } ], "total", "limit", "after_id", "has_more" }`
    - `farmer_name` is PCIC CSV format (surname first). `effectivity_date`/`expiry_date` are `MM/DD/YYYY` strings. `policy_no` is CIC NO in the newer PCIC CSV layout, "Policy No." in the legacy one. Insurance fields come from the farm's **most recent** `InsuranceRecord`, if any.
    - **`has_geometry`** is a boolean, **not** a GeoJSON blob (2026-08-18). This endpoint's only consumer of geometry content was a Yes/No "Surveyed" badge; actual polygons come exclusively from `GET /api/farms/geometry`.
    - Omitting `limit` returns every matching farm in one `data` array with `total = len(data)`, `limit: null`, `after_id: 0`, `has_more: false`, and skips the COUNT query. A COUNT is added only for the first page of a paginated walk (`after_id == 0`).
  - **Performance:** 2 queries per request regardless of farm count (plus a 3rd for the "Used For Typhoon" column when the page has insurance). The "most recent policy per farm" lookup is a single indexed hit against `mv_farm_latest_insurance` (`app/core/farms_view.py`) once `backend/migrations/2026-08-09_farms_perf.sql` is applied; until then it falls back to bulk-fetching the page's policies and reducing in Python. Responses are cached per query-shape when `REDIS_URL` is set (`app/core/farms_cache.py`); ingestion and the final PABS export invalidate that cache.
* **GET `/api/farms/geometry`**
  - **Query:** `bbox` (`minLon,minLat,maxLon,maxLat`, WGS84 — the map's visible bounds), `farm_id`, `farmer_id`, `active_only`, `municipality`, `typhoon_id`, `affected_typhoon_id`.
  - **Description:** Viewport-based geometry for the map (2026-08-17), via a real PostGIS `ST_Intersects` against `location_geom`'s GiST index — replaces computing bbox intersection client-side over every farm's geometry. Deliberately separate from `GET /api/farms/`: the map never needs farmer/insurance fields, and the Farm Records table never needs polygons.
  - **Response:** `{ "status": "success", "data": [ { "farm_id": 5, "location_geom": { "type": "Polygon", "coordinates": [...] } } ] }`
  - `farm_id` ignores every other filter and returns just that farm. `farmer_id` without `bbox` returns all of that farmer's farms with geometry, ignoring `active_only`/`municipality`/`bbox` — used to fly the map to a searched farmer regardless of viewport. **400** if `bbox` is absent and neither `farm_id` nor `farmer_id` is given, or if `bbox` is malformed.
* **Shared filter semantics** for both endpoints above:
  - **`active_only=true`:** farms with a policy inside its coverage dates today **and not locked as used** by a final PABS export (2026-10-12).
  - **`typhoon_id`:** farms whose policy was locked as used for that typhoon. Those farms are by definition not active, so this **overrides** `active_only`.
  - **`affected_typhoon_id`:** farms inside that typhoon's TCWS signal >= 2 areas in **any** of its bulletins (2026-10-12; per typhoon, replacing the earlier per-bulletin `affected_bulletin_id`) — the Spatial Analysis "Affected by" dropdown. Matching is the same `(province, municipality)` text join `ExposureCalculatorService` uses against `tbl_tcb_signals`, so it is municipality-granular, **not** a geometric intersection with a wind footprint. Unlike `typhoon_id` (already exported/locked as used) it works as soon as a bulletin is parsed, before any assessment run, and it AND's with `active_only`/`municipality`/`farmer_id` rather than overriding them. Signals with no `province` recorded (pre-2026-08-20 rows) are skipped. The filtered set is the AOI for the SAR planted check — see `docs/SAR_ISPLANTED_METHOD.md`.
* **GET `/api/farms/used-typhoons`**
  - **Description:** Typhoons with at least one policy locked as used by a final export, with how many farms each — the Farm Records typhoon filter's options (2026-10-12). Newest year first.
  - **Response:** `{ "status": "success", "data": [ { "typhoon_id": 7, "name": "OPONG", "year": 2026, "farm_count": 20 } ] }`
* **GET `/api/farms/municipalities`**
  - **Description:** Distinct municipality names for the Farm Records search box's suggestion list (2026-08-18). Sourced from `tbl_admin_boundaries`, **not** `tbl_farms` — a small fixed reference table, safe to return in full however large `tbl_farms` gets, and it stays populated even before a first farm search.
  - **Response:** `{ "status": "success", "data": ["CAGAYAN DE ORO CITY", ...] }`
* **GET `/api/farms/farmers`**
  - **Query:** `q` (required, min length 1) — partial, case-insensitive match against `first_name || ' ' || last_name` as one concatenated string, which covers a first name, a last name, or both without an OR of conditions.
  - **Description:** Debounced server-side farmer search for the Farm Records search box (2026-08-18), capped at 20 results. Unlike municipalities, `tbl_farmers_profile` scales with the farm count, so it can't be preloaded whole for a client-side type-ahead.
  - **Response:** `{ "status": "success", "data": [ { "farmer_id": 12, "name": "..." } ] }`

## 9. SAR Planted Verification (`/api/sar`)

Implements `docs/SAR_ISPLANTED_METHOD.md`. The SAR verdict is **never** read by the
assessment engine or the PABS/PCIC export — it is an advisory layer for the GIS
Specialist only.

### 9a. Visual layer (Phase 1, 2026-10-12)

* **POST `/api/sar/layer`**
  - **Payload:** `{ "typhoon_id": 7 }`
  - **Description:** Pre-event Sentinel-1 VV/VH-ratio tile layer from Google Earth Engine, clipped (20 m inward buffer) to the typhoon's affected farm polygons — the `affected_typhoon_id` set on `GET /api/farms/`, narrowed to farms insured when it hit (same rule as the planted check below), GPX-surveyed farms only, capped at 5,000. Window: the 24 days before the typhoon's first bulletin; descending IW scenes from the single most frequent relative orbit; colour stretch 4.5-7.5 dB. Cached server-side for 1 hour.
  - **Response:** `{ "status": "success", "data": { "tile_url": "https://earthengine.googleapis.com/.../{z}/{x}/{y}", "scene_dates": ["2026-09-06", "2026-09-18"], "relative_orbit": 105, "window_start": "2026-09-01", "window_end": "2026-09-24", "min_db": 4.5, "max_db": 7.5, "palette": ["#14532d", "#22c55e", "#d2b48c", "#7c4a1e"], "typhoon_id": 7, "event_date": "2026-09-25", "farm_count": 120, "capped": false, "skipped_no_geom": 3 } }`
  - **Errors:** 404 unknown typhoon or no bulletins; 503 Earth Engine not configured; 422 no affected polygons or no pre-event scenes; 502 Earth Engine failure.

### 9b. Manual verdicts (Phase 1) — retained, no longer called by the frontend

* **GET `/api/sar/verifications?typhoon_id=7`** — `{ "status": "success", "data": [ { "farm_id": 5, "typhoon_id": 7, "is_planted": true, "verified_by": "Juan Dela Cruz", "verified_at": "...", "notes": null } ] }`
* **PUT `/api/sar/verifications/{farm_id}`** — payload `{ "typhoon_id": 7, "is_planted": false, "notes": "bare soil" }`; creates or replaces the verdict for that farm and typhoon (`tbl_planted_verification`, unique per farm + typhoon). 404 unknown farm.
* **DELETE `/api/sar/verifications/{farm_id}?typhoon_id=7`** — back to unchecked; `{ "status": "success", "deleted": 1 }`.
* These three are **no longer called by the frontend** (2026-10-12; replaced by the automatic check below). They stay so verdicts already recorded remain readable.

### 9c. Automatic planted check (Phase 2, 2026-10-12)

Method doc §3: every affected farm comes back GREEN `planted` (all five conditions
pass, no field visit) or YELLOW `field_verify` (anything else). SAR never returns
"not planted" on its own.

* **POST `/api/sar/check`**
  - **Payload:** `{ "typhoon_id": 7 }`
  - **Description:** Classifies every farm in the typhoon's `affected_typhoon_id` set (signal 2+ in any of its bulletins) that was **insured when it hit** (2026-10-13): a policy in force on the first-bulletin date and not already spent on a different typhoon by a final export — a policy exported for this same typhoon still counts. Uninsured farms are never sent to Earth Engine and get no result. Window: the 150 days before the typhoon's first bulletin. Farms with no GPX polygon (`no_boundary`), or nothing left after the 20 m inward buffer (`too_small`), are yellow without an Earth Engine call. The per-farm, per-scene polygon-mean VV/VH is cached in `tbl_sar_observation`; Earth Engine is only queried for farms whose window isn't already covered (`tbl_sar_fetch_coverage`) or whose boundary changed, so a fully cached re-run works even with Earth Engine unconfigured. The run replaces any earlier result for the typhoon (`tbl_sar_planted_check`, unique per farm + typhoon). **Synchronous** — a first run on a large typhoon can take minutes.
  - **Response:** `{ "status": "success", "data": { "summary": { "typhoon_id": 7, "window_start": "2025-04-27", "window_end": "2025-09-23", "checked_at": "...", "checked": 148, "planted": 97, "field_verify": 51, "reasons": [ { "code": "no_canopy_closure", "label": "No canopy closure (C3)", "count": 19 } ], "fetched_from_gee": 140, "from_cache": 0 }, "results": [ { "farm_id": 5, "status": "planted", "reason_code": "all_conditions_met", "reason": "All 5 conditions met", "t0_date": "2025-06-15", "tp_date": "2025-08-14", "vh_rise_db": 3.0, "ratio_drop_db": 1.9, "relative_orbit": 105, "scene_count": 13 } ] } }`
  - **Reason codes:** `all_conditions_met`, `no_boundary`, `too_small`, `too_few_scenes`, `no_flood_minimum` (C1), `crop_too_young`, `no_biomass_rise` (C2), `no_canopy_closure` (C3), `vv_vh_disagree` (C4), `outside_planting_window` (C5).
  - **Errors:** 404 unknown typhoon or no bulletins; 422 no affected farms; 503 Earth Engine needed but not configured; 502 Earth Engine failure.
* **GET `/api/sar/checks?typhoon_id=7`** — the stored result, in the same `{ summary, results }` shape without `fetched_from_gee`/`from_cache`. `summary` is `null` if the check has never been run for that typhoon.

### 9d. Field verification list (2026-10-13)

* **GET `/api/sar/field-verify?typhoon_id=7`**
  - **Description:** The typhoon's YELLOW `field_verify` farms, narrowed to farms eligible for insurance on that typhoon — meaning a computed `RiskAssessment` (`matrix_id` set, same rule as the PABS rows) under one of its exposure summaries. The SAR check alone covers every affected insured farm, which is a wider set (no signal/exposure/crop-stage/matrix rule). Read-only: unlike the PABS export it locks no policy.
  - **Response:** `{ "status": "success", "data": { "typhoon_id", "typhoon_name", "checked", "assessed", "checked_at", "rows": [ { farm_id, FARMER_NAME, FARMERID, FARMID, CIC_NO, PROVINCE, MUNICIPALITY, BARANGAY, AREA, TYPHOON_NAME, SAR_REASON } ] } }`
  - `checked: 0` means the planted check was never run for the typhoon; `assessed: 0` means Compute Assessments was never run. The farmer shown is the assessed policy's, falling back to the farm's.
* **GET `/api/sar/field-verify/export?typhoon_id=7`**
  - **Description:** The same list as a CSV download, headers `FARMER NAME, FARMERSID, FARMID, CIC NO, PROVINCE, MUNICIPALITY, BARANGAY, AREA, TYPHOON_NAME, SAR REASON`; AREA to 2 decimals.
  - **422** if the planted check has never been run for the typhoon.

## 10. Insurance (`/api/insurance`)

* **GET `/api/insurance/summary`**
  - **Description:** Counts policies currently within their effectivity/expiry window (inclusive) **and** with `is_used = false` (2026-10-12, per Fabio: a policy marked used when an assessment gives it a payout no longer counts as active) against the total policy count. Backs the Main Dashboard's "Active Insurance" card.
  - **Response:** `{ "status": "success", "active_count": 412, "total_count": 1113 }`
* **GET `/api/insurance/usage`**
  - **Query:** `typhoon_id`, `insurance_records_id` (both optional).
  - **Description:** Per-typhoon insurance usage status from `tbl_insurance_usage` (see `AssessmentService._sync_insurance_usage`). Without `typhoon_id`, returns every typhoon a policy has been assessed against — the same policy can be used for one typhoon and unused for another, tracked independently, so callers that want "is it used right now" must scope to a typhoon.
  - **Response:** `{ "status": "success", "data": [ { usage_id, insurance_records_id, typhoon_id, policy_no, farmer_id, farmer_name, is_used, assessment_id, marked_at, finalized_at } ] }`, newest `marked_at` first. `finalized_at` is set once the final PABS CSV export locks the usage.

## 10a. Admin Settings (`/api/settings`) — 2026-10-22

* **GET `/api/settings`** (any signed-in user)
  - **Response:** `{ "status": "success", "data": { "coverage_rate_per_ha": 25000, "coverage_rate_min": 1000, "coverage_rate_max": 100000, "auto_backup_enabled": true } }`
* **PUT `/api/settings/coverage-rate`** (admin)
  - **Body:** `{ "coverage_rate_per_ha": 30000 }`. **400** outside ₱1,000–100,000.
  - The RSBSA rate is the **default** Amount of Cover: at CSV upload, a record with a blank or zero `AmountofCover` gets `rate × area_size`. CSV values always win, and records already on file are not changed.
* **PUT `/api/settings/auto-backup`** (admin)
  - **Body:** `{ "enabled": false }`. Toggles the nightly 23:00 PHT backup.
* **GET `/api/settings/matrices`** (admin, read-only)
  - **Response:** `{ "data": { "recsap": [ { crop_stage_no, crop_stage, wind_signal_tcws, exposure_hours, estimated_yield_loss } ], "indemnity": [ { crop_stage_group, yield_loss_min, yield_loss_max, indemnity_factor } ] } }`
  - Active rows only. The matrices are changed only by migration.

## 10b. Database Backup & Archive (`/api/archives`, `/api/backups`) — 2026-10-22

Archives live in a **separate, read-only database** (`backend/archive_schema.sql`). Every archive endpoint answers **503** if `ARCHIVE_DATABASE_URL` / `ARCHIVE_WRITER_DATABASE_URL` are unset.

* **GET `/api/archives/eligibility`** (any signed-in user)
  - **Response:** `{ "data": { eligible, reason, eligible_at, clear_after_days: 7, counts: { farmers, farms, policies, assessments }, typhoons: [ { typhoon_id, name, year, last_bulletin_at, clear_after } ], label, archive_configured, confirm_word: "CLEAR" } }`
  - Eligible only when all of these hold:
    - there is live data
    - at least one typhoon was assessed, locked or SAR-checked against it
    - now ≥ every such typhoon's last bulletin + 7 days
* **POST `/api/archives`** (any signed-in user: Admin or GIS Specialist)
  - **Body:** `{ "confirm": "CLEAR" }`
  - Runs a safety `pg_dump` (sent to Google Drive), then copies every uploaded PABS record and polygon into the archive, verifies the counts, and deletes them from live.
  - Typhoons, bulletins, signals, exposure summaries and boundaries are copied but kept live.
  - **Errors:**
    - **400:** not eligible, wrong confirmation, or the dump/copy failed. Nothing is deleted.
    - **409:** another archive is already running.
    - **503:** the archive database is not configured.
  - **Response:** `{ "data": { archive_id, label, row_counts: { arc_farms: 1180, ... }, record_count, dump_file_name, gdrive_uploaded, gdrive_error } }`
* **GET `/api/archives/typhoons`** (any signed-in user)
  - **Response:** `{ "data": [ { typhoon_id, name, year, archive_id, label, archived_at } ] }`, newest archive per typhoon.
  - Returns `[]` when the archive is not configured.
  - Assessment & Reporting uses it to tag archived typhoons.
* **GET `/api/archives/typhoon/{typhoon_id}/pabs-rows`** (any signed-in user, read-only)
  - **Response:** `{ "data": { archive_id, label, archived_at, rows: [...] } }`. The rows have the same shape as `GET /api/assessments/pabs-summary`.
  - **404** if the typhoon was never archived.
* **GET `/api/archives`** (admin)
  - Lists `{ archive_id, label, typhoons, archived_at, archived_by_name, row_counts, record_count, dump_file_name, gdrive_file_id }`, newest first.
* **GET `/api/archives/{id}/records?q=&page=1&page_size=50`** (admin)
  - **Response:** `{ total, page, page_size, rows: [ { farmer_name, farmers_id, farm_reference, province, municipality, barangay, area_size, policy_no, amount_cover, typhoon_name, typhoon_year, wind_signal, crop_stage, indemnity_factor, final_indemnity_payment, ... } ] }`
  - One row per policy × computed assessment.
* **GET `/api/archives/{id}/farms?bbox=w,s,e,n`** (admin)
  - Returns a GeoJSON FeatureCollection of archived farm polygons with `total_payout`, plus `truncated` (capped at 5,000) and `extent`.
* **GET `/api/archives/{id}/exposure`** (admin)
  - Returns GeoJSON: exposure-area municipality outlines (`kind: "exposure"`, `max_signal_level`) and typhoon tracks (`kind: "track"`).
* **GET `/api/archives/{id}/export`** (admin)
  - CSV of every records row. Logged to the Activity Log.
* **GET `/api/backups`** (admin)
  - **Response:** `{ backups: [ { backup_id, kind, file_name, size_bytes, status, error, gdrive_uploaded, gdrive_error, created_at, file_available } ], last_backup, stored_count, gdrive_configured, archive_configured }`
* **POST `/api/backups`** (admin)
  - Runs `pg_dump -Fc` now. **500** if pg_dump fails. A Drive upload failure is reported, not raised.
* **GET `/api/backups/{id}/download`** (admin)
  - The `.dump` file. **404** if it is no longer on the server. Logged.
* **Restore is not offered in-app.** It stays a manual `pg_restore`, and archives are never restored into live.

## 11. Unauthenticated utility endpoints

* **GET `/`** — `{"message": "Welcome to the AgriSureGIS Backend!"}`
* **GET `/api/test-db`** — counts `tbl_farms` through SQLAlchemy to prove the PostGIS connection works. `{"status": "success", "message": "...", "total_farms_found": 1113}`, or **500** with the connection error. A development aid; the frontend doesn't call it.

## 12. Not implemented

Things the UI or older docs may imply, but which have **no backend endpoint**:

- **Database restore.** Backups and archiving are real since 2026-10-22 (§10b). Restoring a dump stays Fabio's own `pg_restore`, run by hand.
- **Editing the PCIC matrices.** They are shown read-only (§10a) and change only by migration. The assessment still reads `amount_cover` off each `tbl_insurance_records` row; the coverage-rate setting only fills in a blank AC at upload time.
- **GeoServer layers.** WMS/WFS layers go from GeoServer to the browser (through the Vite dev proxy), not through FastAPI — see `.claude/GEOSERVER_SETUP.md`.
