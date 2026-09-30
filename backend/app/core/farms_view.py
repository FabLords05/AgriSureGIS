"""
Optional materialized view (mv_farm_latest_insurance) precomputing "most
recent InsuranceRecord per farm" -- the thing backend/app/api/farms.py's
list_farms() otherwise recomputes on every request (bulk-fetch every
InsuranceRecord for the current page's farms, then reduce to one-per-farm
in Python). Creating the view is a DB migration
(backend/migrations/2026-08-09_farms_perf.sql), handed off for Fabio to run
himself via psql -- this module never assumes it exists.

Existence is checked once and memoized (`_view_exists`), not re-checked on
every request: a materialized view query failing mid-request would abort
that request's whole Postgres transaction (any SQL error does, until
ROLLBACK), which would break the *fallback* path too if not handled
carefully. Checking once up front avoids ever needing that recovery inside
a real request's transaction, and gives the same "just works before and
after the migration is applied" behavior as app/core/farms_cache.py's
REDIS_URL check.
"""
from sqlalchemy import text
from sqlalchemy.orm import Session

_view_exists: bool | None = None


def materialized_view_available(db: Session) -> bool:
    """Only memoizes a *positive* result permanently -- once the view is
    known to exist, no reason to keep re-checking. A negative result is
    re-checked on every call instead (a `pg_matviews` lookup is cheap and
    never at risk of the transaction-abort issue described in this module's
    docstring, unlike querying the view itself) so that running the
    migration doesn't require restarting the backend process for this to
    notice -- the very next request just starts using it.
    """
    global _view_exists
    if _view_exists is True:
        return True
    try:
        row = db.execute(
            text("SELECT 1 FROM pg_matviews WHERE matviewname = 'mv_farm_latest_insurance'")
        ).first()
        _view_exists = row is not None
    except Exception:
        db.rollback()
        _view_exists = False
    return _view_exists


def fetch_latest_insurance_from_view(db: Session, farm_ids: list[int]):
    """Returns {farm_id: Row} for the given farm_ids, Row exposing
    .policy_no/.effectivity_date/.expiry_date -- a drop-in replacement for
    the equivalent dict list_farms() builds from a raw InsuranceRecord query.
    """
    rows = db.execute(
        text(
            "SELECT farm_id, policy_no, effectivity_date, expiry_date "
            "FROM mv_farm_latest_insurance WHERE farm_id = ANY(:farm_ids)"
        ),
        {"farm_ids": farm_ids},
    ).all()
    return {row.farm_id: row for row in rows}


def refresh_farm_latest_insurance_view(db: Session) -> None:
    """Called after a write to tbl_insurance_records through the app
    (CSV/GPX upload) so the view doesn't serve stale data until its next
    scheduled/manual refresh. CONCURRENTLY avoids locking the view against
    concurrent reads during the refresh (requires the unique index the
    migration also creates). A no-op if the view doesn't exist yet -- same
    "not installed" fallback as materialized_view_available() above.

    Scripts that write directly to the DB outside the app (e.g.
    backend/seed_active_insurance.py) call this too, but only because they
    import and call it explicitly -- anything writing via raw psql bypasses
    it the same way it already bypasses everything else app-side.

    Deliberately doesn't skip based on a cached "doesn't exist" the way
    materialized_view_available()'s read path can -- this only runs after a
    write (not per-request), so the extra attempt is cheap, and skipping it
    on stale information would mean a migration applied mid-session doesn't
    get its first refresh until whatever the next write happens to be.
    """
    global _view_exists
    try:
        db.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_farm_latest_insurance"))
        db.commit()
        _view_exists = True
    except Exception:
        db.rollback()
        _view_exists = False
