import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_
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
    ("POST", re.compile(r"^/api/upload/gpkg$"), "Uploaded a GeoPackage file"),
    ("INGEST", re.compile(r"^/api/upload/csv$"), "CSV ingestion finished"),
    ("SYSTEM", re.compile(r"^scheduler/pagasa-poll$"), "Automatic PAGASA TCB ingestion"),
    ("POST", re.compile(r"^/api/bulletins/parse$"), "Triggered a manual bulletin parse"),
    ("POST", re.compile(r"^/api/bulletins/upload$"), "Manually uploaded a bulletin PDF"),
    ("PUT", re.compile(r"^/api/bulletins/settings$"), "Updated parser settings"),
    ("POST", re.compile(r"^/api/bulletins/\d+/compute-exposure$"), "Computed exposure for a bulletin"),
    ("POST", re.compile(r"^/api/assessments/calculate$"), "Calculated assessments"),
    ("GET", re.compile(r"^/api/assessments/export$"), "Exported the PCIC payout CSV"),
    ("POST", re.compile(r"^/api/assessments/export-pabs$"), "Exported the final PABS indemnity CSV"),
    ("POST", re.compile(r"^/api/sar/check$"), "Ran the SAR planted check"),
    ("GET", re.compile(r"^/api/sar/field-verify/export$"), "Exported the SAR field verification CSV"),
    ("POST", re.compile(r"^/api/sar/layer$"), "Requested a SAR planted layer"),
    ("PUT", re.compile(r"^/api/sar/verifications/\d+$"), "Recorded a planted verification"),
    ("DELETE", re.compile(r"^/api/sar/verifications/\d+$"), "Cleared a planted verification"),
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


# The LOGIN/LOGOUT labels _summarize() derives from action + status code, as
# SQL conditions, so the Action filter can select them server-side.
_LOGIN_LABEL_FILTERS = {
    "Logged in": and_(ActivityLog.action == "LOGIN", ActivityLog.status_code == 200),
    "Login blocked (pending approval)": and_(ActivityLog.action == "LOGIN", ActivityLog.status_code == 403),
    "Failed login attempt": and_(ActivityLog.action == "LOGIN", ActivityLog.status_code.notin_([200, 403])),
    "Logged out": ActivityLog.action == "LOGOUT",
}

# Every summary the Action filter offers, in the order shown in its dropdown.
ACTION_TYPES: list[str] = list(_LOGIN_LABEL_FILTERS) + list(
    dict.fromkeys(summary for _, _, summary in _ENDPOINT_SUMMARIES)
)


def _action_type_filter(action_type: str):
    """SQL condition matching exactly the rows _summarize() labels
    `action_type`. Filtered in the database rather than the browser so a
    narrowed view reaches past the newest `limit` rows. Postgres's `~`
    regex operator accepts the same patterns as _ENDPOINT_SUMMARIES (`\\d`,
    `^`, `$`, `?`). No two patterns overlap, so first-match-wins in
    _summarize() and this any-match agree."""
    if action_type in _LOGIN_LABEL_FILTERS:
        return _LOGIN_LABEL_FILTERS[action_type]
    conditions = [
        and_(ActivityLog.action == method, ActivityLog.endpoint.op("~")(pattern.pattern))
        for method, pattern, summary in _ENDPOINT_SUMMARIES
        if summary == action_type
    ]
    if not conditions:
        raise HTTPException(status_code=400, detail=f'Unknown action type "{action_type}".')
    return or_(*conditions)


def _entry_to_dict(entry: ActivityLog) -> dict:
    return {
        "log_id": entry.log_id,
        "user_id": entry.user_id,
        "user_name": f"{entry.user.firstname} {entry.user.lastname}".strip() if entry.user else None,
        "user_email": entry.user.email if entry.user else None,
        "action": entry.action,
        "endpoint": entry.endpoint,
        "summary": _summarize(entry.action, entry.endpoint, entry.status_code),
        "remarks": entry.remarks,
        "status_code": entry.status_code,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


@router.get("/")
def list_activity_log(
    db: Session = Depends(get_db),
    limit: int = Query(200, ge=1, le=1000),
    user_id: int | None = Query(None),
    action_type: str | None = Query(None),
):
    """
    Backs the admin-only Activity Log tab -- records every login, logout,
    and mutating (POST/PUT/PATCH/DELETE) backend call (see main.py's
    activity_log_middleware + app/api/users.py's explicit LOGIN/LOGOUT
    logging). Newest first, capped at `limit` -- this table has no upper
    bound on growth, so an unbounded query isn't safe long-term. Optional
    `user_id` narrows to one account (e.g. reviewing a single user's
    history; used by the Activity Log tab's User filter since 2026-10-22).
    Optional `action_type` narrows to one summary label from ACTION_TYPES
    (the tab's Action filter); 400 for an unknown label.
    """
    query = db.query(ActivityLog).options(joinedload(ActivityLog.user))
    if user_id is not None:
        query = query.filter(ActivityLog.user_id == user_id)
    if action_type:
        query = query.filter(_action_type_filter(action_type))
    entries = query.order_by(ActivityLog.created_at.desc()).limit(limit).all()
    return {"status": "success", "data": [_entry_to_dict(e) for e in entries]}


@router.get("/filters")
def list_activity_log_filters(db: Session = Depends(get_db)):
    """
    Options for the Activity Log tab's User and Action dropdowns (2026-10-22):
    every account with at least one log entry (any role, admins included --
    unlike GET /api/users/, which lists GIS Specialists only), and every
    action summary label.
    """
    users = (
        db.query(SystemUser)
        .filter(SystemUser.user_id.in_(db.query(ActivityLog.user_id).filter(ActivityLog.user_id.isnot(None))))
        .order_by(SystemUser.firstname, SystemUser.lastname)
        .all()
    )
    return {
        "status": "success",
        "data": {
            "users": [
                {"user_id": u.user_id, "name": f"{u.firstname} {u.lastname}".strip(), "email": u.email, "role": u.role}
                for u in users
            ],
            "action_types": ACTION_TYPES,
        },
    }
