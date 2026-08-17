"""
Optional Redis-backed cache for GET /api/farms/'s page responses.

This is a no-op unless REDIS_URL is set: without it, get_cached_farms_page()
always returns None (cache miss) and cache_farms_page()/invalidate_farms_cache()
do nothing -- behavior is identical to not having this module at all. Built
to degrade gracefully rather than require installing/running Redis just to
pick this change up -- same handoff philosophy as the DB/venv/npm rules in
.claude/CLAUDE.md: the code can be written here, but standing up a new
service is Fabio's call, made in his own environment. To actually enable
it: `pip install redis` (not in requirements.txt -- deliberately not a
forced dependency), run a Redis server, and set REDIS_URL (e.g.
redis://localhost:6379/0) in backend/.env.

Why this matters at all: multiple real users each independently walking the
same ~48,588-farm dataset would otherwise each cost the DB the same queries
redundantly. A shared cache means only the first request for a given page
actually touches Postgres within the TTL window; everyone else gets served
from Redis instead. Client-side IndexedDB caching (frontend/src/lib/useFarmsData.ts)
only helps repeat visits from the *same* browser -- it can't help a
different user's first walk, which is the gap this closes.
"""
import json
import os
from typing import Any

# Short enough that a CSV/GPX upload's new data shows up reasonably promptly
# even without invalidate_farms_cache() (belt-and-suspenders -- that's also
# called explicitly from backend/app/api/upload.py after a successful
# ingest, so this TTL is really just a backstop).
_TTL_SECONDS = 300

_redis_client = None
_redis_unavailable = False


def _get_client():
    """Lazily connects on first use, memoizing both success and failure so
    every request doesn't retry a connection that's never going to work
    (REDIS_URL unset, or set but nothing is actually listening).
    """
    global _redis_client, _redis_unavailable
    if _redis_client is not None or _redis_unavailable:
        return _redis_client

    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        _redis_unavailable = True
        return None

    try:
        import redis  # optional dependency -- see this module's docstring
        client = redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        _redis_client = client
    except Exception:
        # Configured but unreachable (not installed, not running, wrong
        # URL...) -- fail safe to "no caching," never break the request.
        _redis_unavailable = True
    return _redis_client


# municipality defaults to None (not "" ) so a request with no filter and a
# request explicitly filtering to some future "" value can never collide.
def _cache_key(*, limit: int | None, after_id: int, active_only: bool, municipality: str | None = None) -> str:
    return f"agrisuregis:farms:{limit}:{after_id}:{active_only}:{municipality}"


def get_cached_farms_page(
    *, limit: int | None, after_id: int, active_only: bool, municipality: str | None = None
) -> dict[str, Any] | None:
    client = _get_client()
    if client is None:
        return None
    try:
        raw = client.get(_cache_key(limit=limit, after_id=after_id, active_only=active_only, municipality=municipality))
        return json.loads(raw) if raw else None
    except Exception:
        return None  # fail safe -- any Redis error is treated as a cache miss


def cache_farms_page(
    *,
    limit: int | None,
    after_id: int,
    active_only: bool,
    result: dict[str, Any],
    municipality: str | None = None,
) -> None:
    client = _get_client()
    if client is None:
        return
    try:
        client.setex(
            _cache_key(limit=limit, after_id=after_id, active_only=active_only, municipality=municipality),
            _TTL_SECONDS,
            json.dumps(result),
        )
    except Exception:
        pass  # best-effort -- a failed cache write should never break the request


def invalidate_farms_cache() -> None:
    """Called after a write that changes farm/insurance data through the app
    (CSV/GPX upload) so the next request re-reads fresh data immediately
    instead of waiting out _TTL_SECONDS. Scripts that write directly to the
    DB outside the app (e.g. backend/seed_active_insurance.py) bypass this
    the same way they already bypass frontend cache invalidation -- see
    that script's own docstring/changelog entry for the same caveat.
    """
    client = _get_client()
    if client is None:
        return
    try:
        for key in client.scan_iter("agrisuregis:farms:*"):
            client.delete(key)
    except Exception:
        pass
