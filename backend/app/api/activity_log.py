from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.security import require_admin
from app.models.models import ActivityLog, SystemUser

router = APIRouter(prefix="/activity-log", tags=["activity-log"], dependencies=[Depends(require_admin)])


def _entry_to_dict(entry: ActivityLog) -> dict:
    return {
        "log_id": entry.log_id,
        "user_name": f"{entry.user.firstname} {entry.user.lastname}".strip() if entry.user else None,
        "user_email": entry.user.email if entry.user else None,
        "action": entry.action,
        "endpoint": entry.endpoint,
        "status_code": entry.status_code,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


@router.get("/")
def list_activity_log(
    db: Session = Depends(get_db),
    limit: int = Query(200, ge=1, le=1000),
    user_id: int | None = Query(None),
):
    """
    Backs the admin-only Activity Log tab -- records every login, logout,
    and mutating (POST/PUT/PATCH/DELETE) backend call (see main.py's
    activity_log_middleware + app/api/users.py's explicit LOGIN/LOGOUT
    logging). Newest first, capped at `limit` -- this table has no upper
    bound on growth, so an unbounded query isn't safe long-term. Optional
    `user_id` narrows to one account (e.g. reviewing a single user's
    history from their row in User Management, not built yet but the filter
    is here for it).
    """
    query = db.query(ActivityLog).options(joinedload(ActivityLog.user))
    if user_id is not None:
        query = query.filter(ActivityLog.user_id == user_id)
    entries = query.order_by(ActivityLog.created_at.desc()).limit(limit).all()
    return {"status": "success", "data": [_entry_to_dict(e) for e in entries]}
