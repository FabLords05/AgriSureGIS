import io

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import AdminBoundary, AreaExposureSummary, FarmerProfile, InsuranceRecord, RiskAssessment, Typhoon
from app.services.assessment_service import AssessmentService

router = APIRouter(prefix="/assessments", tags=["assessments"])


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

    return {
        "status": "success",
        "data": [
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
            }
            for a in assessments
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


def _build_pabs_rows(db: Session) -> list[dict]:
    """
    Shared row-building for the PABS-format views (JSON summary + CSV export):
    every typhoon combined, not scoped to one bulletin/typhoon folder, in the
    exact column layout PCIC's PABS system requires for indemnity computation,
    per Fabio's request.

    Three columns from the required format -- IRID, P, and S -- have no known
    equivalent anywhere in our schema and no definition was available at
    implementation time (not in the manuscript, not in any project doc). They are
    left blank (None) rather than filled with guessed values. REMARKS is per the
    source format's own legend a manually-inputted field, so it's left blank too,
    for someone to fill in afterward -- this system has no source for that data.
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

        farmer_name = None
        if farmer:
            middle_initial = f" {farmer.middle_name[0]}." if farmer.middle_name else ""
            farmer_name = f"{farmer.last_name}, {farmer.first_name}.{middle_initial}"

        rows.append(
            {
                "assessment_id": a.assessment_id,
                "FARMER_NAME": farmer_name,
                "FARMERID": farmer.farmers_id if farmer else None,
                "FARMID": farm.farm_id if farm else None,
                "IRID": None,  # Unresolved -- see docstring above.
                "AREA": float(farm.area_size) if farm and farm.area_size is not None else None,
                "TYPHOON_NAME": typhoon.name if typhoon else None,
                "PERIOD_OF_EXPOSURE": a.period_of_exposure,
                "WIND_VELOCITY": a.wind_velocity,
                # MM/DD/YYYY -- matches the PABS reference format exactly (see
                # pabs_format_mockup.csv), not the raw datetime the DB stores.
                "DATE_FILED": a.assessment_date.strftime("%m/%d/%Y") if a.assessment_date else None,
                "DATE_OF_OCCURRENCE": summary.start_time.strftime("%m/%d/%Y") if summary and summary.start_time else None,
                "P": None,  # Unresolved -- see docstring above.
                "S": None,  # Unresolved -- see docstring above.
                "AC": float(insurance.amount_cover) if insurance and insurance.amount_cover is not None else None,
                "REMARKS": None,  # Manually inputted per the source format's own legend.
                # Extra fields beyond the PABS spec, kept for on-screen filtering/context
                # (not written to the CSV export).
                "municipality": farm.boundary.municipality if farm and farm.boundary else None,
                "province": farm.boundary.province if farm and farm.boundary else None,
            }
        )
    return rows


@router.get("/pabs-summary")
def get_assessments_pabs_summary(db: Session = Depends(get_db)):
    """JSON version of the PABS-format combined summary, for on-screen display."""
    return {"status": "success", "data": _build_pabs_rows(db)}


@router.get("/export-pabs")
def export_assessments_pabs_csv(db: Session = Depends(get_db)):
    """Downloads the same combined PABS-format summary as a CSV file."""
    rows = _build_pabs_rows(db)
    pabs_columns = [
        "FARMER_NAME", "FARMERID", "FARMID", "IRID", "AREA", "TYPHOON_NAME",
        "PERIOD_OF_EXPOSURE", "WIND_VELOCITY", "DATE_FILED", "DATE_OF_OCCURRENCE",
        "P", "S", "AC", "REMARKS",
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
