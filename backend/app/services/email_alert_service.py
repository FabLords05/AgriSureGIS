"""
Sends a real email alert to every active system user when a newly-parsed TCB
belongs to a typhoon PAGASA's status page currently lists as active. Replaces
the old Calibration screen mockup (a hardcoded "Alert Email Recipients" text
field + a decorative on/off toggle, neither wired to anything) with actual
backend automation -- no admin UI involved at all now; see FUNCTION_CHANGES.md
for the 2026-08-16 entry. Also sends the account activated/deactivated email
(send_account_status_email, added 2026-10-22) over the same SMTP settings.

Same "no-op unless configured" philosophy as farms_cache.py's optional Redis
cache: without SMTP_HOST set in backend/.env, send_new_bulletin_alerts() does
nothing (and logs that it's skipping) rather than erroring, so a backend
without mail configured keeps working exactly as before. Uses smtplib from
the standard library -- no new pip dependency, unlike Redis.

Deliberately gated on Typhoon.is_active, not "was a bulletin just parsed" --
per Fabio's explicit instruction, a bulletin that parses successfully for a
typhoon PAGASA no longer lists as active (e.g. a late/backfilled bulletin, or
one that arrives in the same poll tick right as the storm is downgraded) must
NOT trigger an alert. Callers should call this AFTER
PagasaStatusService.sync_active_typhoons() has run for the same poll/parse
cycle, so Typhoon.is_active reflects the freshest status, not the previous
cycle's.
"""
import logging
import os
import smtplib
from email.mime.text import MIMEText

from sqlalchemy.orm import Session

from app.models.models import SystemUser, TropicalCycloneBulletin

logger = logging.getLogger("agrisuregis.email_alerts")


def _smtp_config() -> dict | None:
    host = os.getenv("SMTP_HOST")
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    if not host or not user or not password:
        return None
    return {
        "host": host,
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": user,
        "password": password,
        # Brevo (and most relay providers) log in with a generated SMTP ID
        # that isn't a real mailbox, so the From address has to be a
        # separately verified sender. Gmail logs in with the address itself,
        # so leaving SMTP_FROM unset keeps the old SMTP_USER behavior.
        "sender": os.getenv("SMTP_FROM") or user,
    }


def smtp_configured() -> bool:
    """Whether SMTP settings are present in backend/.env -- for the Monitoring
    dashboard's System Status panel. Does not test the mail server."""
    return _smtp_config() is not None


def _active_typhoon_bulletins(created: list[dict], db: Session) -> list[TropicalCycloneBulletin]:
    """Re-fetches each just-created bulletin by tcb_id (the `created` dicts from
    BulletinParserService.scrape_and_save_all only carry tcb_id/title/
    bulletin_count/is_final, not typhoon_id) and keeps only the ones whose
    typhoon is currently active.
    """
    alertable = []
    for item in created:
        bulletin = db.query(TropicalCycloneBulletin).filter(
            TropicalCycloneBulletin.tcb_id == item["tcb_id"]
        ).first()
        if bulletin and bulletin.typhoon and bulletin.typhoon.is_active:
            alertable.append(bulletin)
    return alertable


def send_new_bulletin_alerts(created: list[dict], db: Session) -> None:
    """
    Emails every active tbl_system_users row, one email per bulletin, about
    whichever of the just-created bulletins (see scrape_and_save_all's return
    shape) belong to a currently-active typhoon. A bulletin whose typhoon is
    not active when it arrives is skipped for good, not retried on a later
    poll (Fabio's decision, 2026-10-22). Silently does nothing if SMTP isn't
    configured, there's nothing alert-worthy, or there are no active user
    accounts to notify -- never raises, so a failure here can't take down the
    scrape/parse request or the scheduler thread that called it.
    """
    if not created:
        return

    config = _smtp_config()
    if not config:
        logger.info("SMTP not configured (SMTP_HOST/SMTP_USER/SMTP_PASSWORD) -- skipping bulletin email alerts.")
        return

    bulletins = _active_typhoon_bulletins(created, db)
    if not bulletins:
        logger.info("No newly-parsed bulletins belong to a currently-active typhoon -- no alert sent.")
        return

    recipients = [
        u.email for u in db.query(SystemUser).filter(SystemUser.is_active.is_(True)).all()
    ]
    if not recipients:
        logger.info("No active user accounts to alert.")
        return

    # One email per new TCB (Fabio's decision, 2026-10-22), not one digest
    # per poll -- each bulletin arriving is its own notification.
    messages = []
    for b in bulletins:
        body = "\n".join([
            "A new Tropical Cyclone Bulletin has been parsed for an active typhoon.",
            "",
            f"- {b.typhoon.name}: {b.title} (Bulletin #{b.bulletin_count}, {b.category})",
            "",
            "Log in to AgriSureGIS to review the full bulletin and exposure impact.",
        ])
        subject = f"AgriSureGIS: New PAGASA Tropical Cyclone Bulletin #{b.bulletin_count} for {b.typhoon.name}"
        # Sent BCC-style -- every active user is in the sendmail() envelope
        # recipient list, not in a visible header, so recipients can't see
        # each other's addresses. The To: header is set to the sender itself
        # (a common convention for broadcast mail with no single "primary"
        # recipient) rather than left blank.
        messages.append(_compose(config, config["sender"], subject, body))

    try:
        _send(config, recipients, messages)
        logger.info("Sent %d bulletin alert email(s) to %d active user(s).", len(messages), len(recipients))
    except Exception:
        logger.exception("Failed to send bulletin alert email.")


def send_account_status_email(email: str, name: str, activated: bool) -> None:
    """
    Tells a user their account was activated or deactivated by an
    administrator (PATCH /api/users/{user_id}). Sent to that user only, any
    role. Same no-op/never-raises rules as send_new_bulletin_alerts, since
    it runs as a background task after the admin's save has already
    committed. Takes plain values, not the SystemUser row, because the
    request's DB session is closed by the time the task runs.
    """
    config = _smtp_config()
    if not config:
        logger.info("SMTP not configured (SMTP_HOST/SMTP_USER/SMTP_PASSWORD) -- skipping account status email.")
        return

    if activated:
        subject = "AgriSureGIS: Your account has been activated"
        status_line = "Your AgriSureGIS account has been activated by an administrator. You can now log in."
    else:
        subject = "AgriSureGIS: Your account has been deactivated"
        status_line = ("Your AgriSureGIS account has been deactivated by an administrator. "
                       "You can no longer log in or receive bulletin alerts.")
    body = "\n".join([
        f"Hello {name},",
        "",
        status_line,
        "",
        "If you think this is a mistake, please contact your system administrator.",
    ])

    try:
        _send(config, [email], [_compose(config, email, subject, body)])
        logger.info("Sent account %s email to %s.", "activation" if activated else "deactivation", email)
    except Exception:
        logger.exception("Failed to send account status email.")


def _compose(config: dict, to_header: str, subject: str, body: str) -> MIMEText:
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = config["sender"]
    msg["To"] = to_header
    return msg


def _send(config: dict, recipients: list[str], messages: list[MIMEText]) -> None:
    """One SMTP login for every message in the batch. Raises on failure --
    callers log it, so a mail problem never escapes to their own caller."""
    with smtplib.SMTP(config["host"], config["port"], timeout=10) as server:
        server.starttls()
        server.login(config["user"], config["password"])
        for msg in messages:
            server.sendmail(config["sender"], recipients, msg.as_string())
