from datetime import datetime, timezone

import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.activity_log import record_activity
from app.core.database import get_db
from app.core.security import create_access_token, get_current_user, require_admin
from app.models.models import SystemUser

router = APIRouter(prefix="/users", tags=["users"])


# Calls bcrypt directly rather than through passlib's CryptContext -- passlib
# 1.7.4 (last released 2020, effectively unmaintained) has a documented
# compatibility bug with bcrypt>=4.1.0 (it reads an `__about__.__version__`
# attribute bcrypt removed), which can silently break hashing/verification
# depending on the exact installed versions. bcrypt's own API is stable and
# simple enough not to need the wrapper.
def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed/foreign hash format (e.g. leftover passlib-produced hash
        # from before this change) -- treat as a failed verification, not a
        # crash.
        return False


# Only two roles actually mean anything anywhere else in this app (Login's
# role toggle, Registration's own restriction to GIS Specialist/System
# Administrator) -- kept in sync with those, not the UI prototype's wider
# 4-option dropdown (Data Analyst/Field Supervisor), which had no backing
# permission logic anywhere in the app.
ALLOWED_ROLES = {"GIS Specialist", "System Administrator"}


class RegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=1)
    email: EmailStr
    employee_id: str = Field(..., min_length=1)
    role: str
    password: str = Field(..., min_length=8)
    division: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class CreateUserRequest(BaseModel):
    name: str = Field(..., min_length=1)
    email: EmailStr
    role: str
    password: str = Field(..., min_length=8)


class UpdateUserRequest(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    role: str | None = None
    is_active: bool | None = None
    session_timeout_minutes: int | None = Field(None, ge=0, le=120)


class UpdateMeRequest(BaseModel):
    """
    Self-service counterpart to UpdateUserRequest -- deliberately has no
    `role`/`is_active` fields at all (not just left unset), so there's no
    payload shape that could ever let a user promote or reactivate/deactivate
    themselves. Those stay exclusively behind PATCH /{user_id} + require_admin.
    """
    name: str | None = Field(None, min_length=1)
    email: EmailStr | None = None
    session_timeout_minutes: int | None = Field(None, ge=0, le=120)
    current_password: str | None = None
    new_password: str | None = Field(None, min_length=8)


def _split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.strip().split(" ", 1)
    return (parts[0], parts[1] if len(parts) > 1 else "")


def _user_to_dict(u: SystemUser) -> dict:
    return {
        "user_id": u.user_id,
        "name": f"{u.firstname} {u.lastname}".strip(),
        "email": u.email,
        "role": u.role,
        "is_active": u.is_active,
        "last_login": u.last_login.isoformat() if u.last_login else None,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "session_timeout_minutes": u.session_timeout_minutes,
    }


def _require_role(role: str) -> None:
    if role not in ALLOWED_ROLES:
        raise HTTPException(status_code=400, detail=f"Role must be one of: {', '.join(sorted(ALLOWED_ROLES))}")


@router.post("/register")
def register_user(payload: RegisterRequest, db: Session = Depends(get_db)):
    """
    Public self-registration (LoginScreen's "Request System Access" form) --
    creates a pending account (is_active=False) awaiting administrator
    approval via the Calibration & Settings User Account Management panel.
    """
    _require_role(payload.role)

    firstname, lastname = _split_name(payload.full_name)
    user = SystemUser(
        username=payload.employee_id,
        password_hash=_hash_password(payload.password),
        email=payload.email,
        firstname=firstname,
        lastname=lastname,
        role=payload.role,
        is_active=False,
    )
    db.add(user)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this employee ID or email already exists.")
    db.refresh(user)
    return {"status": "success", "message": "Registration submitted. Pending administrator approval."}


@router.post("/login")
def login_user(payload: LoginRequest, db: Session = Depends(get_db)):
    """
    Real credential check against tbl_system_users, replacing the old
    client-side DEMO_ACCOUNTS comparison. Returns the same {name, role,
    email} shape App.tsx/authStorage.ts already expect, plus a real signed
    session token (2026-08-16 -- see app/core/security.py) that every other
    route now requires.
    """
    user = db.query(SystemUser).filter(SystemUser.email == payload.email).first()
    if not user or not _verify_password(payload.password, user.password_hash):
        # user_id logged as None on a wrong-email/wrong-password attempt (no
        # confirmed identity), or the real one on a right-email-wrong-password
        # attempt -- both worth an audit trail entry either way.
        record_activity(db, user.user_id if user else None, "LOGIN", "/api/users/login", 401)
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    if not user.is_active:
        record_activity(db, user.user_id, "LOGIN", "/api/users/login", 403)
        raise HTTPException(status_code=403, detail="This account is pending administrator approval.")

    user.last_login = datetime.now(timezone.utc)
    db.commit()
    record_activity(db, user.user_id, "LOGIN", "/api/users/login", 200)
    return {
        "status": "success",
        "token": create_access_token(user),
        "user": {
            "name": f"{user.firstname} {user.lastname}".strip(),
            "role": user.role,
            "email": user.email,
            "session_timeout_minutes": user.session_timeout_minutes,
        },
    }


@router.post("/logout")
def logout_user(db: Session = Depends(get_db), current_user: SystemUser = Depends(get_current_user)):
    """
    Does nothing to the token itself -- it's a stateless JWT with no
    server-side blocklist (see app/core/security.py's module docstring), so
    "logout" is really just the frontend discarding it. This endpoint exists
    purely so a LOGOUT event gets recorded before the frontend clears its
    local storage.
    """
    record_activity(db, current_user.user_id, "LOGOUT", "/api/users/logout", 200)
    return {"status": "success"}


@router.get("/")
def list_users(db: Session = Depends(get_db), _admin: SystemUser = Depends(require_admin)):
    """Backs Calibration & Settings' User Account Management table (admin-exclusive in the UI)."""
    users = db.query(SystemUser).order_by(SystemUser.user_id.asc()).all()
    return {"status": "success", "data": [_user_to_dict(u) for u in users]}


@router.post("/")
def create_user(payload: CreateUserRequest, db: Session = Depends(get_db), _admin: SystemUser = Depends(require_admin)):
    """Admin-created account (Calibration's "Add User") -- active immediately, no approval step needed."""
    _require_role(payload.role)

    firstname, lastname = _split_name(payload.name)
    user = SystemUser(
        # No employee-ID field in the admin "Add User" form (unlike public
        # self-registration) -- email local-part is a reasonable stand-in,
        # still unique since email itself is unique.
        username=payload.email.split("@")[0],
        password_hash=_hash_password(payload.password),
        email=payload.email,
        firstname=firstname,
        lastname=lastname,
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    db.refresh(user)
    return {"status": "success", "data": _user_to_dict(user)}


@router.patch("/me")
def update_me(payload: UpdateMeRequest, db: Session = Depends(get_db), current_user: SystemUser = Depends(get_current_user)):
    """
    Self-service Account Settings tab (2026-08-16) -- any authenticated user
    editing their own name/email/session timeout/password, no admin role
    required. Registered ahead of PATCH /{user_id} below so "/me" is matched
    as a static path first, not swallowed by the int-typed {user_id} route.
    """
    user = current_user

    if payload.name is not None:
        user.firstname, user.lastname = _split_name(payload.name)
    if payload.email is not None:
        user.email = payload.email
    if payload.session_timeout_minutes is not None:
        user.session_timeout_minutes = payload.session_timeout_minutes

    if payload.new_password is not None:
        if not payload.current_password or not _verify_password(payload.current_password, user.password_hash):
            raise HTTPException(status_code=400, detail="Current password is incorrect.")
        user.password_hash = _hash_password(payload.new_password)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    db.refresh(user)
    return {"status": "success", "data": _user_to_dict(user)}


@router.patch("/{user_id}")
def update_user(user_id: int, payload: UpdateUserRequest, db: Session = Depends(get_db), _admin: SystemUser = Depends(require_admin)):
    """Admin edit / activate / deactivate (Calibration's Edit modal + Deactivate button)."""
    user = db.query(SystemUser).filter(SystemUser.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    if payload.role is not None:
        _require_role(payload.role)

    if payload.name is not None:
        user.firstname, user.lastname = _split_name(payload.name)
    if payload.email is not None:
        user.email = payload.email
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.session_timeout_minutes is not None:
        user.session_timeout_minutes = payload.session_timeout_minutes

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    db.refresh(user)
    return {"status": "success", "data": _user_to_dict(user)}
