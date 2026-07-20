# AgriSureGIS - Environment Variable Guide

Copy `.env.example` to `.env` in the `backend/` directory. **Do not commit `.env` to Git.**

## Variables Configuration

| Variable | Description | Where to get it |
|---|---|---|
| `DATABASE_URL` | PostGIS database connection string. | Provided by Fabio (DB Admin). |
| `PAGASA_SCRAPE_URL` | PAGASA Tropical Cyclone Bulletin webpage URL. | PAGASA official website. |
| `SMTP_HOST` | SMTP server address for email alerts. | Internal mail server / SMTP provider. |
| `SMTP_USER` | SMTP server login username. | Mail administrator. |
| `SMTP_PASSWORD`| SMTP server password. | Mail administrator. |
| `VITE_API_BASE_URL` | Backend base URL for frontend API calls. | Default is `http://localhost:8000/api`. |

## Key Security Rules
1. Never put database passwords directly in the codebase. Always use environment variables.

## Rules
1. `.env` is already gitignored (`backend/.env` — covered by the root `.gitignore`'s `.env` / `.env.local` / `.env.*.local` entries). Never commit it.
2. Frontend vars are **public** by build-time convention — Vite requires the `VITE_` prefix, and anything with that prefix ships into the browser bundle. Never put a secret (`DATABASE_URL`, `SMTP_PASSWORD`, etc.) in a frontend-facing variable.
3. Secrets that must stay server-side (`DATABASE_URL`, `SMTP_PASSWORD`) only ever go in `backend/.env`.
4. When you add a new variable, add it to `.env.example` with a placeholder value in the same commit — don't let `.env.example` drift from what the code actually reads.\n