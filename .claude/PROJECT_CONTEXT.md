# AgriSureGIS - Project Context

## Overview
AgriSureGIS is a WebGIS-based Typhoon Parametric Insurance Assessment platform developed for the Philippine Crop Insurance Corporation (PCIC) Regional Office X. 

The platform aims to modernize spatial data management and claim verification workflows. It eliminates fragmented "data silos" (localized CSV and GPX files in standalone desktop GIS) by centralizing farmer profiles, insurance policies, and farm lot boundaries into a localized spatial database. 

During typhoon disasters, the platform automates the extraction of meteorological data from PAGASA bulletins, overlays wind hazard footprints with insured farm boundaries, and computes estimated claim payouts instantly, reducing processing times from weeks to minutes.

## Technology Stack
- **Backend:** FastAPI (Python), PostgreSQL with PostGIS extension, SQLAlchemy ORM, GeoAlchemy2, GeoPandas, Shapely, pyproj, BeautifulSoup4 (PAGASA PDF scraping), pdfplumber.
- **Frontend:** React (Vite), Leaflet JS (map rendering), Tailwind CSS.
- **Deployment:** On-premise local server within PCIC Region X LAN (no public cloud dependency for data privacy).

## User Roles
1. **GIS Specialist:**
   - Imports farmer profile CSVs and GPX farm boundary files.
   - Triggers the PAGASA bulletin parser.
   - Performs parametric damage assessments.
   - Generates and exports payout-ready CSV reports.
2. **System Administrator (Fabio):**
   - Configures user accounts and permissions.
   - Calibration of system parameters (e.g., amount of cover, wind signal threshold rates).
   - Manages database backups and restores.

## Core Features & Logic
- **Parametric Indemnity Formula:** `I = (AC / 1000) * IF * Area`
  - `I` = Indemnity Payout (PHP)
  - `AC` = Amount of Cover per hectare (configured in Settings, e.g., 25,000 PHP)
  - `IF` = Indemnity Factor based on Yield Loss % (booting, flowering, maturity growth stages crossed with wind signals 2 to 5 and exposure duration).
  - `Area` = Land size in hectares.
- **PAGASA Bulletins:** Automatically scraped and parsed. Tracks TCWS wind speeds:
  - Signal 2: 62-88 km/h
  - Signal 3: 89-117 km/h
  - Signal 4: 118-184 km/h
  - Signal 5: 185 km/h+\n