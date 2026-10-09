# AgriSureGIS — GeoServer Setup & Layer Publishing Runbook

GeoServer is the 2nd-tier spatial layer server shown in `docs/system architecture.png`,
sitting between the Presentation Layer (React/Leaflet) and the Database Layer
(PostgreSQL/PostGIS). It serves map layers directly to the frontend via WMS/WFS,
separate from FastAPI's business-logic API.

**As of 2026-08-11, this runs as a Docker container on the remote mock server**
(192.168.1.41), a third service in `backend/docker-compose.yml` alongside `backend`
and `redis` — not a native local install. This supersedes the original native/JDK
approach: the database GeoServer needs to query now lives on that box (see
`.claude/PROJECT_CONTEXT.md`'s remote-server notes), so colocating GeoServer with
Postgres avoids a network hop on every internal PostGIS query GeoServer makes,
and reuses the Docker/Postgres-reachability groundwork already laid for the
`backend` container (`host.docker.internal`, the Docker-subnet `pg_hba.conf`/
firewall rules) instead of opening new surface area.

Every command below runs either as a normal local repo edit, or as a handoff to
Fabio's own SSH session on the remote box — same rigor as the rest of `.claude/
CLAUDE.md`'s Database/venv/Docker execution rules. Building/pulling the
`docker.osgeo.org/geoserver` image needs the **physical console** on that box, not
SSH — a known limitation of this specific Windows machine (Windows Credential
Manager/DPAPI needs an interactive logon session that SSH-created sessions don't
have), already worked around the same way for the `backend` image.

---

## 1. Prerequisites

- Docker Desktop already installed and working on 192.168.1.41 (it is, as of the
  backend containerization work — see `backend/Dockerfile`/`docker-compose.yml`).
- The existing `agrisure_db` PostgreSQL/PostGIS database, native on that same box,
  already running and reachable from its Docker network (already true — the
  `backend` container already connects to it via `host.docker.internal`).
- `tbl_admin_boundaries.boundary_geom` column applied (see `backend/init_schema.sql`)
  and backfilled (see step 4 below) — needed before the boundary layer can be published.

## 2. Add the `geoserver` service and bring it up

The service definition already exists in `backend/docker-compose.yml`:

```yaml
  geoserver:
    image: docker.osgeo.org/geoserver:3.0.x
    restart: unless-stopped
    ports:
      - "8080:8080"
    env_file:
      - .env
    environment:
      GEOSERVER_DATA_DIR: /opt/geoserver_data
      EXTRA_JAVA_OPTS: "-Xms512m -Xmx1g"
      SKIP_DEMO_DATA: "true"
    volumes:
      - geoserver-data:/opt/geoserver_data
```

1. On the remote box, in `backend/.env` (gitignored, edited in place — never
   committed), add:
   ```
   GEOSERVER_ADMIN_USER=admin
   GEOSERVER_ADMIN_PASSWORD=<pick a real password, not the "geoserver" default>
   ```
   The image reads these on first boot and provisions the admin account with
   them directly — no separate "log in with the default and change it" step
   the native install needed.
2. Add a Windows Firewall inbound rule for port 8080 (this is genuinely new —
   only 8000 (backend) and 5432 (Postgres, Docker-subnet-scoped) have been
   opened so far):
   ```
   New-NetFirewallRule -DisplayName "GeoServer" -Direction Inbound -Protocol TCP -LocalPort 8080 -RemoteAddress 172.16.0.0/12,192.168.1.0/24 -Action Allow
   ```
3. **At the physical console** (not SSH — see the note above): `cd` into
   `backend/` and run `docker compose build` if anything changed, then
   `docker compose up -d`. This also (re)creates `backend` and `redis` if they
   aren't already running — `docker compose up -d` only touches services that
   changed, so this is safe to run even with the stack already up.
4. Confirm it's up: `docker compose ps` should show `geoserver` as `Up`, and
   `docker compose logs geoserver` should show it finish startup (first boot
   is slower than restarts — GeoServer initializes its data directory).
5. Open `http://192.168.1.41:8080/geoserver/web` and log in with the
   `GEOSERVER_ADMIN_USER`/`PASSWORD` you set in step 1.

## 3. Apply the schema change

`boundary_geom` (and its GIST index) is now part of `backend/init_schema.sql`. Re-apply
it against `agrisure_db` the same way you normally apply schema updates — **on the
remote box**, since that's where `agrisure_db` lives now, not a local venv.

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

Both of these run **on the remote box** (SSH, its own venv), against its own local
`agrisure_db` — no new network path needed, same as any other backend script there.

If you re-ran the full `init_schema.sql`, reseed first so `tbl_admin_boundaries` has
rows for the backfill to match against:
```
python seed_database.py
```

Then, from `backend/`, using the remote box's project venv:
```
python backfill_admin_boundary_geom.py
```
This reads `frontend/public/data/region10-boundaries.geojson` and populates
`boundary_geom` for every matching `(province, municipality)` in
`tbl_admin_boundaries`. It prints any geojson municipalities that had no matching
rows (municipalities with no seeded farms yet) — that's expected, not an error.

## 5. Create the workspace + PostGIS datastore

In the GeoServer admin UI (`http://192.168.1.41:8080/geoserver/web`):
1. **Data > Workspaces > Add new workspace**
   - Name: `agrisuregis`
   - Namespace URI: `http://agrisuregis.local` (placeholder, not publicly resolved)
2. **Data > Stores > Add new Store > PostGIS**
   - Workspace: `agrisuregis`
   - Data Source Name: `agrisure_db`
   - Connection params: **host `host.docker.internal`**, port `5432`, database
     `agrisure_db`, same user/password as `backend/.env`'s `DATABASE_URL` — this
     is the same Docker Desktop DNS indirection the `backend` container already
     uses to reach native Postgres from inside a container, not `localhost`
     (that would mean "inside the GeoServer container," which has no Postgres
     of its own).

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

The Docker image does support this natively (`CORS_ENABLED=true` and related
`CORS_ALLOWED_*` env vars) — **deliberately not used here**. `frontend/vite.config.ts`
already proxies `/geoserver-proxy/*` to `VITE_GEOSERVER_URL` server-side (see
`server.proxy` in that file), so every GeoServer request from `GISLeafletMap.tsx`
goes through that same-origin proxy path and the browser never makes a genuinely
cross-origin request — CORS never applies either way. Keeping this the single
source of truth avoids maintaining the same policy in two places, and sidesteps
depending on GeoServer's own CORS filter at all (the native install's version of
this filter was a real, previously-hit failure mode — see the git history of this
file — enabling GeoServer-side CORS unnecessarily reintroduces that surface for no
benefit here). This proxy only covers `npm run dev` — a production static
build/reverse-proxy setup (not built yet) will need its own equivalent (e.g. an
nginx location block proxying `/geoserver` to GeoServer, alongside whatever proxies
`/api` to FastAPI).

## 8. Point the frontend at it

In `frontend/.env`:
```
VITE_GEOSERVER_URL=http://192.168.1.41:8080/geoserver
```
(or the Tailscale address, `http://100.80.128.92:8080/geoserver`, if working
away from the LAN — see `.claude/CLAUDE.md`'s remote-server/Tailscale notes.)
Restart the frontend dev server after changing this — Vite reads `.env` at
server start, not live.

## 9. Verify

- `docker compose ps` on the remote box shows `geoserver` as `Up`.
- WMS capabilities: `http://192.168.1.41:8080/geoserver/agrisuregis/wms?service=WMS&version=1.3.0&request=GetCapabilities`
- WFS GetFeature test for boundaries (should return GeoJSON):
  ```
  http://192.168.1.41:8080/geoserver/agrisuregis/ows?service=WFS&version=2.0.0&request=GetFeature&typeName=agrisuregis:tbl_admin_boundaries&outputFormat=application/json
  ```
- With `VITE_GEOSERVER_URL` set (step 8) and the frontend dev server restarted,
  the map should load region boundaries from GeoServer (falling back to the
  static file if GeoServer is unreachable) and show a "GeoServer overlay"
  toggle for farm boundaries.

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
- `EXTRA_JAVA_OPTS` is set conservatively (`-Xms512m -Xmx1g`) since this box also
  runs `backend`, `redis`, native Postgres, and Docker Desktop itself. Raise it if
  `docker compose logs geoserver` shows memory pressure under real concurrent WMS
  tile rendering.
- `docker compose build`/`up` for this service needs the physical console on
  192.168.1.41, same known limitation as the `backend` image — day-to-day
  management (`restart`, `logs`, `ps`) works fine over SSH once it's built.
