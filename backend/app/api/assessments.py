import io

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import AdminBoundary, AreaExposureSummary, FarmerProfile, InsuranceRecord, RiskAssessment
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
                "crop_stage": a.crop_stage,
                "period_of_exposure": a.period_of_exposure,
                "wind_velocity": a.wind_velocity,
                "estimated_damage": float(a.estimated_damage),
                "final_indemnity_payment": float(a.final_indemnity_payment),
                "assessment_date": a.assessment_date,
            }
            for a in assessments
        ],
    }


@router.get("/export")
def export_assessments_csv(db: Session = Depends(get_db)):
    """
    Downloads a PCIC-formatted CSV: original pabs_results.csv row layout with the
    Sprint 4 computed columns appended. Only includes assessments this engine
    computed (matrix_id is not null) -- excludes the legacy rows created at CSV
    import time, which have no matrix_id.
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
