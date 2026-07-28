# AgriSureGIS — Windows Setup Guide

This is a Windows-specific walkthrough for getting the full stack running locally:
PostgreSQL/PostGIS, the FastAPI backend, the React frontend, and (optionally)
GeoServer. All commands below are for **PowerShell** unless noted otherwise.

This guide documents what the code actually does today, including a couple of
places where the project's own docs (`.claude/ENV_GUIDE.md`) describe an
env-var-driven setup that the code doesn't actually implement yet — flagged inline
below so you don't waste time debugging a `.env` file that's silently ignored.

---

## 1. Prerequisites

Install these first (all have standard Windows installers):

| Tool | Version | Notes |
|---|---|---|
| [Git for Windows](https://git-scm.com/download/win) | latest | includes Git Bash, optional but handy |
| [Python](https://www.python.org/downloads/windows/) | 3.11+ | during install, check **"Add python.exe to PATH"** |
| [Node.js](https://nodejs.org/) | 20 LTS | includes `npm` |
| [PostgreSQL](https://www.postgresql.org/download/windows/) | 15+ | use the EDB installer — it bundles **Stack Builder**, which you'll use to add PostGIS |
| [PostGIS](https://postgis.net/) | 3+ | install via Stack Builder (launches automatically at the end of the PostgreSQL installer, or run it separately from the Start Menu) |
| JDK | 11 or 17 | only needed if you're setting up GeoServer (§6) — [Eclipse Temurin](https://adoptium.net/) is a good source on Windows |

After installing, open a **new** PowerShell window (so PATH updates take effect) and verify:
```powershell
git --version
python --version
node --version
npm --version
psql --version
```
If `psql` isn't found, add PostgreSQL's `bin` folder to PATH manually (typically
`C:\Program Files\PostgreSQL\<version>\bin`).

---

## 2. Clone the repository

```powershell
git clone <repo-url>
cd AgriSureGIS
```

---

## 3. Database setup

Open **SQL Shell (psql)** from the Start Menu (installed alongside PostgreSQL), or
run `psql -U postgres` from PowerShell, then:

```sql
CREATE USER agrisure_admin WITH PASSWORD 'agrisure_password';
CREATE DATABASE agrisure_db OWNER agrisure_admin;
\c agrisure_db
CREATE EXTENSION IF NOT EXISTS postgis;
```

> **Use exactly this username/password.** Unlike what `.claude/ENV_GUIDE.md`
> describes, the backend does **not** read a `DATABASE_URL` environment variable —
> `backend/app/core/database.py` has the connection string hardcoded:
> `postgresql://agrisure_admin:agrisure_password@localhost:5432/agrisure_db`.
> If you want different credentials, you'll need to edit that line directly instead
> of setting an env var.

Apply the schema (from the repo root):
```powershell
psql -U agrisure_admin -d agrisure_db -h localhost -f backend\init_schema.sql
```

---

## 4. Backend setup

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
```

> If PowerShell blocks the activation script with an execution-policy error, run
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first (only affects
> the current window), then retry.

```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

`geopandas`/`shapely`/`pyproj` all ship prebuilt Windows wheels for recent Python
versions, so this should install cleanly without needing separate GDAL/OSGeo
tooling. If `pip install` fails specifically on `geopandas`, upgrading `pip` first
(above) usually resolves it — pin issues are rare but check the error for a
specific missing wheel if it does fail.

Seed sample data (optional, reads `backend/pabs_results.csv`):
```powershell
python seed_database.py
```

Run the API server:
```powershell
uvicorn app.main:app --reload
```
Swagger UI: http://127.0.0.1:8000/docs

`backend/.env` is **not required** — nothing in `backend/app/` reads environment
variables today (`python-dotenv` is listed in `requirements.txt` but never
imported). The `PAGASA_SCRAPE_URL` bulletin-scraping endpoint is similarly
hardcoded in `backend/app/services/bulletin_parser.py`, not env-configurable.

---

## 5. Frontend setup

Open a **new** PowerShell window (keep the backend running in the first one):
```powershell
cd frontend
copy .env.example .env
npm install
npm run dev
```
Open the printed URL (usually http://localhost:5173).

`.env.example` already has working defaults:
```
VITE_API_BASE_URL=http://localhost:8000
VITE_GEOSERVER_URL=http://localhost:8080/geoserver
```
Leave `VITE_API_BASE_URL` **without** a trailing `/api` — every API call in
`frontend/src/lib/api.ts` already includes its own `/api/...` prefix, so adding it
here causes a `/api/api/...` 404 on every request (a mistake made and fixed during
GeoServer setup — see `.claude/FUNCTION_CHANGES.md`, 2026-07-28 entry, for the story).

If you're not setting up GeoServer, either leave `VITE_GEOSERVER_URL` as-is (the
map silently falls back to a bundled static boundary file if GeoServer isn't
reachable) or remove the line entirely — both are safe.

---

## 6. GeoServer setup (optional)

Only needed if you want live spatial layers (region boundaries, farm overlay) served
from PostGIS instead of the bundled static file. Skip this section otherwise.

1. Download the **Platform Independent Binary** (`.zip`) from the
   [GeoServer downloads page](https://geoserver.org/download/) — version 2.24.x or
   2.25.x.
2. Extract it somewhere stable, e.g. `C:\geoserver`.
3. Set `JAVA_HOME` (System Properties → Environment Variables, or via PowerShell for
   the current session):
   ```powershell
   $env:JAVA_HOME = "C:\Program Files\Eclipse Adoptium\jdk-11.x.x.x-hotspot"
   $env:PATH = "$env:JAVA_HOME\bin;$env:PATH"
   ```
   Use your actual install path — check `C:\Program Files\Eclipse Adoptium\` after
   installing the JDK. **JDK 17 has a known issue** on this GeoServer version: WMS
   `GetMap`/rendering operations throw `NoClassDefFoundError` /
   `IllegalAccessError` on `sun.java2d` classes (a Marlin-renderer/module-system
   incompatibility). If you hit that, switch to JDK 11.
4. Start it (bundles its own Jetty server — no separate Tomcat/servlet container
   needed):
   ```powershell
   C:\geoserver\bin\startup.bat
   ```
5. Open http://localhost:8080/geoserver/web, log in with `admin`/`geoserver`, and
   change the password (Security → Users/Groups/Roles) unless this is throwaway
   local dev.

### Do not edit GeoServer's `web.xml` for CORS

The bundled `web.xml` has a commented-out CORS filter block that says "enable CORS
in Tomcat" — this GeoServer distribution runs on **Jetty**, not Tomcat, and
uncommenting that filter crashes the entire GeoServer deployment
(`ClassNotFoundException: org.apache.catalina.filters.CorsFilter`). This was hit
and fixed for real during development (see `.claude/FUNCTION_CHANGES.md`,
2026-07-28 "Incident" note) — don't repeat it.

CORS is already handled for you: `frontend/vite.config.ts` proxies
`/geoserver-proxy/*` to `VITE_GEOSERVER_URL` server-side, so the browser never makes
a genuinely cross-origin request. You don't need to touch GeoServer's config for
this at all.

### Create the workspace, datastore, and publish layers

Follow **`.claude/GEOSERVER_SETUP.md`, sections 5–6** — those steps are identical on
Windows (they're all GeoServer's own web admin UI, not OS-specific). In short:
create workspace `agrisuregis` → PostGIS datastore `agrisure_db` (host `localhost`,
port `5432`, same credentials as §3 above) → publish `tbl_farms` and
`tbl_admin_boundaries` as layers.

Once published, reload the frontend — region boundaries should load live from
GeoServer, and a "GeoServer farm overlay" checkbox appears in the map's top-right
corner.

---

## 7. Troubleshooting

- **`'python' is not recognized`**: Python wasn't added to PATH during install.
  Reinstall and check "Add python.exe to PATH", or add it manually.
- **`.venv\Scripts\Activate.ps1 cannot be loaded because running scripts is
  disabled`**: see the execution-policy note in §4.
- **`psql: FATAL: password authentication failed`**: credentials don't match what
  `backend/app/core/database.py` expects (§3's warning) — either use the exact
  `agrisure_admin`/`agrisure_password`, or edit that file to match your own.
- **Frontend loads but every API call 404s**: check `frontend/.env` for a
  `VITE_API_BASE_URL` with a trailing `/api` — remove it (§5), then fully restart
  `npm run dev` (Vite only reads `.env` at startup, not on change).
- **GeoServer won't start / crashes on startup**: if you've edited `web.xml`,
  restore a clean copy from the original downloaded `.zip` rather than trying to
  hand-fix it — malformed XML there takes down the entire GeoServer instance,
  including the admin UI.
