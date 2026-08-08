import random
from datetime import date, timedelta

import psycopg2

# Same connection convention as seed_database.py.
DB_CONFIG = {
    "dbname": "agrisure_db",
    "user": "agrisure_admin",
    "password": "agrisure_password",
    "host": "localhost",
    "port": "5432",
}

# How many new *active* InsuranceRecord rows to add. "Active" mirrors the same
# definition backend/app/api/farms.py's active_only filter and
# backend/app/api/insurance.py's summary endpoint already use:
# effectivity_date <= today <= expiry_date.
TARGET_NEW_ACTIVE_RECORDS = 1000

# Matches pabs_results.csv's template row convention (2.50 ha -> ₱62,500.00
# InsuredAmountofCover, i.e. ~₱25,000/ha) rather than a flat amount, so the
# new records don't stand out from real ones by coverage size alone.
AMOUNT_PER_HECTARE = 25000
PROGRAM_TYPE = "Rice Parametric"  # matches pabs_results.csv's Program Type column

# Deliberately distinct from both the real dataset's plain numeric policy_no
# (e.g. "1192155") and the existing large synthetic batch's "POL<digits>"
# (e.g. "POL10483323900") -- makes this seeding batch trivially identifiable
# and greppable/removable later (`WHERE policy_no LIKE 'POL-SEED-%'`) without
# touching real or previously-seeded data.
POLICY_PREFIX = "POL-SEED-"


def run():
    print("Connecting to database...")
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    today = date.today()

    print(f"Finding up to {TARGET_NEW_ACTIVE_RECORDS} farms with no currently-active insurance...")
    cur.execute(
        """
        SELECT f.farm_id, f.farmer_id, f.area_size
        FROM tbl_farms f
        WHERE NOT EXISTS (
            SELECT 1 FROM tbl_insurance_records ir
            WHERE ir.farm_id = f.farm_id
              AND ir.effectivity_date <= %s
              AND ir.expiry_date >= %s
        )
        ORDER BY random()
        LIMIT %s
        """,
        (today, today, TARGET_NEW_ACTIVE_RECORDS),
    )
    candidates = cur.fetchall()

    if len(candidates) < TARGET_NEW_ACTIVE_RECORDS:
        print(
            f"Only found {len(candidates)} eligible farms without active coverage "
            f"(requested {TARGET_NEW_ACTIVE_RECORDS}) -- inserting what's available."
        )

    inserted = 0
    for farm_id, farmer_id, area_size in candidates:
        # Effectivity spread over the last 30 days rather than all on one date,
        # so the new records read as coverage that started at different recent
        # points instead of one obviously-batch-inserted date. 1-year expiry
        # matches a standard annual policy duration.
        effectivity_date = today - timedelta(days=random.randint(0, 30))
        expiry_date = effectivity_date + timedelta(days=365)

        area = float(area_size) if area_size is not None else 1.0
        amount_cover = round(area * AMOUNT_PER_HECTARE, 2)
        policy_no = f"{POLICY_PREFIX}{farm_id}"

        cur.execute(
            """
            INSERT INTO tbl_insurance_records
                (farmer_id, farm_id, policy_no, program_type, effectivity_date, expiry_date, amount_cover)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (policy_no, farm_id) DO NOTHING
            """,
            (farmer_id, farm_id, policy_no, PROGRAM_TYPE, effectivity_date, expiry_date, amount_cover),
        )
        inserted += cur.rowcount

    conn.commit()
    cur.close()
    conn.close()
    print(f"Inserted {inserted} new active InsuranceRecord rows.")


if __name__ == "__main__":
    run()
