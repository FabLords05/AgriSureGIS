"""One-off mock-data seeder: creates a fictional typhoon ("ALBRITCH", clearly not a
real PAGASA name) with ten Tropical Cyclone Bulletins 6 hours apart, tracking
westward across Bukidnon and carrying a realistic escalate-then-weaken wind-signal
arc (TD -> TS -> STS -> TY peak -> STS -> TS -> TD -> Low Pressure Area) over
Lantapan, Impasug-ong, City of Malaybalay, and Maramag -- so the Assessment &
Reporting module's per-typhoon exposure panel has real data to show while testing
usability with mock_farmers_albritch_bukidnon.csv (Karylle Maagad/Lantapan,
Fabio Tugonon/Impasug-ong, James Gayla/City of Malaybalay+Maramag).

Directly inserts bulletins/signals -- deliberately bypasses BulletinParserService
and the PAGASA scrape/parse pipeline entirely (no PDFs involved), per Fabio's
request to skip scraping for this mock scenario.

Does NOT touch tbl_area_exposure_summary or tbl_risk_assessment directly -- run the
app's own "Compute Exposure Summary" (Monitoring) and "Compute Assessments"
(Assessment & Reporting) actions afterward, so the rest of the pipeline is exercised
for real rather than mocked further.

Requires tbl_admin_boundaries rows for Lantapan, Impasug-ong, City of Malaybalay,
and Maramag -- ExposureCalculatorService matches tbl_tcb_signals.area_name against
tbl_admin_boundaries.municipality, case-insensitively. These rows get auto-created
by the CSV upload endpoint (mock_farmers_albritch_bukidnon.csv) if they don't
already exist, so upload that CSV first.

Safe to re-run: skips creating the typhoon/bulletins again if a typhoon named
"ALBRITCH" (2026) already exists.
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

TYPHOON_NAME = "ALBRITCH"
TYPHOON_YEAR = 2026

# island_group: 0=Luzon, 1=Visayas, 2=Mindanao (matches the real convention in
# backend/app/services/bulletin_parser.py -- the older seed_mock_typhoon.py script
# predates that convention and used a placeholder value of 3).
MINDANAO = 2

BULLETINS = [
    {
        "bulletin_count": 1,
        "title": 'Tropical Cyclone Bulletin No. 1 for Tropical Depression "ALBRITCH" (MOCK/TEST DATA)',
        "category": "Tropical Depression",
        "max_sustained_winds": 45,
        "gustiness": 60,
        "issued_at": datetime(2026, 8, 10, 8, 0),
        "expires_at": datetime(2026, 8, 10, 14, 0),
        "center_lon": 128.2,
        "center_lat": 7.8,
        "signals": [
            {"signal_level": 1, "area_name": "Lantapan"},
            {"signal_level": 1, "area_name": "Impasug-ong"},
        ],
    },
    {
        "bulletin_count": 2,
        "title": 'Tropical Cyclone Bulletin No. 2 for Tropical Depression "ALBRITCH" (MOCK/TEST DATA)',
        "category": "Tropical Depression",
        "max_sustained_winds": 55,
        "gustiness": 70,
        "issued_at": datetime(2026, 8, 10, 14, 0),
        "expires_at": datetime(2026, 8, 10, 20, 0),
        "center_lon": 127.5,
        "center_lat": 7.9,
        "signals": [
            {"signal_level": 1, "area_name": "Lantapan"},
            {"signal_level": 1, "area_name": "Impasug-ong"},
            {"signal_level": 1, "area_name": "City of Malaybalay"},
            {"signal_level": 1, "area_name": "Maramag"},
        ],
    },
    {
        "bulletin_count": 3,
        "title": 'Tropical Cyclone Bulletin No. 3 for Tropical Storm "ALBRITCH" (MOCK/TEST DATA)',
        "category": "Tropical Storm",
        "max_sustained_winds": 65,
        "gustiness": 80,
        "issued_at": datetime(2026, 8, 10, 20, 0),
        "expires_at": datetime(2026, 8, 11, 2, 0),
        "center_lon": 126.7,
        "center_lat": 8.0,
        "signals": [
            {"signal_level": 2, "area_name": "Lantapan"},
            {"signal_level": 2, "area_name": "Impasug-ong"},
            {"signal_level": 2, "area_name": "City of Malaybalay"},
            {"signal_level": 2, "area_name": "Maramag"},
        ],
    },
    {
        "bulletin_count": 4,
        "title": 'Tropical Cyclone Bulletin No. 4 for Severe Tropical Storm "ALBRITCH" (MOCK/TEST DATA)',
        "category": "Severe Tropical Storm",
        "max_sustained_winds": 95,
        "gustiness": 120,
        "issued_at": datetime(2026, 8, 11, 2, 0),
        "expires_at": datetime(2026, 8, 11, 8, 0),
        "center_lon": 125.9,
        "center_lat": 8.1,
        "signals": [
            {"signal_level": 2, "area_name": "Lantapan"},
            {"signal_level": 2, "area_name": "Impasug-ong"},
            {"signal_level": 3, "area_name": "City of Malaybalay"},
            {"signal_level": 3, "area_name": "Maramag"},
        ],
    },
    {
        "bulletin_count": 5,
        "title": 'Tropical Cyclone Bulletin No. 5 for Typhoon "ALBRITCH" (MOCK/TEST DATA)',
        "category": "Typhoon",
        "max_sustained_winds": 130,
        "gustiness": 160,
        "issued_at": datetime(2026, 8, 11, 8, 0),
        "expires_at": datetime(2026, 8, 11, 14, 0),
        "center_lon": 125.3,
        "center_lat": 8.2,
        "signals": [
            {"signal_level": 3, "area_name": "Lantapan"},
            {"signal_level": 3, "area_name": "Impasug-ong"},
            {"signal_level": 3, "area_name": "City of Malaybalay"},
            {"signal_level": 4, "area_name": "Maramag"},
        ],
    },
    {
        # Peak intensity, eye passing nearest Bukidnon.
        "bulletin_count": 6,
        "title": 'Tropical Cyclone Bulletin No. 6 for Typhoon "ALBRITCH" (MOCK/TEST DATA)',
        "category": "Typhoon",
        "max_sustained_winds": 155,
        "gustiness": 190,
        "issued_at": datetime(2026, 8, 11, 14, 0),
        "expires_at": datetime(2026, 8, 11, 20, 0),
        "center_lon": 124.9,
        "center_lat": 8.25,
        "signals": [
            {"signal_level": 4, "area_name": "Lantapan"},
            {"signal_level": 4, "area_name": "Impasug-ong"},
            {"signal_level": 4, "area_name": "City of Malaybalay"},
            {"signal_level": 4, "area_name": "Maramag"},
        ],
    },
    {
        "bulletin_count": 7,
        "title": 'Tropical Cyclone Bulletin No. 7 for Severe Tropical Storm "ALBRITCH" (MOCK/TEST DATA)',
        "category": "Severe Tropical Storm",
        "max_sustained_winds": 100,
        "gustiness": 125,
        "issued_at": datetime(2026, 8, 11, 20, 0),
        "expires_at": datetime(2026, 8, 12, 2, 0),
        "center_lon": 124.4,
        "center_lat": 8.3,
        "signals": [
            {"signal_level": 3, "area_name": "Lantapan"},
            {"signal_level": 3, "area_name": "Impasug-ong"},
            {"signal_level": 3, "area_name": "City of Malaybalay"},
            {"signal_level": 3, "area_name": "Maramag"},
        ],
    },
    {
        "bulletin_count": 8,
        "title": 'Tropical Cyclone Bulletin No. 8 for Tropical Storm "ALBRITCH" (MOCK/TEST DATA)',
        "category": "Tropical Storm",
        "max_sustained_winds": 70,
        "gustiness": 90,
        "issued_at": datetime(2026, 8, 12, 2, 0),
        "expires_at": datetime(2026, 8, 12, 8, 0),
        "center_lon": 123.8,
        "center_lat": 8.4,
        "signals": [
            {"signal_level": 2, "area_name": "Lantapan"},
            {"signal_level": 2, "area_name": "Impasug-ong"},
            {"signal_level": 2, "area_name": "City of Malaybalay"},
            {"signal_level": 2, "area_name": "Maramag"},
        ],
    },
    {
        "bulletin_count": 9,
        "title": 'Tropical Cyclone Bulletin No. 9 for Tropical Depression "ALBRITCH" (MOCK/TEST DATA)',
        "category": "Tropical Depression",
        "max_sustained_winds": 50,
        "gustiness": 65,
        "issued_at": datetime(2026, 8, 12, 8, 0),
        "expires_at": datetime(2026, 8, 12, 14, 0),
        "center_lon": 123.2,
        "center_lat": 8.5,
        "signals": [
            {"signal_level": 1, "area_name": "Lantapan"},
            {"signal_level": 1, "area_name": "Impasug-ong"},
            {"signal_level": 1, "area_name": "City of Malaybalay"},
            {"signal_level": 1, "area_name": "Maramag"},
        ],
    },
    {
        # Final bulletin: weakened below tropical depression strength, no signal
        # hoisted anywhere -- mirrors the real "Low Pressure Area (formerly ...)"
        # pattern found in a live PAGASA bulletin (TCB#13_luis.pdf) that motivated
        # the bulletin-title-parsing fix earlier in this session.
        "bulletin_count": 10,
        "title": 'Tropical Cyclone Bulletin No. 10F: Low Pressure Area (formerly "ALBRITCH") (MOCK/TEST DATA)',
        "category": "Low Pressure Area",
        "max_sustained_winds": None,
        "gustiness": None,
        "issued_at": datetime(2026, 8, 12, 14, 0),
        "expires_at": datetime(2026, 8, 12, 20, 0),
        "center_lon": 122.5,
        "center_lat": 8.6,
        "signals": [],
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
        "INSERT INTO tbl_typhoons (name, year, is_active) VALUES (%s, %s, FALSE) RETURNING typhoon_id",
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
        print(f"  Created bulletin #{b['bulletin_count']} ({b['category']}) -- tcb_id={tcb_id}")

        for s in b["signals"]:
            cur.execute(
                """
                INSERT INTO tbl_tcb_signals (tcb_id, signal_level, island_group, area_name)
                VALUES (%s, %s, %s, %s)
                """,
                (tcb_id, s["signal_level"], MINDANAO, s["area_name"]),
            )
            print(f"    Signal No. {s['signal_level']} over {s['area_name']}")

    conn.commit()
    cur.close()
    conn.close()

    print()
    print("Done. Next steps in the running app:")
    print("  1. Upload mock_farmers_albritch_bukidnon.csv via the Spatial Analysis & Data Import module")
    print("     (or it may already be uploaded via curl -- check Farm Records first).")
    print(f"  2. Monitoring module -> find typhoon {TYPHOON_NAME} -> Compute Exposure Summary")
    print("     (populates tbl_area_exposure_summary for Lantapan/Impasug-ong/City of Malaybalay/Maramag)")
    print("  3. Assessment & Reporting module -> click typhoon "
          f"{TYPHOON_NAME} -> Compute Assessments")
    print("     (populates tbl_risk_assessment payouts for the mock CSV policies)")


if __name__ == "__main__":
    run_seed()
