# AgriSureGIS - Environment Variable Guide

Copy `.env.example` to `.env` in the `backend/` directory. **Do not commit `.env` to Git.**

## Variables Configuration

| Variable | Description | Where to get it |
|---|---|---|
| `DATABASE_URL` | PostGIS database connection string. | Provided by Fabio (DB Admin). |
| `JWT_SECRET_KEY` | **Required** -- signs/verifies login session tokens (`backend/app/core/security.py`). No insecure hardcoded fallback like `DATABASE_URL` has; the backend refuses to start without it. | Generate your own: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Never share/commit the value. |
| `REDIS_URL` | Optional -- `GET /api/farms/`'s page cache (`backend/app/core/farms_cache.py`). Unset/empty means caching is a no-op; nothing else changes. | A locally running Redis server, e.g. `redis://localhost:6379/0`. |
| `PAGASA_SCRAPE_URL` | **Dead variable — nothing reads it.** Still present in `.env.example` for historical reasons. The bulletin index URL is hardcoded as `PAGASA_INDEX_URL` in `backend/app/services/bulletin_parser.py`; setting this has no effect. Either wire it up or drop it from `.env.example`. | n/a |
| `SMTP_HOST` | SMTP server address for email alerts (`backend/app/services/email_alert_service.py`). Optional -- unset (along with `SMTP_USER`/`SMTP_PASSWORD`) means alerts are a no-op, same convention as `REDIS_URL` above. | Internal mail server / SMTP provider. |
| `SMTP_PORT` | SMTP server port. Defaults to `587` (STARTTLS) if unset. | Mail administrator. |
| `SMTP_USER` | SMTP server login username -- also used as the From/To address on outgoing alert emails unless `SMTP_FROM` is set. | Mail administrator. |
| `SMTP_PASSWORD`| SMTP server password. | Mail administrator. |
| `SMTP_FROM` | Optional From/To address for alert emails. Unset = `SMTP_USER` (correct for Gmail). Required for Brevo (`SMTP_HOST=smtp-relay.brevo.com`), whose SMTP login is a generated ID, not a mailbox -- set it to a sender address verified in Brevo. | Brevo dashboard → Senders. |
| `GEE_SERVICE_ACCOUNT_KEY_PATH` | Optional -- path to the Google Earth Engine service-account JSON key for SAR planted verification (`backend/app/services/gee_sar_service.py`, 2026-10-12). Unset means the SAR layer endpoint returns 503 "not configured"; nothing else changes. Only the key's `client_email`/`project_id` are ever shown (Calibration & Settings → Google Earth Engine). | The GCP project's service-account key (`webgis-pcic-*.json`, gitignored). The account must be registered for Earth Engine and the project must have the Earth Engine API enabled. |
| `ARCHIVE_DATABASE_URL` | Optional -- the **read-only** login to the separate archive database (`backend/archive_schema.sql`, 2026-10-22), used by every archive-viewing endpoint. Unset means the archive endpoints return 503; nothing else changes. | `postgresql://agrisure_archive_reader:<password>@localhost:5432/agrisure_archive` -- password set by Fabio when applying `archive_schema.sql`. |
| `ARCHIVE_WRITER_DATABASE_URL` | Optional -- the INSERT-only archive login, used only by Archive & Clear. Required together with `ARCHIVE_DATABASE_URL`. | `postgresql://agrisure_archive_writer:<password>@localhost:5432/agrisure_archive`. |
| `PG_DUMP_PATH` | Optional -- the `pg_dump` binary for backups (`backend/app/services/backup_service.py`). Default `pg_dump` on PATH. Its major version must match the server's. | e.g. `C:\Program Files\PostgreSQL\16\bin\pg_dump.exe` on Windows. |
| `BACKUP_DIR` | Optional -- where `.dump` files are written. Default `backend/backups/` (gitignored). | Any local folder with enough space. |
| `GDRIVE_CLIENT_ID` / `GDRIVE_CLIENT_SECRET` | Optional -- a Google OAuth "Desktop app" client, used to upload backups to Google Drive. Unset means backups stay local only. | Google Cloud Console → Credentials, with the Drive API enabled. Set the consent screen to "In production", or the refresh token expires in 7 days. |
| `GDRIVE_REFRESH_TOKEN` | Optional -- a personal Gmail's Drive refresh token (scope `drive.file`). Secret. | Run `python scripts/gdrive_authorize.py` once from `backend/`. |
| `GDRIVE_FOLDER_ID` | Optional -- the Drive folder that backups go into. | The id at the end of the folder's URL (`drive.google.com/drive/folders/<id>`). |
| `PG_RESTORE_PATH` | Optional -- the `pg_restore` binary, used to check every new dump (`pg_restore --list`) and by Verify. Default `pg_restore` on PATH; same major version as the server. | e.g. `C:\Program Files\PostgreSQL\16\bin\pg_restore.exe`. |
| `BACKUP_RETENTION_COUNT` | Optional -- how many manual/scheduled `.dump` files stay in `BACKUP_DIR` (newest first, default 30). Older files are deleted; their log rows and Drive copies are kept. Archive dumps are never pruned. | Size it to the disk. |
| `BACKUP_ENCRYPTION_KEY` | Optional but recommended with Drive -- encrypts the Google Drive copy of each backup (AES-256-GCM, `backend/app/core/backup_crypto.py`). The local dump stays plain. **Lose it and every encrypted Drive copy is unreadable** -- keep a copy somewhere other than this machine. | `python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"` |
| `BACKUP_VERIFY_DATABASE_URL` | Optional -- a **separate, disposable** database that Database Backup → Verify restores a backup into and checks (row counts per table against the dump's own snapshot). Its contents are replaced on every verify. Pointing it at the live database or the archive database (`agrisure_archive`) is refused -- it must be its own, separate database. Unset = Verify is hidden. | Fabio creates it (see "Backup verification & manual restore" below), e.g. `postgresql://agrisure_admin:<password>@localhost:5432/agrisure_verify`. |
| `VITE_API_BASE_URL` | Backend base URL for frontend API calls. **No `/api` suffix** — every path in `frontend/src/lib/api.ts` already includes its own leading `/api/...`, so appending `/api` here causes a `/api/api/...` 404. | Default is `http://localhost:8000`. |
| `VITE_GEOSERVER_URL` | GeoServer base URL for WMS/WFS spatial layer requests (farm boundary overlay, region boundaries). | Default is `http://localhost:8080/geoserver`. See `.claude/GEOSERVER_SETUP.md`. If unset or unreachable, the map falls back to the bundled static boundary file and skips the farm overlay. |

## Activating Email Alerts (new-TCB notification)

The alert in `email_alert_service.py` stays a silent no-op until **all three** of
`SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD` are set -- `SMTP_PORT` alone defaults to `587`.
For a Gmail sender: `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER=<the account>`,
`SMTP_PASSWORD=<16-character App Password>` (an App Password requires 2-Step Verification on
that account; a normal Google password is rejected). Outbound port 587 must not be blocked
on the backend host. For Brevo, also set `SMTP_FROM` (see the table above) -- its SMTP login
is a generated ID rather than a mailbox, so the From address has to be a separately verified
sender.

Recipients are every `tbl_system_users` row with `is_active = true` -- GIS Specialists **and**
System Administrators -- so at least one of those rows needs a real, deliverable inbox.

After editing `backend/.env`, restart the backend (env is read at process start, not hot-reloaded),
then verify with `backend/simulation/simulate_new_bulletin_alert.py` (dry run by default;
`--send` really delivers; or `simulate.bat alert` from the repo root). The Monitoring dashboard's System Status panel also shows an "Email Alerts:
Configured / Not configured" row, fed by `GET /api/system/status`.

## Backup verification & manual restore (2026-10-22)

**One-time setup of the verification database** (Fabio, as the postgres superuser):

```
createdb -U postgres -O agrisure_admin agrisure_verify
psql -U postgres -d agrisure_verify -c "CREATE EXTENSION IF NOT EXISTS postgis;"
```

Then set `BACKUP_VERIFY_DATABASE_URL` in `backend/.env` and restart the backend. Verify
(Database Backup tab) restores the chosen backup -- from the server, or downloaded and
decrypted from Google Drive -- into this database and compares every table's row count with
the counts read from the dump's own snapshot. It never touches `agrisure_db`.

**Restoring the live database** stays manual, by the DB admin, after a successful Verify of
the same backup:

1. Stop the backend (nothing may write during the restore).
2. Take a fresh safety dump first: `pg_dump -Fc --no-owner -U agrisure_admin -d agrisure_db -f before_restore.dump`
3. For a Google Drive copy (`*.dump.enc`), decrypt it from `backend/`:
   `python scripts/decrypt_backup.py <file>.dump.enc` (needs `BACKUP_ENCRYPTION_KEY`).
4. Restore: `pg_restore --clean --if-exists --no-owner -U agrisure_admin -d agrisure_db <file>.dump`
5. Start the backend and check the Main Dashboard / Activity Log.

## Key Security Rules
1. Never put database passwords directly in the codebase. Always use environment variables.

## Rules
1. `.env` is already gitignored (`backend/.env` — covered by the root `.gitignore`'s `.env` / `.env.local` / `.env.*.local` entries). Never commit it.
2. Frontend vars are **public** by build-time convention — Vite requires the `VITE_` prefix, and anything with that prefix ships into the browser bundle. Never put a secret (`DATABASE_URL`, `SMTP_PASSWORD`, etc.) in a frontend-facing variable.
3. Secrets that must stay server-side (`DATABASE_URL`, `SMTP_PASSWORD`, `JWT_SECRET_KEY`, the GEE key file) only ever go in `backend/.env` (or, for the GEE key, a gitignored file it points to).
4. When you add a new variable, add it to `.env.example` with a placeholder value in the same commit — don't let `.env.example` drift from what the code actually reads.\n