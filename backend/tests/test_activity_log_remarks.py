"""
Activity Log remarks (added 2026-10-22): every entry carries a full sentence
of what was done, stated by the route via note_activity() and completed with
the error message by main.py's exception handlers when the request is
rejected. The helper tests need no DB; the middleware tests drive the real
app through TestClient (no `with` block, so the lifespan/scheduler never
starts) with record_activity and SessionLocal patched out.
"""
import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.core import activity_log
from app.core.activity_log import (
    compose_request_remarks,
    end_request_remarks,
    note_activity,
    note_activity_error,
    plural,
    record_activity,
    start_request_remarks,
)

with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-only-not-a-real-secret"}, clear=False):
    from app import main


class RemarksHelperTests(unittest.TestCase):
    def test_note_activity_outside_a_request_is_a_no_op(self):
        note_activity("nothing to attach this to")  # must not raise

    def test_route_remarks_and_rejection_are_combined(self):
        holder, token = start_request_remarks()
        try:
            note_activity('CSV upload "farmers.xlsx".')
            note_activity_error("Please upload a CSV file.")
        finally:
            end_request_remarks(token)
        self.assertEqual(
            compose_request_remarks(holder, 400),
            'CSV upload "farmers.xlsx". Rejected: Please upload a CSV file.',
        )

    def test_server_error_is_labelled_failed(self):
        holder = {"remarks": None, "error": "boom"}
        self.assertEqual(compose_request_remarks(holder, 500), "Failed: boom")

    def test_validation_error_list_is_flattened(self):
        holder, token = start_request_remarks()
        try:
            note_activity_error([{"loc": ("body", "email"), "msg": "value is not a valid email address"}])
        finally:
            end_request_remarks(token)
        self.assertEqual(holder["error"], "email: value is not a valid email address")

    def test_plural(self):
        self.assertEqual(plural(1, "row"), "1 row")
        self.assertEqual(plural(1113, "row"), "1,113 rows")
        self.assertEqual(plural(2, "policy", "policies"), "2 policies")

    def test_long_remarks_are_truncated(self):
        db = MagicMock()
        record_activity(db, 1, "INGEST", "/api/upload/csv", 200, "x" * 5000)
        stored = db.add.call_args.args[0].remarks
        self.assertEqual(len(stored), activity_log._MAX_REMARKS_LENGTH)
        self.assertTrue(stored.endswith("…"))


class MiddlewareRemarksTests(unittest.TestCase):
    def _post(self, path, **kwargs):
        with patch.object(main, "record_activity") as recorded, patch.object(main, "SessionLocal"):
            response = TestClient(main.app).post(path, **kwargs)
        return response, recorded

    def test_sync_route_remarks_reach_the_log_with_the_rejection_reason(self):
        # register_user runs in a threadpool worker; its note_activity() must
        # still reach the middleware's holder.
        response, recorded = self._post("/api/users/register", json={
            "full_name": "Juan Dela Cruz", "email": "juan@pcic.gov.ph", "employee_id": "E-1",
            "role": "System Administrator", "password": "longenough",
        })
        self.assertEqual(response.status_code, 400)
        args = recorded.call_args.args
        self.assertEqual(args[2:5], ("POST", "/api/users/register", 400))
        self.assertIn("Access request from Juan Dela Cruz <juan@pcic.gov.ph>", args[5])
        self.assertIn("Rejected: Role must be GIS Specialist.", args[5])

    def test_unauthenticated_upload_is_logged_as_rejected(self):
        response, recorded = self._post("/api/upload/csv", files={"file": ("a.csv", b"x", "text/csv")})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(recorded.call_args.args[5], "Rejected: Not authenticated.")

    def test_unlogged_get_writes_nothing(self):
        with patch.object(main, "record_activity") as recorded, patch.object(main, "SessionLocal"):
            TestClient(main.app).get("/")
        recorded.assert_not_called()


if __name__ == "__main__":
    unittest.main()
