"""
One-off test setup for the Assessment module: makes Typhoon OPONG (BUALOI,
Sep 2025) the latest TCB in the app and activates 20 EXISTING insurance
records on farms in Surigao del Norte to assess against it.

1. Parses the 23 real PAGASA bulletins (simulation/tcb_opong/TCB#1_opong.pdf ..
   TCB#23_opong.pdf, NR. 23F is final -- moved into the repo on 2026-10-13 out
   of the gitignored client export) through the app's own
   BulletinParserService. Content is kept as issued -- only every `issued_at`
   is shifted forward by one shared whole-day offset, so the final bulletin
   lands on today (same time of day) and OPONG sorts as the newest TCB.
   Relative timing between bulletins, and so every exposure duration, is
   unchanged.

2. TEST-ONLY OVERRIDE: guarantees a TCWS No. 2 row (tbl_tcb_signals) for
   every Surigao del Norte municipality in NR. 12-16 -- the bulletins in which
   PAGASA actually hoisted the province (as Signal 1), 12h apart. Existing
   rows are raised to 2, missing ones added, so the insured areas are always
   in the TCB regardless of what the PDF matching stored. OPONG never put
   Mindanao above Signal 1, so no farm there could otherwise reach the
   Signal >= 2 payout threshold. The bulletins' raw PAGASA text (tcws_areas,
   shown in the TCB viewer) still says Signal 1.

   Note: at Signal 2 / 12h only Booting, Flowering and Milking pay out --
   Maturity (e.g. Dough Stage) gives 10% yield loss, and PCIC's indemnity
   brackets start above 10%. Step 3's ranking prefers records that pay.

3. Picks the 20 existing insurance records on Surigao del Norte farms most
   likely to produce a payout (same signal / hours / crop-stage / RECSAP-rule
   checks AssessmentService applies) and sets their coverage to span OPONG's
   shifted dates (effectivity 30 days before the first bulletin, 1-year
   expiry). Their original dates are saved first to
   opong_test_original_dates.json, so --restore can put them back.

Also undoes this script's earlier version, which activated USTP CAPSTONE CSV
records instead: any of those whose dates differ from the CSV are put back.

Does NOT run the assessment itself -- that is left to the app (Assessment &
Reporting module) since that is what is being tested.

Safe to re-run: bulletins already saved are skipped (same typhoon/bulletin
number) and previously activated records are restored before the 20 are
re-selected.

--reset   clears OPONG's assessment results so the demo can be run again:
          deletes the computed tbl_risk_assessment rows for OPONG's exposure
          summaries (crop-stage seed rows, matrix_id IS NULL, are kept -- the
          assessment reads them), deletes OPONG's tbl_insurance_usage rows, and
          clears the is_used/used_for_typhoon_id/used_at mirror where it points
          at OPONG. Bulletins, the override and the 20 active records stay.
--restore puts the 20 records' original effectivity/expiry dates back.

Run from backend/:
    python simulation/seed_opong_assessment_test.py
    python simulation/seed_opong_assessment_test.py --reset
    python simulation/seed_opong_assessment_test.py --restore
"""

import argparse
import csv
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# This file lives in backend/simulation/ (moved 2026-10-13) but imports the
# backend package `app`, so backend/ has to be on sys.path -- running
# `python simulation/seed_opong_assessment_test.py` from backend/ puts only
# backend/simulation/ there, not backend/ itself.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import SessionLocal
from app.core.indemnity_calc import ParametricAssessment
from app.models.models import (
    AdminBoundary,
    AreaExposureSummary,
    Farm,
    InsuranceRecord,
    InsuranceUsage,
    RiskAssessment,
    TcbSignal,
    TropicalCycloneBulletin,
    Typhoon,
)
from app.services.assessment_service import ELIGIBLE_CROP_STAGES, MIN_ELIGIBLE_HOURS, MIN_ELIGIBLE_SIGNAL
from app.services.bulletin_parser import PHT, BulletinParserService
from app.services.exposure_calculator import ExposureCalculatorService

# parent.parent.parent, not parent.parent: this file moved from backend/ into
# backend/simulation/ on 2026-10-13, so the repo root is now three levels up.
# Getting this wrong fails quietly -- the TCB glob just finds no PDFs.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _find_ustp_dir() -> Path:
    """
    The client's export folder carries its Google Drive download timestamp in
    the name ("USTP CAPSTONE-20261009T021551Z-1-001"), so it differs on every
    machine and every re-download -- the hardcoded name was already stale on
    Fabio's laptop ("...-20261008T140025Z-..."), and a stale name fails
    quietly: the TCB glob finds nothing and the script reports no PDFs rather
    than a bad path. So match whichever export is actually present, newest
    first, and fall back to the original name purely so the downstream error
    message still names a concrete path.
    """
    for candidate in sorted(_REPO_ROOT.glob("USTP CAPSTONE-*/USTP CAPSTONE"), reverse=True):
        if candidate.is_dir():
            return candidate
    return _REPO_ROOT / "USTP CAPSTONE-20261009T021551Z-1-001" / "USTP CAPSTONE"


USTP_DIR = _find_ustp_dir()

# OPONG's 23 bulletins now live in the repo (moved out of the client export on
# 2026-10-13, Fabio's decision, and committed on purpose): they are public
# PAGASA documents, unlike the rest of that export, so the simulation set no
# longer depends on a gitignored folder whose name varies per download. The
# export stays the fallback for anyone who still has the PDFs only there.
_LOCAL_TCB_DIR = Path(__file__).resolve().parent / "tcb_opong"
TCB_DIR = _LOCAL_TCB_DIR if any(_LOCAL_TCB_DIR.glob("TCB#*_opong.pdf")) else USTP_DIR / "TCB"

# Stays inside the gitignored export deliberately -- real PCIC farmer records
# (PII). Only the bulletins above were moved into version control.
USTP_CSV = USTP_DIR / "INSURANCE RECORDS" / "PCIC10 GPX 11-05-2025 WITH EXISTING IC AFFECTED BY TY.csv"
BACKUP_FILE = Path(__file__).resolve().parent / "opong_test_original_dates.json"

TARGET_ACTIVE_RECORDS = 20
COVERAGE_STARTS_DAYS_BEFORE = 30
COVERAGE_DAYS = 365

OVERRIDE_PROVINCE = "Surigao del Norte"
OVERRIDE_TO_SIGNAL = 2
# Bulletins in which PAGASA hoisted Surigao del Norte (Signal 1): NR. 12-16, 12h.
OVERRIDE_BULLETINS = range(12, 17)
MINDANAO_ISLAND_GROUP = 2  # bulletin_parser: 0=Luzon, 1=Visayas, 2=Mindanao
TYPHOON_NAME = "OPONG"


def _bulletin_number(path: Path) -> int:
    match = re.search(r"TCB#(\d+)", path.name)
    return int(match.group(1)) if match else 0


def ingest_bulletins(tcb_dir: Path, db) -> int:
    """Parses + saves every OPONG bulletin with shifted issued_at. Returns typhoon_id."""
    pdfs = sorted(tcb_dir.glob("TCB#*_opong.pdf"), key=_bulletin_number)
    if not pdfs:
        sys.exit(f"No TCB#*_opong.pdf files found in {tcb_dir}")

    parsed = [BulletinParserService.parse_bulletin_text(str(p)) for p in pdfs]
    if any(p["issued_at"] is None for p in parsed):
        sys.exit("A bulletin's 'Issued at' could not be parsed -- aborting rather than guess its time.")
    finals = [p for p in parsed if p["is_final"]]
    if not finals:
        sys.exit("No final (NR. ..F) bulletin found among the OPONG PDFs.")
    original_final = finals[0]["issued_at"]

    # Whole days, so every bulletin keeps its real time of day; never in the future.
    now = datetime.now(PHT)
    offset = timedelta(days=(now.date() - original_final.date()).days)
    if original_final + offset > now:
        offset -= timedelta(days=1)

    typhoon_id = None
    for data in parsed:
        data["issued_at"] = data["issued_at"] + offset
        bulletin = BulletinParserService.save_bulletin_to_db(data, db)
        typhoon_id = bulletin.typhoon_id

        # save_bulletin_to_db() only seeds signal rows on a bulletin's FIRST
        # insert -- an OPONG bulletin saved earlier with none (seen: 0 Surigao
        # del Norte rows) would keep none forever. Rebuild them from the PDF
        # every run so the exposure calculation sees what the bulletin says.
        db.query(TcbSignal).filter(TcbSignal.tcb_id == bulletin.tcb_id).delete(synchronize_session=False)
        BulletinParserService._seed_tcb_signals(bulletin, data.get("signals") or {}, db)
        db.commit()

        rows = db.query(TcbSignal).filter(TcbSignal.tcb_id == bulletin.tcb_id)
        province_rows = rows.filter(TcbSignal.province == OVERRIDE_PROVINCE).count()
        print(
            f"  {bulletin.title}  issued_at={bulletin.issued_at}  final={bulletin.is_final}  "
            f"signal rows={rows.count()} ({OVERRIDE_PROVINCE}: {province_rows})"
        )
    return typhoon_id


def override_signal(typhoon_id: int, db) -> None:
    """Test-only: guarantees TCWS >= 2 for every Surigao del Norte municipality
    in the bulletins PAGASA hoisted it in (see module docstring)."""
    bulletins = (
        db.query(TropicalCycloneBulletin)
        .filter(
            TropicalCycloneBulletin.typhoon_id == typhoon_id,
            TropicalCycloneBulletin.bulletin_count.in_(OVERRIDE_BULLETINS),
        )
        .all()
    )
    municipalities = [
        m for (m,) in db.query(AdminBoundary.municipality)
        .filter(AdminBoundary.province == OVERRIDE_PROVINCE)
        .distinct()
        .all()
    ]
    if not municipalities:
        sys.exit(f"No {OVERRIDE_PROVINCE} municipalities in tbl_admin_boundaries.")

    raised = inserted = 0
    for bulletin in bulletins:
        existing = {
            s.area_name: s
            for s in db.query(TcbSignal).filter(
                TcbSignal.tcb_id == bulletin.tcb_id, TcbSignal.province == OVERRIDE_PROVINCE
            )
        }
        for municipality in municipalities:
            signal = existing.get(municipality)
            if signal is None:
                db.add(TcbSignal(
                    tcb_id=bulletin.tcb_id,
                    signal_level=OVERRIDE_TO_SIGNAL,
                    island_group=MINDANAO_ISLAND_GROUP,
                    area_name=municipality,
                    province=OVERRIDE_PROVINCE,
                ))
                inserted += 1
            elif signal.signal_level < OVERRIDE_TO_SIGNAL:
                signal.signal_level = OVERRIDE_TO_SIGNAL
                raised += 1
    db.commit()
    print(
        f"TEST OVERRIDE: {OVERRIDE_PROVINCE} ({len(municipalities)} municipalities) set to TCWS "
        f"{OVERRIDE_TO_SIGNAL} in bulletin(s) {sorted(b.bulletin_count for b in bulletins)} -- "
        f"{raised} row(s) raised, {inserted} row(s) added."
    )


def undo_ustp_activation(db) -> int:
    """Puts USTP CSV records the earlier version of this script shifted back to their CSV dates."""
    if not USTP_CSV.exists():
        return 0
    coverage = {}
    with open(USTP_CSV, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            coverage[(row["FARMID"].strip(), row["CIC NO"].strip())] = tuple(
                datetime.strptime(row[col].strip(), "%m/%d/%Y").date()
                for col in ("EFFECTIVITY DATE", "EXPIRY DATE")
            )
    undone = 0
    for insurance, farm in (
        db.query(InsuranceRecord, Farm)
        .join(Farm, InsuranceRecord.farm_id == Farm.farm_id)
        .filter(Farm.csv_farm_reference.in_({farm_ref for farm_ref, _ in coverage}))
        .all()
    ):
        original = coverage.get((farm.csv_farm_reference, insurance.policy_no))
        if original and (insurance.effectivity_date, insurance.expiry_date) != original:
            insurance.effectivity_date, insurance.expiry_date = original
            undone += 1
    db.commit()
    return undone


def restore_records(db) -> int:
    """Puts every previously activated record's original dates back; removes the backup."""
    if not BACKUP_FILE.exists():
        return 0
    backup = json.loads(BACKUP_FILE.read_text(encoding="utf-8"))
    for insurance_records_id, (effectivity, expiry) in backup.items():
        insurance = db.get(InsuranceRecord, int(insurance_records_id))
        if insurance is not None:
            insurance.effectivity_date = date.fromisoformat(effectivity) if effectivity else None
            insurance.expiry_date = date.fromisoformat(expiry) if expiry else None
    db.commit()
    BACKUP_FILE.unlink()
    return len(backup)


def select_records(typhoon_id: int, db):
    """Ranks Surigao del Norte insurance records by how likely AssessmentService is to pay them out."""
    # Keyed like AssessmentService matches: by the farm's (province, municipality).
    summaries = {
        (s.province, s.municipality): s for s in ExposureCalculatorService.compute_for_typhoon(typhoon_id, db)
    }
    matrix = ParametricAssessment(db)

    rows = (
        db.query(InsuranceRecord, Farm, AdminBoundary)
        .join(Farm, InsuranceRecord.farm_id == Farm.farm_id)
        .join(AdminBoundary, Farm.boundary_id == AdminBoundary.boundary_id)
        .filter(AdminBoundary.province == OVERRIDE_PROVINCE)
        .all()
    )

    ranked = []
    for insurance, farm, boundary in rows:
        prior = (
            db.query(RiskAssessment)
            .filter(RiskAssessment.insurance_records_id == insurance.insurance_records_id)
            .order_by(RiskAssessment.assessment_date.desc())
            .first()
        )
        stage_ok = prior is not None and prior.crop_stage_no in ELIGIBLE_CROP_STAGES
        summary = summaries.get((boundary.province, boundary.municipality))
        signal = summary.max_signal_level if summary else 0
        hours = float(summary.total_exposure_hours) if summary else 0.0
        eligible = signal >= MIN_ELIGIBLE_SIGNAL and hours >= MIN_ELIGIBLE_HOURS
        has_rule = bool(
            stage_ok
            and eligible
            and matrix.get_matrix_rule(prior.crop_stage_no, signal, int(hours), getattr(prior, "stage_group", None))
        )
        ranked.append(((has_rule, eligible, stage_ok, signal, hours), insurance, farm, boundary, prior))

    ranked.sort(key=lambda r: r[0], reverse=True)
    return ranked[:TARGET_ACTIVE_RECORDS], len(rows)


def refresh_caches(db) -> None:
    """Same post-write cleanup as seed_active_insurance.py -- both no-op if absent."""
    try:
        db.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_farm_latest_insurance"))
        db.commit()
        print("Refreshed mv_farm_latest_insurance.")
    except SQLAlchemyError:
        db.rollback()  # view doesn't exist -- nothing to refresh

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
        pass  # Redis not installed/configured/running


def reset_assessment(db) -> None:
    """Clears OPONG's assessment results (see module docstring, --reset)."""
    typhoon = (
        db.query(Typhoon)
        .join(TropicalCycloneBulletin, TropicalCycloneBulletin.typhoon_id == Typhoon.typhoon_id)
        .filter(Typhoon.name == TYPHOON_NAME, TropicalCycloneBulletin.is_final.is_(True))
        .order_by(TropicalCycloneBulletin.issued_at.desc())
        .first()
    )
    if typhoon is None:
        sys.exit(f"No {TYPHOON_NAME} typhoon with a final bulletin found -- run the seeder first.")

    usage_deleted = (
        db.query(InsuranceUsage)
        .filter(InsuranceUsage.typhoon_id == typhoon.typhoon_id)
        .delete(synchronize_session=False)
    )
    summary_ids = db.query(AreaExposureSummary.summary_id).filter(
        AreaExposureSummary.typhoon_id == typhoon.typhoon_id
    )
    assessments_deleted = (
        db.query(RiskAssessment)
        .filter(
            RiskAssessment.summary_id.in_(summary_ids.scalar_subquery()),
            RiskAssessment.matrix_id.isnot(None),
        )
        .delete(synchronize_session=False)
    )
    mirrors_cleared = (
        db.query(InsuranceRecord)
        .filter(InsuranceRecord.used_for_typhoon_id == typhoon.typhoon_id)
        .update(
            {
                InsuranceRecord.is_used: False,
                InsuranceRecord.used_for_typhoon_id: None,
                InsuranceRecord.used_at: None,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    print(
        f"Reset {TYPHOON_NAME} (typhoon_id={typhoon.typhoon_id}): deleted {assessments_deleted} computed "
        f"assessment(s) and {usage_deleted} usage row(s); cleared {mirrors_cleared} used-for-{TYPHOON_NAME} "
        f"mark(s). Bulletins and the 20 active records are unchanged -- ready to assess again."
    )
    refresh_caches(db)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--reset", action="store_true", help=f"clear {TYPHOON_NAME}'s assessment results only")
    mode.add_argument("--restore", action="store_true", help="put the activated records' original dates back")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.reset:
            reset_assessment(db)
            return
        if args.restore:
            print(f"Restored original dates on {restore_records(db)} record(s).")
            refresh_caches(db)
            return

        print(f"Ingesting {TYPHOON_NAME} bulletins...")
        typhoon_id = ingest_bulletins(TCB_DIR, db)
        print(f"typhoon_id={typhoon_id}")
        override_signal(typhoon_id, db)

        undone = undo_ustp_activation(db)
        if undone:
            print(f"Put {undone} USTP CSV record(s) back to their CSV dates (earlier version of this script).")
        restored = restore_records(db)
        if restored:
            print(f"Restored {restored} previously activated record(s) before re-selecting.")

        selected, candidates = select_records(typhoon_id, db)
        if not selected:
            sys.exit(f"No insurance records on farms in {OVERRIDE_PROVINCE} found.")
        print(f"\n{candidates} insurance record(s) on {OVERRIDE_PROVINCE} farms; activating {len(selected)}:")

        first_issued = (
            db.query(TropicalCycloneBulletin.issued_at)
            .filter(TropicalCycloneBulletin.typhoon_id == typhoon_id)
            .order_by(TropicalCycloneBulletin.issued_at.asc())
            .first()[0]
        )
        effectivity = first_issued.astimezone(PHT).date() - timedelta(days=COVERAGE_STARTS_DAYS_BEFORE)
        expiry = effectivity + timedelta(days=COVERAGE_DAYS)

        backup = {}
        expected_payouts = 0
        for (has_rule, _, _, signal, hours), insurance, farm, boundary, prior in selected:
            backup[str(insurance.insurance_records_id)] = [
                insurance.effectivity_date.isoformat() if insurance.effectivity_date else None,
                insurance.expiry_date.isoformat() if insurance.expiry_date else None,
            ]
            insurance.effectivity_date, insurance.expiry_date = effectivity, expiry
            expected_payouts += has_rule
            print(
                f"  ir={insurance.insurance_records_id} policy={insurance.policy_no} farm={farm.farm_id} "
                f"| {boundary.municipality}, {boundary.barangay} | TCWS {signal}, {hours:g}h "
                f"| stage={prior.crop_stage if prior else None} | expected payout: {'yes' if has_rule else 'no'}"
            )

        # Written before the commit, so the originals are never lost.
        BACKUP_FILE.write_text(json.dumps(backup, indent=2), encoding="utf-8")
        db.commit()
        print(f"\nCoverage set to {effectivity}..{expiry}. Originals saved to {BACKUP_FILE.name}.")
        print(f"Done. {expected_payouts} of {len(selected)} are expected to produce a payout.")
        if expected_payouts == 0:
            print(
                f"None qualify -- if the TEST OVERRIDE line says 0 {OVERRIDE_PROVINCE} rows in total, "
                f"OPONG's saved bulletins have no {OVERRIDE_PROVINCE} signal rows in tbl_tcb_signals."
            )

        refresh_caches(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
