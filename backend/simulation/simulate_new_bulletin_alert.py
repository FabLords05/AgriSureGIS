"""
Single entry point for activating and exercising the TCB email-alert path
(`backend/app/services/email_alert_service.py`), which has never actually run:
it is a deliberate no-op until SMTP_HOST/SMTP_USER/SMTP_PASSWORD are set in
`backend/.env`, so until now a "new TCB arrived" email had never been composed,
addressed or delivered even once.

WHY THIS SCRIPT EXISTS -- the real arrival path cannot email off-season:
  * POST /api/bulletins/parse raises 404 ("No active bulletin PDFs found")
    before it ever reaches the alert step, whenever PAGASA has nothing posted.
  * The 15-minute scheduler calls PagasaStatusService.sync_active_typhoons()
    BEFORE the alert step, and an empty-but-successful status fetch sets
    is_active = False on every typhoon -- so hand-setting is_active = true in
    psql and waiting for the poll gets wiped in that same tick, and
    send_new_bulletin_alerts() correctly finds nothing alertable.
Hence the default `service` mode below, which drives the real alert function
with a real bulletin row while temporarily holding its typhoon active.

MODES (every call site of send_new_bulletin_alerts, in one file):
  service    (default) The exact call core/scheduler.py:72 makes -- builds the
             same `created` list shape scrape_and_save_all returns from a
             bulletin already in the database. No network, no new rows.
             Temporarily sets that typhoon is_active (auto-reverted).
  upload     Calls the real POST /api/bulletins/upload route function with
             --pdf. Proves the alert wiring added to that route on 2026-10-13.
             WRITES a real bulletin row -- needs --confirm-db-write.
  parse      Calls the real POST /api/bulletins/parse route function. Only
             meaningful while PAGASA has bulletins posted; 404s otherwise.
             WRITES real bulletin rows and re-syncs is_active -- needs
             --confirm-db-write.
  scheduler  Runs the real run_scheduled_scrape() poll tick. Same caveats as
             `parse`, plus: its own is_active re-sync makes --activate-typhoon
             pointless, so that flag is ignored here.

EMAIL IS NOT SENT unless --send is passed. Without it, smtplib is swapped for
a recorder inside the service module and the composed message (subject, real
recipient list, body) is printed instead -- everything except the SMTP
handshake still runs for real.

Run from backend/ (needs the live database, so: the server machine):
    python simulation/simulate_new_bulletin_alert.py                      # dry run, newest bulletin
    python simulation/simulate_new_bulletin_alert.py --tcb-id 432
    python simulation/simulate_new_bulletin_alert.py --send               # really deliver
    python simulation/simulate_new_bulletin_alert.py --preview-without-smtp
    python simulation/simulate_new_bulletin_alert.py --mode upload --pdf "../docs/TCB#11_kiyapo.pdf" \
        --activate-typhoon KIYAPO --confirm-db-write --send
"""

import argparse
import asyncio
import contextlib
import inspect
import logging
import os
import sys
from types import SimpleNamespace

# See the same note in seed_opong_assessment_test.py: this file sits in
# backend/simulation/ but imports `app`, so backend/ must be on sys.path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.models import SystemUser, TropicalCycloneBulletin, Typhoon
from app.services import email_alert_service


class _RecordingSMTP:
    """
    Stand-in for smtplib.SMTP used by every run without --send. Accepts the
    same calls send_new_bulletin_alerts() makes (context manager, starttls,
    login, sendmail) and records the envelope instead of opening a socket, so
    a dry run still exercises the config read, the Typhoon.is_active gate, the
    recipient query and the message body -- only the network is faked.
    """

    captured: list[dict] = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        self.login_user = user

    def sendmail(self, from_addr, to_addrs, message):
        _RecordingSMTP.captured.append({
            "host": self.host,
            "port": self.port,
            "from": from_addr,
            "to": list(to_addrs),
            "message": message,
        })


@contextlib.contextmanager
def _dry_run_smtp(placeholder_config: bool):
    """
    Swaps the service module's own `smtplib` reference (not the global module)
    for one whose SMTP is _RecordingSMTP. With `placeholder_config`, also
    stubs _smtp_config() so the body is still composed on a machine with no
    SMTP credentials at all -- otherwise the function short-circuits at its
    "SMTP not configured" guard and there is nothing to preview.
    """
    real_smtplib = email_alert_service.smtplib
    real_config = email_alert_service._smtp_config
    email_alert_service.smtplib = SimpleNamespace(SMTP=_RecordingSMTP)
    if placeholder_config:
        email_alert_service._smtp_config = lambda: {
            "host": "smtp.example.invalid",
            "port": 587,
            "user": "placeholder@example.invalid",
            "password": "placeholder",
        }
    try:
        yield
    finally:
        email_alert_service.smtplib = real_smtplib
        email_alert_service._smtp_config = real_config


@contextlib.contextmanager
def _temporarily_active(typhoon, db):
    """
    Holds `typhoon` active for the duration of the alert call, then restores
    the original value -- send_new_bulletin_alerts() only emails about
    bulletins whose typhoon is_active, and off-season nothing is. Restored in
    a finally block so an interrupted run can't leave a storm falsely active
    (which would also mislead the Monitoring dashboard's own status panel).
    """
    if typhoon is None:
        yield
        return
    original = typhoon.is_active
    if not original:
        typhoon.is_active = True
        db.commit()
        print(f"  Temporarily set {typhoon.name} is_active = True (will revert to False).")
    try:
        yield
    finally:
        db.refresh(typhoon)
        if typhoon.is_active != original:
            typhoon.is_active = original
            db.commit()
            print(f"  Reverted {typhoon.name} is_active = {original}.")


def _preflight(db) -> None:
    print("=" * 72)
    print("PREFLIGHT")
    print("=" * 72)

    config = email_alert_service._smtp_config()
    if config:
        print(f"  SMTP: configured -- {config['user']} via {config['host']}:{config['port']}")
    else:
        missing = [k for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD") if not os.getenv(k)]
        print(f"  SMTP: NOT configured -- missing {', '.join(missing)} in backend/.env")
        print("        send_new_bulletin_alerts() will log and return without composing anything.")

    recipients = db.query(SystemUser).filter(SystemUser.is_active.is_(True)).all()
    print(f"  Recipients (is_active users): {len(recipients)}")
    for user in recipients:
        print(f"    - {user.email}  ({user.role})")
    if not recipients:
        print("    (none -- the function returns before sending)")

    newest = (
        db.query(TropicalCycloneBulletin)
        .order_by(TropicalCycloneBulletin.tcb_id.desc())
        .first()
    )
    if newest:
        typhoon = newest.typhoon
        state = f"is_active={typhoon.is_active}" if typhoon else "no typhoon row"
        print(f"  Newest bulletin: tcb_id={newest.tcb_id} #{newest.bulletin_count} "
              f"{getattr(typhoon, 'name', '?')} ({state})")
    else:
        print("  Newest bulletin: none -- the database has no bulletins to simulate with")

    # A real check that each ingestion path still calls the alert, rather than
    # a hardcoded claim -- if a call site is ever removed, this stops saying OK.
    # The import can fail loudly on a machine whose backend/.env is incomplete
    # (app.core.security raises at import time without JWT_SECRET_KEY), which
    # has nothing to do with email alerts -- so say so plainly and carry on.
    try:
        from app.api.bulletins import trigger_pagasa_scrape, upload_bulletin_pdf
        from app.core.scheduler import run_scheduled_scrape
    except Exception as e:
        print(f"  Alert call sites: could not check -- {type(e).__name__}: {e}")
        print()
        return
    print("  Alert call sites:")
    for label, func in (
        ("scheduler.run_scheduled_scrape", run_scheduled_scrape),
        ("POST /api/bulletins/parse", trigger_pagasa_scrape),
        ("POST /api/bulletins/upload", upload_bulletin_pdf),
    ):
        wired = "send_new_bulletin_alerts(" in inspect.getsource(func)
        print(f"    [{'OK' if wired else 'MISSING'}] {label}")
    print()


def _report_captured(sent_for_real: bool) -> None:
    print("=" * 72)
    print("RESULT")
    print("=" * 72)
    if sent_for_real:
        print("  --send was passed: the message left via the real SMTP server if the")
        print("  log above says so. Check the recipient inbox, and look for a")
        print("  'Sent bulletin alert email to N active user(s).' line.")
        return
    if not _RecordingSMTP.captured:
        print("  No message was composed. Per the log lines above, the function")
        print("  short-circuited -- SMTP unconfigured, no alertable bulletin")
        print("  (typhoon not active), or no active user accounts.")
        print("  Re-run with --preview-without-smtp to see the body anyway.")
        return
    for item in _RecordingSMTP.captured:
        print(f"  Would connect to {item['host']}:{item['port']}")
        print(f"  Envelope from: {item['from']}")
        print(f"  Envelope to ({len(item['to'])}): {', '.join(item['to'])}")
        print("  " + "-" * 68)
        for line in item["message"].splitlines():
            print(f"  | {line}")
        print("  " + "-" * 68)
    print("  Nothing was transmitted (no --send).")


def _mode_service(args, db) -> None:
    query = db.query(TropicalCycloneBulletin)
    if args.tcb_id is not None:
        bulletin = query.filter(TropicalCycloneBulletin.tcb_id == args.tcb_id).first()
        if bulletin is None:
            sys.exit(f"No bulletin with tcb_id={args.tcb_id}.")
    else:
        bulletin = query.order_by(TropicalCycloneBulletin.tcb_id.desc()).first()
        if bulletin is None:
            sys.exit("The database has no bulletins -- nothing to simulate with.")

    created = [{
        "tcb_id": bulletin.tcb_id,
        "title": bulletin.title,
        "bulletin_count": bulletin.bulletin_count,
        "is_final": bulletin.is_final,
    }]
    print(f"  Simulating arrival of tcb_id={bulletin.tcb_id} ({bulletin.title!r}),")
    print("  with the same `created` payload scrape_and_save_all returns:")
    print(f"    {created[0]}")

    with _temporarily_active(bulletin.typhoon, db):
        email_alert_service.send_new_bulletin_alerts(created, db)


def _mode_upload(args, db) -> None:
    if not args.pdf:
        sys.exit("--mode upload needs --pdf <path to a PAGASA bulletin PDF>.")
    if not os.path.exists(args.pdf):
        sys.exit(f"No such file: {args.pdf}")

    from fastapi import UploadFile

    from app.api.bulletins import upload_bulletin_pdf

    typhoon = None
    if args.activate_typhoon:
        typhoon = (
            db.query(Typhoon)
            .filter(Typhoon.name == args.activate_typhoon.upper())
            .order_by(Typhoon.year.desc())
            .first()
        )
        if typhoon is None:
            sys.exit(f"No typhoon named {args.activate_typhoon.upper()} in tbl_typhoons.")

    print(f"  Uploading {args.pdf} through the real route function.")
    with open(args.pdf, "rb") as handle:
        upload = UploadFile(file=handle, filename=os.path.basename(args.pdf))
        with _temporarily_active(typhoon, db):
            result = asyncio.run(upload_bulletin_pdf(file=upload, db=db))
    print(f"  Route returned: {result}")


def _mode_parse(args, db) -> None:
    from fastapi import HTTPException

    from app.api.bulletins import trigger_pagasa_scrape

    print("  Calling the real POST /api/bulletins/parse route function.")
    try:
        result = asyncio.run(trigger_pagasa_scrape(db=db))
    except HTTPException as e:
        sys.exit(f"  Route returned HTTP {e.status_code}: {e.detail}\n"
                 "  PAGASA has no active bulletin PDFs posted, so this path cannot\n"
                 "  reach the alert step at all. Use --mode service instead.")
    print(f"  Route returned: {result}")


def _mode_scheduler(args, db) -> None:
    from app.core.scheduler import run_scheduled_scrape

    print("  Running one real run_scheduled_scrape() tick (network + is_active re-sync).")
    print("  Note: its own PagasaStatusService sync decides is_active, so a storm")
    print("  PAGASA no longer lists is deactivated before the alert step runs.")
    run_scheduled_scrape()


MODES = {
    "service": _mode_service,
    "upload": _mode_upload,
    "parse": _mode_parse,
    "scheduler": _mode_scheduler,
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Activate/exercise the new-TCB email alert. Dry run unless --send.",
    )
    parser.add_argument("--mode", choices=sorted(MODES), default="service",
                        help="Which call site to drive (default: service).")
    parser.add_argument("--tcb-id", type=int, default=None,
                        help="service mode: which bulletin to simulate (default: newest).")
    parser.add_argument("--pdf", default=None,
                        help="upload mode: the bulletin PDF to upload.")
    parser.add_argument("--activate-typhoon", default=None, metavar="NAME",
                        help="upload mode: hold this typhoon active for the call "
                             "(auto-reverted). service mode does this on its own.")
    parser.add_argument("--send", action="store_true",
                        help="Really transmit via SMTP. Without it, the message is "
                             "composed and printed but never sent.")
    parser.add_argument("--preview-without-smtp", action="store_true",
                        help="Dry run only: inject a placeholder SMTP config so the "
                             "message body is still composed on a machine with no "
                             "credentials.")
    parser.add_argument("--confirm-db-write", action="store_true",
                        help="Required by upload/parse/scheduler modes, which insert "
                             "real bulletin rows.")
    args = parser.parse_args()

    if args.mode in ("upload", "parse", "scheduler") and not args.confirm_db_write:
        sys.exit(f"--mode {args.mode} writes real bulletin rows to the database. "
                 "Re-run with --confirm-db-write if that is what you want "
                 "(or use the default --mode service, which writes nothing).")
    if args.send and args.preview_without_smtp:
        sys.exit("--preview-without-smtp is a dry-run aid; it cannot be combined with --send.")

    # The service logs its decisions (unconfigured / nothing alertable / no
    # recipients / sent) at INFO -- without this they would be invisible and a
    # silent no-op would look indistinguishable from a bug.
    logging.basicConfig(level=logging.INFO, format="  [%(name)s] %(message)s")

    db = SessionLocal()
    try:
        _preflight(db)
        print("=" * 72)
        print(f"MODE: {args.mode}" + ("  (REAL SEND)" if args.send else "  (dry run)"))
        print("=" * 72)
        if args.send:
            MODES[args.mode](args, db)
        else:
            with _dry_run_smtp(placeholder_config=args.preview_without_smtp):
                MODES[args.mode](args, db)
        print()
        _report_captured(sent_for_real=args.send)
    finally:
        db.close()


if __name__ == "__main__":
    main()
