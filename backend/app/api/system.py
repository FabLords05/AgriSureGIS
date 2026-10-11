from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core import scheduler as scheduler_module
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import TropicalCycloneBulletin, Typhoon
from app.services.email_alert_service import smtp_configured

router = APIRouter(prefix="/system", tags=["system"], dependencies=[Depends(get_current_user)])


@router.get("/status")
def get_system_status(request: Request, db: Session = Depends(get_db)):
    """
    Backs the Monitoring dashboard's System Status panel (2026-10-11):
    the PAGASA polling job's last/next run, the newest bulletin in the
    database, and whether SMTP email alerts are configured.

    last_run comes from scheduler.py's in-memory `last_run`, so it is null
    until the first scheduled run after a backend restart. next_run_at is read
    straight from the running APScheduler job.
    """
    job = request.app.state.scheduler.get_job(scheduler_module.BULLETIN_JOB_ID)
    last_run = scheduler_module.last_run

    latest = (
        db.query(TropicalCycloneBulletin, Typhoon.name)
        .outerjoin(Typhoon, Typhoon.typhoon_id == TropicalCycloneBulletin.typhoon_id)
        .order_by(TropicalCycloneBulletin.issued_at.desc())
        .first()
    )

    return {
        "status": "success",
        "parser": {
            "interval_minutes": scheduler_module.FIXED_POLL_INTERVAL_MINUTES,
            "last_run_at": last_run["finished_at"],
            "scrape_ok": last_run["scrape_ok"],
            "status_sync_ok": last_run["status_sync_ok"],
            "next_run_at": job.next_run_time if job else None,
        },
        "last_bulletin": (
            {
                "tcb_id": latest[0].tcb_id,
                "bulletin_count": latest[0].bulletin_count,
                "is_final": latest[0].is_final,
                "typhoon_name": latest[1],
                "issued_at": latest[0].issued_at,
            }
            if latest
            else None
        ),
        "email_alerts": {"configured": smtp_configured()},
    }
