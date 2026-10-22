# AgriSureGIS - Development Team

Structure last reconciled with `.claude/CLAUDE.md` on **2026-10-18**. `CLAUDE.md`'s
"Team at a Glance" is the authority; this file is the expanded roster.

## Core developers — equal owners of the whole system

Fabio and Cristian are the only two who write code in this repository. They own the
system equally: the areas below are **focus areas, not boundaries**, and either may
work anywhere in the codebase.

### Fabio Joseph Tugonon
* **Role:** Core Developer — Database Administrator & Backend
* **Focus areas:**
  - Database schema architecture, creation, and maintenance (Postgres + PostGIS).
  - Migrations, spatial indexing, query optimization, and geoprocessing logic at the DB level.
  - Data ingestion (CSV / GPX / GeoPackage) and the backend over it.
  - Database backup and recovery configurations.
* **Environment custodian:** `sudo`/`psql` access, DB superuser credentials, the
  project venv, the frontend `node_modules`, and GitHub remote authentication all
  live only in his environment — see `CLAUDE.md`'s execution rules.
* **Tooling:** Uses Claude Code as an AI pair-programming assistant for implementation, documentation, and workflow tasks in this repository.

### Cristian A. Aton
* **Role:** Core Developer — Backend logic & Frontend
* **Focus areas:**
  - Application architecture and API design (FastAPI).
  - Web scraping pipeline for PAGASA PDF bulletin parsing.
  - Assessment, exposure, SAR and payout logic.
  - Integration of Python GIS libraries (GeoPandas, Shapely, pyproj).
  - Frontend implementation (React + Leaflet).

## Supporting roles

These members do **not** implement the system.

### James Andrew B. Gayla
* **Role:** Frontend Design
* **Responsibilities:**
  - UI/UX design. [`ui-prototype/`](../ui-prototype/) is his, and it is the design
    source of truth that `CLAUDE.md`'s Scope Guard refers to — implement those
    layouts as closely as possible; don't redesign or invent screens.

### Albritch Benj S. Tragico
* **Role:** Documenter & System Analyst
* **Responsibilities:**
  - Documentation of the system.
  - Requirements gathering and specification for payout generation algorithms and export functionalities.
  - Process and workflow analysis to define system use cases and functional requirements.

### Karylle Anne Maagad
* **Role:** Technical Writer
* **Responsibilities:**
  - User-facing guides and onboarding materials for the platform.

> **Open question for Fabio (2026-10-18):** `CLAUDE.md`'s "Team at a Glance" lists
> only James and Albritch under supporting roles, so Karylle's current involvement
> is unclear, as is how her documentation scope divides from Albritch's. Her entry
> is kept here pending your confirmation rather than removed — correct or delete it
> as appropriate.
