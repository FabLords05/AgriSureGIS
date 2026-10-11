from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import (
    AreaExposureSummary,
    InsuranceRecord,
    InsuranceUsage,
    RiskAssessment,
    TropicalCycloneBulletin,
    Typhoon,
)

router = APIRouter(prefix="/typhoons", tags=["typhoons"], dependencies=[Depends(get_current_user)])


@router.get("/active")
def get_active_typhoons(db: Session = Depends(get_db)):
    """
    Typhoon(s) PAGASA's severe-weather-bulletin status page currently lists as
    active (see PagasaStatusService) -- not derived from TCB bulletin parsing.
    Backs the Monitoring dashboard's "Active Typhoon" card. Usually 0 or 1
    entries; PAGASA's status page can show more than one tab at once if
    multiple cyclones are active in the PAR simultaneously.
    """
    typhoons = (
        db.query(Typhoon)
        .filter(Typhoon.is_active.is_(True))
        .order_by(Typhoon.typhoon_id.desc())
        .all()
    )
    return {
        "status": "success",
        "active_typhoons": [
            {"typhoon_id": t.typhoon_id, "name": t.name, "year": t.year}
            for t in typhoons
        ],
    }


@router.get("/{typhoon_id}/progress")
def get_typhoon_progress(typhoon_id: int, db: Session = Depends(get_db)):
    """
    Backs the Monitoring dashboard's typhoon progress strip (2026-10-11):
    where one typhoon is in the workflow, from bulletins collected to the
    final PABS export. Read-only counts over data other steps already store;
    nothing here triggers a compute.

    in_par is Typhoon.is_active -- PAGASA's status page only lists cyclones
    inside PAR (see PagasaStatusService), so not listed means exited. No exit
    time is stored, so none is returned.

    assessed_farms only counts RiskAssessment rows tied to this typhoon's
    exposure summaries (summary_id), which leaves out the CSV-seeded rows
    (summary_id NULL) that only carry crop stage.
    """
    typhoon = db.query(Typhoon).filter(Typhoon.typhoon_id == typhoon_id).first()
    if typhoon is None:
        raise HTTPException(status_code=404, detail="Typhoon not found.")

    bulletin_count = (
        db.query(func.count(TropicalCycloneBulletin.tcb_id))
        .filter(TropicalCycloneBulletin.typhoon_id == typhoon_id)
        .scalar()
    )
    final_bulletin = (
        db.query(TropicalCycloneBulletin)
        .filter(TropicalCycloneBulletin.typhoon_id == typhoon_id, TropicalCycloneBulletin.is_final.is_(True))
        .order_by(TropicalCycloneBulletin.issued_at.desc())
        .first()
    )

    summary_ids = db.query(AreaExposureSummary.summary_id).filter(AreaExposureSummary.typhoon_id == typhoon_id)
    exposure_areas = summary_ids.count()

    assessed_farms = (
        db.query(func.count(func.distinct(InsuranceRecord.farm_id)))
        .join(RiskAssessment, RiskAssessment.insurance_records_id == InsuranceRecord.insurance_records_id)
        .filter(RiskAssessment.summary_id.in_(summary_ids))
        .scalar()
    )

    exported_policies, exported_at = (
        db.query(func.count(InsuranceUsage.usage_id), func.max(InsuranceUsage.finalized_at))
        .filter(InsuranceUsage.typhoon_id == typhoon_id, InsuranceUsage.finalized_at.isnot(None))
        .one()
    )

    return {
        "status": "success",
        "typhoon_id": typhoon.typhoon_id,
        "typhoon_name": typhoon.name,
        "in_par": typhoon.is_active,
        "bulletin_count": bulletin_count,
        "final_bulletin": (
            {"bulletin_count": final_bulletin.bulletin_count, "issued_at": final_bulletin.issued_at}
            if final_bulletin
            else None
        ),
        "exposure_areas": exposure_areas,
        "assessed_farms": assessed_farms or 0,
        "exported_policies": exported_policies,
        "exported_at": exported_at,
    }
