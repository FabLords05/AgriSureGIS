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
on PATH).

Verification and test restore (2026-10-22):
- Every dump is taken inside one exported REPEATABLE READ snapshot, and the
  row count of every table is read from that same snapshot, so the counts
  describe exactly what the dump holds (tbl_backup_log.row_counts).
- The dump's sha256 is recorded and `pg_restore --list` must read it.
- The Drive copy is encrypted when BACKUP_ENCRYPTION_KEY is set
  (app/core/backup_crypto.py) and checked against Drive's own md5.
- verify_backup() restores a dump -- from BACKUP_DIR or from Google Drive --
  into BACKUP_VERIFY_DATABASE_URL, a separate database (the "secondary
  backup database"), and compares every table's row count with the counts
  recorded at dump time. The live database is never the target: that is
  refused outright. Replacing live data stays a deliberate, manual
  pg_restore by the DB admin (runbook in .claude/ENV_GUIDE.md).
"""
import hashlib
import logging
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.backup_crypto import BackupCryptoError, decrypt_file, encrypt_file, load_key
from app.core.database import (
    ARCHIVE_DATABASE_URL,
    ARCHIVE_WRITER_DATABASE_URL,
    SQLALCHEMY_DATABASE_URL,
    engine,
)
from app.models.models import BackupLog

logger = logging.getLogger("agrisuregis.backup")

PHT = ZoneInfo("Asia/Manila")

BACKUP_DIR = Path(os.getenv("BACKUP_DIR") or Path(__file__).resolve().parents[2] / "backups")
PG_DUMP_PATH = os.getenv("PG_DUMP_PATH") or "pg_dump"
PG_RESTORE_PATH = os.getenv("PG_RESTORE_PATH") or "pg_restore"
BACKUP_VERIFY_DATABASE_URL = os.getenv("BACKUP_VERIFY_DATABASE_URL")
BACKUP_ENCRYPTION_KEY = os.getenv("BACKUP_ENCRYPTION_KEY")
# Local manual/scheduled dump files kept in BACKUP_DIR (newest first); older
# files are deleted, their log rows kept. Archive dumps are never pruned.
BACKUP_RETENTION_COUNT = int(os.getenv("BACKUP_RETENTION_COUNT") or 30)

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


def verify_db_configured() -> bool:
    return bool(BACKUP_VERIFY_DATABASE_URL)


def encryption_configured() -> bool:
    return bool(BACKUP_ENCRYPTION_KEY)


def _file_digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# User tables in public, minus extension-owned ones (PostGIS's
# spatial_ref_sys): their data isn't a plain table dump.
_TABLES_SQL = """
    SELECT c.relname
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
      AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype = 'e')
    ORDER BY c.relname
"""


def _row_counts(conn) -> dict[str, int]:
    return {
        name: conn.execute(text(f'SELECT count(*) FROM public."{name}"')).scalar_one()
        for (name,) in conn.execute(text(_TABLES_SQL)).all()
    }


def _backup_path(kind: str) -> Path:
    stamp = datetime.now(PHT).strftime("%Y-%m-%d_%H%M%S")
    return BACKUP_DIR / f"agrisure_{kind}_{stamp}.dump"


def _pg_connection_args(database_url: str) -> tuple[list[str], dict[str, str]]:
    """Connection details go in as arguments and PGPASSWORD, never as a URL
    with the password embedded on the command line (visible in the process
    list)."""
    url = make_url(database_url)
    args = ["-d", url.database or ""]
    if url.host:
        args += ["-h", url.host]
    if url.port:
        args += ["-p", str(url.port)]
    if url.username:
        args += ["-U", url.username]
    env = {**os.environ}
    if url.password:
        env["PGPASSWORD"] = url.password
    return args, env


def _run_pg_dump(path: Path, snapshot: str | None = None) -> None:
    """`snapshot`: an exported snapshot id, so the dump sees exactly the same
    data the row counts were read from (see run_backup)."""
    conn_args, env = _pg_connection_args(SQLALCHEMY_DATABASE_URL)
    args = [PG_DUMP_PATH, "-Fc", "--no-owner", "-f", str(path), *conn_args]
    if snapshot:
        args += [f"--snapshot={snapshot}"]

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


def _check_dump_readable(path: Path) -> None:
    """`pg_restore --list` reads the archive's table of contents end to end;
    a truncated or corrupt custom-format dump fails here."""
    try:
        result = subprocess.run(
            [PG_RESTORE_PATH, "--list", str(path)], capture_output=True, text=True, timeout=PG_DUMP_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        raise BackupError(
            f"pg_restore was not found ({PG_RESTORE_PATH}). Install the PostgreSQL client tools on the "
            "backend host or set PG_RESTORE_PATH in backend/.env."
        )
    if result.returncode != 0:
        raise BackupError(f"The dump could not be read back by pg_restore: {(result.stderr or '').strip()[:500]}")


def _drive_service():
    """googleapiclient/google-auth ship with earthengine-api, already in
    requirements.txt -- imported lazily like gee_sar_service's `ee`."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=GDRIVE_REFRESH_TOKEN,
        client_id=GDRIVE_CLIENT_ID,
        client_secret=GDRIVE_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=GDRIVE_SCOPES,
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def upload_to_gdrive(path: Path) -> tuple[str, str | None]:
    """Uploads one file into GDRIVE_FOLDER_ID; returns (Drive file id, the md5
    Drive computed of what it stored)."""
    from googleapiclient.http import MediaFileUpload

    media = MediaFileUpload(str(path), mimetype="application/octet-stream", resumable=True)
    created = (
        _drive_service().files()
        .create(body={"name": path.name, "parents": [GDRIVE_FOLDER_ID]}, media_body=media, fields="id,md5Checksum")
        .execute()
    )
    return created["id"], created.get("md5Checksum")


def download_from_gdrive(file_id: str, target: Path) -> None:
    from googleapiclient.http import MediaIoBaseDownload

    request = _drive_service().files().get_media(fileId=file_id)
    with target.open("wb") as f:
        downloader = MediaIoBaseDownload(f, request, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk()


def _upload_offsite(path: Path, entry: BackupLog) -> None:
    """Encrypts (when a key is set) and uploads the dump, then checks Drive's
    md5 of the stored file against ours. Records the outcome on `entry`;
    never raises -- the local dump already exists."""
    if not gdrive_configured():
        entry.gdrive_error = "Google Drive is not configured (GDRIVE_* keys in backend/.env)."
        return
    encrypted_path = None
    try:
        key = load_key(BACKUP_ENCRYPTION_KEY)
        upload_path = path
        if key is not None:
            encrypted_path = path.with_name(path.name + ".enc")
            encrypt_file(path, encrypted_path, key)
            upload_path = encrypted_path
        local_md5 = _file_digest(upload_path, "md5")
        entry.gdrive_file_id, entry.gdrive_md5 = upload_to_gdrive(upload_path)
        entry.encrypted = key is not None
        if entry.gdrive_md5 != local_md5:
            entry.gdrive_error = (
                f"Google Drive's checksum ({entry.gdrive_md5}) does not match the uploaded file ({local_md5}); "
                "the Drive copy may be incomplete."
            )
    except Exception as exc:
        entry.gdrive_error = f"Google Drive upload failed: {exc}"[:1000]
        logger.exception("Google Drive upload of %s failed.", path.name)
    finally:
        if encrypted_path is not None:
            encrypted_path.unlink(missing_ok=True)


def run_backup(db: Session, kind: str, user_id: int | None) -> BackupLog:
    """Dump -> Drive -> log. Raises BackupError if the dump itself failed
    (after logging the failure); a Drive failure is recorded on the row and
    does not raise. Commits the log row."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = _backup_path(kind)
    entry = BackupLog(kind=kind, file_name=path.name, created_by=user_id, verify_status="pending")

    try:
        # Read-only on the live DB: pg_dump copies, nothing is moved or
        # deleted. One exported snapshot for the counts and the dump alike.
        with engine.connect() as conn:
            conn = conn.execution_options(isolation_level="REPEATABLE READ")
            with conn.begin():
                snapshot = conn.execute(text("SELECT pg_export_snapshot()")).scalar_one()
                entry.row_counts = _row_counts(conn)
                _run_pg_dump(path, snapshot=snapshot)
        _check_dump_readable(path)
    except Exception as exc:
        path.unlink(missing_ok=True)
        entry.status = "failed"
        entry.error = str(exc) if isinstance(exc, BackupError) else f"Backup failed: {exc}"
        entry.verify_status = None
        db.add(entry)
        db.commit()
        logger.error("%s backup failed: %s", kind, exc)
        if isinstance(exc, BackupError):
            raise
        raise BackupError(entry.error) from exc

    entry.status = "success"
    entry.size_bytes = path.stat().st_size
    entry.sha256 = _file_digest(path, "sha256")
    _upload_offsite(path, entry)

    db.add(entry)
    db.commit()
    db.refresh(entry)
    logger.info("%s backup written: %s (%d bytes).", kind, path.name, entry.size_bytes)
    _prune_local_dumps(db)
    return entry


def _prune_local_dumps(db: Session) -> None:
    """Keeps the newest BACKUP_RETENTION_COUNT manual/scheduled dump files on
    disk. Never touches archive dumps, Drive copies, or the log rows."""
    keep = max(BACKUP_RETENTION_COUNT, 1)
    old = (
        db.query(BackupLog)
        .filter(BackupLog.status == "success", BackupLog.kind.in_(("manual", "scheduled")))
        .order_by(BackupLog.created_at.desc())
        .offset(keep)
        .all()
    )
    for entry in old:
        path = backup_file_path(entry)
        if path is not None:
            path.unlink(missing_ok=True)
            logger.info("Retention: removed local dump %s (Drive copy and log row kept).", entry.file_name)


def _same_database(url_a: str, url_b: str) -> bool:
    a, b = make_url(url_a), make_url(url_b)
    return (a.host or "localhost", a.port or 5432, a.database) == (b.host or "localhost", b.port or 5432, b.database)


def verify_backup(db: Session, entry: BackupLog, source: str = "local") -> BackupLog:
    """
    Restores one backup into the separate verification database and checks
    it: sha256 against the value recorded at dump time, then every table's
    row count against the counts read from the dump's own snapshot.
    `source` is "local" (BACKUP_DIR) or "gdrive" (downloaded, then decrypted
    if it was encrypted). Never touches the live database.
    """
    if not verify_db_configured():
        raise BackupError("No verification database configured (BACKUP_VERIFY_DATABASE_URL in backend/.env).")
    if _same_database(BACKUP_VERIFY_DATABASE_URL, SQLALCHEMY_DATABASE_URL):
        raise BackupError("BACKUP_VERIFY_DATABASE_URL points at the live database; refusing to restore over it.")
    # pg_restore --clean drops every table in the target: on the archive DB
    # that would erase the archived typhoons. It must be its own database.
    for archive_url in (ARCHIVE_DATABASE_URL, ARCHIVE_WRITER_DATABASE_URL):
        if archive_url and _same_database(BACKUP_VERIFY_DATABASE_URL, archive_url):
            raise BackupError(
                "BACKUP_VERIFY_DATABASE_URL points at the archive database; refusing to restore over it. "
                "Use a separate, empty database (e.g. agrisure_verify)."
            )
    if entry.status != "success":
        raise BackupError("Only a successful backup can be verified.")

    detail: dict = {"source": source, "verify_database": make_url(BACKUP_VERIFY_DATABASE_URL).database}
    with tempfile.TemporaryDirectory(prefix="agrisure_verify_") as tmp:
        if source == "gdrive":
            if not entry.gdrive_file_id:
                raise BackupError("This backup has no Google Drive copy.")
            if not gdrive_configured():
                raise BackupError("Google Drive is not configured (GDRIVE_* keys in backend/.env).")
            downloaded = Path(tmp) / "download"
            download_from_gdrive(entry.gdrive_file_id, downloaded)
            if entry.gdrive_md5 and _file_digest(downloaded, "md5") != entry.gdrive_md5:
                raise BackupError("The file downloaded from Google Drive does not match its recorded checksum.")
            dump = Path(tmp) / "restore.dump"
            if entry.encrypted:
                key = load_key(BACKUP_ENCRYPTION_KEY)
                if key is None:
                    raise BackupError("This Drive copy is encrypted but BACKUP_ENCRYPTION_KEY is not set.")
                try:
                    decrypt_file(downloaded, dump, key)
                except BackupCryptoError as exc:
                    raise BackupError(str(exc)) from exc
            else:
                downloaded.rename(dump)
        else:
            dump = backup_file_path(entry)
            if dump is None:
                raise BackupError("That backup file is no longer on the server; verify it from Google Drive instead.")

        mismatches: list[dict] = []
        if entry.sha256 and _file_digest(dump, "sha256") != entry.sha256:
            mismatches.append({"check": "sha256", "error": "file checksum differs from the one recorded at backup time"})
        else:
            restore_errors = _restore_into_verify_db(dump)
            if restore_errors:
                detail["pg_restore_messages"] = restore_errors
            verify_engine = create_engine(BACKUP_VERIFY_DATABASE_URL, pool_pre_ping=True)
            try:
                with verify_engine.connect() as conn:
                    restored = _row_counts(conn)
            finally:
                verify_engine.dispose()
            expected = entry.row_counts or {}
            for table, count in expected.items():
                if restored.get(table) != count:
                    mismatches.append({"table": table, "expected": count, "restored": restored.get(table)})
            detail["tables_checked"] = len(expected)
            detail["rows_checked"] = sum(expected.values())
            if not expected:
                mismatches.append({"check": "row_counts", "error": "no row counts were recorded for this backup"})

    detail["mismatches"] = mismatches
    entry.verify_status = "failed" if mismatches else "verified"
    entry.verify_detail = detail
    entry.verified_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(entry)
    return entry


def _restore_into_verify_db(dump: Path) -> str | None:
    """pg_restore --clean into the verification DB. pg_restore exits non-zero
    for harmless per-object warnings too (e.g. it may not drop the PostGIS
    extension it didn't create), so success is judged by the row counts that
    follow; its messages are kept for the record."""
    conn_args, env = _pg_connection_args(BACKUP_VERIFY_DATABASE_URL)
    args = [PG_RESTORE_PATH, "--clean", "--if-exists", "--no-owner", "--no-privileges", *conn_args, str(dump)]
    try:
        result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=PG_DUMP_TIMEOUT_SECONDS)
    except FileNotFoundError:
        raise BackupError(f"pg_restore was not found ({PG_RESTORE_PATH}).")
    except subprocess.TimeoutExpired:
        raise BackupError(f"pg_restore did not finish within {PG_DUMP_TIMEOUT_SECONDS // 60} minutes.")
    if result.returncode != 0:
        return (result.stderr or "").strip()[-2000:] or f"pg_restore exited with {result.returncode}"
    return None


def backup_file_path(entry: BackupLog) -> Path | None:
    """The dump on disk for a log row, or None if it is gone. Never trusts the
    stored name to stay inside BACKUP_DIR."""
    if not entry.file_name:
        return None
    path = (BACKUP_DIR / entry.file_name).resolve()
    if path.parent != BACKUP_DIR.resolve() or not path.is_file():
        return None
    return path
