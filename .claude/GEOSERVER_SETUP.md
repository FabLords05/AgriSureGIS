# AgriSureGIS — GeoServer Setup & Layer Publishing Runbook

GeoServer is the 2nd-tier spatial layer server shown in `docs/system architecture.png`,
sitting between the Presentation Layer (React/Leaflet) and the Database Layer
(PostgreSQL/PostGIS). It serves map layers directly to the frontend via WMS/WFS,
separate from FastAPI's business-logic API.

**GeoServer is optional.** With `VITE_GEOSERVER_URL` unset or unreachable, the map
falls back to the bundled static boundary file (`frontend/public/data/region10-boundaries.geojson`)
and simply hides the GeoServer farm overlay. Nothing else in the app depends on it.

> **This runbook is deliberately host-agnostic** (rewritten 2026-10-18). It used to
> be written against one specific machine and install method, which went stale as
> soon as the stack moved. Substitute your own values for:
>
> | Placeholder | Meaning |
> |---|---|
> | `<GEOSERVER_HOST>` | Host:port serving GeoServer, e.g. `localhost:8080` |
> | `<DB_HOST>` | How GeoServer reaches Postgres — see §4 |
>
> For the machine-specific particulars of whichever box is currently hosting the
> stack (ports, service names, Tailscale addresses, firewall rules), see
> `.claude/LOCAL_SERVER_SETUP.md` — that file tracks the live host; this one tracks
> the procedure.

Every command below runs either as a normal local repo edit, or as a handoff to
Fabio on the host — same rigor as the rest of `.claude/CLAUDE.md`'s
Database/venv/frontend execution rules. Nothing here is run via a tool call.

---

## 1. Prerequisites

- GeoServer installed by either route (both work; pick one and record which in
  `LOCAL_SERVER_SETUP.md`):
  - **Native:** the platform-independent binary + a JDK (Temurin 17 is known-good).
  - **Docker:** the `docker.osgeo.org/geoserver` image. A service definition exists
    in `backend/docker-compose.yml`.
- The `agrisure_db` PostgreSQL/PostGIS database running and reachable **from
  wherever GeoServer runs**.
- `tbl_admin_boundaries.boundary_geom` present (it is part of
  `backend/init_schema.sql`) **and backfilled** — see §3. Without the backfill the
  boundary layer publishes empty.

## 2. Install and start

### Native
1. Extract the binary, set `JAVA_HOME`, start it (`bin/startup.sh` / `startup.bat`).
2. Log in at `http://<GEOSERVER_HOST>/geoserver/web` with the default
   `admin`/`geoserver` and **change the password immediately**.

### Docker
1. In `backend/.env` (gitignored — never committed), set:
   ```
   GEOSERVER_ADMIN_USER=admin
   GEOSERVER_ADMIN_PASSWORD=<a real password, not the "geoserver" default>
   ```
   The image reads these on first boot and provisions the admin account directly,
   so there is no "log in with the default, then change it" step.
2. From `backend/`: `docker compose up -d` (add `docker compose build` first if
   anything changed). This also starts the other services defined there if they
   aren't already up.
3. Confirm with `docker compose ps` (`geoserver` should be `Up`) and
   `docker compose logs geoserver`. First boot is slower than restarts — it
   initializes its data directory.

Either way, open a firewall rule for GeoServer's port if it must be reachable from
other machines, scoped to the LAN/tailnet rather than left open.

## 3. Backfill the boundary geometry

From `backend/`, in the host's project venv — **Fabio runs this himself**:

```bash
python backfill_admin_boundary_geom.py
```

This reads `frontend/public/data/region10-boundaries.geojson` and populates
`boundary_geom` for every matching `(province, municipality)` in
`tbl_admin_boundaries`. It prints any GeoJSON municipalities with no matching rows
(municipalities with no seeded farms yet) — that is expected, not an error.

If `tbl_admin_boundaries` is empty, seed it first (`seed_admin_boundaries.py`, or
`seed_all.py` for the whole sequence — see `.claude/BACKEND_DATABASE_WORKFLOW.md` §4).

## 4. Create the workspace + PostGIS datastore

In the GeoServer admin UI (`http://<GEOSERVER_HOST>/geoserver/web`):

1. **Data > Workspaces > Add new workspace**
   - Name: `agrisuregis`
   - Namespace URI: `http://agrisuregis.local` (a placeholder; not publicly resolved)
2. **Data > Stores > Add new Store > PostGIS**
   - Workspace: `agrisuregis`
   - Data Source Name: `agrisure_db`
   - Connection: host `<DB_HOST>`, port `5432`, database `agrisure_db`, and the same
     user/password as `backend/.env`'s `DATABASE_URL`.

**Choosing `<DB_HOST>`** — this is the single most common setup mistake:

| GeoServer runs | Postgres runs | `<DB_HOST>` |
|---|---|---|
| Natively, same machine | Natively, same machine | `localhost` |
| In Docker | Natively on the host | `host.docker.internal` (Docker Desktop) |
| In Docker | In Docker, same compose file | the Postgres service name |
| Anywhere | A different machine | that machine's LAN/tailnet IP |

From inside a container, `localhost` means "this container", which has no Postgres
of its own. If Postgres is native and GeoServer is containerized, the Docker subnet
also needs a `pg_hba.conf` entry and a firewall rule for 5432.

The workspace name `agrisuregis` is **not** arbitrary — `GISLeafletMap.tsx` builds
its WMS/WFS URLs from it. Changing it means changing that file too.

## 5. Publish the layers

Under the `agrisure_db` store, **Publish** these two tables:

| Table | Geometry column | Layer name | Purpose |
|---|---|---|---|
| `tbl_farms` | `location_geom` | `agrisuregis:tbl_farms` | Optional WMS reference overlay (the frontend keeps its own interactive farm layer from FastAPI — see §7) |
| `tbl_admin_boundaries` | `boundary_geom` | `agrisuregis:tbl_admin_boundaries` | Live WFS source, replacing the bundled static `region10-boundaries.geojson` |

For each: on the "Publish" tab, click **Compute from data** and **Compute from
native bounds** to fill the bounding box, then Save.

(Optional) On the "Publishing" tab you can attach an SLD style for `tbl_farms`
matching the frontend's colour scheme (`#1e3a5f` fill). This only affects the
optional WMS overlay, not the interactive layer.

## 6. CORS — handled by the frontend dev proxy, not GeoServer

The browser blocks cross-origin `fetch` calls (frontend dev server on `:5173`
calling GeoServer on another port) unless GeoServer sends CORS headers. Visiting a
GeoServer URL directly in the address bar works regardless — page navigation isn't
subject to CORS — which can make this look fine until the frontend actually tries it.

`frontend/vite.config.ts` already proxies `/geoserver-proxy/*` to
`VITE_GEOSERVER_URL` server-side (see `server.proxy`), so every GeoServer request
from `GISLeafletMap.tsx` goes through a same-origin path and the browser never makes
a genuinely cross-origin request. CORS never applies either way.

**Do not enable GeoServer's own CORS filter** (`CORS_ENABLED=true` and friends on the
Docker image). Keeping the proxy as the single source of truth avoids maintaining
the same policy in two places, and the native install's version of that filter was a
real, previously-hit failure mode — see this file's git history.

This proxy only covers `npm run dev`. A production static build behind a reverse
proxy (not built yet) needs its own equivalent — e.g. an nginx `location` block
proxying `/geoserver` to GeoServer, alongside whatever proxies `/api` to FastAPI.

## 7. Point the frontend at it

In `frontend/.env`:

```
VITE_GEOSERVER_URL=http://<GEOSERVER_HOST>/geoserver
```

Restart the frontend dev server afterward — Vite reads `.env` at server start, not
live. (Hand that restart to Fabio; see `CLAUDE.md`'s Frontend Local Environment rule.)

## 8. Verify

- GeoServer is up: the admin UI loads, or `docker compose ps` shows it `Up`.
- WMS capabilities:
  `http://<GEOSERVER_HOST>/geoserver/agrisuregis/wms?service=WMS&version=1.3.0&request=GetCapabilities`
- WFS GetFeature for boundaries (should return GeoJSON, not an empty collection —
  an empty one means §3's backfill didn't run):
  ```
  http://<GEOSERVER_HOST>/geoserver/agrisuregis/ows?service=WFS&version=2.0.0&request=GetFeature&typeName=agrisuregis:tbl_admin_boundaries&outputFormat=application/json
  ```
- With `VITE_GEOSERVER_URL` set and the dev server restarted, the map loads region
  boundaries from GeoServer (falling back to the static file if unreachable) and
  shows a "GeoServer overlay" toggle for farm boundaries.

## Notes / current scope

- **The wind-footprint overlay is not published through GeoServer.** Exposure is a
  `(province, municipality)` text join against parsed TCWS areas, not a stored
  PostGIS geometry, so there is no table to publish. See
  `MASTER_DEVELOPMENT_CONTEXT.md` §2.
- **The typhoon track** comes from `GET /api/typhoons/{id}/track` as plain
  coordinates and is drawn client-side by `TyphoonTrackLayer.tsx` — not worth a
  GeoServer layer.
- **`tbl_farms` publishing is additive only.** The frontend's primary farm rendering
  (click-to-select, popups, per-farm styling) still comes from
  `GET /api/farms/geometry` via FastAPI, to avoid losing that interactivity — WMS
  returns raster tiles, not clickable features.
- **Memory:** if GeoServer shares a box with Postgres, the backend and Redis, keep
  its heap conservative (`EXTRA_JAVA_OPTS: "-Xms512m -Xmx1g"` in the compose file).
  Raise it only if the logs show memory pressure under real concurrent WMS tile
  rendering.
