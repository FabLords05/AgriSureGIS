# Proposal: Add Municipal Boundary Geometry + Signal-to-Boundary FK

**Status:** Proposal for Fabio's review — nothing in this document has been applied to the schema. Per `CLAUDE.md`, any database structure modification must be proposed to Fabio and approved before implementation.

## Problem
Two related gaps have been flagged since the original Sprint 3 backend work (see `.claude/FUNCTION_CHANGES.md`, "Sprint 3 Backend: GPX Parser & Exposure Calculation" entry) and are reconfirmed by `docs/ERD.drawio.png`, which already shows both fields in the intended design:

1. **`tbl_admin_boundaries` has no geometry column.** There is no municipal/provincial boundary polygon stored anywhere in the database. This blocks any real "typhoon path crosses this municipality" map visualization — today the frontend can only show a typhoon's center point (from `tbl_tropical_cyclone_bulletins.center_geom`) and a plain-text list of affected municipality names, never an actual polygon overlay.
2. **`tbl_tcb_signals` has no `boundary_id` FK.** Signal-to-municipality matching (in `bulletin_parser.py`'s `save_bulletin_to_db()` and `exposure_calculator.py`'s `compute_for_typhoon()`) currently works by comparing `TcbSignal.area_name` (free text) against `AdminBoundary.municipality` (free text) — fragile: it breaks on typos, alternate spellings, or two provinces sharing a municipality name.

## Proposed change
1. Add `tbl_admin_boundaries.geom` — a `Geometry(POLYGON, srid=4326)` column (nullable, since boundary polygons would need to be sourced/imported separately — e.g. from PSGC/PhilGIS shapefiles — this proposal only adds the column, not the data).
2. Add `tbl_tcb_signals.boundary_id` — `INTEGER REFERENCES tbl_admin_boundaries(boundary_id) ON DELETE SET NULL`. `bulletin_parser.py`'s `save_bulletin_to_db()` would populate this directly (it already loads the matching `AdminBoundary` row via the same lookup used to set `area_name` today — this just also stores the ID), replacing the text-matching in `exposure_calculator.py` with a plain join.

## What this unblocks
- A real municipal-boundary polygon layer on the Leaflet map.
- Robust signal-to-municipality joins (no more string matching).
- A real "does the typhoon's affected area intersect this municipality's boundary" check, if ever needed.

## What this does NOT include
- No typhoon-track polyline or TCWS signal-radius geometry — PAGASA publishes named affected-area lists per bulletin, not radii, so that reinterpretation (documented in `exposure_calculator.py`'s docstring) stands regardless of this proposal.
- No data backfill — sourcing real boundary polygons (PSGC/PhilGIS or similar) is a separate follow-up once the column exists.

## Files that would need updating if approved
- `backend/init_schema.sql` — add both columns/constraints.
- `backend/app/models/models.py` — add `geom` to `AdminBoundary`, `boundary_id` to `TcbSignal`.
- `backend/app/services/bulletin_parser.py` — set `boundary_id` when creating each `TcbSignal`.
- `backend/app/services/exposure_calculator.py` — join on `boundary_id` instead of matching `area_name` against `municipality` text.
