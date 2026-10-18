# AgriSureGIS - Master Development Context

## 1. System Overview
AgriSureGIS is a localized WebGIS platform built to automate typhoon parametric insurance assessments for rice crops in PCIC Region X (Northern Mindanao, Philippines).

Traditional insurance validation depends on physical inspections of damaged areas after a typhoon, which takes weeks and is logistically difficult. AgriSureGIS automates this by intersecting geographical farm polygons with typhoon wind footprint models and computing indemnities based on biological growth stages.

## 2. Three-Tier System Architecture
- **Presentation Layer:** React + TypeScript with Leaflet JS, styled with Tailwind CSS. Renders interactive maps showing farm boundaries (from GPX/GeoPackage surveys) and typhoon trajectories. Polygons are fetched per viewport (`GET /api/farms/geometry`), not loaded wholesale, so the browser never holds the full dataset. Installable as a PWA.
- **Web-GIS Application Layer:** FastAPI coordinates API endpoints, with GeoServer serving spatial layers (farm boundaries, administrative boundaries) to the Presentation Layer via WMS/WFS.
  - Uses `BeautifulSoup` + `httpx` to scrape new bulletins from PAGASA, on an APScheduler background poll.
  - Uses `pdfplumber` to extract typhoon metrics from bulletin PDFs.
  - Uses `GeoPandas` and `Shapely` to perform geometric intersections.
  - Uses `gpxpy` and a GeoPackage reader to turn field surveys into farm polygons.
  - Calls Google Earth Engine for Sentinel-1 SAR planted verification (optional).
  - Enforces authentication and roles itself (signed session tokens, `require_admin`), and records every mutating call to the Activity Log.
- **Database Layer:** Localized PostgreSQL database with the PostGIS extension, managed via SQLAlchemy and GeoAlchemy2. An optional Redis cache fronts the Farm Records listing; a `mv_farm_latest_insurance` materialized view keeps the "latest policy per farm" lookup to one indexed hit.

> **Note on the wind footprint.** Exposure is **not** computed by intersecting farm
> polygons with a drawn wind footprint. It is a `(province, municipality)` text join
> between parsed TCWS signal areas (`tbl_tcb_signals`) and administrative boundaries,
> so it is municipality-granular. Any doc describing a geometric footprint
> intersection is describing an intention, not the implementation.

## 3. Parametric Damage Calculations
The calculation engine operates strictly on the predefined PCIC Typhoon-Induced Strong Winds Matrix.
- **Indemnity Formula:** `I = (AC / 1000) * IF` — farm area is **not** a factor (`app/core/indemnity_calc.py`).
- **Yield Loss (YL) Matrices:** `tbl_recsap_matrix`, crossing exposure duration (6h, 12h, 24h) with the TCWS Signal Level (2 to 5) and the growth stage (Booting, Flowering, Maturity). Raw exposure hours are bucketed **down** to those brackets; under 6 hours yields no rule.
- **Indemnity Factor (IF) Lookup:** `tbl_indemnity_factor_matrix`, linking the YL% bracket (exclusive-lower, inclusive-upper) with PCIC's 5-group crop-stage taxonomy — `Early Vegetative | Late Vegetative | Reproductive | Late Reproductive | Maturity`. This is a **separate taxonomy** from `tbl_recsap_matrix`'s 3-value `crop_stage_no`, and the two are resolved independently (`app/services/crop_stage_resolver.py` → `tbl_crop_stage_mapping`), because neither is a function of the other: Milking and Flowering share `crop_stage_no` 2 while sitting in Late Reproductive and Reproductive respectively.
- **Advisory SAR check:** Sentinel-1 planted verification runs alongside the assessment but its verdict is **never** read by the calculation or the export.
- **Exporting:** Two shapes — the legacy PCIC row layout with computed columns appended, and PCIC's exact PABS "final output" headers. The final PABS export also locks each paid policy as used for that typhoon, so it cannot be claimed again for a later storm.\n