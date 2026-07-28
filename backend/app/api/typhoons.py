from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import AreaExposureSummary, RiskAssessment, TropicalCycloneBulletin, Typhoon

router = APIRouter(prefix="/typhoons", tags=["typhoons"])


@router.get("/{typhoon_id}/summary")
def get_typhoon_summary(typhoon_id: int, db: Session = Depends(get_db)):
    """
    Read-only consolidated summary for a typhoon's entire bulletin sequence:
    every affected municipality (per tbl_area_exposure_summary), aggregate
    area-affected/exposure figures, and payout totals (per tbl_risk_assessment).

    Does not compute anything itself — it only reads whatever's already been
    computed (by the auto-trigger on the typhoon's final bulletin, or by the
    manual compute-exposure/calculate endpoints), so it works for any typhoon
    regardless of is_active state, including one with nothing computed yet.
    """
    typhoon = db.query(Typhoon).filter(Typhoon.typhoon_id == typhoon_id).first()
    if typhoon is None:
        raise HTTPException(status_code=404, detail="Typhoon not found.")

    bulletins = (
        db.query(TropicalCycloneBulletin)
        .filter(TropicalCycloneBulletin.typhoon_id == typhoon_id)
        .order_by(TropicalCycloneBulletin.issued_at.asc())
        .all()
    )

    areas = db.query(AreaExposureSummary).filter(AreaExposureSummary.typhoon_id == typhoon_id).all()

    assessments = (
        db.query(RiskAssessment)
        .join(AreaExposureSummary, RiskAssessment.summary_id == AreaExposureSummary.summary_id)
        .filter(AreaExposureSummary.typhoon_id == typhoon_id)
        .all()
    )

    return {
        "status": "success",
        "typhoon_id": typhoon.typhoon_id,
        "typhoon_name": typhoon.name,
        "year": typhoon.year,
        "is_active": typhoon.is_active,
        "total_bulletins_issued": len(bulletins),
        "first_issued_at": bulletins[0].issued_at if bulletins else None,
        "last_issued_at": bulletins[-1].issued_at if bulletins else None,
        "total_municipalities_affected": len(areas),
        "peak_signal_level": max((a.max_signal_level for a in areas), default=None),
        "total_eligible_boundaries": sum(1 for a in areas if a.is_eligible_6hr),
        "areas_affected": [
            {
                "boundary_id": a.boundary_id,
                "province": a.province,
                "municipality": a.municipality,
                "max_signal_level": a.max_signal_level,
                "start_time": a.start_time,
                "end_time": a.end_time,
                "total_exposure_hours": float(a.total_exposure_hours),
                "is_eligible_6hr": a.is_eligible_6hr,
            }
            for a in areas
        ],
        "assessments_computed": len(assessments),
        "total_indemnity_payout": float(sum(a.final_indemnity_payment for a in assessments)),
    }
