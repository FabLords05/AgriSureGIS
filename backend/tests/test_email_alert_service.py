"""
First tests for the new-TCB email alert (added 2026-10-13; the service itself
dates to 2026-08-16 and had none). Follows this suite's convention of calling
the function directly with a stand-in session rather than going through
TestClient, and patches the service module's own `smtplib` reference so no
socket is ever opened.
"""
import os
import unittest
from unittest.mock import MagicMock, patch

from app.models.models import SystemUser, TropicalCycloneBulletin, Typhoon
from app.services import email_alert_service
from app.services.email_alert_service import send_new_bulletin_alerts, smtp_configured

SMTP_ENV = {
    "SMTP_HOST": "smtp.test.invalid",
    "SMTP_PORT": "2525",
    "SMTP_USER": "alerts@test.invalid",
    "SMTP_PASSWORD": "secret",
}


def _bulletin(tcb_id, bulletin_count, typhoon_name, is_active, category="Typhoon"):
    typhoon = Typhoon(name=typhoon_name, year=2026, is_active=is_active)
    bulletin = TropicalCycloneBulletin(
        tcb_id=tcb_id,
        title=f"Tropical Cyclone Bulletin No. {bulletin_count}",
        bulletin_count=bulletin_count,
        category=category,
        is_final=False,
    )
    bulletin.typhoon = typhoon
    return bulletin


class _FakeQuery:
    """
    Honours only `filter(Column == value)` on `match_on`, which is all
    _active_typhoon_bulletins() needs (it looks each bulletin up by tcb_id).
    The SystemUser query's `is_active.is_(True)` is left to SQLAlchemy -- its
    criteria are recorded instead, and asserted on in
    RecipientTests.test_queries_only_active_users.
    """

    def __init__(self, rows, match_on=None, recorder=None):
        self._rows = rows
        self._match_on = match_on
        self._recorder = recorder

    def filter(self, *criteria):
        if self._recorder is not None:
            self._recorder.extend(str(c) for c in criteria)
        rows = self._rows
        if self._match_on:
            for criterion in criteria:
                wanted = criterion.right.value
                rows = [r for r in rows if getattr(r, self._match_on) == wanted]
        return _FakeQuery(rows, self._match_on, self._recorder)

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, bulletins=(), users=()):
        self.bulletins = list(bulletins)
        self.users = list(users)
        self.user_criteria: list[str] = []

    def query(self, model):
        if model is TropicalCycloneBulletin:
            return _FakeQuery(self.bulletins, match_on="tcb_id")
        if model is SystemUser:
            return _FakeQuery(self.users, recorder=self.user_criteria)
        raise AssertionError(f"unexpected query({model})")


def _created(bulletin):
    """The dict shape scrape_and_save_all returns for each saved bulletin."""
    return {
        "tcb_id": bulletin.tcb_id,
        "title": bulletin.title,
        "bulletin_count": bulletin.bulletin_count,
        "is_final": bulletin.is_final,
    }


class NoOpPathTests(unittest.TestCase):
    def test_empty_created_returns_immediately(self):
        db = _FakeSession()
        with patch.object(email_alert_service, "smtplib") as mock_smtplib:
            send_new_bulletin_alerts([], db)
        mock_smtplib.SMTP.assert_not_called()

    def test_unconfigured_smtp_is_a_noop(self):
        bulletin = _bulletin(1, 16, "OPONG", is_active=True)
        db = _FakeSession([bulletin], [SystemUser(email="gis@test.invalid")])
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(email_alert_service, "smtplib") as mock_smtplib:
            send_new_bulletin_alerts([_created(bulletin)], db)
        mock_smtplib.SMTP.assert_not_called()

    def test_partial_smtp_config_is_a_noop(self):
        """All three of HOST/USER/PASSWORD are required -- host alone is not enough."""
        bulletin = _bulletin(1, 16, "OPONG", is_active=True)
        db = _FakeSession([bulletin], [SystemUser(email="gis@test.invalid")])
        with patch.dict(os.environ, {"SMTP_HOST": "smtp.test.invalid"}, clear=True), \
                patch.object(email_alert_service, "smtplib") as mock_smtplib:
            send_new_bulletin_alerts([_created(bulletin)], db)
        mock_smtplib.SMTP.assert_not_called()

    def test_inactive_typhoon_is_not_alerted(self):
        """
        The gate Fabio asked for: a bulletin that parses for a typhoon PAGASA
        no longer lists as active (a late/backfilled bulletin, or one landing
        in the same tick the storm is downgraded) must not trigger an alert.
        """
        bulletin = _bulletin(1, 16, "OPONG", is_active=False)
        db = _FakeSession([bulletin], [SystemUser(email="gis@test.invalid")])
        with patch.dict(os.environ, SMTP_ENV, clear=True), \
                patch.object(email_alert_service, "smtplib") as mock_smtplib:
            send_new_bulletin_alerts([_created(bulletin)], db)
        mock_smtplib.SMTP.assert_not_called()

    def test_missing_bulletin_row_is_skipped(self):
        """A tcb_id that no longer resolves must not raise."""
        db = _FakeSession([], [SystemUser(email="gis@test.invalid")])
        with patch.dict(os.environ, SMTP_ENV, clear=True), \
                patch.object(email_alert_service, "smtplib") as mock_smtplib:
            send_new_bulletin_alerts([{"tcb_id": 999, "title": "x", "bulletin_count": 1}], db)
        mock_smtplib.SMTP.assert_not_called()

    def test_no_active_users_means_no_send(self):
        bulletin = _bulletin(1, 16, "OPONG", is_active=True)
        db = _FakeSession([bulletin], [])
        with patch.dict(os.environ, SMTP_ENV, clear=True), \
                patch.object(email_alert_service, "smtplib") as mock_smtplib:
            send_new_bulletin_alerts([_created(bulletin)], db)
        mock_smtplib.SMTP.assert_not_called()


class SendPathTests(unittest.TestCase):
    def _send(self, bulletins, users):
        db = _FakeSession(bulletins, users)
        with patch.dict(os.environ, SMTP_ENV, clear=True), \
                patch.object(email_alert_service, "smtplib") as mock_smtplib:
            send_new_bulletin_alerts([_created(b) for b in bulletins], db)
        server = mock_smtplib.SMTP.return_value.__enter__.return_value
        return mock_smtplib, server, db

    def test_sends_to_every_active_user(self):
        bulletin = _bulletin(1, 16, "OPONG", is_active=True)
        users = [
            SystemUser(email="gis@test.invalid", role="GIS Specialist"),
            SystemUser(email="admin@test.invalid", role="System Administrator"),
        ]
        mock_smtplib, server, _ = self._send([bulletin], users)

        mock_smtplib.SMTP.assert_called_once_with("smtp.test.invalid", 2525, timeout=10)
        server.starttls.assert_called_once()
        server.login.assert_called_once_with("alerts@test.invalid", "secret")
        from_addr, to_addrs, message = server.sendmail.call_args.args
        self.assertEqual(from_addr, "alerts@test.invalid")
        self.assertEqual(to_addrs, ["gis@test.invalid", "admin@test.invalid"])
        self.assertIn("Subject: AgriSureGIS: New PAGASA Tropical Cyclone Bulletin", message)
        self.assertIn("OPONG", message)
        self.assertIn("Bulletin #16", message)

    def test_recipients_are_not_in_a_visible_header(self):
        """Broadcast is BCC-style: addresses ride the envelope, not To:."""
        bulletin = _bulletin(1, 16, "OPONG", is_active=True)
        _, server, _ = self._send([bulletin], [SystemUser(email="gis@test.invalid")])
        _, _, message = server.sendmail.call_args.args
        self.assertIn("To: alerts@test.invalid", message)
        self.assertNotIn("To: gis@test.invalid", message)

    def test_default_port_is_587_when_unset(self):
        bulletin = _bulletin(1, 16, "OPONG", is_active=True)
        db = _FakeSession([bulletin], [SystemUser(email="gis@test.invalid")])
        env = {k: v for k, v in SMTP_ENV.items() if k != "SMTP_PORT"}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(email_alert_service, "smtplib") as mock_smtplib:
            send_new_bulletin_alerts([_created(bulletin)], db)
        mock_smtplib.SMTP.assert_called_once_with("smtp.test.invalid", 587, timeout=10)

    def test_subject_pluralizes_and_body_lists_each_bulletin(self):
        first = _bulletin(1, 16, "OPONG", is_active=True)
        second = _bulletin(2, 3, "TINO", is_active=True, category="Tropical Storm")
        _, server, _ = self._send([first, second], [SystemUser(email="gis@test.invalid")])
        _, _, message = server.sendmail.call_args.args
        self.assertIn("Tropical Cyclone Bulletins", message)
        self.assertIn("OPONG", message)
        self.assertIn("TINO", message)
        self.assertIn("Tropical Storm", message)

    def test_only_active_typhoons_are_listed_in_a_mixed_batch(self):
        active = _bulletin(1, 16, "OPONG", is_active=True)
        stale = _bulletin(2, 9, "NANDO", is_active=False)
        _, server, _ = self._send([active, stale], [SystemUser(email="gis@test.invalid")])
        _, _, message = server.sendmail.call_args.args
        self.assertIn("OPONG", message)
        self.assertNotIn("NANDO", message)

    def test_smtp_failure_never_raises(self):
        """
        A mail failure must not take down the scrape request or the scheduler
        thread that called it.
        """
        bulletin = _bulletin(1, 16, "OPONG", is_active=True)
        db = _FakeSession([bulletin], [SystemUser(email="gis@test.invalid")])
        with patch.dict(os.environ, SMTP_ENV, clear=True), \
                patch.object(email_alert_service, "smtplib") as mock_smtplib:
            mock_smtplib.SMTP.side_effect = OSError("connection refused")
            send_new_bulletin_alerts([_created(bulletin)], db)  # must not raise


class RecipientTests(unittest.TestCase):
    def test_queries_only_active_users(self):
        bulletin = _bulletin(1, 16, "OPONG", is_active=True)
        db = _FakeSession([bulletin], [SystemUser(email="gis@test.invalid")])
        with patch.dict(os.environ, SMTP_ENV, clear=True), \
                patch.object(email_alert_service, "smtplib"):
            send_new_bulletin_alerts([_created(bulletin)], db)
        self.assertEqual(len(db.user_criteria), 1)
        self.assertIn("is_active", db.user_criteria[0])


class SmtpConfiguredTests(unittest.TestCase):
    """GET /api/system/status reads this for the Monitoring "Email Alerts" row."""

    def test_true_when_all_three_set(self):
        with patch.dict(os.environ, SMTP_ENV, clear=True):
            self.assertTrue(smtp_configured())

    def test_false_when_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(smtp_configured())


class UploadRouteWiringTests(unittest.TestCase):
    """
    The manual-upload route was the one ingestion path that saved a bulletin
    and notified nobody (fixed 2026-10-13). Asserts the alert is called with
    the just-saved bulletin, without going near a real PDF or the database.
    """

    @classmethod
    def setUpClass(cls):
        # Importing app.api.bulletins pulls in app.core.security, which raises
        # at import time when JWT_SECRET_KEY is unset -- deliberate (no
        # insecure fallback), but unrelated to this test, which never signs a
        # token. A throwaway value lets the import succeed on a machine with
        # no backend/.env; patch.dict restores the environment afterwards.
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-only-not-a-real-secret"}, clear=False):
            from app.api import bulletins as bulletins_api
        cls.bulletins_api = bulletins_api

    def test_upload_route_sends_the_alert(self):
        import asyncio

        bulletins_api = self.bulletins_api

        saved = _bulletin(7, 4, "OPONG", is_active=True)
        upload = MagicMock(filename="TCB#4_opong.pdf")

        with patch.object(bulletins_api.BulletinParserService, "parse_bulletin_text",
                          return_value={"is_final": False}), \
                patch.object(bulletins_api.BulletinParserService, "save_bulletin_to_db",
                             return_value=saved), \
                patch.object(bulletins_api, "send_new_bulletin_alerts") as mock_alert, \
                patch.object(bulletins_api.shutil, "copyfileobj"), \
                patch("builtins.open", MagicMock()), \
                patch.object(bulletins_api.os.path, "exists", return_value=False), \
                patch.object(bulletins_api.os, "makedirs"):
            asyncio.run(bulletins_api.upload_bulletin_pdf(file=upload, db=MagicMock()))

        mock_alert.assert_called_once()
        created_arg = mock_alert.call_args.args[0]
        self.assertEqual(created_arg, [{
            "tcb_id": 7,
            "title": "Tropical Cyclone Bulletin No. 4",
            "bulletin_count": 4,
            "is_final": False,
        }])


if __name__ == "__main__":
    unittest.main()
