# AgriSureGIS - API Contract

**Base URL:** `/api/`

## 1. Authentication
* **POST `/api/auth/login/`** - Authenticate user and return JWT tokens.
* **POST `/api/auth/logout/`** - Blacklist JWT refresh token.

## 2. Spatial Data & Profile Ingestion
* **POST `/api/upload/csv`**
  - **Description:** Bulk upload farmer and policy records.
  - **Payload:** Multipart Form (CSV file).
* **POST `/api/upload/gpx`**
  - **Description:** Upload GPX track files to build farm boundary geometries.
  - **Payload:** Multipart Form (GPX file, `farmer_id`, `farm_id`).

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