"""
Database backups (2026-10-22) -- replaces the Database Backup tab's old
UI-only mock.

run_backup() runs `pg_dump -Fc` on the live database into BACKUP_DIR, uploads
the file to Google Drive when configured, and records a tbl_backup_log row.
Called by the "Run Backup Now" button, the nightly 23:00 PHT scheduler job,
and archive_service.archive_and_clear (a safety dump before anything is
deleted).

Google Drive uses a personal Gmail account over OAuth (a refresh token minted
once by scripts/gdrive_authorize.py), not a service account: service
accounts have no Drive storage of their own, so they can't upload into a
normal "My Drive" folder. Same "no-op unless configured" philosophy as
gee_sar_service / email_alert_service -- without the GDRIVE_* keys the dump
still lands in BACKUP_DIR and the Drive step is just skipped. A failed upload
never fails the backup: the local dump already exists.

pg_dump must be installed on the backend host and its major version must
match the server's (PG_DUMP_PATH overrides the binary; default "pg_dump"
on PATH). Restore is deliberately NOT offered in-app -- it is Fabio's
pg_restore, run by hand.
"""
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.database import SQLALCHEMY_DATABASE_URL
from app.models.models import BackupLog

logger = logging.getLogger("agrisuregis.backup")

PHT = ZoneInfo("Asia/Manila")

BACKUP_DIR = Path(os.getenv("BACKUP_DIR") or Path(__file__).resolve().parents[2] / "backups")
PG_DUMP_PATH = os.getenv("PG_DUMP_PATH") or "pg_dump"

GDRIVE_CLIENT_ID = os.getenv("GDRIVE_CLIENT_ID")
GDRIVE_CLIENT_SECRET = os.getenv("GDRIVE_CLIENT_SECRET")
GDRIVE_REFRESH_TOKEN = os.getenv("GDRIVE_REFRESH_TOKEN")
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID")

GDRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# A full dump of the ~48k-farm DB takes well under a minute locally; this only
# stops a hung pg_dump (e.g. waiting on a lock) from blocking forever.
PG_DUMP_TIMEOUT_SECONDS = 1800


class BackupError(RuntimeError):
    pass


def gdrive_configured() -> bool:
    return all((GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET, GDRIVE_REFRESH_TOKEN, GDRIVE_FOLDER_ID))


def _backup_path(kind: str) -> Path:
    stamp = datetime.now(PHT).strftime("%Y-%m-%d_%H%M%S")
    return BACKUP_DIR / f"agrisure_{kind}_{stamp}.dump"


def _run_pg_dump(path: Path) -> None:
    """Connection details go in as arguments and PGPASSWORD, never as a URL
    with the password embedded on the command line (visible in the process
    list)."""
    url = make_url(SQLALCHEMY_DATABASE_URL)
    args = [PG_DUMP_PATH, "-Fc", "--no-owner", "-f", str(path), "-d", url.database or ""]
    if url.host:
        args += ["-h", url.host]
    if url.port:
        args += ["-p", str(url.port)]
    if url.username:
        args += ["-U", url.username]
    env = {**os.environ}
    if url.password:
        env["PGPASSWORD"] = url.password

    try:
        result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=PG_DUMP_TIMEOUT_SECONDS)
    except FileNotFoundError:
        raise BackupError(
            f"pg_dump was not found ({PG_DUMP_PATH}). Install the PostgreSQL client tools on the "
            "backend host or set PG_DUMP_PATH in backend/.env."
        )
    except subprocess.TimeoutExpired:
        raise BackupError(f"pg_dump did not finish within {PG_DUMP_TIMEOUT_SECONDS // 60} minutes.")
    if result.returncode != 0:
        path.unlink(missing_ok=True)
        raise BackupError(f"pg_dump failed: {(result.stderr or '').strip()[:500]}")


def upload_to_gdrive(path: Path) -> str:
    """Uploads one file into GDRIVE_FOLDER_ID and returns its Drive file id.
    googleapiclient/google-auth ship with earthengine-api, already in
    requirements.txt -- imported lazily like gee_sar_service's `ee`."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = Credentials(
        token=None,
        refresh_token=GDRIVE_REFRESH_TOKEN,
        client_id=GDRIVE_CLIENT_ID,
        client_secret=GDRIVE_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=GDRIVE_SCOPES,
    )
    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    media = MediaFileUpload(str(path), mimetype="application/octet-stream", resumable=True)
    created = (
        service.files()
        .create(body={"name": path.name, "parents": [GDRIVE_FOLDER_ID]}, media_body=media, fields="id")
        .execute()
    )
    return created["id"]


def run_backup(db: Session, kind: str, user_id: int | None) -> BackupLog:
    """Dump -> Drive -> log. Raises BackupError if the dump itself failed
    (after logging the failure); a Drive failure is recorded on the row and
    does not raise. Commits the log row."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = _backup_path(kind)
    entry = BackupLog(kind=kind, file_name=path.name, created_by=user_id)

    try:
        _run_pg_dump(path)
    except BackupError as exc:
        entry.status = "failed"
        entry.error = str(exc)
        db.add(entry)
        db.commit()
        logger.error("%s backup failed: %s", kind, exc)
        raise

    entry.status = "success"
    entry.size_bytes = path.stat().st_size
    if gdrive_configured():
        try:
            entry.gdrive_file_id = upload_to_gdrive(path)
        except Exception as exc:
            entry.gdrive_error = f"Google Drive upload failed: {exc}"[:1000]
            logger.exception("Google Drive upload of %s failed.", path.name)
    else:
        entry.gdrive_error = "Google Drive is not configured (GDRIVE_* keys in backend/.env)."

    db.add(entry)
    db.commit()
    db.refresh(entry)
    logger.info("%s backup written: %s (%d bytes).", kind, path.name, entry.size_bytes)
    return entry


def backup_file_path(entry: BackupLog) -> Path | None:
    """The dump on disk for a log row, or None if it is gone. Never trusts the
    stored name to stay inside BACKUP_DIR."""
    if not entry.file_name:
        return None
    path = (BACKUP_DIR / entry.file_name).resolve()
    if path.parent != BACKUP_DIR.resolve() or not path.is_file():
        return None
    return path
