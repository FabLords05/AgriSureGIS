"""
Adds TARGET_NEW_FARMS synthetic farms (+ one new synthetic farmer each) for
local scale-testing of the on-demand-pagination redesign (see
.claude/FUNCTION_CHANGES.md, 2026-08-17) -- Fabio's real local dataset sits
at ~48,588 farms; this tops it up toward TARGET_NEW_FARMS synthetic farms on
top (currently 1,000,000, for testing at the top of the 100k-1M range
discussed) so pagination/table/map behavior can be exercised at real scale
without waiting on real PABS data to ever reach that size.

Deliberately narrow scope: only tbl_farmers_profile + tbl_farms rows.
No InsuranceRecord/RiskAssessment rows -- that's what
backend/seed_active_insurance.py is for, run separately if needed.
No location_geom -- matches the real dataset's own sparse-geometry pattern
(most real farms don't have an uploaded GPX boundary either); synthetic
bulk geometry isn't needed to test listing/pagination scale.

Safe to re-run after raising TARGET_NEW_FARMS: farmer index generation
always starts at 0, and `ON CONFLICT (rsbsa_no) DO NOTHING` + reading back
only the RETURNING rows that actually inserted means a rerun with a higher
target naturally picks up exactly where the last run left off (e.g. first
run at 100,000, then raised to 1,000,000: indices 0-99,999 skip as
conflicts, 100,000-999,999 insert as new) -- no need to track/pass an
explicit offset by hand.

Same connection convention as the other seed_*.py scripts. Bulk-inserts via
execute_values in batches (not one INSERT per row, and not one single
million-row statement) -- both a meaningfully faster round trip than
row-by-row, and a bounded amount of data held in memory/sent per statement.
"""
import random
import time

import psycopg2
from psycopg2.extras import execute_values

# Same connection convention as seed_database.py/seed_active_insurance.py.
DB_CONFIG = {
    "dbname": "agrisure_db",
    "user": "agrisure_admin",
    "password": "agrisure_password",
    "host": "localhost",
    "port": "5432",
}

TARGET_NEW_FARMS = 1_000_000
BATCH_SIZE = 5_000

# Distinct from real RSBSA numbers (e.g. "120961") and the CSV reference
# format -- makes this batch trivially identifiable/removable later
# (`WHERE rsbsa_no LIKE 'SEED-FARMER-%'` / `WHERE csv_farm_reference LIKE
# 'SEED-FARM-%'`) without touching real or previously-seeded data.
FARMER_PREFIX = "SEED-FARMER-"
FARM_PREFIX = "SEED-FARM-"

# Typical rice-farm size range, matching the spread already seen in
# docs/Rice Risk Exposure Region X 04-15-2026.csv (mostly 1-3 ha, occasional
# smaller/larger) rather than a flat value for every synthetic row.
MIN_AREA_HA = 0.5
MAX_AREA_HA = 5.0


def run():
    print("Connecting to database...")
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    print("Loading existing admin boundaries to link new farms against...")
    cur.execute("SELECT boundary_id FROM tbl_admin_boundaries")
    boundary_ids = [row[0] for row in cur.fetchall()]
    if not boundary_ids:
        print("No rows in tbl_admin_boundaries -- run seed_database.py first. Aborting.")
        cur.close()
        conn.close()
        return

    print(f"Inserting {TARGET_NEW_FARMS} synthetic farmers...")
    start = time.time()
    farmer_ids: list[int] = []
    for batch_start in range(0, TARGET_NEW_FARMS, BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, TARGET_NEW_FARMS)
        rows = [
            (f"{FARMER_PREFIX}{i:07d}", "SeedFarmer", f"{i:07d}", None)
            for i in range(batch_start, batch_end)
        ]
        inserted = execute_values(
            cur,
            """
            INSERT INTO tbl_farmers_profile (rsbsa_no, last_name, first_name, middle_name)
            VALUES %s
            ON CONFLICT (rsbsa_no) DO NOTHING
            RETURNING farmer_id
            """,
            rows,
            fetch=True,
        )
        farmer_ids.extend(row[0] for row in inserted)
        print(f"  farmers {batch_end}/{TARGET_NEW_FARMS}...")
    conn.commit()
    print(f"Inserted {len(farmer_ids)} farmers in {time.time() - start:.1f}s.")

    print(f"Inserting {len(farmer_ids)} synthetic farms (1 per new farmer)...")
    start = time.time()
    farms_inserted = 0
    for batch_start in range(0, len(farmer_ids), BATCH_SIZE):
        batch = farmer_ids[batch_start : batch_start + BATCH_SIZE]
        rows = [
            (
                farmer_id,
                random.choice(boundary_ids),
                f"{FARM_PREFIX}{farmer_id:07d}",
                None,  # georef_id -- not meaningful for synthetic rows
                round(random.uniform(MIN_AREA_HA, MAX_AREA_HA), 2),
            )
            for farmer_id in batch
        ]
        execute_values(
            cur,
            """
            INSERT INTO tbl_farms (farmer_id, boundary_id, csv_farm_reference, georef_id, area_size)
            VALUES %s
            """,
            rows,
        )
        farms_inserted += len(rows)
        print(f"  farms {batch_start + len(rows)}/{len(farmer_ids)}...")
    conn.commit()
    print(f"Inserted {farms_inserted} farms in {time.time() - start:.1f}s.")

    # This script writes straight to Postgres, bypassing the app entirely --
    # so GET /api/farms/'s Redis page cache (app/core/farms_cache.py) would
    # otherwise keep serving pre-seed page-1/total values for up to its
    # 300s TTL. No-ops gracefully if Redis isn't configured/running.
    try:
        import os

        import redis

        redis_url = os.getenv("REDIS_URL")
        if redis_url:
            client = redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
            for key in client.scan_iter("agrisuregis:farms:*"):
                client.delete(key)
            print("Invalidated Redis farms cache.")
    except Exception:
        pass  # Redis not installed/configured/running -- nothing to invalidate

    cur.close()
    conn.close()
    print(f"Done. tbl_farms should now read ~48,588 + {farms_inserted} = ~{48588 + farms_inserted}.")


if __name__ == "__main__":
    run()
