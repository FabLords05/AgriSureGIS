"""
One command to get the system presentation-ready (run via ../../simulate.bat ready).

Replaces the slow manual sequence -- reset results, upload CSV, upload GPKG,
seed OPONG, activate -- with one run that leaves only the app's own Compute
buttons to click. Deletes NO farm data: farmers, farms, insurance records,
OPONG's bulletins and every SAR row (radar readings, fetch coverage, planted
checks, field verifications) are kept -- SAR rows are keyed to farm_id and
typhoon_id with ON DELETE CASCADE, so deleting either would throw away the
slow Earth Engine fetches.

1. Clears OPONG's computed results via seed_opong_assessment_test's
   reset_assessment() (the same as `opong --reset`): computed assessment rows
   (crop-stage seed rows are kept -- the assessment reads them), OPONG's
   insurance-usage rows including export locks, and the used-for-OPONG marks.
   Then clears the activity log. Skipped on a database with no OPONG yet.
2. Ingestion: runs the client's full Typhoon Tino CSV, then its GeoPackage,
   through the same functions the Upload CSV / Upload GPX buttons run. Rows
   already in the database are skipped (CSV: same policy no. + farm) and
   polygons re-applied, so this only adds what's missing.
3. Re-seeds OPONG exactly like `seed_opong_assessment_test.py --all`: bulletins
   already saved are skipped, the TEST-ONLY Surigao del Norte Signal 2
   override is re-applied, and EVERY insurance record is activated over
   OPONG's dates (originals restored first, then re-saved to
   opong_test_original_dates.json -- ids are stable since nothing is deleted).

Then, in the app: Monitoring -> Compute Exposure Summary, then
Assessment & Reporting -> Compute Assessments.

--skip-ingest skips step 2 (how ingestion is shown in the presentation is
still to be decided).

Run from backend/:
    python simulation/prepare_presentation.py
    python simulation/prepare_presentation.py --yes          # no confirmation prompt
    python simulation/prepare_presentation.py --skip-ingest  # no CSV/GPKG ingestion
"""

import argparse
import sys
from pathlib import Path

# Lives in backend/simulation/ but imports `app` and the backend-level
# prepare_ingestion_demo module, so backend/ must be on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import seed_opong_assessment_test as opong  # noqa: E402
from prepare_ingestion_demo import ingest_csv, ingest_gpkg  # noqa: E402

TINO_CSV = opong.USTP_CSV
TINO_GPKG = opong.USTP_DIR / "GPX" / "PCICX GPX_EXISTING IC AFFECTED BY TY TINO_11-05-2025.gpkg"


def clear_results() -> None:
    """OPONG's computed results (if OPONG exists) and the activity log."""
    from sqlalchemy import text

    from app.core.database import SessionLocal
    from app.models.models import TropicalCycloneBulletin, Typhoon

    db = SessionLocal()
    try:
        has_opong = (
            db.query(Typhoon)
            .join(TropicalCycloneBulletin, TropicalCycloneBulletin.typhoon_id == Typhoon.typhoon_id)
            .filter(Typhoon.name == opong.TYPHOON_NAME, TropicalCycloneBulletin.is_final.is_(True))
            .first()
        )
        if has_opong:
            opong.reset_assessment(db)
        else:
            print(f"  No {opong.TYPHOON_NAME} in the database yet -- nothing to reset.")

        db.execute(text("TRUNCATE tbl_activity_log RESTART IDENTITY"))
        db.commit()
        print("  Cleared the activity log.")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare the database for the presentation.")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    parser.add_argument("--skip-ingest", action="store_true", help="skip the CSV/GPKG ingestion")
    args = parser.parse_args()

    if not args.skip_ingest:
        missing = [p for p in (TINO_CSV, TINO_GPKG) if not p.exists()]
        if missing:
            sys.exit("Source file(s) not found:\n" + "\n".join(f"  {p}" for p in missing))

    if not args.yes:
        print(f"This clears {opong.TYPHOON_NAME}'s assessment results, insurance usage (including")
        print("PABS export locks) and the activity log. Farms, insurance records, bulletins and")
        print("all SAR data are kept.")
        if input("Type YES to continue: ").strip() != "YES":
            print("Cancelled -- database not touched.")
            return

    print("\n[1/3] Clearing results ...")
    clear_results()

    if args.skip_ingest:
        print("\n[2/3] Ingestion skipped (--skip-ingest).")
    else:
        print("\n[2/3] Ingesting the Tino CSV ...")
        csv_result = ingest_csv(TINO_CSV)
        print(f"  {csv_result['rows_inserted']} inserted, {csv_result['rows_skipped']} skipped (already in), "
              f"{csv_result['rows_failed']} failed")
        for failure in csv_result["failures"][:10]:
            print(f"    row {failure['row']}: {failure['error']}")

        print("\n      Ingesting the Tino GeoPackage ...")
        gpkg_result = ingest_gpkg(TINO_GPKG)
        print(f"  {gpkg_result['features_updated']} updated, {gpkg_result['features_failed']} not applied, "
              f"{gpkg_result['duplicates_skipped']} duplicate(s) skipped")
        for failure in gpkg_result["failures"][:10]:
            print(f"    {failure['file_name']}: {failure['error']}")

    print(f"\n[3/3] Seeding {opong.TYPHOON_NAME} and activating every record ...")
    sys.argv = [sys.argv[0], "--all"]
    opong.main()

    print("\nReady. In the app: Monitoring -> Compute Exposure Summary,")
    print("then Assessment & Reporting -> Compute Assessments.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\n!!! Failed: {exc!r}")
        sys.exit(1)
