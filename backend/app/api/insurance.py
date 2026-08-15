from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import InsuranceRecord

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
