from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import SystemUser

router = APIRouter(prefix="/users", tags=["users"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

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
        password_hash=pwd_context.hash(payload.password),
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
    email} shape App.tsx/authStorage.ts already expect, so nothing else
    downstream of a successful login needs to change.
    """
    user = db.query(SystemUser).filter(SystemUser.email == payload.email).first()
    if not user or not pwd_context.verify(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account is pending administrator approval.")

    user.last_login = datetime.now(timezone.utc)
    db.commit()
    return {
        "status": "success",
        "user": {"name": f"{user.firstname} {user.lastname}".strip(), "role": user.role, "email": user.email},
    }


@router.get("/")
def list_users(db: Session = Depends(get_db)):
    """Backs Calibration & Settings' User Account Management table (admin-exclusive in the UI)."""
    users = db.query(SystemUser).order_by(SystemUser.user_id.asc()).all()
    return {"status": "success", "data": [_user_to_dict(u) for u in users]}


@router.post("/")
def create_user(payload: CreateUserRequest, db: Session = Depends(get_db)):
    """Admin-created account (Calibration's "Add User") -- active immediately, no approval step needed."""
    _require_role(payload.role)

    firstname, lastname = _split_name(payload.name)
    user = SystemUser(
        # No employee-ID field in the admin "Add User" form (unlike public
        # self-registration) -- email local-part is a reasonable stand-in,
        # still unique since email itself is unique.
        username=payload.email.split("@")[0],
        password_hash=pwd_context.hash(payload.password),
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


@router.patch("/{user_id}")
def update_user(user_id: int, payload: UpdateUserRequest, db: Session = Depends(get_db)):
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

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    db.refresh(user)
    return {"status": "success", "data": _user_to_dict(user)}
