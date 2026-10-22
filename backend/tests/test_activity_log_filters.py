"""
Activity Log User / Action filters (added 2026-10-22). The Action filter
selects rows by the same summary label the table shows, translated to SQL by
_action_type_filter(); these tests pin that every label is offered, that the
translation targets the right method/endpoint pattern, and that an unknown
label is a 400. No DB: conditions are compiled against the Postgres dialect.
"""
import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-only-not-a-real-secret"}, clear=False):
    from app.api import activity_log as api


def _sql(condition) -> str:
    return str(condition.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class ActionTypeFilterTests(unittest.TestCase):
    def test_every_summary_label_is_offered(self):
        for _, _, summary in api._ENDPOINT_SUMMARIES:
            self.assertIn(summary, api.ACTION_TYPES)
        for label in ("Logged in", "Failed login attempt", "Login blocked (pending approval)", "Logged out"):
            self.assertIn(label, api.ACTION_TYPES)

    def test_labels_are_unique(self):
        self.assertEqual(len(api.ACTION_TYPES), len(set(api.ACTION_TYPES)))

    def test_endpoint_label_filters_on_method_and_pattern(self):
        sql = _sql(api._action_type_filter("Uploaded a CSV file"))
        self.assertIn("tbl_activity_log.action = 'POST'", sql)
        self.assertIn("tbl_activity_log.endpoint ~ '^/api/upload/csv$'", sql)

    def test_login_labels_filter_on_status(self):
        self.assertIn("status_code = 200", _sql(api._action_type_filter("Logged in")))
        self.assertIn("NOT IN (200, 403)", _sql(api._action_type_filter("Failed login attempt")))

    def test_unknown_label_is_400(self):
        with self.assertRaises(HTTPException) as ctx:
            api._action_type_filter("Deleted everything")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_each_pattern_matches_what_summarize_labels(self):
        # A concrete endpoint per pattern must summarise back to its own label,
        # i.e. no earlier pattern shadows it (first-match-wins vs. any-match).
        samples = {
            "Updated a user account": ("PATCH", "/api/users/9"),
            "Recorded a planted verification": ("PUT", "/api/sar/verifications/5"),
            "Computed exposure for a bulletin": ("POST", "/api/bulletins/12/compute-exposure"),
            "CSV ingestion finished": ("INGEST", "/api/upload/csv"),
            "Automatic PAGASA TCB ingestion": ("SYSTEM", "scheduler/pagasa-poll"),
        }
        for label, (method, endpoint) in samples.items():
            self.assertEqual(api._summarize(method, endpoint, 200), label)


if __name__ == "__main__":
    unittest.main()
