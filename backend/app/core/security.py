"""
Real session-token auth. Before this, login checked real credentials against
tbl_system_users but issued nothing -- the frontend just trusted a plain
{name, role, email} object in localStorage forever, and no backend route
ever verified who (or whether anyone) was calling it. "Admin-only" was a
frontend UI convention only; any route was directly callable by anyone.

Deliberately a stateless signed JWT, not a DB-backed session table (see
2026-08-16 FUNCTION_CHANGES.md entry for the tradeoff discussion) -- per
Fabio's explicit direction, the token is invalidated by discarding it
client-side (an explicit Logout click, or the client-side inactivity timer
in App.tsx), not by a server-side expiry/blocklist. TOKEN_EXPIRY_HOURS below
is a safety-net upper bound, not the timeout mechanism itself.
"""
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import SystemUser

# No insecure hardcoded fallback (unlike DATABASE_URL's local-dev default) --
# this is what makes tokens unforgeable, so an unset value fails loudly at
# import time rather than silently signing tokens with a guessable default.
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not JWT_SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY is not set. Generate one and add it to backend/.env -- "
        "see .claude/ENV_GUIDE.md. The backend cannot start without it."
    )

JWT_ALGORITHM = "HS256"
TOKEN_EXPIRY_HOURS = 24


def create_access_token(user: SystemUser) -> str:
    payload = {
        "sub": str(user.user_id),
        "role": user.role,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRY_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def get_current_user(
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> SystemUser:
    """
    Verifies the `Authorization: Bearer <token>` header, present on every
    authenticated frontend request (see frontend/src/lib/api.ts's request()).
    Also stamps `request.state.user` -- read back by main.py's activity-log
    middleware after the route finishes, so logged actions know who
    performed them without decoding the token a second time.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated.")
    token = authorization.removeprefix("Bearer ").strip()

    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session token.")

    user = db.query(SystemUser).filter(SystemUser.user_id == int(payload["sub"])).first()
    # Re-checks is_active on every request, not just at login -- a token
    # issued before an admin deactivates the account stops working
    # immediately instead of staying valid until it naturally expires.
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Account not found or deactivated.")

    request.state.user = user
    return user


def require_admin(user: SystemUser = Depends(get_current_user)) -> SystemUser:
    if user.role != "System Administrator":
        raise HTTPException(status_code=403, detail="Administrator access required.")
    return user
