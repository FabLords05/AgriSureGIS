# AgriSureGIS

AgriSureGIS is a WebGIS-based parametric insurance assessment platform (capstone project).
This repository contains the frontend and backend components used to ingest farm and insurance data, run spatial queries with PostGIS, and expose APIs for map and assessment UIs.

## PAGASA API refactor status

**PARTIALLY FIXED — FOLLOW-UP REQUIRED** (reviewed 2026-09-26 at `eafc2c6`).

The 16 bulletin tests pass, but parsing, error reporting, and resource-handling gaps remain. The refactor is not complete. Start with the [review handoff and open checklist](docs/bulletin-refactor-status.md) to resume work on `fabio/backend/bulletin-scraper-review`.

## Contents

- Backend: See [backend/README.md](backend/README.md) for detailed setup, database initialization, and API info.
- Frontend: See [frontend/README.md](frontend/README.md) for the Vite + React frontend and developer instructions.

## Quickstart

1. Backend (API + DB)

```bash
cd backend
# create virtualenv, install deps
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
# initialize database (Postgres + PostGIS)
psql -U agrisure_admin -d agrisure_db -h localhost -f init_schema.sql
# seed sample data (optional)
python seed_database.py
# run the API server
uvicorn app.main:app --reload
```

2. Frontend

```bash
cd frontend
# Follow the frontend/README.md for setup (pnpm/npm install + dev server)
```

## Notes

- The primary database name used in examples is `agrisure_db` and the default DB user is `agrisure_admin` (see backend/seed_database.py and backend/app/core/database.py).
- API docs are available at `http://127.0.0.1:8000/docs` once the backend server is running.
