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

## 3. PAGASA Bulletin Monitoring
* **GET `/api/bulletins/`** - List all parsed tropical cyclone bulletins.
* **POST `/api/bulletins/parse`**
  - **Description:** Trigger scraper to check PAGASA portal, download PDF, and parse details.
  - **Response:** `{ "status": "success", "bulletin_id": 12, "typhoon_name": "Leon" }`

## 4. Parametric Assessments
* **POST `/api/assessments/calculate`**
  - **Description:** Compute exposure hours, yield loss, and claim payouts for all active policies in the typhoon-affected area.
  - **Payload:** `{ "typhoon_id": 1, "bulletin_id": 12 }`
* **GET `/api/assessments/`** - Search and filter calculated risk assessments.
* **GET `/api/assessments/export`**
  - **Description:** Download payout-ready PCIC-formatted CSV file.\n