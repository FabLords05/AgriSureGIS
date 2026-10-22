from datetime import datetime, timezone

import bcrypt
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.activity_log import note_activity, record_activity
from app.core.database import get_db
from app.core.security import create_access_token, get_current_user, require_admin
from app.models.models import SystemUser
from app.services.email_alert_service import send_account_status_email

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


# The only role this API creates, lists, or edits (2026-10-22). System
# Administrator accounts are provisioned by the superuser outside the app
# (seed_system_users.py / SQL), so admins manage GIS Specialists only: they
# can't see, create, promote to, or edit an admin account, and public
# registration can't request one.
MANAGED_ROLE = "GIS Specialist"


class RegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=1)
    email: EmailStr
    employee_id: str = Field(..., min_length=1)
    role: str = MANAGED_ROLE
    password: str = Field(..., min_length=8)
    division: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class CreateUserRequest(BaseModel):
    name: str = Field(..., min_length=1)
    email: EmailStr
    role: str = MANAGED_ROLE
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


def _full_name(u: SystemUser) -> str:
    return f"{u.firstname} {u.lastname}".strip()


def _account_changes(user: SystemUser, payload) -> list[str]:
    """Before -> after phrases for the Activity Log remarks, computed BEFORE the
    payload is applied. Passwords are only ever named, never logged."""
    changes = []
    fields = payload.model_fields_set
    if "name" in fields and payload.name is not None and payload.name.strip() != _full_name(user):
        changes.append(f'name "{_full_name(user)}" → "{payload.name.strip()}"')
    if "email" in fields and payload.email is not None and payload.email != user.email:
        changes.append(f"email {user.email} → {payload.email}")
    if getattr(payload, "role", None) is not None and payload.role != user.role:
        changes.append(f"role {user.role} → {payload.role}")
    if getattr(payload, "is_active", None) is not None and payload.is_active != user.is_active:
        changes.append("account activated" if payload.is_active else "account deactivated")
    if payload.session_timeout_minutes is not None and payload.session_timeout_minutes != user.session_timeout_minutes:
        changes.append(f"session timeout {user.session_timeout_minutes} → {payload.session_timeout_minutes} min")
    if getattr(payload, "new_password", None) is not None:
        changes.append("password changed")
    return changes


def _require_role(role: str) -> None:
    if role != MANAGED_ROLE:
        raise HTTPException(status_code=400, detail=f"Role must be {MANAGED_ROLE}.")


@router.post("/register")
def register_user(payload: RegisterRequest, db: Session = Depends(get_db)):
    """
    Public self-registration (LoginScreen's "Request System Access" form) --
    creates a pending account (is_active=False) awaiting administrator
    approval via the Calibration & Settings User Account Management panel.
    """
    note_activity(
        f"Access request from {payload.full_name.strip()} <{payload.email}> "
        f"(employee ID {payload.employee_id}, role {payload.role})."
    )
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
    note_activity(
        f"Access request from {payload.full_name.strip()} <{payload.email}> "
        f"(employee ID {payload.employee_id}, role {payload.role}) submitted; "
        "account created inactive, pending administrator approval."
    )
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
        reason = "wrong password" if user else "no account with this email"
        record_activity(
            db, user.user_id if user else None, "LOGIN", "/api/users/login", 401,
            f"Failed login attempt for {payload.email}: {reason}.",
        )
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    if not user.is_active:
        record_activity(
            db, user.user_id, "LOGIN", "/api/users/login", 403,
            f"Login blocked for {payload.email}: the account is not active "
            "(pending administrator approval or deactivated).",
        )
        raise HTTPException(status_code=403, detail="This account is pending administrator approval.")

    user.last_login = datetime.now(timezone.utc)
    db.commit()
    record_activity(
        db, user.user_id, "LOGIN", "/api/users/login", 200,
        f"Logged in as {_full_name(user)} ({user.role}).",
    )
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
    record_activity(
        db, current_user.user_id, "LOGOUT", "/api/users/logout", 200,
        f"{_full_name(current_user)} logged out.",
    )
    return {"status": "success"}


@router.get("/")
def list_users(db: Session = Depends(get_db), _admin: SystemUser = Depends(require_admin)):
    """Backs the User Management tab -- GIS Specialist accounts only, never admins."""
    users = (
        db.query(SystemUser)
        .filter(SystemUser.role == MANAGED_ROLE)
        .order_by(SystemUser.user_id.asc())
        .all()
    )
    return {"status": "success", "data": [_user_to_dict(u) for u in users]}


@router.post("/")
def create_user(payload: CreateUserRequest, db: Session = Depends(get_db), _admin: SystemUser = Depends(require_admin)):
    """Admin-created account (Calibration's "Add User") -- active immediately, no approval step needed."""
    note_activity(f"Create {payload.role} account for {payload.name.strip()} <{payload.email}>.")
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
    note_activity(f"Created {user.role} account for {_full_name(user)} <{user.email}>; active immediately.")
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
    changes = _account_changes(user, payload)
    note_activity(f"Update own account ({'; '.join(changes) or 'no changes'}).")

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
    note_activity(f"Updated own account: {'; '.join(changes) or 'no changes'}.")
    return {"status": "success", "data": _user_to_dict(user)}


@router.patch("/{user_id}")
def update_user(
    user_id: int,
    payload: UpdateUserRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _admin: SystemUser = Depends(require_admin),
):
    """
    Admin edit / activate / deactivate (User Management's Edit modal +
    Deactivate button), GIS Specialist accounts only. When is_active actually changes, the affected user is emailed
    about it (any role) after the response is sent, so the admin's save never
    waits on the mail server.
    """
    note_activity(f"Update user account #{user_id}.")
    user = db.query(SystemUser).filter(SystemUser.user_id == user_id).first()
    # Admin accounts answer 404 like a missing one -- they're outside this
    # API's scope, and that doesn't confirm to the caller that one exists.
    if not user or user.role != MANAGED_ROLE:
        raise HTTPException(status_code=404, detail="User not found.")
    was_active = user.is_active
    target = f"{_full_name(user)} <{user.email}>"
    changes = _account_changes(user, payload)
    note_activity(f"Update user account {target} ({'; '.join(changes) or 'no changes'}).")

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

    if user.is_active != was_active:
        background_tasks.add_task(
            send_account_status_email,
            user.email,
            f"{user.firstname} {user.lastname}".strip(),
            user.is_active,
        )
        changes.append(f"{'activation' if user.is_active else 'deactivation'} email sent to {user.email}")
    note_activity(f"Updated user account {target}: {'; '.join(changes) or 'no changes'}.")
    return {"status": "success", "data": _user_to_dict(user)}
