# AgriSureGIS - Team Responsibilities

Reconciled with `.claude/CLAUDE.md` and `.claude/TEAM.md` on **2026-10-18**.

## Roles & Areas of Ownership

### Core developers — equal owners of the whole system
Fabio and Cristian are the only two who write code here. The areas below are
**focus areas, not boundaries**; either works anywhere in the codebase.

* **Fabio Joseph Tugonon (Core Developer — Database Administrator & Backend):**
  Database schema architecture, creation and maintenance (Postgres + PostGIS);
  migrations, spatial indexing, query optimization and DB-level geoprocessing;
  data ingestion (CSV / GPX / GeoPackage) and the backend over it; backup and
  recovery.
  * Example branches: `fabio/db/*`, `fabio/backend/*`, `fabio/frontend/*`
* **Cristian A. Aton (Core Developer — Backend logic & Frontend):** Application
  architecture and API design (FastAPI); the PAGASA scraping/parsing pipeline;
  assessment, exposure, SAR and payout logic; Python GIS library integration
  (GeoPandas, Shapely, pyproj); frontend implementation.
  * Example branches: `cristian/backend/*`, `cristian/frontend/*`

### Supporting roles — they do not implement the system
* **James Andrew B. Gayla (Frontend Design):** UI/UX design. `ui-prototype/` is his
  and is the design source of truth for the Scope Guard in `CLAUDE.md`.
  * Example branches: `james/design/*`
* **Albritch Benj S. Tragico (Documenter & System Analyst):** Documentation of the
  system; requirements gathering and specification for payout generation and export
  functionality; process/workflow analysis defining use cases and functional
  requirements.
  * Example branches: `albritch/analysis/*`, `albritch/docs/*`
* **Karylle Anne Maagad (Technical Writer):** User-facing guides and onboarding
  materials. *(Current involvement pending Fabio's confirmation — see the note in
  `TEAM.md`. `GITHUB_WORKFLOW.md`'s branch examples now route docs branches to
  `albritch/docs/*`, so she has no branch prefix of her own.)*

## Review and Merging Workflow
- Any database structure modifications must be proposed to Fabio.
- All code changes must go through a pull request and get approved by at least one
  other developer before merging into `develop`. `main` only receives merges from
  `develop` at a release point (see `.claude/GITHUB_WORKFLOW.md` Phase 7) — it stays
  frozen otherwise.

> **Practice note (2026-10-18).** The git history shows a number of commits pushed
> straight to `develop`, each marked as being on Fabio's or Cristian's explicit
> instruction (e.g. "skip-PR, per explicit direction"). With two core developers who
> own the system equally, the PR-review requirement above is treated as the default
> rather than an absolute. The documented process is unchanged; this note exists so
> the history doesn't read as a violation of it. If the rule should actually be
> relaxed in writing, say so and it will be edited rather than foot-noted.
