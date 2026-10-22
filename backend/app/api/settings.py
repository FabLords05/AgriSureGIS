"""
Admin Panel settings (2026-10-22) -- backs CalibrationModule.tsx, whose
coverage-rate field and damage-factor table used to be client-side only.

- The RSBSA coverage rate is the DEFAULT Amount of Cover per hectare, applied
  at upload only to records with no (or a zero) AmountofCover -- see
  app/api/upload.py. CSV values always win.
- The PCIC matrices are shown READ-ONLY: they are the real two-step lookup
  app/core/indemnity_calc.py pays out from, changed only by DB migration.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.activity_log import note_activity
from app.core.database import get_db
from app.core.security import get_current_user, require_admin
from app.core.system_settings import (
    AUTO_BACKUP_KEY,
    COVERAGE_RATE_KEY,
    COVERAGE_RATE_MAX,
    COVERAGE_RATE_MIN,
    get_setting,
    set_setting,
)
from app.models.models import IndemnityFactorMatrix, RecsapMatrix, SystemUser

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(get_current_user)])

# tbl_recsap_matrix.crop_stage_no -> label (PCIC Table 11's 3-stage taxonomy;
# see indemnity_calc.CROP_STAGE_TO_INDEMNITY_GROUP).
RECSAP_STAGE_LABELS = {1: "Booting", 2: "Flowering", 3: "Maturity"}


class CoverageRateRequest(BaseModel):
    coverage_rate_per_ha: float


class AutoBackupRequest(BaseModel):
    enabled: bool


def _settings_payload(db: Session) -> dict:
    return {
        "coverage_rate_per_ha": float(get_setting(db, COVERAGE_RATE_KEY)),
        "coverage_rate_min": COVERAGE_RATE_MIN,
        "coverage_rate_max": COVERAGE_RATE_MAX,
        "auto_backup_enabled": bool(get_setting(db, AUTO_BACKUP_KEY)),
    }


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    return {"status": "success", "data": _settings_payload(db)}


@router.put("/coverage-rate")
def update_coverage_rate(
    payload: CoverageRateRequest,
    db: Session = Depends(get_db),
    admin: SystemUser = Depends(require_admin),
):
    rate = payload.coverage_rate_per_ha
    if not COVERAGE_RATE_MIN <= rate <= COVERAGE_RATE_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"Coverage rate must be between ₱{COVERAGE_RATE_MIN:,} and ₱{COVERAGE_RATE_MAX:,} per hectare.",
        )
    previous = float(get_setting(db, COVERAGE_RATE_KEY))
    set_setting(db, COVERAGE_RATE_KEY, rate, admin.user_id)
    db.commit()
    note_activity(
        f"Changed the default RSBSA coverage rate from ₱{previous:,.2f} to ₱{rate:,.2f} per hectare "
        "(applies to future uploads with no Amount of Cover)."
    )
    return {"status": "success", "data": _settings_payload(db)}


@router.put("/auto-backup")
def update_auto_backup(
    payload: AutoBackupRequest,
    db: Session = Depends(get_db),
    admin: SystemUser = Depends(require_admin),
):
    set_setting(db, AUTO_BACKUP_KEY, payload.enabled, admin.user_id)
    db.commit()
    note_activity(f"{'Enabled' if payload.enabled else 'Disabled'} the automatic daily backup at 23:00 PHT.")
    return {"status": "success", "data": _settings_payload(db)}


@router.get("/matrices")
def get_matrices(db: Session = Depends(get_db), _admin: SystemUser = Depends(require_admin)):
    recsap = (
        db.query(RecsapMatrix)
        .filter(RecsapMatrix.is_active.is_(True))
        .order_by(RecsapMatrix.crop_stage_no, RecsapMatrix.wind_signal_tcws, RecsapMatrix.exposure_hours)
        .all()
    )
    indemnity = (
        db.query(IndemnityFactorMatrix)
        .filter(IndemnityFactorMatrix.is_active.is_(True))
        .order_by(IndemnityFactorMatrix.indemnity_id)
        .all()
    )
    return {
        "status": "success",
        "data": {
            "recsap": [
                {
                    "crop_stage_no": r.crop_stage_no,
                    "crop_stage": RECSAP_STAGE_LABELS.get(r.crop_stage_no, f"Stage {r.crop_stage_no}"),
                    "wind_signal_tcws": r.wind_signal_tcws,
                    "exposure_hours": r.exposure_hours,
                    "estimated_yield_loss": float(r.estimated_yield_loss),
                }
                for r in recsap
            ],
            "indemnity": [
                {
                    "crop_stage_group": r.crop_stage_group,
                    "yield_loss_min": float(r.yield_loss_min),
                    "yield_loss_max": float(r.yield_loss_max),
                    "indemnity_factor": float(r.indemnity_factor),
                }
                for r in indemnity
            ],
        },
    }
