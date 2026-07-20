# AgriSureGIS - Development Plan

## Sprint 1: Foundation & Infrastructure (Completed)
* **Objectives:** Database schema initialization, CSV/GPX seeder development, baseline FastAPI API setup, and frontend shell layout integration.
* **Tasks:**
  - Setup PostGIS database and execute `init_schema.sql`. [Done]
  - Develop `seed_database.py` for PABS/insurance records. [Done]
  - Implement basic REST endpoints in FastAPI (`/api/health`, `/api/upload/csv`). [Done]
  - Create the multi-module dashboard UI (Home, Spatial, Assessment, Settings). [Done]

## Sprint 2: Bulletins & Scraping Module (Completed)
* **Objectives:** Real-time PAGASA bulletin retrieval and PDF text/coordinate parsing.
* **Tasks:**
  - Build BeautifulSoup web scraper for PAGASA Tropical Cyclone Bulletin PDFs. [Done]
  - Integrate `pdfplumber` to extract TCWS levels, meteorological center coordinates, and affected municipalities. [Done]
  - Write test cases for bulletin normalization and coordinate parsing. [Done]

## Sprint 3: Spatial Processing & Data Ingestion (Current)
* **Objectives:** GPX boundary parser, GeoJSON mapping, geoprocessing of storm trajectories, and exposure calculations.
* **Tasks:**
  - Create the GPX parser utilizing `gpxpy`, converting track points to Polygon geometries.
  - Implement GeoPandas and Shapely routines to calculate how many hours municipal boundaries were within a specific TCWS signal radius.
  - Integrate Leaflet JS maps on the frontend to visualize farm boundaries and typhoon path overlaps.

## Sprint 4: Parametric Payouts & Export Module
* **Objectives:** Indemnity calculations and CSV report export.
* **Tasks:**
  - Build the parametric payout engine applying `I = (AC / 1000) * IF * Area`.
  - Generate the final payout report in the legacy PCIC CSV format.
  - System testing and manual validation audits.\n