from sqlalchemy.orm import Session

from app.core.indemnity_calc import ParametricAssessment
from app.models.models import (
    Farm,
    InsuranceRecord,
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

        for summary in eligible_summaries:
            insurance_records = (
                db.query(InsuranceRecord)
                .join(Farm, InsuranceRecord.farm_id == Farm.farm_id)
                .filter(
                    Farm.boundary_id == summary.boundary_id,
                    InsuranceRecord.effectivity_date <= as_of,
                    InsuranceRecord.expiry_date >= as_of,
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
                rule = assessment.get_matrix_rule(prior.crop_stage_no, summary.max_signal_level, exposure_hours)
                if rule is None:
                    continue

                amount_cover = float(insurance.amount_cover)
                payout = assessment.calculate_final_payout(
                    amount_cover, prior.crop_stage_no, summary.max_signal_level, exposure_hours
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
                existing.period_of_exposure = exposure_hours
                existing.wind_velocity = summary.max_signal_level
                existing.indemnity_factor = rule.indemnity_factor
                existing.estimated_damage = estimated_damage
                existing.final_indemnity_payment = payout

                results.append(existing)

        db.commit()
        for result in results:
            db.refresh(result)

        return results
