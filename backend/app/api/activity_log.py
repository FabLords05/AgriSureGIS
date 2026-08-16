import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.security import require_admin
from app.models.models import ActivityLog, SystemUser

router = APIRouter(prefix="/activity-log", tags=["activity-log"], dependencies=[Depends(require_admin)])


# (method, path-regex) -> summary text, matched in order, first match wins.
# Dynamic id segments are matched generically (\d+) -- the summary never
# needs to name *which* row was touched, just what kind of action happened.
# Covers every mutating route in the app as of 2026-08-16; anything added
# later without a matching entry here just falls through to the raw
# "{ACTION} {endpoint}" format in _summarize() below, so it's never hidden.
_ENDPOINT_SUMMARIES: list[tuple[str, re.Pattern, str]] = [
    ("POST", re.compile(r"^/api/users/register$"), "Requested account registration"),
    ("POST", re.compile(r"^/api/users/?$"), "Created a new user account"),
    ("PATCH", re.compile(r"^/api/users/me$"), "Updated their own account"),
    ("PATCH", re.compile(r"^/api/users/\d+$"), "Updated a user account"),
    ("POST", re.compile(r"^/api/upload/csv$"), "Uploaded a CSV file"),
    ("POST", re.compile(r"^/api/upload/gpx$"), "Uploaded a GPX file"),
    ("POST", re.compile(r"^/api/bulletins/parse$"), "Triggered a manual bulletin parse"),
    ("POST", re.compile(r"^/api/bulletins/upload$"), "Manually uploaded a bulletin PDF"),
    ("PUT", re.compile(r"^/api/bulletins/settings$"), "Updated parser settings"),
    ("POST", re.compile(r"^/api/bulletins/\d+/compute-exposure$"), "Computed exposure for a bulletin"),
    ("POST", re.compile(r"^/api/assessments/calculate$"), "Calculated assessments"),
]


def _summarize(action: str, endpoint: str, status_code: int) -> str:
    """Human-readable summary of an activity-log row for the admin-facing
    table, replacing the raw action+endpoint pair (Fabio's explicit ask,
    2026-08-16)."""
    if action == "LOGIN":
        if status_code == 200:
            return "Logged in"
        if status_code == 403:
            return "Login blocked (pending approval)"
        return "Failed login attempt"
    if action == "LOGOUT":
        return "Logged out"

    for method, pattern, summary in _ENDPOINT_SUMMARIES:
        if action == method and pattern.match(endpoint):
            return summary

    return f"{action} {endpoint}"


def _entry_to_dict(entry: ActivityLog) -> dict:
    return {
        "log_id": entry.log_id,
        "user_name": f"{entry.user.firstname} {entry.user.lastname}".strip() if entry.user else None,
        "user_email": entry.user.email if entry.user else None,
        "action": entry.action,
        "endpoint": entry.endpoint,
        "summary": _summarize(entry.action, entry.endpoint, entry.status_code),
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
