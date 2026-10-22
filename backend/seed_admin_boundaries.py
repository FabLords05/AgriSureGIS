"""Loads EVERY barangay in app/data/psgc_nationwide_boundaries.csv into
tbl_admin_boundaries (2026-09-30).

Before this, boundary rows were only created on demand for barangays that
had farms (seed_database.py, upload.py). So a PAGASA TCWS area outside those
barangays -- e.g. all of Luzon/Visayas -- could never resolve to a boundary,
and bulletin_parser.py dropped it from tbl_tcb_signals / exposure.

Idempotent: ON CONFLICT (psgc_code) DO NOTHING, so it's safe on an existing DB
-- rows seed_database.py/upload.py already created carry the same PSGC codes
and are left untouched. boundary_geom stays NULL for new rows (only Region X
polygons exist -- see backfill_admin_boundary_geom.py); exposure matching is
by (province, municipality) name, so it doesn't need geometry.

Run from backend/ (seed_all.py runs it as its first step):

    python seed_admin_boundaries.py
"""
import os

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values

# Same connection the backend uses (backend/.env's DATABASE_URL, see
# app/core/database.py); DB_CONFIG below is only the local-dev fallback.
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

DB_CONFIG = {
    "dbname": "agrisure_db",
    "user": "agrisure_admin",
    "password": "agrisure_password",
    "host": "localhost",
    "port": "5432",
}

PSGC_CSV_PATH = "app/data/psgc_nationwide_boundaries.csv"
BATCH_SIZE = 5000


def run():
    print("Loading PSGC CSV...")
    df = pd.read_csv(PSGC_CSV_PATH, dtype=str).dropna(subset=["psgc_code"])
    rows = list(df[["psgc_code", "province", "municipality", "barangay"]].itertuples(index=False, name=None))
    print(f"{len(rows)} barangay row(s), {df['province'].nunique()} province(s) in CSV.")

    print("Connecting to database...")
    if DATABASE_URL:
        # psycopg2 takes a plain libpq URI, not SQLAlchemy's "+psycopg2" dialect form.
        conn = psycopg2.connect(DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://"))
    else:
        conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    inserted = 0
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start:start + BATCH_SIZE]
        returned = execute_values(
            cur,
            """
            INSERT INTO tbl_admin_boundaries (psgc_code, province, municipality, barangay)
            VALUES %s
            ON CONFLICT (psgc_code) DO NOTHING
            RETURNING boundary_id
            """,
            batch,
            page_size=BATCH_SIZE,
            fetch=True,
        )
        inserted += len(returned)
    conn.commit()
    cur.close()
    conn.close()

    print(f"Inserted {inserted} new boundary row(s); {len(rows) - inserted} already existed.")


if __name__ == "__main__":
    run()
