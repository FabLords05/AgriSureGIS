"""
Shared helper for writing to tbl_activity_log. Used three ways:

1. main.py's activity-log middleware calls this generically for every
   mutating (POST/PUT/PATCH/DELETE) request -- plus the two CSV export GETs
   in _LOGGED_GET_PATHS -- that isn't self-logged (see #2), resolving the
   acting user from `request.state.user` (stamped by
   app/core/security.py's get_current_user dependency).
2. app/api/users.py's login/logout routes call this directly instead, since
   neither fits the generic case cleanly: a login attempt (successful or
   not) has no bearer token yet for get_current_user to have populated
   request.state.user from, and both want a distinct LOGIN/LOGOUT action
   label rather than the generic "POST" the middleware would otherwise
   record for those two paths.
3. Work that finishes outside any request -- the CSV ingestion thread
   (INGEST) and the scheduled PAGASA poll (SYSTEM) -- calls this directly
   once it knows its real outcome.

Remarks (2026-10-22): every entry also carries a free-text `remarks`
sentence saying exactly what was done -- which file, which record, what
changed, how many rows were accepted or rejected. A route states it with
note_activity() and the middleware picks it up; the route never needs a
`Request` parameter for this (so the tests that call route functions
directly are unaffected -- note_activity() is a no-op outside a request).
If the request ends in an HTTPException, main.py's exception handler adds
the error message the user saw via note_activity_error(), so a rejected
upload is logged with why it was rejected.

Never raises -- a logging failure must not break the request it's
describing. Every write is its own short-lived commit, deliberately not
sharing a transaction with whatever the route itself is doing, so a logging
failure can't roll back real work (or vice versa).
"""
import logging
from contextvars import ContextVar, Token

from sqlalchemy.orm import Session

from app.models.models import ActivityLog, TropicalCycloneBulletin, Typhoon

logger = logging.getLogger("agrisuregis.activity_log")

# Remarks longer than this are cut -- a 23,917-row CSV can fail on thousands of
# rows, and the log only needs the first few reasons, not all of them.
_MAX_REMARKS_LENGTH = 2000

# One mutable holder per request, set by the middleware before the route runs.
# A dict rather than the string itself: the route runs in a copied context (a
# threadpool worker for a sync route), so re-setting the var there wouldn't be
# seen by the middleware, but mutating the shared dict is.
_request_remarks: ContextVar[dict | None] = ContextVar("activity_remarks", default=None)


def start_request_remarks() -> tuple[dict, Token]:
    holder: dict = {"remarks": None, "error": None}
    return holder, _request_remarks.set(holder)


def end_request_remarks(token: Token) -> None:
    _request_remarks.reset(token)


def note_activity(remarks: str) -> None:
    """Sets (or replaces) the current request's remarks. Call it early with
    what was attempted ('CSV upload "x.csv"') so a rejection is still
    described, then again with the outcome once it's known."""
    holder = _request_remarks.get()
    if holder is not None:
        holder["remarks"] = remarks


def note_activity_error(detail) -> None:
    holder = _request_remarks.get()
    if holder is not None:
        holder["error"] = _format_error_detail(detail)


def _format_error_detail(detail) -> str:
    # A RequestValidationError's detail is a list of pydantic error dicts.
    if isinstance(detail, list):
        parts = []
        for err in detail:
            if isinstance(err, dict):
                loc = ".".join(str(p) for p in err.get("loc", ())[1:]) or "request"
                parts.append(f"{loc}: {err.get('msg', 'invalid')}")
            else:
                parts.append(str(err))
        return "; ".join(parts)
    return str(detail)


def compose_request_remarks(holder: dict, status_code: int) -> str | None:
    remarks, error = holder.get("remarks"), holder.get("error")
    if not error:
        return remarks
    label = "Failed" if status_code >= 500 else "Rejected"
    return f"{remarks} {label}: {error}" if remarks else f"{label}: {error}"


def plural(count: int, singular: str, plural_form: str | None = None) -> str:
    return f"{count:,} {singular if count == 1 else (plural_form or singular + 's')}"


def describe_new_bulletins(created: list[dict], db: Session) -> str:
    """One line per newly-saved TCB, from scrape_and_save_all()'s return shape,
    e.g. 'Typhoon OPONG Bulletin #5 (Severe Tropical Storm, max Signal 3, 74 kph
    winds)'. Shared by the manual /bulletins/parse route and the scheduler.

    Never raises: it only describes an ingestion that already happened, so a
    lookup problem here falls back to the bulletin's title rather than
    failing the route that saved it."""
    parts = []
    for item in created:
        fallback = str(item.get("title") or f"TCB #{item.get('tcb_id')}")
        try:
            bulletin = db.get(TropicalCycloneBulletin, item["tcb_id"])
            if bulletin is None:
                parts.append(fallback)
                continue
            typhoon = db.get(Typhoon, bulletin.typhoon_id) if bulletin.typhoon_id else None
            details = [bulletin.category]
            details.append(f"max Signal {bulletin.max_signal_level}" if bulletin.max_signal_level else "no wind signal raised")
            if bulletin.max_sustained_winds:
                details.append(f"{bulletin.max_sustained_winds} kph winds")
            if bulletin.is_final:
                details.append("final bulletin")
            parts.append(
                f"{typhoon.name if typhoon else 'Unknown typhoon'} Bulletin #{bulletin.bulletin_count} "
                f"({', '.join(str(d) for d in details if d)})"
            )
        except Exception:
            logger.exception("Could not describe TCB %s for the activity log.", item.get("tcb_id"))
            parts.append(fallback)
    return "; ".join(parts)


def record_activity(
    db: Session,
    user_id: int | None,
    action: str,
    endpoint: str,
    status_code: int,
    remarks: str | None = None,
) -> None:
    if remarks and len(remarks) > _MAX_REMARKS_LENGTH:
        remarks = remarks[: _MAX_REMARKS_LENGTH - 1] + "…"
    try:
        db.add(ActivityLog(user_id=user_id, action=action, endpoint=endpoint, status_code=status_code, remarks=remarks))
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to record activity log entry (%s %s).", action, endpoint)
