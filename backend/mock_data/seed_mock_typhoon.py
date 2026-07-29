"""One-off mock-data seeder: creates a fictional typhoon ("MARISOL", clearly not a
real PAGASA name) with two Tropical Cyclone Bulletins ~12 hours apart, carrying wind
signals over Talakag (Bukidnon) and Claveria (Misamis Oriental) only -- so the
Assessment & Reporting module's per-typhoon exposure panel has real data to show
while testing usability with mock_farmers_talakag_claveria.csv / gpx/*.gpx.

Does NOT touch tbl_area_exposure_summary or tbl_risk_assessment directly -- run the
app's own "Compute Exposure Summary" (Monitoring) and "Compute Assessments"
(Assessment & Reporting) actions afterward, so the rest of the pipeline is exercised
for real rather than mocked further.

Requires tbl_admin_boundaries rows for Talakag and Claveria to already exist
(ExposureCalculatorService matches tbl_tcb_signals.area_name against
tbl_admin_boundaries.municipality, case-insensitively) -- i.e. seed_database.py
must have been run already.

Safe to re-run: skips creating the typhoon/bulletins again if a typhoon named
"MARISOL" (2026) already exists.
"""
from datetime import datetime

import psycopg2

DB_CONFIG = {
    "dbname": "agrisure_db",
    "user": "agrisure_admin",
    "password": "agrisure_password",
    "host": "localhost",
    "port": "5432",
}

TYPHOON_NAME = "MARISOL"
TYPHOON_YEAR = 2026

# Both bulletins list the same two municipalities so each accumulates the full
# 12-hour gap between them as total_exposure_hours (matches tbl_recsap_matrix's
# 12h bucket) -- see ExposureCalculatorService.compute_for_typhoon().
BULLETINS = [
    {
        "bulletin_count": 1,
        "title": 'Tropical Cyclone Bulletin No. 1 for Typhoon "MARISOL" (MOCK/TEST DATA)',
        "category": "TYPHOON",
        "max_sustained_winds": 130,
        "gustiness": 160,
        "issued_at": datetime(2026, 7, 25, 8, 0),
        "expires_at": datetime(2026, 7, 25, 20, 0),
        "center_lon": 124.95,
        "center_lat": 8.45,
        "signals": [
            {"signal_level": 3, "island_group": 3, "area_name": "Talakag"},
            {"signal_level": 2, "island_group": 3, "area_name": "Claveria"},
        ],
    },
    {
        "bulletin_count": 2,
        "title": 'Tropical Cyclone Bulletin No. 2 for Typhoon "MARISOL" (MOCK/TEST DATA)',
        "category": "TYPHOON",
        "max_sustained_winds": 120,
        "gustiness": 150,
        "issued_at": datetime(2026, 7, 25, 20, 0),
        "expires_at": datetime(2026, 7, 26, 8, 0),
        "center_lon": 124.80,
        "center_lat": 8.55,
        "signals": [
            {"signal_level": 3, "island_group": 3, "area_name": "Talakag"},
            {"signal_level": 2, "island_group": 3, "area_name": "Claveria"},
        ],
    },
]


def run_seed():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    cur.execute(
        "SELECT typhoon_id FROM tbl_typhoons WHERE name = %s AND year = %s",
        (TYPHOON_NAME, TYPHOON_YEAR),
    )
    existing = cur.fetchone()
    if existing:
        print(f"Typhoon {TYPHOON_NAME} ({TYPHOON_YEAR}) already exists "
              f"(typhoon_id={existing[0]}) -- skipping, nothing inserted.")
        cur.close()
        conn.close()
        return

    cur.execute(
        "INSERT INTO tbl_typhoons (name, year, is_active) VALUES (%s, %s, TRUE) RETURNING typhoon_id",
        (TYPHOON_NAME, TYPHOON_YEAR),
    )
    typhoon_id = cur.fetchone()[0]
    print(f"Created typhoon {TYPHOON_NAME} ({TYPHOON_YEAR}) -- typhoon_id={typhoon_id}")

    for b in BULLETINS:
        cur.execute(
            """
            INSERT INTO tbl_tropical_cyclone_bulletins
                (typhoon_id, title, bulletin_count, category, max_sustained_winds,
                 gustiness, issued_at, expires_at, center_geom)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326))
            RETURNING tcb_id
            """,
            (
                typhoon_id, b["title"], b["bulletin_count"], b["category"],
                b["max_sustained_winds"], b["gustiness"], b["issued_at"], b["expires_at"],
                b["center_lon"], b["center_lat"],
            ),
        )
        tcb_id = cur.fetchone()[0]
        print(f"  Created bulletin #{b['bulletin_count']} -- tcb_id={tcb_id}")

        for s in b["signals"]:
            cur.execute(
                """
                INSERT INTO tbl_tcb_signals (tcb_id, signal_level, island_group, area_name)
                VALUES (%s, %s, %s, %s)
                """,
                (tcb_id, s["signal_level"], s["island_group"], s["area_name"]),
            )
            print(f"    Signal No. {s['signal_level']} over {s['area_name']}")

    conn.commit()
    cur.close()
    conn.close()

    print()
    print("Done. Next steps in the running app:")
    print(f"  1. Upload mock_farmers_talakag_claveria.csv and gpx/*.gpx via the Data Ingestion module.")
    print(f"  2. Monitoring module -> find typhoon {TYPHOON_NAME} -> Compute Exposure Summary")
    print("     (populates tbl_area_exposure_summary for Talakag + Claveria)")
    print("  3. Assessment & Reporting module -> click typhoon "
          f"{TYPHOON_NAME} -> Compute Assessments")
    print("     (populates tbl_risk_assessment payouts for the mock CSV policies)")


if __name__ == "__main__":
    run_seed()
