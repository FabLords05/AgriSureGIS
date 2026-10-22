"""
Read/write helpers for tbl_system_settings (2026-10-22).

DEFAULTS is the fallback for a key that has no row yet (e.g. an already-
provisioned DB the migration seed hasn't reached), so a missing row never
breaks an upload or the nightly backup job.
"""
from sqlalchemy.orm import Session

from app.models.models import SystemSetting

COVERAGE_RATE_KEY = "coverage_rate_per_ha"
AUTO_BACKUP_KEY = "auto_backup_enabled"

DEFAULTS = {
    # PCIC RSBSA fixed rate for rice, ₱ per hectare.
    COVERAGE_RATE_KEY: 25000,
    AUTO_BACKUP_KEY: True,
}

COVERAGE_RATE_MIN = 1000
COVERAGE_RATE_MAX = 100000


def get_setting(db: Session, key: str):
    row = db.query(SystemSetting).filter(SystemSetting.setting_key == key).first()
    return row.setting_value if row is not None else DEFAULTS.get(key)


def set_setting(db: Session, key: str, value, user_id: int | None) -> None:
    """Upserts one setting. Caller commits."""
    row = db.query(SystemSetting).filter(SystemSetting.setting_key == key).first()
    if row is None:
        db.add(SystemSetting(setting_key=key, setting_value=value, updated_by=user_id))
    else:
        row.setting_value = value
        row.updated_by = user_id


def get_coverage_rate(db: Session) -> float:
    return float(get_setting(db, COVERAGE_RATE_KEY))
