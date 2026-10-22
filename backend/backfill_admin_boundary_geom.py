"""One-off backfill: populate tbl_admin_boundaries.boundary_geom from the static
frontend/public/data/region10-boundaries.geojson reference file, so GeoServer can
publish region boundaries as a live WFS layer instead of the bundled static file.

The geojson has one polygon per municipality (91 features); tbl_admin_boundaries
rows are per barangay, so every barangay row under a given (province, municipality)
receives the same municipality outline. Matched on (province, municipality) text,
not psgc_code, because the geojson's psgc_municipality codes are municipality-level
(...000 suffix) and don't correspond to any single barangay's psgc_code.

Run once after applying the boundary_geom column (see .claude/GEOSERVER_SETUP.md).
Safe to re-run: it always overwrites boundary_geom for matching rows.
"""
import json

import psycopg2

DB_CONFIG = {
    "dbname": "agrisure_db",
    "user": "agrisure_admin",
    "password": "agrisure_password",
    "host": "localhost",
    "port": "5432",
}

GEOJSON_PATH = "../frontend/public/data/region10-boundaries.geojson"


def run_backfill():
    print("Loading region10-boundaries.geojson...")
    with open(GEOJSON_PATH) as f:
        boundaries = json.load(f)

    print("Connecting to database...")
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    updated = 0
    unmatched = []
    for feature in boundaries["features"]:
        props = feature["properties"]
        province = props["province"]
        municipality = props["municipality"]
        geom_json = json.dumps(feature["geometry"])

        cur.execute(
            """
            UPDATE tbl_admin_boundaries
            SET boundary_geom = ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))
            WHERE province = %s AND municipality = %s
            """,
            (geom_json, province, municipality),
        )
        if cur.rowcount == 0:
            unmatched.append((province, municipality))
        else:
            updated += cur.rowcount

    conn.commit()
    cur.close()
    conn.close()

    print(f"Updated boundary_geom on {updated} row(s).")
    if unmatched:
        print(f"{len(unmatched)} geojson feature(s) had no matching tbl_admin_boundaries rows "
              "(municipality has no seeded farms/barangays yet):")
        for province, municipality in unmatched:
            print(f"  - {municipality}, {province}")


if __name__ == "__main__":
    run_backfill()
