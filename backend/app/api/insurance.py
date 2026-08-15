from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import InsuranceRecord
from app.models.models import FarmerProfile, InsuranceRecord, InsuranceUsage

router = APIRouter(prefix="/insurance", tags=["insurance"], dependencies=[Depends(get_current_user)])


@router.get("/summary")
def get_insurance_summary(db: Session = Depends(get_db)):
    """
    Counts insurance policies currently within their effectivity/expiry window
    ("active" = today's date falls between effectivity_date and expiry_date,
    inclusive) against the total policy count. Backs Monitoring's "Active
    Insurance Policies" stat card.
    """
    today = date.today()
    total = db.query(InsuranceRecord).count()
    active = (
        db.query(InsuranceRecord)
        .filter(
            InsuranceRecord.effectivity_date.isnot(None),
            InsuranceRecord.expiry_date.isnot(None),
            InsuranceRecord.effectivity_date <= today,
            InsuranceRecord.expiry_date >= today,
        )
        .count()
    )
    return {"status": "success", "active_count": active, "total_count": total}


@router.get("/usage")
def get_insurance_usage(
    typhoon_id: int | None = Query(default=None),
    insurance_records_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Per-typhoon insurance usage status, sourced from tbl_insurance_usage (see
    AssessmentService._sync_insurance_usage). Optionally scoped to a single
    typhoon and/or a single policy line. Without typhoon_id, returns every
    typhoon a given policy has ever been assessed against -- callers that want
    only "is it used right now" should filter to a specific typhoon_id, since
    the same policy can be used for one typhoon and unused for another.
    """
    query = db.query(InsuranceUsage).join(InsuranceUsage.insurance_record)

    if typhoon_id is not None:
        query = query.filter(InsuranceUsage.typhoon_id == typhoon_id)
    if insurance_records_id is not None:
        query = query.filter(InsuranceUsage.insurance_records_id == insurance_records_id)

    usage_rows = query.order_by(InsuranceUsage.marked_at.desc()).all()

    data = []
    for u in usage_rows:
        insurance = u.insurance_record
        farmer = (
            db.query(FarmerProfile).filter(FarmerProfile.farmer_id == insurance.farmer_id).first()
            if insurance and insurance.farmer_id
            else None
        )
        data.append(
            {
                "usage_id": u.usage_id,
                "insurance_records_id": u.insurance_records_id,
                "typhoon_id": u.typhoon_id,
                "policy_no": insurance.policy_no if insurance else None,
                "farmer_id": farmer.farmer_id if farmer else None,
                "farmer_name": f"{farmer.last_name}, {farmer.first_name}" if farmer else None,
                "is_used": u.is_used,
                "assessment_id": u.assessment_id,
                "marked_at": u.marked_at,
            }
        )

    return {"status": "success", "data": data}
