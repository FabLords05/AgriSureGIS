import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.activity_log import describe_new_bulletins, plural, record_activity
from app.core.database import SessionLocal
from app.core.system_settings import AUTO_BACKUP_KEY, get_setting
from app.services.backup_service import BackupError, run_backup
from app.services.bulletin_parser import BulletinParserService
from app.services.email_alert_service import send_new_bulletin_alerts
from app.services.pagasa_status_scraper import PagasaStatusService

logger = logging.getLogger("agrisuregis.scheduler")

BULLETIN_JOB_ID = "pagasa_bulletin_poll"
BACKUP_JOB_ID = "nightly_db_backup"

# Fixed at PAGASA's fastest meaningful cadence -- no longer admin-configurable
# via the Calibration screen (tbl_parser_settings/api/bulletins/settings still
# exist and still work if called directly, but nothing in the UI calls the PUT
# route anymore as of 2026-08-16; the GET route lives on purely as a backend
# connectivity ping for CalibrationModule's System Status section).
FIXED_POLL_INTERVAL_MINUTES = 15

# Outcome of the most recent run_scheduled_scrape(), read by GET
# /api/system/status for the Monitoring dashboard's System Status panel.
# In memory only -- resets on backend restart, so until the first scheduled
# run (up to FIXED_POLL_INTERVAL_MINUTES later) finished_at stays None.
last_run: dict = {"finished_at": None, "scrape_ok": None, "status_sync_ok": None}


def run_scheduled_scrape() -> None:
    """
    APScheduler job target for automated PAGASA TCB ingestion, plus the
    separate active-typhoon status sync (PagasaStatusService). Opens and
    closes its own DB session — there is no FastAPI request context in a
    background job, so `Depends(get_db)` can't be used here. Each step has its
    own try/except so a failure in one doesn't skip or hide the other; neither
    ever lets an exception escape this function, so one bad poll doesn't kill
    the scheduler thread.
    """
    db = SessionLocal()
    created: list[dict] = []
    scrape_ok = False
    status_sync_ok = False
    try:
        created = asyncio.run(BulletinParserService.scrape_and_save_all(db))
        scrape_ok = True
        if created:
            logger.info("Scheduled PAGASA scrape saved %d new bulletin(s).", len(created))
        else:
            logger.info("Scheduled PAGASA scrape found no new bulletins.")
    except Exception:
        logger.exception("Scheduled PAGASA scrape failed.")

    try:
        active_names = asyncio.run(PagasaStatusService.fetch_active_storm_names())
        PagasaStatusService.sync_active_typhoons(active_names, db)
        status_sync_ok = True
        logger.info("Synced active-typhoon status: %s", ", ".join(active_names) or "none active")
    except Exception:
        logger.exception("PAGASA active-typhoon status sync failed.")

    try:
        _log_scheduled_run(db, created, scrape_ok, status_sync_ok)
    except Exception:
        db.rollback()
        logger.exception("Failed to record the scheduled poll in the activity log.")

    last_run.update(
        finished_at=datetime.now(timezone.utc),
        scrape_ok=scrape_ok,
        status_sync_ok=status_sync_ok,
    )

    # Runs after the active-typhoon sync above (not inside the same try) so
    # Typhoon.is_active reflects this cycle's freshest status, not the
    # previous poll's -- see email_alert_service's module docstring.
    try:
        send_new_bulletin_alerts(created, db)
    except Exception:
        logger.exception("Bulletin alert email step failed.")
    finally:
        db.close()


def _log_scheduled_run(db, created: list[dict], scrape_ok: bool, status_sync_ok: bool) -> None:
    """
    SYSTEM Activity Log entry for the automatic TCB ingestion (2026-10-22).
    Only written when something actually happened -- new bulletins saved, or
    a step newly started failing -- not for every quiet poll: at one run per
    15 minutes that would be ~96 "nothing new" rows a day burying the real
    actions. A failure is logged once when it starts (last_run still holds the
    previous run's outcome here), not again on every poll while PAGASA stays
    unreachable.
    """
    parts = []
    if created:
        parts.append(
            f"Automatic PAGASA poll ingested {plural(len(created), 'new TCB')}: "
            f"{describe_new_bulletins(created, db)}."
        )
    if not scrape_ok and last_run["scrape_ok"] is not False:
        parts.append("Automatic PAGASA TCB scrape failed (portal unreachable or returned an error); will retry next poll.")
    if not status_sync_ok and last_run["status_sync_ok"] is not False:
        parts.append("PAGASA active-typhoon status sync failed; typhoon active/inactive flags were not updated.")
    if not parts:
        return
    status_code = 200 if scrape_ok and status_sync_ok else 500
    record_activity(db, None, "SYSTEM", "scheduler/pagasa-poll", status_code, " ".join(parts))


def run_scheduled_backup() -> None:
    """
    Nightly 23:00 PHT pg_dump (2026-10-22), the Database Backup tab's
    "Automatic daily backup" checkbox. The job is always scheduled; the
    checkbox (tbl_system_settings.auto_backup_enabled) is read each night, so
    toggling it needs no reschedule. Logged to the Activity Log either way.
    """
    db = SessionLocal()
    try:
        if not get_setting(db, AUTO_BACKUP_KEY):
            logger.info("Automatic daily backup is disabled; skipping.")
            return
        try:
            entry = run_backup(db, "scheduled", None)
        except BackupError as exc:
            record_activity(db, None, "SYSTEM", "scheduler/nightly-backup", 500,
                            f"Automatic daily backup failed: {exc}")
            return
        drive = "uploaded to Google Drive" if entry.gdrive_file_id else f"not uploaded ({entry.gdrive_error})"
        record_activity(db, None, "SYSTEM", "scheduler/nightly-backup", 200,
                        f"Automatic daily backup {entry.file_name} ({entry.size_bytes:,} bytes), {drive}.")
    except Exception:
        logger.exception("Nightly backup job crashed.")
    finally:
        db.close()


def build_scheduler(initial_interval_minutes: int) -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_scheduled_scrape,
        "interval",
        minutes=initial_interval_minutes,
        id=BULLETIN_JOB_ID,
        replace_existing=True,
        max_instances=1,  # guard against overlapping runs if a scrape outlasts the interval
    )
    scheduler.add_job(
        run_scheduled_backup,
        "cron",
        hour=23,
        minute=0,
        timezone="Asia/Manila",
        id=BACKUP_JOB_ID,
        replace_existing=True,
        max_instances=1,
    )
    return scheduler


def reschedule_bulletin_job(scheduler: BackgroundScheduler, new_interval_minutes: int) -> None:
    scheduler.reschedule_job(BULLETIN_JOB_ID, trigger="interval", minutes=new_interval_minutes)
    logger.info("Rescheduled PAGASA poll job to every %dmin.", new_interval_minutes)
