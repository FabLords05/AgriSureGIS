# AgriSureGIS - Project Context

## Overview
AgriSureGIS is a WebGIS-based Typhoon Parametric Insurance Assessment platform developed for the Philippine Crop Insurance Corporation (PCIC) Regional Office X. 

The platform aims to modernize spatial data management and claim verification workflows. It eliminates fragmented "data silos" (localized CSV and GPX files in standalone desktop GIS) by centralizing farmer profiles, insurance policies, and farm lot boundaries into a localized spatial database. 

During typhoon disasters, the platform automates the extraction of meteorological data from PAGASA bulletins, overlays wind hazard footprints with insured farm boundaries, and computes estimated claim payouts instantly, reducing processing times from weeks to minutes.

## Technology Stack
- **Backend:** FastAPI (Python), PostgreSQL with PostGIS extension, SQLAlchemy ORM, GeoAlchemy2, GeoPandas, Shapely, pyproj, BeautifulSoup4 + httpx (PAGASA scraping), pdfplumber (bulletin PDFs), gpxpy (GPX tracks).
- **Auth:** PyJWT (stateless HS256 session tokens) + bcrypt password hashing. See `.claude/API_CONTRACT.md`'s Conventions.
- **Scheduling:** APScheduler, for the background PAGASA bulletin poll.
- **Remote sensing:** `earthengine-api` (Google Earth Engine), for Sentinel-1 SAR planted verification. Optional — unconfigured means the SAR endpoints return 503 and nothing else changes.
- **Caching (optional):** Redis, for the Farm Records page cache. Unset `REDIS_URL` makes caching a no-op.
- **Email (optional):** SMTP, for new-bulletin alerts to active users.
- **Spatial Layer Serving:** GeoServer, serving map layers (farm boundaries, administrative boundaries) via WMS/WFS between the Web-GIS Application Layer and the Presentation Layer. Optional — unset `VITE_GEOSERVER_URL` and the map falls back to a bundled static boundary file.
- **Frontend:** React + TypeScript (Vite), Leaflet JS / react-leaflet (map rendering), Tailwind CSS, Radix UI + MUI components, Recharts (dashboard charts). Installable as a PWA.
- **Deployment:** On-premise local server within PCIC Region X LAN (no public cloud dependency for data privacy). Currently running on a developer PC; public access during development goes through Tailscale Funnel + Caddy (`deploy/Caddyfile`) because the host sits behind CGNAT.

## User Roles
These two strings are the **only** roles the backend accepts (`ALLOWED_ROLES` in
`backend/app/api/users.py`); the UI prototype's wider dropdown had no backing
permission logic and is not implemented.

1. **GIS Specialist:**
   - Imports farmer profile CSVs, GPX farm boundary files, and the client's multi-farm GeoPackage exports.
   - Triggers the PAGASA bulletin parser (or uploads a bulletin PDF by hand when the portal is down).
   - Performs parametric damage assessments.
   - Runs the SAR planted check and exports the field-verification list.
   - Generates and exports payout-ready PCIC/PABS CSV reports.
2. **System Administrator (Fabio):**
   - Everything a GIS Specialist can do, plus the admin-only surfaces.
   - Configures user accounts and permissions (approve pending registrations, create/edit/activate/deactivate accounts, set per-account session timeouts).
   - Reviews the Activity Log.
   - Calibration of system parameters (e.g., the TCB polling interval).
   - Manages database backups and restores — **outside the app**: there is no backup endpoint, only `pg_dump`/`pg_restore` in Fabio's own terminal.

Role enforcement is server-side: `require_admin` guards the admin routes, so an
admin-only surface is not merely hidden in the UI.

## Core Features & Logic
- **Parametric Indemnity Formula:** `I = (AC / 1000) * IF`
  - `I` = Indemnity Payout (PHP)
  - `AC` = Amount of Cover. Read **per policy** from `tbl_insurance_records.amount_cover` as ingested from the PCIC CSV — *not* a global value configured in Settings (no endpoint persists one).
  - `IF` = Indemnity Factor, from a **two-step** lookup: `tbl_recsap_matrix` gives estimated yield loss % for (crop stage, TCWS signal, exposure hours), then `tbl_indemnity_factor_matrix` gives the factor for (yield-loss bracket, PCIC crop-stage group).
  - Per PCIC (the source of this formula), farm area is not a separate factor. An earlier `* Area` variant was corrected on 2026-07-23; treat any doc still showing it as wrong.
  - Eligibility gate: wind signal >= 2, exposure >= 6 hours (bucketed down to 6/12/24), and a crop stage in Booting/Flowering/Maturity.
  - `estimated_damage` is tracked separately as `AC * yield_loss% / 100`.
- **PAGASA Bulletins:** Automatically scraped and parsed. Tracks TCWS wind speeds:
  - Signal 2: 62-88 km/h
  - Signal 3: 89-117 km/h
  - Signal 4: 118-184 km/h
  - Signal 5: 185 km/h+
  - Polled on a background schedule (APScheduler), with a manual "Parse Latest Bulletin" trigger and a manual PDF upload path for when the PAGASA portal is unreachable. Each newly parsed bulletin emails every active user, if SMTP is configured.
- **Insurance usage is tracked per typhoon.** An assessment marks a policy used/unused for *that* typhoon (`tbl_insurance_usage`), and the final PABS export locks it, so the same policy cannot be paid out twice across storms. A locked policy stops counting as "active insurance".
- **SAR planted verification (advisory only).** Sentinel-1 imagery via Google Earth Engine gives the Specialist a visual pre-event layer plus an automatic per-farm check that returns GREEN `planted` or YELLOW `field_verify` — never "not planted" on its own. Yellow farms can be exported as a field-verification list. **The SAR result is never read by the assessment engine or the payout export.** Method: `docs/SAR_ISPLANTED_METHOD.md`.
- **Access control.** Real credentials against `tbl_system_users`, signed session tokens, and server-side role enforcement. Self-registration creates a *pending* account an administrator must approve. Every login, logout and mutating API call is recorded in the Activity Log.
- **Exports.** Two CSV shapes: the legacy PCIC row layout with computed columns appended, and PCIC's exact PABS "final output" headers. Files name themselves after the typhoon and export time.\n