from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import Typhoon

router = APIRouter(prefix="/typhoons", tags=["typhoons"])


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
