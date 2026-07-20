# AgriSureGIS - Master Development Context

## 1. System Overview
AgriSureGIS is a localized WebGIS platform built to automate typhoon parametric insurance assessments for rice crops in PCIC Region X (Northern Mindanao, Philippines).

Traditional insurance validation depends on physical inspections of damaged areas after a typhoon, which takes weeks and is logistically difficult. AgriSureGIS automates this by intersecting geographical farm polygons with typhoon wind footprint models and computing indemnities based on biological growth stages.

## 2. Three-Tier System Architecture
- **Presentation Layer:** Developed using React and Leaflet JS, styled with Tailwind CSS. Renders interactive maps showing farm boundaries (from GPX files), typhoon trajectories, and wind footprint layers.
- **Web-GIS Application Layer:** FastAPI coordinates API endpoints.
  - Uses `BeautifulSoup` to scrape new bulletins from PAGASA.
  - Uses `pdfplumber` to extract typhoon metrics from bulletin PDFs.
  - Uses `GeoPandas` and `Shapely` to perform geometric intersections.
- **Database Layer:** Localized PostgreSQL database with the PostGIS extension, managed via SQLAlchemy and GeoAlchemy2.

## 3. Parametric Damage Calculations
The calculation engine operates strictly on the predefined PCIC Typhoon-Induced Strong Winds Matrix.
- **Indemnity Formula:** `I = (AC / 1000) * IF * Area`
- **Yield Loss (YL) Matrices:** Calculated by crossing exposure duration (6h, 12h, 24h) with the TCWS Signal Level (2 to 5) and the growth stage (Booting, Flowering, Maturity).
- **Indemnity Factor (IF) Lookup:** Determined by linking the calculated YL% with the crop's vegetative/reproductive/maturity stage.
- **Exporting:** The final assessment yields a payout report extending the original PCIC formatting with parsed parameters and final indemnity payout calculations.\n