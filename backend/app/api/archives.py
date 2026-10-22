"""
Database Backup & Archive (2026-10-22) -- replaces DatabaseBackupModule.tsx's
UI-only mock. See app/services/archive_service.py and backup_service.py.

Access:
- Archive & Clear (eligibility + POST): any signed-in user. Both Admins
  (Database Backup tab) and GIS Specialists (Account Settings) may clear.
- Everything else (viewing archives, backups, dump downloads): Admin only.
Archives are read-only and are never restored into the live DB.
"""
import csv
import io
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.activity_log import note_activity, plural
from app.core.database import ArchiveNotConfiguredError, archive_configured, get_db
from app.core.security import get_current_user, require_admin
from app.models.models import BackupLog, SystemUser
from app.services import archive_service
from app.services.archive_service import CONFIRM_WORD, ArchiveBusyError, ArchiveError
from app.services.backup_service import BackupError, backup_file_path, gdrive_configured, run_backup

router = APIRouter(tags=["archives"], dependencies=[Depends(get_current_user)])


class ArchiveRequest(BaseModel):
    confirm: str


def _not_configured(exc: ArchiveNotConfiguredError) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc))


def _require_archive(archive_id: int) -> dict:
    try:
        archive = archive_service.get_archive(archive_id)
    except ArchiveNotConfiguredError as exc:
        raise _not_configured(exc)
    if archive is None:
        raise HTTPException(status_code=404, detail="Archive not found.")
    return archive


# ─── Archive & Clear (Admin + GIS Specialist) ────────────────────────────────

@router.get("/archives/eligibility")
def get_eligibility(db: Session = Depends(get_db)):
    data = archive_service.eligibility(db)
    data["archive_configured"] = archive_configured()
    data["confirm_word"] = CONFIRM_WORD
    return {"status": "success", "data": data}


@router.post("/archives")
def archive_and_clear(
    payload: ArchiveRequest,
    db: Session = Depends(get_db),
    user: SystemUser = Depends(get_current_user),
):
    note_activity("Attempted Archive & Clear of the live PABS records.")
    if payload.confirm.strip() != CONFIRM_WORD:
        raise HTTPException(status_code=400, detail=f'Type "{CONFIRM_WORD}" to confirm.')
    try:
        result = archive_service.archive_and_clear(db, user)
    except ArchiveNotConfiguredError as exc:
        raise _not_configured(exc)
    except ArchiveBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (ArchiveError, BackupError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    counts = result["row_counts"]
    drive = "uploaded to Google Drive" if result["gdrive_uploaded"] else "NOT uploaded to Google Drive"
    note_activity(
        f'Archived and cleared live PABS records for {result["label"]} (archive #{result["archive_id"]}): '
        f'{plural(counts.get("arc_farmers", 0), "farmer")}, {plural(counts.get("arc_farms", 0), "farm")}, '
        f'{plural(counts.get("arc_insurance_records", 0), "policy", "policies")}, '
        f'{plural(counts.get("arc_risk_assessment", 0), "assessment")}. '
        f'Safety dump {result["dump_file_name"]} {drive}.'
    )
    return {"status": "success", "data": result}


# ─── Viewing archives (Admin, read-only) ─────────────────────────────────────

@router.get("/archives")
def list_archives(_admin: SystemUser = Depends(require_admin)):
    try:
        data = archive_service.list_archives()
    except ArchiveNotConfiguredError as exc:
        raise _not_configured(exc)
    return {"status": "success", "data": data}


@router.get("/archives/{archive_id}/records")
def get_archive_records(
    archive_id: int,
    q: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _admin: SystemUser = Depends(require_admin),
):
    _require_archive(archive_id)
    return {"status": "success", "data": archive_service.archive_records(archive_id, q, page, page_size)}


@router.get("/archives/{archive_id}/farms")
def get_archive_farms(
    archive_id: int,
    bbox: str | None = Query(None, description="west,south,east,north (EPSG:4326)"),
    _admin: SystemUser = Depends(require_admin),
):
    _require_archive(archive_id)
    parsed = None
    if bbox:
        try:
            parsed = tuple(float(v) for v in bbox.split(","))
        except ValueError:
            parsed = None
        if parsed is None or len(parsed) != 4:
            raise HTTPException(status_code=400, detail="bbox must be west,south,east,north.")
    return archive_service.archive_farms_geojson(archive_id, parsed)


@router.get("/archives/{archive_id}/exposure")
def get_archive_exposure(archive_id: int, _admin: SystemUser = Depends(require_admin)):
    _require_archive(archive_id)
    return archive_service.archive_exposure_geojson(archive_id)


_EXPORT_COLUMNS = [
    ("farmers_id", "FARMERID"), ("farmer_name", "FARMER_NAME"), ("farm_reference", "FARMID"),
    ("province", "PROVINCE"), ("municipality", "MUNICIPALITY"), ("barangay", "BARANGAY"), ("area_size", "AREA"),
    ("policy_no", "CIC_NO"), ("program_type", "PROGRAM"), ("effectivity_date", "EFFECTIVITY_DATE"),
    ("expiry_date", "EXPIRY_DATE"), ("amount_cover", "AC"), ("typhoon_name", "TYPHOON_NAME"),
    ("typhoon_year", "TYPHOON_YEAR"), ("wind_signal", "TCWS"), ("crop_stage", "CROP_STAGE"),
    ("period_of_exposure", "PERIOD_OF_EXPOSURE"), ("wind_velocity", "WIND_VELOCITY"),
    ("indemnity_factor", "INDEMNITY_FACTOR"), ("estimated_damage", "ESTIMATED_DAMAGE"),
    ("final_indemnity_payment", "FINAL_INDEMNITY_PAYMENT"), ("assessment_date", "ASSESSMENT_DATE"),
]


@router.get("/archives/{archive_id}/export")
def export_archive_csv(archive_id: int, _admin: SystemUser = Depends(require_admin)):
    archive = _require_archive(archive_id)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([header for _, header in _EXPORT_COLUMNS])
    count = 0
    for row in archive_service.archive_records_all(archive_id):
        writer.writerow(["" if row[key] is None else row[key] for key, _ in _EXPORT_COLUMNS])
        count += 1

    slug = re.sub(r"[^A-Za-z0-9]+", "_", archive["label"]).strip("_") or "archive"
    filename = f"Archive_{archive_id}_{slug}.csv"
    note_activity(f'Exported archive #{archive_id} ({archive["label"]}) as "{filename}": {plural(count, "row")}.')
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─── Backups (Admin) ─────────────────────────────────────────────────────────

def _backup_dict(entry: BackupLog) -> dict:
    return {
        "backup_id": entry.backup_id,
        "kind": entry.kind,
        "file_name": entry.file_name,
        "size_bytes": entry.size_bytes,
        "status": entry.status,
        "error": entry.error,
        "gdrive_uploaded": entry.gdrive_file_id is not None,
        "gdrive_error": entry.gdrive_error,
        "created_at": entry.created_at,
        "file_available": backup_file_path(entry) is not None,
    }


@router.get("/backups")
def list_backups(db: Session = Depends(get_db), _admin: SystemUser = Depends(require_admin)):
    entries = db.query(BackupLog).order_by(BackupLog.created_at.desc()).limit(30).all()
    last_ok = (
        db.query(BackupLog).filter(BackupLog.status == "success").order_by(BackupLog.created_at.desc()).first()
    )
    stored = db.query(BackupLog).filter(BackupLog.status == "success").count()
    return {
        "status": "success",
        "data": {
            "backups": [_backup_dict(e) for e in entries],
            "last_backup": _backup_dict(last_ok) if last_ok else None,
            "stored_count": stored,
            "gdrive_configured": gdrive_configured(),
            "archive_configured": archive_configured(),
        },
    }


@router.post("/backups")
def create_backup(db: Session = Depends(get_db), admin: SystemUser = Depends(require_admin)):
    note_activity("Attempted a manual database backup.")
    try:
        entry = run_backup(db, "manual", admin.user_id)
    except BackupError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    drive = "uploaded to Google Drive" if entry.gdrive_file_id else "not uploaded to Google Drive"
    note_activity(f"Ran a manual database backup: {entry.file_name} ({entry.size_bytes:,} bytes), {drive}.")
    return {"status": "success", "data": _backup_dict(entry)}


@router.get("/backups/{backup_id}/download")
def download_backup(backup_id: int, db: Session = Depends(get_db), _admin: SystemUser = Depends(require_admin)):
    entry = db.query(BackupLog).filter(BackupLog.backup_id == backup_id).first()
    path = backup_file_path(entry) if entry else None
    if path is None:
        raise HTTPException(status_code=404, detail="That backup file is no longer on the server.")
    note_activity(f"Downloaded database backup {entry.file_name}.")
    return FileResponse(path, media_type="application/octet-stream", filename=entry.file_name)
