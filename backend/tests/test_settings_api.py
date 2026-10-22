"""
Admin Panel settings (2026-10-22): the coverage rate is validated and
persisted, and only administrators may change it. Route functions are called
directly with stand-in sessions, like test_users_api.py.
"""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.models.models import SystemUser

with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-only-not-a-real-secret"}, clear=False):
    from app.api import settings as settings_api
    from app.core.security import require_admin


def _admin():
    return SystemUser(user_id=1, firstname="Ad", lastname="Min", role="System Administrator", email="a@x.ph",
                      password_hash="")


def _db_with_rate(rate):
    db = MagicMock()
    row = SimpleNamespace(setting_key="coverage_rate_per_ha", setting_value=rate, updated_by=None)
    db.query.return_value.filter.return_value.first.return_value = row
    return db, row


class CoverageRateTests(unittest.TestCase):
    def test_valid_rate_is_saved(self):
        db, row = _db_with_rate(25000)
        result = settings_api.update_coverage_rate(
            settings_api.CoverageRateRequest(coverage_rate_per_ha=30000), db=db, admin=_admin()
        )
        self.assertEqual(row.setting_value, 30000)
        self.assertEqual(row.updated_by, 1)
        db.commit.assert_called_once()
        self.assertEqual(result["data"]["coverage_rate_per_ha"], 30000)

    def test_out_of_range_rate_is_rejected(self):
        for bad in (0, 999, 100001):
            db, row = _db_with_rate(25000)
            with self.assertRaises(HTTPException) as ctx:
                settings_api.update_coverage_rate(
                    settings_api.CoverageRateRequest(coverage_rate_per_ha=bad), db=db, admin=_admin()
                )
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertEqual(row.setting_value, 25000)
            db.commit.assert_not_called()

    def test_specialist_cannot_reach_admin_routes(self):
        specialist = SystemUser(user_id=2, role="GIS Specialist")
        with self.assertRaises(HTTPException) as ctx:
            require_admin(specialist)
        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
