"""
One-click reset for the ingestion demo (run via ../reset-demo-data.bat).

Splits the client's real Typhoon Tino export -- the PCIC10 insurance-records
CSV and its matching PCICX boundary GeoPackage -- into two even halves:

  USTP CAPSTONE/DEMO/already_ingested/   loaded into the DB by this script
  USTP CAPSTONE/DEMO/to_ingest/          left for a live upload in the UI
                                         (CSV first, then the .gpkg)

...then clears every farmer-side table and pre-ingests the already_ingested
half through the same functions the /api/upload/csv and /api/upload/gpkg
endpoints run, so it lands exactly as if it had been uploaded by hand.

Halves are split per farmer, not per row/FARMID: GpxFarmerMatcherService
falls back to "the farmer's only farm on file" and to a farmer-name match,
so a farmer whose farms straddled both halves could have a to_ingest
polygon land on an already_ingested farm. FARMERSID, FARMID and normalized
FARMER NAME are linked (union-find) across both files, and each linked
group goes wholly into one half.

Kept as-is: users, admin boundaries, RECSAP/indemnity matrices, crop-stage
mapping, typhoons, bulletins/signals, parser settings, activity log.

    python prepare_ingestion_demo.py               # split, confirm, reset, pre-ingest
    python prepare_ingestion_demo.py --yes         # same, no confirmation prompt
    python prepare_ingestion_demo.py --split-only  # only (re)write the DEMO files
"""
import argparse
import csv
import io
import logging
import re
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT_DIR / "USTP CAPSTONE-20261009T021551Z-1-001" / "USTP CAPSTONE"
SOURCE_CSV = SOURCE_DIR / "INSURANCE RECORDS" / "PCIC10 GPX 11-05-2025 WITH EXISTING IC AFFECTED BY TY.csv"
SOURCE_GPKG = SOURCE_DIR / "GPX" / "PCICX GPX_EXISTING IC AFFECTED BY TY TINO_11-05-2025.gpkg"
DEMO_DIR = SOURCE_DIR / "DEMO"
ALREADY_INGESTED_DIR = DEMO_DIR / "already_ingested"
TO_INGEST_DIR = DEMO_DIR / "to_ingest"

ALREADY_INGESTED = "already_ingested"
TO_INGEST = "to_ingest"

# Farmer-side tables only. TRUNCATE ... CASCADE also empties anything else
# holding a foreign key into these; nothing outside this list does today.
CLEARED_TABLES = (
    "tbl_planted_verification",
    "tbl_insurance_usage",
    "tbl_risk_assessment",
    "tbl_insurance_records",
    "tbl_farms",
    "tbl_farmers_profile",
    "tbl_area_exposure_summary",
)


def _normalize(value) -> str:
    """Same bare-alphanumeric collapse the CSV/GPKG ingest uses for matching."""
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _id_text(value) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value or "").strip()


class _UnionFind:
    def __init__(self):
        self._parent: dict[str, str] = {}

    def find(self, key: str) -> str:
        self._parent.setdefault(key, key)
        while self._parent[key] != key:
            self._parent[key] = self._parent[self._parent[key]]
            key = self._parent[key]
        return key

    def union(self, *keys: str) -> None:
        roots = [self.find(k) for k in keys if k]
        for other in roots[1:]:
            self._parent[other] = roots[0]


def _identity_keys(farmers_id, farm_id, farmer_name) -> list[str]:
    keys = []
    if _id_text(farmers_id):
        keys.append(f"farmer:{_id_text(farmers_id)}")
    if _id_text(farm_id):
        keys.append(f"farm:{_id_text(farm_id)}")
    if _normalize(farmer_name):
        keys.append(f"name:{_normalize(farmer_name)}")
    return keys


def _read_csv(path: Path) -> tuple[str, list[str], list[list[str]]]:
    """Same encoding fallback as upload_csv(): UTF-8 first, then cp1252."""
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if encoding == "utf-8-sig" and not raw.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8"  # don't add a BOM the client's file doesn't have
    reader = csv.reader(io.StringIO(text, newline=""))
    header = next(reader)
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    return encoding, header, rows


def _gpkg_feature_table(conn: sqlite3.Connection) -> str:
    tables = conn.execute("SELECT table_name FROM gpkg_contents WHERE data_type = 'features'").fetchall()
    if len(tables) != 1:
        raise ValueError(f"Expected one feature layer in {SOURCE_GPKG.name}, found {len(tables)}.")
    return tables[0][0]


def _read_gpkg_identities(path: Path) -> tuple[str, list[tuple[int, list[str]]]]:
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        table = _gpkg_feature_table(conn)
        rows = conn.execute(f'SELECT fid, "FARMERSID", "FARMID", "FARMER NAME" FROM "{table}"').fetchall()
    finally:
        conn.close()
    return table, [(fid, _identity_keys(farmers_id, farm_id, name)) for fid, farmers_id, farm_id, name in rows]


def split_source_files() -> dict[str, dict[str, int]]:
    """Writes both halves under DEMO/ and returns per-half row/feature counts."""
    for path in (SOURCE_CSV, SOURCE_GPKG):
        if not path.exists():
            raise FileNotFoundError(f"Source file not found: {path}")

    encoding, header, csv_rows = _read_csv(SOURCE_CSV)
    column = {name.strip().upper(): index for index, name in enumerate(header)}
    for required in ("FARMERSID", "FARMID", "FARMER NAME"):
        if required not in column:
            raise ValueError(f'{SOURCE_CSV.name} has no "{required}" column.')

    def csv_keys(row: list[str]) -> list[str]:
        return _identity_keys(row[column["FARMERSID"]], row[column["FARMID"]], row[column["FARMER NAME"]])

    table, gpkg_features = _read_gpkg_identities(SOURCE_GPKG)

    groups = _UnionFind()
    for row in csv_rows:
        groups.union(*csv_keys(row))
    for _, keys in gpkg_features:
        groups.union(*keys)

    # Groups in first-appearance order (the CSV is grouped by area, so this
    # keeps both halves spread across every province), each handed to
    # whichever half currently has fewer CSV rows.
    group_rows: dict[str, int] = {}
    for row in csv_rows:
        root = groups.find(csv_keys(row)[0])
        group_rows[root] = group_rows.get(root, 0) + 1
    half_of_group: dict[str, str] = {}
    totals = {ALREADY_INGESTED: 0, TO_INGEST: 0}
    for root, count in group_rows.items():
        half = ALREADY_INGESTED if totals[ALREADY_INGESTED] <= totals[TO_INGEST] else TO_INGEST
        half_of_group[root] = half
        totals[half] += count

    def half_of(keys: list[str]) -> str:
        # A GPKG feature with no CSV row at all can't match anything either
        # way -- leave it in to_ingest, where its "not applied" report is visible.
        return half_of_group.get(groups.find(keys[0]), TO_INGEST) if keys else TO_INGEST

    counts = {ALREADY_INGESTED: {"csv_rows": 0, "gpkg_features": 0}, TO_INGEST: {"csv_rows": 0, "gpkg_features": 0}}
    for half, folder in ((ALREADY_INGESTED, ALREADY_INGESTED_DIR), (TO_INGEST, TO_INGEST_DIR)):
        folder.mkdir(parents=True, exist_ok=True)

        half_rows = [row for row in csv_rows if half_of(csv_keys(row)) == half]
        with open(folder / SOURCE_CSV.name, "w", encoding=encoding, newline="") as fh:
            writer = csv.writer(fh, lineterminator="\r\n")
            writer.writerow(header)
            writer.writerows(half_rows)
        counts[half]["csv_rows"] = len(half_rows)

        # Copy the whole GeoPackage and delete the other half's features --
        # keeps the layer schema, SRS and rtree index exactly as the client's
        # file has them. The rtree/feature-count delete triggers are plain SQL
        # (no SpatiaLite functions), so stdlib sqlite3 can fire them.
        gpkg_path = folder / SOURCE_GPKG.name
        shutil.copyfile(SOURCE_GPKG, gpkg_path)
        drop_fids = [(fid,) for fid, keys in gpkg_features if half_of(keys) != half]
        conn = sqlite3.connect(gpkg_path)
        try:
            conn.executemany(f'DELETE FROM "{table}" WHERE fid = ?', drop_fids)
            # Shrink the layer extent QGIS zooms to so it matches what's left.
            conn.execute(
                f"""
                UPDATE gpkg_contents SET
                    min_x = (SELECT MIN(minx) FROM "rtree_{table}_geom"),
                    min_y = (SELECT MIN(miny) FROM "rtree_{table}_geom"),
                    max_x = (SELECT MAX(maxx) FROM "rtree_{table}_geom"),
                    max_y = (SELECT MAX(maxy) FROM "rtree_{table}_geom")
                WHERE table_name = ?
                """,
                (table,),
            )
            conn.commit()
            conn.execute("VACUUM")
            counts[half]["gpkg_features"] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        finally:
            conn.close()

    return counts


def clear_farmer_data() -> None:
    from sqlalchemy import text

    from app.core.database import SessionLocal
    from app.core.farms_cache import invalidate_farms_cache
    from app.core.farms_view import refresh_farm_latest_insurance_view

    db = SessionLocal()
    try:
        db.execute(text(f"TRUNCATE {', '.join(CLEARED_TABLES)} RESTART IDENTITY CASCADE"))
        db.commit()
        refresh_farm_latest_insurance_view(db)
    finally:
        db.close()
    invalidate_farms_cache()


def ingest_csv(path: Path) -> dict:
    """Runs upload_csv()'s background worker inline, on the same parsed frame."""
    import pandas as pd

    from app.api.upload import _run_csv_ingestion
    from app.core import upload_jobs

    raw = path.read_bytes()
    dataframe = None
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            dataframe = pd.read_csv(io.BytesIO(raw), encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    if dataframe is None:
        raise ValueError(f"Unable to decode {path.name}.")

    job_id = upload_jobs.create_job(total=len(dataframe))
    _run_csv_ingestion(job_id, path.name, dataframe)
    job = upload_jobs.get_job(job_id)
    if job.status != "done":
        raise RuntimeError(job.error or "CSV ingestion did not finish.")
    return job.result


def ingest_gpkg(path: Path) -> dict:
    """Calls the /api/upload/gpkg handler directly with the file wrapped as an upload."""
    from fastapi import UploadFile

    from app.api.upload import upload_gpkg
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        with open(path, "rb") as fh:
            return upload_gpkg(file=UploadFile(file=fh, filename=path.name), db=db)
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset the DB to the ingestion-demo starting state.")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    parser.add_argument("--split-only", action="store_true", help="only (re)write the DEMO files; don't touch the DB")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    print(f"Splitting source files into {DEMO_DIR} ...")
    counts = split_source_files()
    for half, folder in ((ALREADY_INGESTED, ALREADY_INGESTED_DIR), (TO_INGEST, TO_INGEST_DIR)):
        print(f"  {half:<17} {counts[half]['csv_rows']:>5} CSV row(s), "
              f"{counts[half]['gpkg_features']:>5} GPKG feature(s)  -> {folder}")
    if args.split_only:
        return

    if not args.yes:
        print("\nThis DELETES every farmer, farm, insurance record, assessment, insurance-usage,")
        print("planted-verification and exposure-summary row, then pre-ingests the")
        print("already_ingested half. Users, boundaries, matrices, typhoons and bulletins are kept.")
        if input("Type YES to continue: ").strip() != "YES":
            print("Cancelled -- database not touched.")
            return

    print("\nClearing farmer-side tables ...")
    clear_farmer_data()

    print("\nIngesting already_ingested CSV ...")
    csv_result = ingest_csv(ALREADY_INGESTED_DIR / SOURCE_CSV.name)
    print(f"  {csv_result['rows_inserted']} inserted, {csv_result['rows_skipped']} skipped, "
          f"{csv_result['rows_failed']} failed")
    for failure in csv_result["failures"][:10]:
        print(f"    row {failure['row']}: {failure['error']}")

    print("\nIngesting already_ingested GeoPackage ...")
    gpkg_result = ingest_gpkg(ALREADY_INGESTED_DIR / SOURCE_GPKG.name)
    print(f"  {gpkg_result['features_updated']} updated, {gpkg_result['features_failed']} not applied, "
          f"{gpkg_result['duplicates_skipped']} duplicate(s) skipped")
    for failure in gpkg_result["failures"][:10]:
        print(f"    {failure['file_name']}: {failure['error']}")

    print(f"\nDone. Upload these through the UI for the live demo (CSV first, then the .gpkg):")
    print(f"  {TO_INGEST_DIR / SOURCE_CSV.name}")
    print(f"  {TO_INGEST_DIR / SOURCE_GPKG.name}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\n!!! Failed: {exc!r}")
        sys.exit(1)
