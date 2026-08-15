import asyncio
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.database import SessionLocal
from app.services.bulletin_parser import BulletinParserService
from app.services.email_alert_service import send_new_bulletin_alerts
from app.services.pagasa_status_scraper import PagasaStatusService

logger = logging.getLogger("agrisuregis.scheduler")

BULLETIN_JOB_ID = "pagasa_bulletin_poll"

# Fixed at PAGASA's fastest meaningful cadence -- no longer admin-configurable
# via the Calibration screen (tbl_parser_settings/api/bulletins/settings still
# exist and still work if called directly, but nothing in the UI calls the PUT
# route anymore as of 2026-08-16; the GET route lives on purely as a backend
# connectivity ping for CalibrationModule's System Status section).
FIXED_POLL_INTERVAL_MINUTES = 15


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
    try:
        created = asyncio.run(BulletinParserService.scrape_and_save_all(db))
        if created:
            logger.info("Scheduled PAGASA scrape saved %d new bulletin(s).", len(created))
        else:
            logger.info("Scheduled PAGASA scrape found no new bulletins.")
    except Exception:
        logger.exception("Scheduled PAGASA scrape failed.")

    try:
        active_names = asyncio.run(PagasaStatusService.fetch_active_storm_names())
        PagasaStatusService.sync_active_typhoons(active_names, db)
        logger.info("Synced active-typhoon status: %s", ", ".join(active_names) or "none active")
    except Exception:
        logger.exception("PAGASA active-typhoon status sync failed.")

    # Runs after the active-typhoon sync above (not inside the same try) so
    # Typhoon.is_active reflects this cycle's freshest status, not the
    # previous poll's -- see email_alert_service's module docstring.
    try:
        send_new_bulletin_alerts(created, db)
    except Exception:
        logger.exception("Bulletin alert email step failed.")
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
    return scheduler


def reschedule_bulletin_job(scheduler: BackgroundScheduler, new_interval_minutes: int) -> None:
    scheduler.reschedule_job(BULLETIN_JOB_ID, trigger="interval", minutes=new_interval_minutes)
    logger.info("Rescheduled PAGASA poll job to every %dmin.", new_interval_minutes)
