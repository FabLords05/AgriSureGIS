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
1. Never put database passwords directly in the codebase. Always use environment variables.\n