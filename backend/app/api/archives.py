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
from types import SimpleNamespace
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.assessments import PABS_PREVALENCE, _pabs_remarks, _yield_loss_fraction
from app.api.users import _verify_password
from app.core.activity_log import note_activity, plural
from app.core.database import ArchiveNotConfiguredError, archive_configured, get_db
from app.core.farmer_name import format_surname_first
from app.core.security import get_current_user, require_admin
from app.models.models import BackupLog, RecsapMatrix, SystemUser
from app.services import archive_service
from app.services.archive_service import ArchiveBusyError, ArchiveError
from app.services.backup_service import (
    BackupError,
    backup_file_path,
    encryption_configured,
    gdrive_configured,
    run_backup,
    verify_backup,
    verify_db_configured,
)

router = APIRouter(tags=["archives"], dependencies=[Depends(get_current_user)])


class ArchiveRequest(BaseModel):
    # The signed-in user's own password -- re-checked here so an unattended
    # signed-in session can't clear the live records.
    password: str


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
    return {"status": "success", "data": data}


@router.post("/archives")
def archive_and_clear(
    payload: ArchiveRequest,
    db: Session = Depends(get_db),
    user: SystemUser = Depends(get_current_user),
):
    note_activity("Attempted Archive & Clear of the live PABS records.")
    if not payload.password or not _verify_password(payload.password, user.password_hash):
        note_activity("Archive & Clear rejected: incorrect password.")
        raise HTTPException(status_code=400, detail="Incorrect password.")
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


# ─── Archived typhoons in Assessment & Reporting (Admin + GIS Specialist) ────
# Clicking an archived typhoon in Assessment & Reporting shows its rows from
# the archive, read-only. Same row shape as GET /api/assessments/pabs-summary
# so the screen renders them with the same table.

@router.get("/archives/typhoons")
def list_archived_typhoons():
    """Which typhoons are archived (and in which archive). Empty, not 503,
    when the archive isn't configured -- the Assessment screen just shows no
    Archived tags then."""
    if not archive_configured():
        return {"status": "success", "data": []}
    try:
        data = archive_service.archived_typhoons()
    except ArchiveNotConfiguredError:
        data = []
    return {"status": "success", "data": data}


@router.get("/archives/typhoon/{typhoon_id}/pabs-rows")
def get_archived_typhoon_rows(typhoon_id: int, db: Session = Depends(get_db)):
    try:
        archived = archive_service.archived_typhoon_assessments(typhoon_id)
    except ArchiveNotConfiguredError as exc:
        raise _not_configured(exc)
    if archived is None:
        raise HTTPException(status_code=404, detail="This typhoon has not been archived.")

    # The PCIC matrices are never cleared, so S and REMARKS are looked up live
    # by matrix_id exactly as the live table does.
    matrix_ids = {r["matrix_id"] for r in archived["rows"] if r["matrix_id"] is not None}
    matrices = (
        {m.matrix_id: m for m in db.query(RecsapMatrix).filter(RecsapMatrix.matrix_id.in_(matrix_ids)).all()}
        if matrix_ids else {}
    )

    rows = []
    for r in archived["rows"]:
        stand_in = SimpleNamespace(matrix=matrices.get(r["matrix_id"]))
        rows.append({
            "assessment_id": r["assessment_id"],
            "FARMER_NAME": format_surname_first(SimpleNamespace(**r), with_middle_initial=True),
            "FARMERID": r["farmers_id"],
            "FARMID": r["csv_farm_reference"],
            "IRID": None,
            "CIC_NO": r["policy_no"],
            "AREA": float(r["area_size"]) if r["area_size"] is not None else None,
            "TYPHOON_NAME": r["typhoon_name"],
            "PERIOD_OF_EXPOSURE": r["period_of_exposure"],
            "WIND_VELOCITY": archived["max_winds"],
            "AC": float(r["amount_cover"]) if r["amount_cover"] is not None else None,
            "FINAL_INDEMNITY_PAYMENT": float(r["final_indemnity_payment"]) if r["final_indemnity_payment"] is not None else None,
            "P": PABS_PREVALENCE,
            "S": _yield_loss_fraction(stand_in),
            "REMARKS": _pabs_remarks(stand_in),
            "municipality": r["municipality"],
            "province": r["province"],
            "barangay": r["barangay"],
            "wind_signal": r["wind_velocity"],
            "crop_stage": r["crop_stage"],
            "insurance_records_id": r["insurance_records_id"],
            "typhoon_id": r["typhoon_id"],
            "final_indemnity_payment": float(r["final_indemnity_payment"]) if r["final_indemnity_payment"] is not None else None,
        })

    return {
        "status": "success",
        "data": {
            "archive_id": archived["archive_id"],
            "label": archived["label"],
            "archived_at": archived["archived_at"],
            "rows": rows,
        },
    }


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
        "sha256": entry.sha256,
        "encrypted": bool(entry.encrypted),
        "tables_counted": len(entry.row_counts) if entry.row_counts else 0,
        "verify_status": entry.verify_status,
        "verify_detail": entry.verify_detail,
        "verified_at": entry.verified_at,
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
            "verify_db_configured": verify_db_configured(),
            "encryption_configured": encryption_configured(),
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


class VerifyBackupRequest(BaseModel):
    source: Literal["local", "gdrive"] = "local"
    # The verification database's current contents are replaced -- the UI
    # asks first, and the request must say so explicitly.
    confirm: bool = False


@router.post("/backups/{backup_id}/verify")
def verify_backup_endpoint(
    backup_id: int,
    payload: VerifyBackupRequest,
    db: Session = Depends(get_db),
    _admin: SystemUser = Depends(require_admin),
):
    """
    Test-restores one backup (from the server, or downloaded from Google
    Drive) into the separate verification database and compares every
    table's row count with the counts recorded when it was taken. The live
    database is never touched.
    """
    entry = db.query(BackupLog).filter(BackupLog.backup_id == backup_id).first()
    if entry is None:
        raise HTTPException(status_code=404, detail="Backup not found.")
    where = "Google Drive" if payload.source == "gdrive" else "the server"
    note_activity(f"Attempted to verify database backup {entry.file_name} from {where}.")
    if not payload.confirm:
        raise HTTPException(
            status_code=400,
            detail="Verifying replaces the verification database's contents; confirm to continue.",
        )
    try:
        entry = verify_backup(db, entry, payload.source)
    except BackupError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    mismatches = len((entry.verify_detail or {}).get("mismatches", []))
    note_activity(
        f"Verified database backup {entry.file_name} from {where}: {entry.verify_status}"
        + (f" ({plural(mismatches, 'mismatch', 'mismatches')})." if mismatches else
           f" -- {(entry.verify_detail or {}).get('rows_checked', 0):,} rows across "
           f"{(entry.verify_detail or {}).get('tables_checked', 0)} tables match.")
    )
    return {"status": "success", "data": _backup_dict(entry)}


@router.get("/backups/{backup_id}/download")
def download_backup(backup_id: int, db: Session = Depends(get_db), _admin: SystemUser = Depends(require_admin)):
    entry = db.query(BackupLog).filter(BackupLog.backup_id == backup_id).first()
    path = backup_file_path(entry) if entry else None
    if path is None:
        raise HTTPException(status_code=404, detail="That backup file is no longer on the server.")
    note_activity(f"Downloaded database backup {entry.file_name}.")
    return FileResponse(path, media_type="application/octet-stream", filename=entry.file_name)
