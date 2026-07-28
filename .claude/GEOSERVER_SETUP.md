# AgriSureGIS — GeoServer Setup & Layer Publishing Runbook

GeoServer is the 2nd-tier spatial layer server shown in `docs/system architecture.png`,
sitting between the Presentation Layer (React/Leaflet) and the Database Layer
(PostgreSQL/PostGIS). It serves map layers directly to the frontend via WMS/WFS,
separate from FastAPI's business-logic API.

This is infrastructure setup on Fabio's local/on-premise machine — per
`.claude/CLAUDE.md`'s Database/venv execution rules, every command below must be
run by Fabio himself, one step at a time.

---

## 1. Prerequisites

- A JDK (11 or 17) installed and on `PATH`.
- The existing `agrisure_db` PostgreSQL/PostGIS database already running and reachable.
- `tbl_admin_boundaries.boundary_geom` column applied (see `backend/init_schema.sql`)
  and backfilled (see step 4 below) — needed before the boundary layer can be published.

## 2. Install GeoServer (native, no Docker)

1. Download the "Platform Independent Binary" release from the official GeoServer
   downloads page for the version matching your PostGIS/JDK (GeoServer 2.24.x or 2.25.x
   is compatible with PostGIS 3+).
2. Extract it somewhere stable, e.g. `/opt/geoserver` (needs root) or a home directory
   path like `/home/fabio/geoserver-2.24.x-latest-bin` if you don't have root access.
3. Start it (bundles its own Jetty server, no separate servlet container needed):
   ```
   export GEOSERVER_HOME=/home/fabio/geoserver-2.24.x-latest-bin
   $GEOSERVER_HOME/bin/startup.sh
   ```
4. Confirm it's up: open `http://localhost:8080/geoserver/web` — default login is
   `admin` / `geoserver`. **Change this password immediately** under
   Security > Users/Groups/Roles in the admin UI.
5. (Optional, recommended for always-on serving) Set it up as a systemd service so it
   survives reboots, instead of running `startup.sh` manually each time.

## 3. Apply the schema change

`boundary_geom` (and its GIST index) is now part of `backend/init_schema.sql`. Re-apply
it against `agrisure_db` the same way you normally apply schema updates.

> **Note:** `init_schema.sql` starts with `DROP TABLE ... CASCADE` for every table, so
> re-running it wipes **all** data (farmers, farms, insurance records, assessments,
> bulletins, everything) — not just `tbl_admin_boundaries`. You'll need to reseed
> afterward (step 4). If you'd rather not wipe existing data, run this targeted
> `ALTER TABLE` against the live DB instead of re-applying the full file:
> ```sql
> ALTER TABLE tbl_admin_boundaries ADD COLUMN boundary_geom GEOMETRY(MultiPolygon, 4326);
> CREATE INDEX idx_admin_boundaries_boundary_geom ON tbl_admin_boundaries USING GIST(boundary_geom);
> ```

## 4. Reseed (if you re-ran the full schema) and backfill region boundary geometry

If you re-ran the full `init_schema.sql`, reseed first so `tbl_admin_boundaries` has
rows for the backfill to match against:
```
python seed_database.py
```

Then, from `backend/`, using your project venv:
```
python backfill_admin_boundary_geom.py
```
This reads `frontend/public/data/region10-boundaries.geojson` and populates
`boundary_geom` for every matching `(province, municipality)` in
`tbl_admin_boundaries`. It prints any geojson municipalities that had no matching
rows (municipalities with no seeded farms yet) — that's expected, not an error.

## 5. Create the workspace + PostGIS datastore

In the GeoServer admin UI:
1. **Data > Workspaces > Add new workspace**
   - Name: `agrisuregis`
   - Namespace URI: `http://agrisuregis.local` (placeholder, not publicly resolved)
2. **Data > Stores > Add new Store > PostGIS**
   - Workspace: `agrisuregis`
   - Data Source Name: `agrisure_db`
   - Connection params: same host/port/db/user/password as `backend/.env`'s
     `DATABASE_URL` (host `localhost`, port `5432`, database `agrisure_db`).

## 6. Publish the layers

Under the `agrisure_db` store, **Publish** these two tables:

| Table | Geometry column | Layer name | Purpose |
|---|---|---|---|
| `tbl_farms` | `location_geom` | `agrisuregis:tbl_farms` | Optional WMS reference overlay (frontend keeps its existing interactive farm layer from FastAPI — see step 7) |
| `tbl_admin_boundaries` | `boundary_geom` | `agrisuregis:tbl_admin_boundaries` | Replaces the static `region10-boundaries.geojson` bundled file as a live WFS source |

For each: in the "Publish" tab, click **Compute from data** and **Compute from
native bounds** to auto-fill the bounding box, then Save.

(Optional) Under the "Publishing" tab you can attach an SLD style for
`tbl_farms` matching the frontend's existing color scheme (`#1e3a5f` fill), but
this only affects the optional WMS overlay, not the interactive GeoJSON layer.

## 7. CORS — handled by the frontend dev proxy, not GeoServer

The browser blocks cross-origin `fetch` calls (frontend dev server on `:5173` calling
GeoServer on `:8080`) unless GeoServer sends CORS headers — visiting a GeoServer URL
directly in the browser address bar works regardless (page navigation isn't subject
to CORS), which can make this look fine until the frontend actually tries it.

**Do not edit GeoServer's `web.xml` to fix this.** The Jetty-bundled "Platform
Independent Binary" distribution ships a *Tomcat*-specific CORS filter
(`org.apache.catalina.filters.CorsFilter`) commented out in `web.xml` — its own
comment says "enable CORS in Tomcat," which is the wrong servlet container for this
Jetty-based install. Uncommenting it throws `ClassNotFoundException` and crashes the
whole webapp deployment (confirmed the hard way). If `web.xml` ever gets edited by
mistake, restore a clean copy from the original downloaded archive rather than
hand-patching the comment markers back — malformed XML there takes the whole
GeoServer instance down, including the admin UI.

Instead, `frontend/vite.config.ts` proxies `/geoserver-proxy/*` to
`VITE_GEOSERVER_URL` server-side (see `server.proxy` in that file). Every GeoServer
request from `GISLeafletMap.tsx` goes through that same-origin proxy path, so the
browser never makes a genuinely cross-origin request and CORS never applies. This
only covers `npm run dev` — a production static build/reverse-proxy setup (not built
yet) will need its own equivalent (e.g. an nginx location block proxying `/geoserver`
to GeoServer, alongside whatever proxies `/api` to FastAPI).

## 8. Verify

- WMS capabilities: `http://localhost:8080/geoserver/agrisuregis/wms?service=WMS&version=1.3.0&request=GetCapabilities`
- WFS GetFeature test for boundaries (should return GeoJSON):
  ```
  http://localhost:8080/geoserver/agrisuregis/ows?service=WFS&version=2.0.0&request=GetFeature&typeName=agrisuregis:tbl_admin_boundaries&outputFormat=application/json
  ```
- Set `VITE_GEOSERVER_URL=http://localhost:8080/geoserver` in `frontend/.env`
  (see `.claude/ENV_GUIDE.md`) and restart the frontend dev server. The map should
  now load region boundaries from GeoServer (falling back to the static file if
  GeoServer is unreachable) and show a "GeoServer overlay" toggle for farm boundaries.

## Notes / current scope

- The wind-footprint overlay is **not** published through GeoServer — it's computed
  on the fly by `GeoPandas`/`Shapely` at request time, not a stored PostGIS geometry,
  so there's no table for GeoServer to publish it from.
- The typhoon-center marker is a single lat/lng point already returned by the
  bulletins API — not worth a dedicated GeoServer layer.
- `tbl_farms` publishing is additive only. The frontend's primary farm rendering
  (click-to-select, popups, per-farm styling) still comes from `GET /api/farms/`
  via FastAPI, unchanged, to avoid losing that interactivity (WMS returns raster
  tiles, not clickable features).
