import io

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.farmer_name import format_surname_first
from app.core.farms_cache import invalidate_farms_cache
from app.core.security import get_current_user
from app.models.models import AdminBoundary, AreaExposureSummary, FarmerProfile, InsuranceRecord, RiskAssessment, Typhoon
from app.models.models import (
    AdminBoundary,
    AreaExposureSummary,
    FarmerProfile,
    InsuranceRecord,
    InsuranceUsage,
    RiskAssessment,
    Typhoon,
)
from app.services.assessment_service import AssessmentService

router = APIRouter(prefix="/assessments", tags=["assessments"], dependencies=[Depends(get_current_user)])


class CalculateAssessmentsRequest(BaseModel):
    typhoon_id: int
    bulletin_id: int


@router.post("/calculate")
def calculate_assessments(payload: CalculateAssessmentsRequest, db: Session = Depends(get_db)):
    """
    Computes exposure hours, checks payout eligibility (wind signal >= 2, exposure
    >= 6h, crop stage in Booting/Flowering/Maturity), and calculates final indemnity
    payments for every active policy in the typhoon-affected area.
    """
    try:
        results = AssessmentService.calculate_for_bulletin(payload.typhoon_id, payload.bulletin_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "status": "success",
        "typhoon_id": payload.typhoon_id,
        "bulletin_id": payload.bulletin_id,
        "assessments_computed": len(results),
        "assessments": [
            {
                "assessment_id": r.assessment_id,
                "insurance_records_id": r.insurance_records_id,
                "crop_stage": r.crop_stage,
                "period_of_exposure": r.period_of_exposure,
                "wind_velocity": r.wind_velocity,
                "indemnity_factor": float(r.indemnity_factor) if r.indemnity_factor is not None else None,
                "estimated_damage": float(r.estimated_damage),
                "final_indemnity_payment": float(r.final_indemnity_payment),
            }
            for r in results
        ],
    }


@router.get("/")
def list_assessments(
    typhoon_id: int | None = Query(default=None),
    policy_no: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Search and filter calculated risk assessments."""
    query = db.query(RiskAssessment).join(RiskAssessment.insurance_record)

    if policy_no is not None:
        query = query.filter(InsuranceRecord.policy_no == policy_no)
    if typhoon_id is not None:
        query = query.join(
            AreaExposureSummary, RiskAssessment.summary_id == AreaExposureSummary.summary_id
        ).filter(AreaExposureSummary.typhoon_id == typhoon_id)

    assessments = query.order_by(RiskAssessment.assessment_date.desc()).all()

    data = []
    for a in assessments:
        # typhoon_id is only known for free when the typhoon_id filter above was
        # used (it joined AreaExposureSummary already); otherwise resolve it
        # per-row through the assessment's summary, same indirection the export
        # endpoints below already use.
        row_typhoon_id = typhoon_id
        if row_typhoon_id is None and a.summary_id is not None:
            summary = (
                db.query(AreaExposureSummary).filter(AreaExposureSummary.summary_id == a.summary_id).first()
            )
            row_typhoon_id = summary.typhoon_id if summary else None

        usage = None
        if row_typhoon_id is not None and a.insurance_records_id is not None:
            usage = (
                db.query(InsuranceUsage)
                .filter(
                    InsuranceUsage.insurance_records_id == a.insurance_records_id,
                    InsuranceUsage.typhoon_id == row_typhoon_id,
                )
                .first()
            )

        data.append(
            {
                "assessment_id": a.assessment_id,
                "policy_no": a.insurance_record.policy_no if a.insurance_record else None,
                "farm_id": a.insurance_record.farm_id if a.insurance_record else None,
                "amount_cover": float(a.insurance_record.amount_cover) if a.insurance_record else None,
                "crop_stage": a.crop_stage,
                "period_of_exposure": a.period_of_exposure,
                "wind_velocity": a.wind_velocity,
                "indemnity_factor": float(a.indemnity_factor) if a.indemnity_factor is not None else None,
                "estimated_damage": float(a.estimated_damage),
                "final_indemnity_payment": float(a.final_indemnity_payment),
                "assessment_date": a.assessment_date,
                "typhoon_id": row_typhoon_id,
                # None when this typhoon has no tbl_insurance_usage row yet for this
                # policy (e.g. assessed before this feature existed, or genuinely
                # never touched) -- distinct from False ("assessed, but unused").
                "insurance_used": usage.is_used if usage is not None else None,
            }
        )

    return {"status": "success", "data": data}


@router.get("/summary")
def get_assessments_summary(db: Session = Depends(get_db)):
    """
    Real SQL-aggregate replacement (2026-08-17, on-demand-pagination
    redesign -- see .claude/FUNCTION_CHANGES.md) for what
    MonitoringModule.tsx's "Affected Farms" stat tile used to compute by
    reducing over the *entire* client-side `farms` array. That only worked
    because useFarmsData.ts eagerly loaded every farm into the browser; the
    redesign stops doing that, so this aggregate has to be computed once,
    server-side, instead.

    "Affected" mirrors the old frontend logic exactly: a farm's most recent
    RiskAssessment (by assessment_date, across all its insurance
    records/typhoons -- same DISTINCT ON semantics as
    app/core/farms_view.py's "latest insurance per farm") has
    wind_velocity set. total_area/total_indemnity are summed only over
    that same affected set, same as the old totalArea/totalIndemnity
    reductions.

    Raw SQL (not the ORM) for the same reason farms_view.py uses it: this
    is a DISTINCT ON + FILTER aggregate that's awkward to express
    correctly through the ORM and cheap for Postgres to run directly.

    growth_stage_distribution/signal_breakdown (2026-08-18, stage 2) round
    out this replacement -- MonitoringModule.tsx's Growth Stage pie and
    Farms by Signal Number bar chart used to reduce over the same full
    `farms` array (joined against `assessments`, itself a separate
    unpaginated GET /assessments/ fetch) client-side. Deliberately three
    separate `db.execute()` calls sharing the same
    latest-assessment-per-farm CTE shape rather than one combined query --
    each stays simple/readable at the cost of Postgres re-scanning
    tbl_risk_assessment/tbl_insurance_records three times, which is fine
    given those tables are far smaller than tbl_farms at 100k-1M scale.
    Deliberately not scoped by municipality (unlike GET /farms/ and GET
    /farms/geometry) -- this is a dashboard summary meant to reflect the
    whole system, not something a user searches into.
    """
    totals_row = db.execute(
        text(
            """
            WITH latest_assessment_per_farm AS (
                SELECT DISTINCT ON (ir.farm_id)
                    ir.farm_id,
                    ra.wind_velocity,
                    ra.final_indemnity_payment
                FROM tbl_risk_assessment ra
                JOIN tbl_insurance_records ir ON ir.insurance_records_id = ra.insurance_records_id
                ORDER BY ir.farm_id, ra.assessment_date DESC
            )
            SELECT
                (SELECT COUNT(*) FROM tbl_farms) AS total_farms,
                COUNT(*) FILTER (WHERE lap.wind_velocity IS NOT NULL) AS affected_farms,
                COALESCE(SUM(f.area_size) FILTER (WHERE lap.wind_velocity IS NOT NULL), 0) AS total_area,
                COALESCE(SUM(lap.final_indemnity_payment) FILTER (WHERE lap.wind_velocity IS NOT NULL), 0) AS total_indemnity
            FROM latest_assessment_per_farm lap
            JOIN tbl_farms f ON f.farm_id = lap.farm_id
            """
        )
    ).first()

    # Growth Stage Distribution -- MonitoringModule.tsx's growthStageData,
    # over ALL farms (LEFT JOIN), bucketed to "Not Assessed" for farms with
    # no RiskAssessment at all yet -- same semantics as the old client-side
    # `f.assessment?.crop_stage ?? "Not Assessed"` reduction.
    growth_stage_rows = db.execute(
        text(
            """
            WITH latest_assessment_per_farm AS (
                SELECT DISTINCT ON (ir.farm_id)
                    ir.farm_id,
                    ra.crop_stage
                FROM tbl_risk_assessment ra
                JOIN tbl_insurance_records ir ON ir.insurance_records_id = ra.insurance_records_id
                ORDER BY ir.farm_id, ra.assessment_date DESC
            )
            SELECT
                COALESCE(lap.crop_stage, 'Not Assessed') AS crop_stage,
                COUNT(*) AS farm_count
            FROM tbl_farms f
            LEFT JOIN latest_assessment_per_farm lap ON lap.farm_id = f.farm_id
            GROUP BY COALESCE(lap.crop_stage, 'Not Assessed')
            ORDER BY farm_count DESC, crop_stage ASC
            """
        )
    ).all()

    # Signal breakdown -- MonitoringModule.tsx's signalChartData, over
    # affected farms only (wind_velocity NOT NULL), same as the old
    # affectedFarmRows reduction.
    signal_rows = db.execute(
        text(
            """
            WITH latest_assessment_per_farm AS (
                SELECT DISTINCT ON (ir.farm_id)
                    ir.farm_id,
                    ra.wind_velocity
                FROM tbl_risk_assessment ra
                JOIN tbl_insurance_records ir ON ir.insurance_records_id = ra.insurance_records_id
                ORDER BY ir.farm_id, ra.assessment_date DESC
            )
            SELECT
                lap.wind_velocity,
                COUNT(*) AS farm_count,
                COALESCE(SUM(f.area_size), 0) AS total_area
            FROM latest_assessment_per_farm lap
            JOIN tbl_farms f ON f.farm_id = lap.farm_id
            WHERE lap.wind_velocity IS NOT NULL
            GROUP BY lap.wind_velocity
            ORDER BY lap.wind_velocity ASC
            """
        )
    ).all()

    return {
        "status": "success",
        "total_farms": totals_row.total_farms if totals_row else 0,
        "affected_farms": totals_row.affected_farms if totals_row else 0,
        "total_area": float(totals_row.total_area) if totals_row and totals_row.total_area is not None else 0.0,
        "total_indemnity": float(totals_row.total_indemnity) if totals_row and totals_row.total_indemnity is not None else 0.0,
        "growth_stage_distribution": [
            {"crop_stage": r.crop_stage, "farm_count": r.farm_count} for r in growth_stage_rows
        ],
        "signal_breakdown": [
            {"wind_velocity": r.wind_velocity, "farm_count": r.farm_count, "total_area": float(r.total_area)}
            for r in signal_rows
        ],
    }


@router.get("/export")
def export_assessments_csv(
    typhoon_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Downloads a PCIC-formatted CSV: original pabs_results.csv row layout with the
    Sprint 4 computed columns appended. Only includes assessments this engine
    computed (matrix_id is not null) -- excludes the legacy rows created at CSV
    import time, which have no matrix_id. Optionally scoped to a single typhoon.
    """
    query = db.query(RiskAssessment).filter(RiskAssessment.matrix_id.isnot(None))

    if typhoon_id is not None:
        query = query.join(
            AreaExposureSummary, RiskAssessment.summary_id == AreaExposureSummary.summary_id
        ).filter(AreaExposureSummary.typhoon_id == typhoon_id)

    assessments = query.order_by(RiskAssessment.assessment_date.desc()).all()

    rows = []
    for a in assessments:
        insurance = a.insurance_record
        farm = insurance.farm if insurance else None
        farmer = (
            db.query(FarmerProfile).filter(FarmerProfile.farmer_id == insurance.farmer_id).first()
            if insurance and insurance.farmer_id
            else None
        )
        boundary = (
            db.query(AdminBoundary).filter(AdminBoundary.boundary_id == farm.boundary_id).first()
            if farm and farm.boundary_id
            else None
        )

        rows.append(
            {
                "Province": boundary.province if boundary else None,
                "Municipality": boundary.municipality if boundary else None,
                "Barangay": boundary.barangay if boundary else None,
                "RSBSA No.": farmer.rsbsa_no if farmer else None,
                "Surname": farmer.last_name if farmer else None,
                "Firstname": farmer.first_name if farmer else None,
                "Middlename": farmer.middle_name if farmer else None,
                "Farm ID": farm.csv_farm_reference if farm else None,
                "Georef ID": farm.georef_id if farm else None,
                "Area": float(farm.area_size) if farm else None,
                "Policy No.": insurance.policy_no if insurance else None,
                "Program Type": insurance.program_type if insurance else None,
                "Effectivity Date": insurance.effectivity_date if insurance else None,
                "Expiry Date": insurance.expiry_date if insurance else None,
                "InsuredAmountofCover": float(insurance.amount_cover) if insurance else None,
                "Stage No.": a.crop_stage_no,
                "Stage": a.crop_stage,
                "Wind Signal (TCWS)": a.wind_velocity,
                "Period of Exposure (Hours)": a.period_of_exposure,
                "EstimatedDamage": float(a.estimated_damage),
                "Final Indemnity Payment": float(a.final_indemnity_payment),
                "Assessment Date": a.assessment_date,
            }
        )

    dataframe = pd.DataFrame(rows)
    buffer = io.StringIO()
    dataframe.to_csv(buffer, index=False)
    buffer.seek(0)

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=pcic_payout_export.csv"},
    )


# PCIC's fixed values for the PABS P/REMARKS columns (2026-10-12, per
# Cristian, from PCIC's final-output reference). P = prevalence, always 100%.
PABS_PREVALENCE = "1.0"
PABS_REMARKS = "Prolonged destructive winds caused severe crop damage with critical production loss."


def _yield_loss_fraction(assessment: RiskAssessment) -> str | None:
    """PABS "S": the RECSAP step-1 estimated yield loss % as a fraction,
    trailing zeros trimmed (30.00 -> "0.3", 25.00 -> "0.25", 5.00 -> "0.05")."""
    if assessment.matrix is None or assessment.matrix.estimated_yield_loss is None:
        return None
    fraction = assessment.matrix.estimated_yield_loss / 100
    return f"{fraction:.4f}".rstrip("0").rstrip(".") or "0"


def _build_pabs_rows(db: Session) -> list[dict]:
    """
    Shared row-building for the PABS-format views (JSON summary + CSV export):
    every typhoon combined, not scoped to one bulletin/typhoon folder, in the
    exact column layout PCIC's PABS system requires for indemnity computation,
    per Fabio's request.

    2026-10-12 (per Cristian, from PCIC's final-output reference): IRID was
    dropped; P is PCIC's fixed 100% prevalence (PABS_PREVALENCE); S is the
    assessment's RECSAP estimated yield loss as a fraction
    (_yield_loss_fraction); REMARKS is PCIC's fixed sentence (PABS_REMARKS).
    P and S are strings so the CSV's float_format="%.2f" doesn't turn them
    into "1.00"/"0.30".
    """
    assessments = (
        db.query(RiskAssessment)
        .filter(RiskAssessment.matrix_id.isnot(None))
        .order_by(RiskAssessment.assessment_date.desc())
        .all()
    )

    rows = []
    for a in assessments:
        insurance = a.insurance_record
        farm = insurance.farm if insurance else None
        farmer = (
            db.query(FarmerProfile).filter(FarmerProfile.farmer_id == insurance.farmer_id).first()
            if insurance and insurance.farmer_id
            else None
        )
        summary = (
            db.query(AreaExposureSummary).filter(AreaExposureSummary.summary_id == a.summary_id).first()
            if a.summary_id
            else None
        )
        typhoon = (
            db.query(Typhoon).filter(Typhoon.typhoon_id == summary.typhoon_id).first()
            if summary and summary.typhoon_id
            else None
        )

        # Same shape as before ('ABANES, ALFONSO. F.'), but a farmer with no name
        # on file now exports as an empty cell rather than a bare ', .'.
        farmer_name = format_surname_first(farmer, with_middle_initial=True)

        rows.append(
            {
                "assessment_id": a.assessment_id,
                "FARMER_NAME": farmer_name,
                "FARMERID": farmer.farmers_id if farmer else None,
                "FARMID": farm.farm_id if farm else None,
                "AREA": float(farm.area_size) if farm and farm.area_size is not None else None,
                "TYPHOON_NAME": typhoon.name if typhoon else None,
                "PERIOD_OF_EXPOSURE": a.period_of_exposure,
                "WIND_VELOCITY": a.wind_velocity,
                # MM/DD/YYYY -- matches the PABS reference format exactly (see
                # pabs_format_mockup.csv), not the raw datetime the DB stores.
                "DATE_FILED": a.assessment_date.strftime("%m/%d/%Y") if a.assessment_date else None,
                "DATE_OF_OCCURRENCE": summary.start_time.strftime("%m/%d/%Y") if summary and summary.start_time else None,
                "P": PABS_PREVALENCE,
                "S": _yield_loss_fraction(a),
                "AC": float(insurance.amount_cover) if insurance and insurance.amount_cover is not None else None,
                # Left blank on purpose (2026-10-12, per Cristian): the payout
                # calculation is being changed per PCIC's request (Fabio). Not
                # the lowercase final_indemnity_payment below, which still
                # drives export locking.
                "FINAL_INDEMNITY_PAYMENT": None,
                "REMARKS": PABS_REMARKS,
                # Extra fields beyond the PABS spec, kept for on-screen filtering/context
                # (not written to the CSV export).
                "municipality": farm.boundary.municipality if farm and farm.boundary else None,
                "province": farm.boundary.province if farm and farm.boundary else None,
                # Used by export_assessments_pabs_csv to lock exported policies.
                "insurance_records_id": a.insurance_records_id,
                "typhoon_id": summary.typhoon_id if summary else None,
                "final_indemnity_payment": float(a.final_indemnity_payment) if a.final_indemnity_payment is not None else None,
            }
        )
    return rows


@router.get("/pabs-summary")
def get_assessments_pabs_summary(db: Session = Depends(get_db)):
    """JSON version of the PABS-format combined summary, for on-screen display."""
    return {"status": "success", "data": _build_pabs_rows(db)}


@router.post("/export-pabs")
def export_assessments_pabs_csv(db: Session = Depends(get_db)):
    """
    Downloads the same combined PABS-format summary as a CSV file, and locks
    every exported policy with a payout as used (see
    AssessmentService.finalize_exported_usage) so no later typhoon can reuse
    it. POST rather than GET because exporting now changes data.
    """
    rows = _build_pabs_rows(db)
    AssessmentService.finalize_exported_usage(
        [
            (row["insurance_records_id"], row["typhoon_id"], row["assessment_id"])
            for row in rows
            if row["insurance_records_id"] is not None
            and row["typhoon_id"] is not None
            and (row["final_indemnity_payment"] or 0) > 0
        ],
        db,
    )
    # Locked policies no longer count as active insurance, so cached Farm
    # Records pages are stale now (2026-10-12).
    invalidate_farms_cache()
    pabs_columns = [
        "FARMER_NAME", "FARMERID", "FARMID", "AREA", "TYPHOON_NAME",
        "PERIOD_OF_EXPOSURE", "WIND_VELOCITY", "DATE_FILED", "DATE_OF_OCCURRENCE",
        "P", "S", "AC", "FINAL_INDEMNITY_PAYMENT", "REMARKS",
    ]
    dataframe = pd.DataFrame(rows, columns=pabs_columns)
    buffer = io.StringIO()
    # float_format matches AREA/AC to the reference format's 2-decimal style
    # (e.g. "16542.00", not "16542.0").
    dataframe.to_csv(buffer, index=False, float_format="%.2f")
    buffer.seek(0)

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=pabs_indemnity_export.csv"},
    )
