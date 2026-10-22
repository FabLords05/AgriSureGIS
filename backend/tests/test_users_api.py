"""
User Management is scoped to GIS Specialist accounts (added 2026-10-22):
System Administrator accounts are provisioned by the superuser outside the
app, so the admin-facing routes must never list, create, promote to, or edit
one, and public registration must not request one. Same convention as the
rest of this suite: call the route functions directly with a stand-in session.
"""
import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.models.models import SystemUser

with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-only-not-a-real-secret"}, clear=False):
    from app.api import users as users_api


def _user(role, is_active=True):
    return SystemUser(user_id=9, email="x.y@pcic.gov.ph", firstname="X", lastname="Y",
                      role=role, is_active=is_active, password_hash="")


def _db_returning(user):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = user
    return db


class ManagedRoleTests(unittest.TestCase):
    def test_list_filters_to_gis_specialists(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        users_api.list_users(db=db, _admin=MagicMock())

        (criterion,), _ = db.query.return_value.filter.call_args
        self.assertEqual(criterion.right.value, "GIS Specialist")

    def test_editing_an_admin_account_is_404(self):
        db = _db_returning(_user("System Administrator"))
        with self.assertRaises(HTTPException) as ctx:
            users_api.update_user(9, users_api.UpdateUserRequest(is_active=False), MagicMock(),
                                  db=db, _admin=MagicMock())
        self.assertEqual(ctx.exception.status_code, 404)
        db.commit.assert_not_called()

    def test_promoting_to_admin_is_rejected(self):
        db = _db_returning(_user("GIS Specialist"))
        with self.assertRaises(HTTPException) as ctx:
            users_api.update_user(9, users_api.UpdateUserRequest(role="System Administrator"), MagicMock(),
                                  db=db, _admin=MagicMock())
        self.assertEqual(ctx.exception.status_code, 400)
        db.commit.assert_not_called()

    def test_creating_an_admin_is_rejected(self):
        db = MagicMock()
        payload = users_api.CreateUserRequest(name="X Y", email="x.y@pcic.gov.ph",
                                              role="System Administrator", password="password1")
        with self.assertRaises(HTTPException) as ctx:
            users_api.create_user(payload, db=db, _admin=MagicMock())
        self.assertEqual(ctx.exception.status_code, 400)
        db.add.assert_not_called()

    def test_create_defaults_to_gis_specialist(self):
        db = MagicMock()
        payload = users_api.CreateUserRequest(name="X Y", email="x.y@pcic.gov.ph", password="password1")
        users_api.create_user(payload, db=db, _admin=MagicMock())
        self.assertEqual(db.add.call_args.args[0].role, "GIS Specialist")

    def test_registering_as_admin_is_rejected(self):
        db = MagicMock()
        payload = users_api.RegisterRequest(full_name="X Y", email="x.y@pcic.gov.ph", employee_id="E1",
                                            role="System Administrator", password="password1")
        with self.assertRaises(HTTPException) as ctx:
            users_api.register_user(payload, db=db)
        self.assertEqual(ctx.exception.status_code, 400)
        db.add.assert_not_called()


if __name__ == "__main__":
    unittest.main()
