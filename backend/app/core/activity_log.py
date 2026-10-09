"""
Shared helper for writing to tbl_activity_log. Used two ways:

1. main.py's activity-log middleware calls this generically for every
   mutating (POST/PUT/PATCH/DELETE) request that isn't self-logged (see #2),
   resolving the acting user from `request.state.user` (stamped by
   app/core/security.py's get_current_user dependency).
2. app/api/users.py's login/logout routes call this directly instead, since
   neither fits the generic case cleanly: a login attempt (successful or
   not) has no bearer token yet for get_current_user to have populated
   request.state.user from, and both want a distinct LOGIN/LOGOUT action
   label rather than the generic "POST" the middleware would otherwise
   record for those two paths.

Never raises -- a logging failure must not break the request it's
describing. Every write is its own short-lived commit, deliberately not
sharing a transaction with whatever the route itself is doing, so a logging
failure can't roll back real work (or vice versa).
"""
import logging

from sqlalchemy.orm import Session

from app.models.models import ActivityLog

logger = logging.getLogger("agrisuregis.activity_log")


def record_activity(db: Session, user_id: int | None, action: str, endpoint: str, status_code: int) -> None:
    try:
        db.add(ActivityLog(user_id=user_id, action=action, endpoint=endpoint, status_code=status_code))
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to record activity log entry (%s %s).", action, endpoint)
