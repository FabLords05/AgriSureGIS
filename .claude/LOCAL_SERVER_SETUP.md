# AgriSureGIS — Local Server Setup (Cristian's PC, no Docker)

How to bring up the full stack on this Windows PC: PostgreSQL/PostGIS, FastAPI
backend, GeoServer (native), and the Vite frontend. Tailscale peers reach the
backend at `100.66.247.20:8000`.

Secrets (DB password, GeoServer admin password) live only in `backend/.env` —
never copy them into this file or commit them.

---

## 1. Prerequisites (one-time)

| Component | Where / version |
|---|---|
| PostgreSQL + PostGIS | Native Windows service, `localhost:5432`, DB `agrisure_db`, user `agrisure_admin` |
| Python venv | `backend\.venv` |
| Java | Temurin JDK 17 (`JAVA_HOME` already set) |
| GeoServer | 3.0.1 platform-independent binary, extracted to `C:\geoserver` |
| Node | `frontend\node_modules` installed (`npm install`) |

`backend/.env` must contain `DATABASE_URL=postgresql://agrisure_admin:<password>@localhost:5432/agrisure_db`.
`frontend/.env` must contain `VITE_GEOSERVER_URL=http://localhost:8080/geoserver`.

## 2. Database

Make sure the PostgreSQL service is running (Services → `postgresql-x64-*`).

**Schema updates — prefer migrations.** `backend/init_schema.sql` DROPs every
table; only use it on a fresh DB. For an existing DB, apply the dated files in
`backend/migrations/` instead (each is idempotent). From `backend\`:

```powershell
psql "postgresql://agrisure_admin:<password>@localhost:5432/agrisure_db" -f migrations/<file>.sql
```

Applied on this PC so far: `2026-10-09_crop_stage_mapping.sql` (17 mapping rows).

Take a backup before anything destructive:

```powershell
pg_dump "postgresql://agrisure_admin:<password>@localhost:5432/agrisure_db" -f agrisure_backup_<date>.sql
```

## 3. Backend (FastAPI)

From `backend\`, in its own terminal:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

`--host 0.0.0.0` is required for Tailscale peers; port 8000 also needs an
inbound Windows Firewall rule (already in place).

Tests (no DB needed) — always `python -m pytest`, not bare `pytest`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -v
```

Known: 10 `test_farms_api.py` failures pre-exist on `develop` (test-only issue).

## 4. GeoServer (native, no Docker)

In its own PowerShell window — closing the window stops GeoServer:

```powershell
$env:GEOSERVER_HOME = "C:\geoserver"; & C:\geoserver\bin\startup.bat
```

Admin UI: http://localhost:8080/geoserver/web (log in top-right).

**One-time configuration** (already done on this PC — redo only on a fresh data dir):

1. Change the `admin` password (Security → Users, Groups, Roles).
2. Data → Workspaces → Add: name `agrisuregis`, URI `http://agrisuregis.local`.
3. Data → Stores → Add → PostGIS: workspace `agrisuregis`, name `agrisure_db`,
   host **`localhost`** (not `host.docker.internal` — that is Docker-only),
   port `5432`, database `agrisure_db`, user `agrisure_admin`, password from `backend/.env`.
4. Publish `tbl_farms` and `tbl_admin_boundaries`. For each: Declared SRS
   `EPSG:4326` → **Compute from data** → **Compute from native bounds** → Save.
   (If Compute from data stays empty, use **Compute from SRS bounds** instead.)

Verify: http://localhost:8080/geoserver/agrisuregis/wms?service=WMS&version=1.3.0&request=GetCapabilities
should list both layers.

## 5. Frontend

From `frontend\`, in its own terminal (restart after any `.env` change):

```powershell
npm run dev
```

Vite proxies `/geoserver-proxy/*` to `VITE_GEOSERVER_URL`, so no CORS setup is
needed. `http proxy error … ECONNREFUSED` in this terminal means GeoServer is
not running.

## 6. Startup order (every reboot)

1. PostgreSQL service running
2. Backend (§3)
3. GeoServer (§4)
4. Frontend (§5)

## 7. Data ingestion order

Upload the **CSV first, then the `.gpkg`/GPX** — the boundary upload only
updates farms the CSV already created. Re-uploading the same CSV is safe:
existing rows come back as skipped.

## 8. Things that look broken but aren't

- **Farm Records shows only a few rows.** "Active Insurance Only" is on by
  default and forced back on when no municipality/farmer is selected — farms
  with expired policies are hidden. Pick a municipality from the dropdown (or
  search a farmer), then switch the toggle off.
- **Polygons not clickable.** The GeoServer overlay is a raster image. Clickable
  polygons come from the backend's farm list, so they follow the same filter above.
- **`crop_stage_no` NULL on ~312 rows** of the PCIC10 export
  (`Panicle Initiation/Booting`, `Harvested`, `Vegetative/Tillering`) — by design,
  pending PCIC's days-per-stage table. See `HANDOFF_2026-10-09_CSV_CROP_STAGE.md` §4.
