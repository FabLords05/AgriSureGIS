# AgriSureGIS — Backend

AgriSureGIS is a WebGIS-based parametric insurance assessment platform. This repository contains the backend API service that ingests and normalizes farm and insurance CSV data, stores spatial and relational records in PostgreSQL/PostGIS, and exposes FastAPI endpoints for map-based UIs and assessment workflows.

Key backend responsibilities:

- Accept and normalize bulk CSV uploads (farms, policies, assessments)
- Maintain normalized relational models for `FarmerProfile`, `AdminBoundary`, `Farm`, `InsuranceRecord`, and `RiskAssessment`
- Store and serve spatial data via GeoAlchemy2/PostGIS (farm polygons / geometries)
- Provide REST APIs and Swagger documentation for frontend integration

---

## Repository layout (backend)

. (backend root)
├── app/
│   ├── api/             # API routers (endpoints) — upload, assessments, GIS services
│   ├── core/
│   │   └── database.py  # SQLAlchemy engine, SessionLocal, Base, and `get_db` dependency
│   ├── models/
│   │   └── models.py    # SQLAlchemy + GeoAlchemy2 ORM classes
│   ├── schemas/         # Pydantic schemas (request/response validation) — reserved for future use
│   ├── services/        # Business logic and external integrations (e.g., PAGASA) — reserved for future use
│   └── main.py          # FastAPI app instance, CORS config, health and test endpoints
├── init_schema.sql      # Idempotent SQL script to create schema, enable PostGIS, and add indexes
├── seed_database.py     # CSV-based seeding utility to load PABS/insurance CSV into normalized schema
└── requirements.txt     # Python dependencies (FastAPI, Uvicorn, SQLAlchemy, GeoAlchemy2, Pandas, psycopg2-binary)

---

## Quick Start — Local Development

These steps assume you have an on-prem PostgreSQL server with the PostGIS extension available and a local user with appropriate privileges.

1. Open a terminal and change to the backend folder:

```bash
cd backend
```

2. Create and activate a Python virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. Install dependencies:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

If your OS enforces system package management (PEP 668), create and use the virtual environment before installing.

---

## Database initialization

1. Ensure PostgreSQL is running. On most Linux systems:

```bash
sudo systemctl start postgresql
systemctl status postgresql
```

2. Create (or confirm) the project database and user. Example using `psql` as a superuser:

```sql
-- run inside `sudo -iu postgres psql`
CREATE USER agrisure_admin WITH PASSWORD 'your_password_here';
CREATE DATABASE agrisure_db OWNER agrisure_admin;
\c agrisure_db
CREATE EXTENSION IF NOT EXISTS postgis;
```

3. Apply the schema from `init_schema.sql`:

```bash
psql -U agrisure_admin -d agrisure_db -h localhost -f init_schema.sql
```

4. (Optional) Seed the database from CSV using the provided seeder:

```bash
# Ensure .venv is activated
python seed_database.py
```

The seeder expects CSV files referenced within the script (e.g., `pabs_results.csv`). Review and adapt `seed_database.py` if your CSV filenames or column headers differ.

---

## Running the API server

Start the FastAPI development server with Uvicorn (reload enabled):

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Once running:

- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc

---

## Important files and how to use them

- `app/main.py`: Register routers and middleware. Add new routers under `app/api/` and include them here if needed.
- `app/core/database.py`: Contains `engine`, `SessionLocal`, `Base`, and the `get_db` dependency. Update `SQLALCHEMY_DATABASE_URL` here for your environment.
- `app/models/models.py`: Canonical ORM definitions. Update or extend models here when database schema changes.
- `init_schema.sql`: Source of truth for the SQL schema. Use this for fresh DB provisioning.
- `seed_database.py`: Procedural seeder for CSV -> DB. Useful for demo data.
- `requirements.txt`: Pin and install the Python packages required to run the backend.

---

## Developer notes

- Keep model changes synchronized between `app/models/models.py` and `init_schema.sql`.
- Prefer relationship-based joins in SQLAlchemy (e.g., `join(Model.relationship_attr)`) to avoid ambiguous join errors.
- When inserting large CSVs, the upload endpoints and seeder attempt to avoid duplicate parent records (farmers/boundaries) using idempotent checks.

---

## Troubleshooting

- If Uvicorn fails to import `app`, ensure your working directory is the project root and `PYTHONPATH` includes the backend folder, or run Uvicorn from the `backend` directory.

```bash
# example if running from repo root
PYTHONPATH=$(pwd)/backend uvicorn app.main:app --reload
```

- Database connection errors: verify credentials in `app/core/database.py` and that Postgres is listening on the configured host/port.

---

## Contact / Next steps

For questions about the backend implementation or to add API documentation, open an issue or contact the project maintainers.

If you want, I can add an `API Endpoints` section documenting currently exposed routes (e.g., `/api/upload/csv`, `/api/assessments`) and small example requests.
