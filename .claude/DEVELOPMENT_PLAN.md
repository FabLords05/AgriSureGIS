# AgriSureGIS - Development Plan

This is the single development-plan file. It merges the former
`DEVELOPMENT_PHASE.md` (deleted 2026-10-18) into this one — the two had drifted
into near-duplicates that disagreed with each other on the indemnity formula.

Status last reconciled against the code on **2026-10-18**, by reading
`backend/app/`, `backend/tests/`, `frontend/src/` and `.claude/FUNCTION_CHANGES.md`.

> **On sprint numbers.** The four sprints below are the *original* plan. The
> sprint pointer is no longer reliable: changelog entries since 2026-10-09 are
> tagged "Sprint 3", yet Sprint 4's deliverables shipped, and a large body of
> work (authentication, user management, activity log, SAR/Earth Engine, PWA,
> email alerts) belongs to no sprint at all. **Do not treat any sprint as "the
> current one" without asking Fabio.** Judge what is done from the per-task
> status markers here and from `FUNCTION_CHANGES.md`, which is kept current.

---

## Sprint 1: Foundation & Infrastructure — Done
* **Objectives:** Database schema initialization, CSV/GPX seeder development, baseline FastAPI API setup, and frontend shell layout integration.
* **Tasks:**
  - Set up the PostGIS database and execute `init_schema.sql`. **[Done]**
  - Develop `seed_database.py` for PABS/insurance records. **[Done]** — joined since by `seed_admin_boundaries.py`, `seed_system_users.py`, `seed_active_insurance.py` and `seed_all.py`.
  - Implement baseline REST endpoints in FastAPI. **[Done]** — the actual endpoints are `GET /` and `GET /api/test-db` (there is no `/api/health`), plus `POST /api/upload/csv`.
  - Create the multi-module dashboard UI. **[Done]** — the four live modules are **Monitoring & Extraction**, **Spatial Analysis & Import**, **Assessment & Reporting** and **Calibration & Settings** (see `frontend/src/app/components/DashboardLayout.tsx`).

## Sprint 2: Bulletins & Scraping Module — Done
* **Objectives:** Real-time PAGASA bulletin retrieval and PDF text/coordinate parsing.
* **Tasks:**
  - Build the PAGASA Tropical Cyclone Bulletin PDF scraper. **[Done]** — `app/services/bulletin_parser.py`, using `httpx` + `BeautifulSoup`, against a hardcoded `PAGASA_INDEX_URL`.
  - Integrate `pdfplumber` to extract TCWS levels, meteorological center coordinates, and affected municipalities. **[Done]**
  - Write test cases for bulletin normalization and coordinate parsing. **[Done]** — `backend/tests/test_bulletin_parser.py`.
  - *Added beyond the original scope:* `app/services/pagasa_status_scraper.py` syncs which typhoons PAGASA still lists as active, and an APScheduler job polls for new bulletins on a fixed interval (`app/core/scheduler.py`).

## Sprint 3: Spatial Processing & Data Ingestion — Done
* **Objectives:** GPX boundary parser, GeoJSON mapping, geoprocessing of storm trajectories, and exposure calculations.
* **Tasks:**
  - Create the GPX parser using `gpxpy`, converting track points to Polygon geometries. **[Done]** — `app/services/gpx_parser.py`, plus `app/services/gpkg_parser.py` for the client's real multi-farm GeoPackage format (added 2026-10-08) and `app/services/gpx_farmer_matcher.py` for filename/attribute-based farm matching.
  - Implement GeoPandas/Shapely routines to calculate how many hours municipal boundaries were within a given TCWS signal radius. **[Done]** — `app/services/exposure_calculator.py`, writing `tbl_area_exposure_summary`.
  - Integrate Leaflet JS maps on the frontend to visualize farm boundaries and typhoon path overlaps. **[Done]** — `GISLeafletMap.tsx` (viewport-culled polygons from `GET /api/farms/geometry`, optional GeoServer WMS/WFS overlays) and `TyphoonTrackLayer.tsx` (track overlay from `GET /api/typhoons/{id}/track`).

## Sprint 4: Parametric Payouts & Export Module — Mostly done
* **Objectives:** Indemnity calculations and CSV report export.
* **Tasks:**
  - Build the parametric payout engine applying **`I = (AC / 1000) * IF`**. **[Done]** — `app/core/indemnity_calc.py` (`ParametricAssessment.calculate_final_payout`) and `app/services/assessment_service.py`.
    - **Farm area is not a factor.** An earlier `* Area` variant appeared in some docs; it was corrected with Fabio on 2026-07-23 and is wrong. See `PROJECT_CONTEXT.md`.
    - The lookup is two-step: `tbl_recsap_matrix` for yield-loss %, then `tbl_indemnity_factor_matrix` for the indemnity factor, bracketed by yield loss and PCIC crop-stage group. Exposure hours are bucketed down to 6/12/24.
    - Crop stage and PCIC stage group are resolved independently by `app/services/crop_stage_resolver.py` against `tbl_crop_stage_mapping` (2026-10-09).
  - Generate the final payout report in the legacy PCIC CSV format. **[Done]** — `GET /api/assessments/export` (legacy layout plus computed columns) and `GET /api/assessments/pabs-summary` + `POST /api/assessments/export-pabs` (PCIC's exact final-output headers; the POST also locks exported policies as used).
  - System testing and manual validation audits. **[Partly done]** — 22 pytest modules under `backend/tests/`. End-to-end manual validation against real PCIC figures is still outstanding.

## Beyond the original plan — shipped, unplanned

Significant work that no sprint above covers. Listed so nobody reads a sprint
list and concludes a feature doesn't exist.

| Area | What exists |
|---|---|
| **Authentication** | Real JWT session tokens (HS256, `JWT_SECRET_KEY`), bcrypt password hashing, router-level `get_current_user` on every protected route, `require_admin` for admin routes. `app/core/security.py`. |
| **User management** | Public self-registration (pending approval), admin create/edit/activate/deactivate, self-service Account Settings, per-account session timeout. `app/api/users.py`. |
| **Activity log** | Middleware records every mutating request plus login/logout to `tbl_activity_log`, with human-readable summaries; admin-only viewer. `app/api/activity_log.py`. |
| **Insurance usage tracking** | `tbl_insurance_usage` marks a policy used/unused **per typhoon**; the final PABS export locks it (`finalized_at`) so no later typhoon reuses it. |
| **SAR planted verification** | Sentinel-1 via Google Earth Engine: visual VV/VH layer, an automatic green/yellow planted check with a per-scene observation cache, and a field-verification CSV export. `app/services/gee_sar_service.py`, `app/services/sar_planted_classifier.py`, `docs/SAR_ISPLANTED_METHOD.md`. Never read by the assessment or the export. |
| **Monitoring dashboard** | Typhoon progress strip (`GET /api/typhoons/{id}/progress`), System Status panel (`GET /api/system/status`), server-side dashboard aggregates (`GET /api/assessments/summary`). |
| **Email alerts** | New-TCB notifications over SMTP to every active user, fired by the scheduled poll, the manual parse, and the manual PDF upload. `app/services/email_alert_service.py`. |
| **Ingestion at scale** | Asynchronous CSV upload jobs with progress polling, up-front wrong-file rejection, per-row SAVEPOINTs, keyset pagination on Farm Records, a `mv_farm_latest_insurance` materialized view, and an optional Redis page cache. |
| **PWA** | Installable app with a post-login install prompt. |
| **Deployment** | Public access via Tailscale Funnel + Caddy (`deploy/Caddyfile`), since the host PC sits behind CGNAT. |

## Deployment & Handover — Upcoming
* **Scope:** On-premise rollout to PCIC Region X and operational handover.
* **Milestones:**
  - Deploy to the on-premise server within the PCIC Region X LAN. *(Currently running on a developer PC reachable over Tailscale, not yet on PCIC hardware.)*
  - Set up user accounts and permissions for the GIS Specialist and System Administrator roles. *(The mechanism exists; the real accounts don't.)*
  - End-user training and documentation handover.

## Known gaps

- **Database restore** is not in-app. Backups (`pg_dump` → Google Drive) and Archive & Clear (into the read-only `agrisure_archive` DB) are real as of 2026-10-22. Restoring a dump is Fabio's manual `pg_restore`.
- **`panicle initiation/booting`** is deliberately left with `crop_stage_no = NULL` in `tbl_crop_stage_mapping`, so those rows ingest and never pay out. This waits on PCIC supplying a days-per-stage table, not on code. Do **not** hard-code a day threshold without PCIC confirming it (day 66 was floated and explicitly rejected as a guess). The row's `notes` column says this too; enabling it is one `UPDATE`.
- **`PAGASA_SCRAPE_URL`** is in `.env.example` and `ENV_GUIDE.md` but nothing reads it — the index URL is hardcoded in `bulletin_parser.py`.
- **The `/api/bulletins/settings` polling interval** is persisted and reschedulable, but app startup uses `scheduler.FIXED_POLL_INTERVAL_MINUTES` instead.
- **Response envelopes are inconsistent** across endpoints (see `API_CONTRACT.md`'s Conventions).
