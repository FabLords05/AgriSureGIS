from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.indemnity_calc import ParametricAssessment
from app.models.models import (
    AdminBoundary,
    Farm,
    InsuranceRecord,
    InsuranceUsage,
    RiskAssessment,
    TropicalCycloneBulletin,
)
from app.services.exposure_calculator import ExposureCalculatorService

ELIGIBLE_CROP_STAGES = {1, 2, 3}  # Booting, Flowering, Maturity
MIN_ELIGIBLE_SIGNAL = 2
MIN_ELIGIBLE_HOURS = 6


class AssessmentService:
    """
    Sprint 4: turns Sprint 3's per-boundary exposure summaries (tbl_area_exposure_summary)
    into per-policy payouts (tbl_risk_assessment).

    A farm's boundary_id (assigned at CSV-ingestion time by matching province/
    municipality/barangay text) stands in for a spatial "typhoon path overlay" --
    tbl_admin_boundaries has no geometry column to intersect against, matching the
    text-matched approach ExposureCalculatorService already uses.

    Crop growth stage is read from each policy's most recent existing RiskAssessment
    row (populated once, at legacy CSV-import time) since the schema has no separate,
    live-updated place tracking a policy's current growth stage.
    """

    @classmethod
    def calculate_for_bulletin(cls, typhoon_id: int, bulletin_id: int, db: Session) -> list[RiskAssessment]:
        bulletin = (
            db.query(TropicalCycloneBulletin)
            .filter(
                TropicalCycloneBulletin.tcb_id == bulletin_id,
                TropicalCycloneBulletin.typhoon_id == typhoon_id,
            )
            .first()
        )
        if bulletin is None:
            raise ValueError("Bulletin not found for this typhoon.")

        summaries = ExposureCalculatorService.compute_for_typhoon(typhoon_id, db)
        eligible_summaries = [
            s
            for s in summaries
            if s.max_signal_level >= MIN_ELIGIBLE_SIGNAL and s.total_exposure_hours >= MIN_ELIGIBLE_HOURS
        ]

        assessment = ParametricAssessment(db)
        as_of = bulletin.issued_at.date()
        results: list[RiskAssessment] = []

        # Policies locked by a final PABS export (see finalize_exported_usage)
        # are left out for every typhoon: a new typhoon can't reuse them, and
        # recalculating the exported typhoon leaves its exported results frozen.
        locked_insurance_ids = select(InsuranceUsage.insurance_records_id).where(
            InsuranceUsage.is_used.is_(True),
            InsuranceUsage.finalized_at.isnot(None),
        )

        for summary in eligible_summaries:
            # Matched on the summary's (province, municipality), not its
            # boundary_id: a farm's boundary is its barangay, and the summary's
            # boundary_id is just one barangay row ExposureCalculatorService
            # picked to stand for the whole municipality -- matching on it
            # skipped every farm in that municipality's other barangays.
            insurance_records = (
                db.query(InsuranceRecord)
                .join(Farm, InsuranceRecord.farm_id == Farm.farm_id)
                .join(AdminBoundary, Farm.boundary_id == AdminBoundary.boundary_id)
                .filter(
                    AdminBoundary.province == summary.province,
                    AdminBoundary.municipality == summary.municipality,
                    InsuranceRecord.effectivity_date <= as_of,
                    InsuranceRecord.expiry_date >= as_of,
                    InsuranceRecord.insurance_records_id.not_in(locked_insurance_ids),
                )
                .all()
            )

            for insurance in insurance_records:
                prior = (
                    db.query(RiskAssessment)
                    .filter(RiskAssessment.insurance_records_id == insurance.insurance_records_id)
                    .order_by(RiskAssessment.assessment_date.desc())
                    .first()
                )
                if prior is None or prior.crop_stage_no not in ELIGIBLE_CROP_STAGES:
                    continue

                exposure_hours = int(summary.total_exposure_hours)
                # The seed row's own PCIC group, resolved at ingestion from the CSV's
                # crop-stage column. Carried explicitly rather than derived from
                # crop_stage_no, which cannot distinguish Milking (Late Reproductive)
                # from Flowering (Reproductive) -- both are crop_stage_no 2.
                stage_group = getattr(prior, "stage_group", None)
                rule = assessment.get_matrix_rule(
                    prior.crop_stage_no, summary.max_signal_level, exposure_hours, stage_group
                )
                if rule is None:
                    continue

                amount_cover = float(insurance.amount_cover)
                payout = assessment.calculate_final_payout(
                    amount_cover, prior.crop_stage_no, summary.max_signal_level, exposure_hours, stage_group
                )
                estimated_damage = round(amount_cover * float(rule.estimated_yield_loss) / 100, 2)

                existing = (
                    db.query(RiskAssessment)
                    .filter(
                        RiskAssessment.insurance_records_id == insurance.insurance_records_id,
                        RiskAssessment.summary_id == summary.summary_id,
                    )
                    .first()
                )
                if existing is None:
                    existing = RiskAssessment(
                        insurance_records_id=insurance.insurance_records_id,
                        summary_id=summary.summary_id,
                    )
                    db.add(existing)

                existing.matrix_id = rule.matrix_id
                existing.indemnity_matrix_id = rule.indemnity_matrix_id
                existing.crop_stage_no = prior.crop_stage_no
                existing.crop_stage = prior.crop_stage
                existing.stage_group = stage_group
                existing.period_of_exposure = exposure_hours
                existing.wind_velocity = summary.max_signal_level
                existing.indemnity_factor = rule.indemnity_factor
                existing.estimated_damage = estimated_damage
                existing.final_indemnity_payment = payout

                results.append(existing)

        db.commit()
        for result in results:
            db.refresh(result)

        cls._sync_insurance_usage(typhoon_id, results, db)

        return results

    @classmethod
    def _sync_insurance_usage(cls, typhoon_id: int, results: list[RiskAssessment], db: Session) -> None:
        """
        Marks each assessed policy's insurance as used/unused for this specific
        typhoon, both in tbl_insurance_usage (the per-typhoon source of truth)
        and the tbl_insurance_records.is_used/used_for_typhoon_id/used_at mirror
        (a convenience snapshot of the latest usage only).

        "Used" = final_indemnity_payment > 0 for this (insurance, typhoon) pair.
        Re-running this typhoon's assessment (e.g. a revised bulletin drops a
        previously-used policy's payout to zero) flips tbl_insurance_usage back
        to unused, rather than leaving a stale "used" mark.

        The mirror on tbl_insurance_records is only ever downgraded to unused
        when it currently points at *this* typhoon (or isn't set yet) -- if it
        already reflects real usage from a *different* typhoon, this typhoon
        computing zero payout must not clobber that, or a farmer whose insurance
        was genuinely used for a past typhoon would incorrectly show as unused/
        available again for a new one. This is the mixing this feature exists to
        prevent -- see .claude/FUNCTION_CHANGES.md.
        """
        now = datetime.now(timezone.utc)
        touched = False

        for result in results:
            insurance = result.insurance_record
            if insurance is None:
                continue
            touched = True

            usage = (
                db.query(InsuranceUsage)
                .filter(
                    InsuranceUsage.insurance_records_id == insurance.insurance_records_id,
                    InsuranceUsage.typhoon_id == typhoon_id,
                )
                .first()
            )
            if usage is None:
                usage = InsuranceUsage(
                    insurance_records_id=insurance.insurance_records_id,
                    typhoon_id=typhoon_id,
                )
                db.add(usage)

            is_used_now = result.final_indemnity_payment is not None and result.final_indemnity_payment > 0
            usage.is_used = is_used_now
            usage.assessment_id = result.assessment_id

            if is_used_now:
                insurance.is_used = True
                insurance.used_for_typhoon_id = typhoon_id
                insurance.used_at = now
            elif insurance.used_for_typhoon_id is None or insurance.used_for_typhoon_id == typhoon_id:
                insurance.is_used = False
                insurance.used_for_typhoon_id = None
                insurance.used_at = None
            # else: the mirror already reflects real usage from a different
            # typhoon -- leave it untouched (see docstring above).

        # Nothing to persist if none of the results had a loaded insurance_record
        # (e.g. unit tests constructing bare RiskAssessment rows outside a real
        # Session, where the relationship resolves to None) -- avoid a no-op commit.
        if touched:
            db.commit()

    @classmethod
    def finalize_exported_usage(cls, exported: list[tuple[int, int, int]], db: Session) -> int:
        """
        Locks the policies on a final PABS CSV export as used. `exported` holds
        one (insurance_records_id, typhoon_id, assessment_id) per exported row
        with a payout above zero.

        Unlike _sync_insurance_usage's provisional calculate-time mark, this sets
        tbl_insurance_usage.finalized_at, which calculate_for_bulletin treats as
        a permanent lock. Rows already locked are left as they were, so
        re-exporting is harmless. Returns how many rows were newly locked.
        """
        if not exported:
            return 0

        now = datetime.now(timezone.utc)
        insurance_ids = {insurance_records_id for insurance_records_id, _, _ in exported}
        usages = {
            (u.insurance_records_id, u.typhoon_id): u
            for u in db.query(InsuranceUsage)
            .filter(InsuranceUsage.insurance_records_id.in_(insurance_ids))
            .all()
        }
        records = {
            r.insurance_records_id: r
            for r in db.query(InsuranceRecord)
            .filter(InsuranceRecord.insurance_records_id.in_(insurance_ids))
            .all()
        }

        newly_locked = 0
        for insurance_records_id, typhoon_id, assessment_id in exported:
            usage = usages.get((insurance_records_id, typhoon_id))
            if usage is None:
                usage = InsuranceUsage(insurance_records_id=insurance_records_id, typhoon_id=typhoon_id)
                db.add(usage)
                usages[(insurance_records_id, typhoon_id)] = usage
            elif usage.is_used and usage.finalized_at is not None:
                continue

            usage.is_used = True
            usage.assessment_id = assessment_id
            usage.finalized_at = now
            newly_locked += 1

            insurance = records.get(insurance_records_id)
            if insurance is not None:
                insurance.is_used = True
                insurance.used_for_typhoon_id = typhoon_id
                insurance.used_at = now

        db.commit()
        return newly_locked
