"""
Recomputes every typhoon's exposure summaries under the per-signal-hours
rules introduced 2026-10-22 (see ExposureCalculatorService and
migrations/2026-10-22_exposure_signal_hours.sql). Run once after applying
that migration; rows computed under the old first-to-last-bulletin rule are
otherwise left as they were.

Default is a DRY RUN: prints, per typhoon, the old vs. new exposure rows
(municipalities, total hours) and writes nothing.

--apply   writes the recomputed summaries and their intervals.
--reseed  also rebuilds each bulletin's tbl_tcb_signals rows from its stored
          tcws_areas text with the current coverage rules (partial
          provincial coverage without a town list is no longer widened to
          the whole province; "excluding" lists are honoured) and records
          unresolved clauses. Needs --apply to write. Typhoons with a final
          PABS export (finalized insurance usage) are skipped with --reseed,
          so exported figures keep the signals they were assessed on.
--typhoon ID  limits the run to one typhoon.

Assessment results (tbl_risk_assessment) are NOT recalculated here -- run
"Compute Assessments" for a typhoon afterwards if its payouts should follow.

Run from backend/:
    python scripts/recompute_exposure.py
    python scripts/recompute_exposure.py --apply
    python scripts/recompute_exposure.py --apply --reseed --typhoon 3
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal
from app.models.models import (
    AdminBoundary,
    AreaExposureSummary,
    InsuranceUsage,
    TcbSignal,
    TcbUnresolvedClause,
    TropicalCycloneBulletin,
    Typhoon,
)
from app.services.bulletin_parser import BulletinParserService, _tcws_hash
from app.services.exposure_calculator import ExposureCalculatorService


def _totals(summaries) -> tuple[int, float]:
    return len(summaries), round(sum(float(s.total_exposure_hours) for s in summaries), 2)


def _reseed(typhoon: Typhoon, db) -> None:
    bulletins = (
        db.query(TropicalCycloneBulletin)
        .filter(TropicalCycloneBulletin.typhoon_id == typhoon.typhoon_id)
        .order_by(TropicalCycloneBulletin.issued_at)
        .all()
    )
    for bulletin in bulletins:
        db.query(TcbSignal).filter(TcbSignal.tcb_id == bulletin.tcb_id).delete(synchronize_session=False)
        db.query(TcbUnresolvedClause).filter(TcbUnresolvedClause.tcb_id == bulletin.tcb_id).delete(
            synchronize_session=False)
        signals = {
            int(level): {int(group): text for group, text in groups.items()}
            for level, groups in (bulletin.tcws_areas or {}).items()
        }
        BulletinParserService._seed_tcb_signals(bulletin, signals, db)
        if bulletin.tcws_hash is None:
            bulletin.tcws_hash = _tcws_hash(bulletin.max_signal_level, bulletin.tcws_areas)
    db.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write the results (default: dry run)")
    parser.add_argument("--reseed", action="store_true", help="rebuild signal rows from stored TCWS text first")
    parser.add_argument("--typhoon", type=int, help="only this typhoon_id")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if db.query(AdminBoundary.boundary_id).first() is None:
            sys.exit("tbl_admin_boundaries is empty -- seed boundaries first (seed_admin_boundaries.py).")

        query = db.query(Typhoon).order_by(Typhoon.typhoon_id)
        if args.typhoon is not None:
            query = query.filter(Typhoon.typhoon_id == args.typhoon)
        typhoons = query.all()
        if not typhoons:
            sys.exit("No typhoons found.")

        for typhoon in typhoons:
            before = _totals(
                db.query(AreaExposureSummary).filter(AreaExposureSummary.typhoon_id == typhoon.typhoon_id).all()
            )
            if args.reseed:
                exported = (
                    db.query(InsuranceUsage.usage_id)
                    .filter(InsuranceUsage.typhoon_id == typhoon.typhoon_id, InsuranceUsage.finalized_at.isnot(None))
                    .first()
                )
                if exported:
                    print(f"{typhoon.name} (#{typhoon.typhoon_id}): has a final PABS export -- signals not reseeded")
                else:
                    _reseed(typhoon, db)

            if args.apply:
                summaries = ExposureCalculatorService.compute_for_typhoon(typhoon.typhoon_id, db)
            else:
                # compute_for_typhoon commits; for a dry run that commit is
                # swapped for a flush, and everything is rolled back below.
                db.commit = db.flush  # type: ignore[method-assign]
                summaries = ExposureCalculatorService.compute_for_typhoon(typhoon.typhoon_id, db)
            after = _totals(summaries)
            print(
                f"{typhoon.name} (#{typhoon.typhoon_id}): "
                f"{before[0]} area(s) / {before[1]}h total  ->  {after[0]} area(s) / {after[1]}h total"
                + ("" if args.apply else "  [dry run]")
            )
            if not args.apply:
                db.rollback()

        if not args.apply:
            print("\nDry run only -- nothing written. Re-run with --apply to save.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
