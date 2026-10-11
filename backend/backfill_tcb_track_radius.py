"""
Backfills the typhoon track overlay columns (wind_radius_km,
storm_force_radius_km, forecast_track -- see
migrations/2026-10-12_tcb_track_radius.sql) for one typhoon's bulletins that
were saved before those columns existed, by re-reading the original PAGASA
PDFs. Touches ONLY those three columns, and only where they are NULL -- signals,
exposure summaries and assessments are left alone (unlike
reparse_opong_bulletins.py), so it is safe to run while the typhoon already
has assessment results.

Default is a DRY RUN: prints, per bulletin, what the PDF yields and writes
nothing. When a PDF yields no wind radius, the lines mentioning "extend"
are printed so the parser's wording can be checked against the real text.

Run from backend/:
    python backfill_tcb_track_radius.py
    python backfill_tcb_track_radius.py --apply
    python backfill_tcb_track_radius.py --typhoon KIYAPO --dir "../docs"
"""

import argparse
import re
import sys
from pathlib import Path

from app.core.database import SessionLocal
from app.models.models import TropicalCycloneBulletin, Typhoon
from app.services.bulletin_parser import BulletinParserService
from seed_opong_assessment_test import TCB_DIR, _bulletin_number

TRACK_COLUMNS = ("wind_radius_km", "storm_force_radius_km", "forecast_track")


def _typhoon(name: str, db) -> Typhoon:
    # Newest typhoon with this name that has bulletins -- names recycle
    # across years.
    typhoon = (
        db.query(Typhoon)
        .join(TropicalCycloneBulletin, TropicalCycloneBulletin.typhoon_id == Typhoon.typhoon_id)
        .filter(Typhoon.name == name)
        .order_by(TropicalCycloneBulletin.issued_at.desc())
        .first()
    )
    if typhoon is None:
        sys.exit(f"No {name} typhoon with bulletins found.")
    return typhoon


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--typhoon", default="OPONG", help="Typhoon name (default OPONG)")
    parser.add_argument("--dir", type=Path, default=TCB_DIR, help=f"Folder with TCB#<n>_<name>.pdf (default {TCB_DIR})")
    parser.add_argument("--apply", action="store_true", help="Write the values (default: dry run)")
    args = parser.parse_args()

    name = args.typhoon.upper()
    pdfs = sorted(args.dir.glob(f"TCB#*_{name.lower()}.pdf"), key=_bulletin_number)
    if not pdfs:
        sys.exit(f"No TCB#*_{name.lower()}.pdf files in {args.dir}")

    db = SessionLocal()
    try:
        typhoon = _typhoon(name, db)
        print(f"{name} (typhoon_id={typhoon.typhoon_id}) -- {len(pdfs)} PDFs -- {'APPLY' if args.apply else 'DRY RUN'}")
        updated = 0
        for pdf in pdfs:
            parsed = BulletinParserService.parse_bulletin_text(str(pdf))
            bulletin = (
                db.query(TropicalCycloneBulletin)
                .filter(
                    TropicalCycloneBulletin.typhoon_id == typhoon.typhoon_id,
                    TropicalCycloneBulletin.bulletin_count == parsed["bulletin_count"],
                )
                .first()
            )
            values = {
                "wind_radius_km": parsed["wind_radius_km"],
                "storm_force_radius_km": parsed["storm_force_radius_km"],
                "forecast_track": parsed["forecast_track"] or None,
            }
            print(
                f"  {pdf.name}: strong={values['wind_radius_km']} km, storm-force={values['storm_force_radius_km']} km, "
                f"forecast points={len(parsed['forecast_track'])}"
                + ("" if bulletin else "  [no matching bulletin in DB -- skipped]")
            )
            if values["wind_radius_km"] is None:
                for line in parsed["raw_text"].splitlines():
                    if re.search(r"extend|extent", line, re.IGNORECASE):
                        print(f"      text: {line.strip()}")
            if bulletin is None:
                continue
            changed = False
            for column in TRACK_COLUMNS:
                if values[column] is not None and getattr(bulletin, column) is None:
                    setattr(bulletin, column, values[column])
                    changed = True
            updated += changed

        if args.apply:
            db.commit()
            print(f"Updated {updated} bulletin(s).")
        else:
            db.rollback()
            print(f"Dry run -- {updated} bulletin(s) would be updated. Re-run with --apply to write.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
