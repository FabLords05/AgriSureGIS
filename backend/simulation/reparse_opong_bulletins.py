"""
Re-parses Typhoon OPONG's saved bulletins from the original PAGASA PDFs
(USTP CAPSTONE/TCB/TCB#1_opong.pdf .. TCB#23_opong.pdf) with the fixed
TCWS parser, so their stored wind-signal areas match what PAGASA issued.
OPONG only (Cristian's decision, 2026-10-11) -- other typhoons are untouched.

Why: bulletin signals are only seeded on a bulletin's first insert, so the
2026-10-11 parser fixes (see .claude/FUNCTION_CHANGES.md) don't reach
bulletins already in the database. For OPONG that left:
  - TCB#13-16 with no Signal No. 2 row at all (the table split at a page
    break and the header-less part was skipped),
  - TCB#1-4 with bogus "Signals 1-9" read from the track-forecast table,
  - LGUs lost to line breaks / island names / Metro Manila, and stray ones
    (City of San Juan, City of Isabela) added by name collisions.

Default is a DRY RUN: prints, per bulletin, the signal rows stored now vs.
what the PDF resolves to, and writes nothing.

--apply  rewrites each OPONG bulletin's tcws_areas / max_signal_level and
         its tbl_tcb_signals rows, recomputes OPONG's
         tbl_area_exposure_summary, and deletes OPONG summaries for
         boundaries no bulletin covers any more (only those with no
         tbl_risk_assessment rows). Refuses to run while OPONG has
         assessment results or insurance-usage rows -- clear them first with
         `python simulation/seed_opong_assessment_test.py --reset`.
         This also removes the seeder's TEST-ONLY Signal 2 override for
         Surigao del Norte; re-run `python simulation/seed_opong_assessment_test.py`
         afterwards if the assessment demo still needs it.

Run from backend/:
    python simulation/reparse_opong_bulletins.py
    python simulation/reparse_opong_bulletins.py --apply
"""

import argparse
import collections
import sys
from pathlib import Path

# See the same note in seed_opong_assessment_test.py: this file sits in
# backend/simulation/ but imports `app` (and its sibling module below), so
# backend/ must be on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal
from app.models.models import (
    AdminBoundary,
    AreaExposureSummary,
    InsuranceUsage,
    RiskAssessment,
    TcbSignal,
    TropicalCycloneBulletin,
    Typhoon,
)
from app.services.bulletin_parser import BulletinParserService, _raw_tcws_columns, resolve_tcws_signals
from app.services.exposure_calculator import ExposureCalculatorService
from seed_opong_assessment_test import TCB_DIR, TYPHOON_NAME, _bulletin_number, refresh_caches

ISLAND_LETTERS = "LVM"  # island_group 0=Luzon, 1=Visayas, 2=Mindanao


def _summary(rows) -> str:
    counts = collections.Counter((level, group) for level, group, *_ in rows)
    ordered = sorted(counts.items(), key=lambda kv: (-kv[0][0], kv[0][1]))
    return " ".join(f"S{level}{ISLAND_LETTERS[group]}={n}" for (level, group), n in ordered) or "-"


def _opong_typhoon(db) -> Typhoon:
    # Same lookup as seed_opong_assessment_test.reset_assessment().
    typhoon = (
        db.query(Typhoon)
        .join(TropicalCycloneBulletin, TropicalCycloneBulletin.typhoon_id == Typhoon.typhoon_id)
        .filter(Typhoon.name == TYPHOON_NAME, TropicalCycloneBulletin.is_final.is_(True))
        .order_by(TropicalCycloneBulletin.issued_at.desc())
        .first()
    )
    if typhoon is None:
        sys.exit(f"No {TYPHOON_NAME} typhoon with a final bulletin found -- nothing to re-parse.")
    return typhoon


def _assessment_blockers(typhoon_id: int, db) -> tuple[int, int]:
    usage = db.query(InsuranceUsage).filter(InsuranceUsage.typhoon_id == typhoon_id).count()
    summary_ids = db.query(AreaExposureSummary.summary_id).filter(AreaExposureSummary.typhoon_id == typhoon_id)
    computed = (
        db.query(RiskAssessment)
        .filter(RiskAssessment.summary_id.in_(summary_ids.scalar_subquery()), RiskAssessment.matrix_id.isnot(None))
        .count()
    )
    return usage, computed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write the re-parsed signals (default: dry run)")
    args = parser.parse_args()

    pdfs = sorted(TCB_DIR.glob("TCB#*_opong.pdf"), key=_bulletin_number)
    if not pdfs:
        sys.exit(f"No TCB#*_opong.pdf files found in {TCB_DIR}")

    db = SessionLocal()
    try:
        typhoon = _opong_typhoon(db)
        if args.apply:
            usage, computed = _assessment_blockers(typhoon.typhoon_id, db)
            if usage or computed:
                sys.exit(
                    f"{TYPHOON_NAME} has {computed} computed assessment(s) and {usage} insurance-usage row(s). "
                    f"Run `python simulation/seed_opong_assessment_test.py --reset` first, then re-run with --apply."
                )

        municipalities_by_province: dict[str, set[str]] = {}
        for province, municipality in db.query(AdminBoundary.province, AdminBoundary.municipality).distinct().all():
            municipalities_by_province.setdefault(province, set()).add(municipality)

        print(f"{TYPHOON_NAME} typhoon_id={typhoon.typhoon_id} -- {'APPLYING' if args.apply else 'DRY RUN (nothing written)'}")
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
            if bulletin is None:
                print(f"  {pdf.name}: no saved bulletin NR. {parsed['bulletin_count']} -- skipped")
                continue

            signals = parsed.get("signals") or {}
            new_rows = resolve_tcws_signals(signals, municipalities_by_province, log_label=f"TCB {bulletin.tcb_id}")
            old_rows = [
                (s.signal_level, s.island_group, s.province, s.area_name)
                for s in db.query(TcbSignal).filter(TcbSignal.tcb_id == bulletin.tcb_id)
            ]
            print(f"  NR. {bulletin.bulletin_count:>2} (tcb_id {bulletin.tcb_id})")
            print(f"      stored: {_summary(old_rows)}")
            print(f"      PDF:    {_summary(new_rows)}")

            if args.apply:
                bulletin.max_signal_level, bulletin.tcws_areas = _raw_tcws_columns(
                    signals, parsed.get("no_signal_hoisted", False)
                )
                db.query(TcbSignal).filter(TcbSignal.tcb_id == bulletin.tcb_id).delete(synchronize_session=False)
                for level, group, province, municipality in new_rows:
                    db.add(TcbSignal(
                        tcb_id=bulletin.tcb_id,
                        signal_level=level,
                        island_group=group,
                        area_name=municipality,
                        province=province,
                    ))
                db.commit()

        if not args.apply:
            print("\nDry run only. Re-run with --apply to write these.")
            return

        summaries = ExposureCalculatorService.compute_for_typhoon(typhoon.typhoon_id, db)
        covered = {s.boundary_id for s in summaries}
        stale = [
            s for s in db.query(AreaExposureSummary).filter(AreaExposureSummary.typhoon_id == typhoon.typhoon_id)
            if s.boundary_id not in covered
        ]
        referenced = {
            row[0] for row in db.query(RiskAssessment.summary_id)
            .filter(RiskAssessment.summary_id.in_([s.summary_id for s in stale]))
        } if stale else set()
        deleted = [s for s in stale if s.summary_id not in referenced]
        for summary in deleted:
            db.delete(summary)
        db.commit()
        print(
            f"\nRecomputed {len(summaries)} exposure summaries; deleted {len(deleted)} for boundaries no "
            f"bulletin covers any more"
            + (f" ({len(stale) - len(deleted)} kept: still referenced by tbl_risk_assessment)." if len(stale) > len(deleted) else ".")
        )
        print(
            "The seeder's TEST-ONLY Surigao del Norte Signal 2 override is gone -- re-run "
            "`python simulation/seed_opong_assessment_test.py` if the assessment demo still needs it."
        )
        refresh_caches(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
