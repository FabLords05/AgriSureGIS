# AgriSureGIS - Team Responsibilities

## Roles & Areas of Ownership
* **Fabio Joseph Tugonon (Database Administrator):** Database schema architecture, creation, and maintenance (Postgres + PostGIS); spatial indexing, query optimization, and geoprocessing logic at the DB level; database backup and recovery configurations.
* **Cristian A. Aton (Backend Developer):** Application architecture and API design (FastAPI); web scraping pipeline for PAGASA PDF bulletin parsing; integration of Python GIS libraries (GeoPandas, Shapely, pyproj).
* **James Andrew B. Gayla (Frontend Developer):** Frontend shell development and mapping component integration; map UI rendering using Leaflet JS; interactive dashboard layouts and data visualization screens.
* **Karylle Anne Maagad (Technical Writer):** Documentation of system architecture, API contracts, and setup/workflow guides; maintaining the development plan, environment guide, and project context references; user-facing guides and onboarding materials for the platform.
* **Albritch Benj S. Tragico (System Analyst):** Requirements gathering and specification for payout generation algorithms and export functionalities; process and workflow analysis to define system use cases and functional requirements.

## Review and Merging Workflow
- Any database structure modifications must be proposed to Fabio.
- All code changes must go through a pull request and get approved by at least one other developer before merging into the `develop` branch.\n