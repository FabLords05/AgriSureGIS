# AgriSureGIS - Environment Variable Guide

Copy `.env.example` to `.env` in the `backend/` directory. **Do not commit `.env` to Git.**

## Variables Configuration

| Variable | Description | Where to get it |
|---|---|---|
| `DATABASE_URL` | PostGIS database connection string. | Provided by Fabio (DB Admin). |
| `JWT_SECRET_KEY` | **Required** -- signs/verifies login session tokens (`backend/app/core/security.py`). No insecure hardcoded fallback like `DATABASE_URL` has; the backend refuses to start without it. | Generate your own: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Never share/commit the value. |
| `REDIS_URL` | Optional -- `GET /api/farms/`'s page cache (`backend/app/core/farms_cache.py`). Unset/empty means caching is a no-op; nothing else changes. | A locally running Redis server, e.g. `redis://localhost:6379/0`. |
| `PAGASA_SCRAPE_URL` | PAGASA Tropical Cyclone Bulletin webpage URL. | PAGASA official website. |
| `SMTP_HOST` | SMTP server address for email alerts (`backend/app/services/email_alert_service.py`). Optional -- unset (along with `SMTP_USER`/`SMTP_PASSWORD`) means alerts are a no-op, same convention as `REDIS_URL` above. | Internal mail server / SMTP provider. |
| `SMTP_PORT` | SMTP server port. Defaults to `587` (STARTTLS) if unset. | Mail administrator. |
| `SMTP_USER` | SMTP server login username -- also used as the From/To address on outgoing alert emails. | Mail administrator. |
| `SMTP_PASSWORD`| SMTP server password. | Mail administrator. |
| `VITE_API_BASE_URL` | Backend base URL for frontend API calls. **No `/api` suffix** — every path in `frontend/src/lib/api.ts` already includes its own leading `/api/...`, so appending `/api` here causes a `/api/api/...` 404. | Default is `http://localhost:8000`. |
| `VITE_GEOSERVER_URL` | GeoServer base URL for WMS/WFS spatial layer requests (farm boundary overlay, region boundaries). | Default is `http://localhost:8080/geoserver`. See `.claude/GEOSERVER_SETUP.md`. If unset or unreachable, the map falls back to the bundled static boundary file and skips the farm overlay. |

## Key Security Rules
1. Never put database passwords directly in the codebase. Always use environment variables.

## Rules
1. `.env` is already gitignored (`backend/.env` — covered by the root `.gitignore`'s `.env` / `.env.local` / `.env.*.local` entries). Never commit it.
2. Frontend vars are **public** by build-time convention — Vite requires the `VITE_` prefix, and anything with that prefix ships into the browser bundle. Never put a secret (`DATABASE_URL`, `SMTP_PASSWORD`, etc.) in a frontend-facing variable.
3. Secrets that must stay server-side (`DATABASE_URL`, `SMTP_PASSWORD`, `JWT_SECRET_KEY`) only ever go in `backend/.env`.
4. When you add a new variable, add it to `.env.example` with a placeholder value in the same commit — don't let `.env.example` drift from what the code actually reads.\n