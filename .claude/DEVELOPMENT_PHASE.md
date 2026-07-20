# AgriSureGIS - Development Phase

## Phase 1: Foundation & Infrastructure (Completed)
* **Scope:** Database schema initialization, CSV/GPX seeder development, baseline FastAPI API setup, and frontend shell layout integration.
* **Milestones:**
  - PostGIS database set up and `init_schema.sql` executed.
  - `seed_database.py` built for PABS/insurance records.
  - Baseline REST endpoints implemented (`/api/health`, `/api/upload/csv`).
  - Multi-module dashboard UI created (Home, Spatial, Assessment, Settings).

## Phase 2: Bulletins & Scraping Module (Completed)
* **Scope:** Real-time PAGASA bulletin retrieval and PDF text/coordinate parsing.
* **Milestones:**
  - BeautifulSoup web scraper built for PAGASA Tropical Cyclone Bulletin PDFs.
  - `pdfplumber` integrated to extract TCWS levels, meteorological center coordinates, and affected municipalities.
  - Test cases written for bulletin normalization and coordinate parsing.

## Phase 3: Spatial Processing & Data Ingestion (Current)
* **Scope:** GPX boundary parsing, GeoJSON mapping, geoprocessing of storm trajectories, and exposure calculations.
* **Milestones:**
  - GPX parser using `gpxpy`, converting track points to Polygon geometries.
  - GeoPandas/Shapely routines to calculate hours municipal boundaries were within a given TCWS signal radius.
  - Leaflet JS map integration on the frontend to visualize farm boundaries and typhoon path overlaps.

## Phase 4: Parametric Payouts & Export Module (Upcoming)
* **Scope:** Indemnity calculations and CSV report export.
* **Milestones:**
  - Parametric payout engine applying `I = (AC / 1000) * IF * Area`.
  - Final payout report generated in the legacy PCIC CSV format.
  - System testing and manual validation audits.

## Phase 5: Deployment & Handover
* **Scope:** On-premise rollout to PCIC Region X and operational handover.
* **Milestones:**
  - Deployment to the on-premise server within the PCIC Region X LAN.
  - User account and permission setup for GIS Specialist and System Administrator roles.
  - End-user training and documentation handover.
