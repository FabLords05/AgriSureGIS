"""
Archive & Clear (2026-10-22). The guarantees under test: nothing is cleared
before CLEAR_AFTER_DAYS past every assessed typhoon's last bulletin, and a
failed archive copy never deletes anything from the live DB. Same convention
as the rest of this suite: stand-in sessions, no live database.
"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.models.models import SystemUser
from app.services import archive_service
from app.services.archive_service import ArchiveError

with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-only-not-a-real-secret"}, clear=False):
    from app.api import archives as archives_api

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
COUNTS = {"farmers": 10, "farms": 12, "policies": 12, "assessments": 8}


def _typhoon(days_since_last_bulletin, typhoon_id=1, name="OPONG"):
    last = NOW - timedelta(days=days_since_last_bulletin)
    return {"typhoon_id": typhoon_id, "name": name, "year": 2025, "last_bulletin_at": last,
            "clear_after": last + timedelta(days=archive_service.CLEAR_AFTER_DAYS)}


def _eligibility(counts, typhoons):
    with (
        patch.object(archive_service, "_live_counts", return_value=counts),
        patch.object(archive_service, "_live_typhoons", return_value=typhoons),
    ):
        return archive_service.eligibility(MagicMock(), now=NOW)


def _user():
    return SystemUser(user_id=4, firstname="Ana", lastname="Cruz", role="GIS Specialist", email="a@x.ph",
                      password_hash="")


class EligibilityTests(unittest.TestCase):
    def test_no_live_data_is_not_clearable(self):
        state = _eligibility({"farmers": 0, "farms": 0, "policies": 0, "assessments": 0}, [])
        self.assertFalse(state["eligible"])

    def test_data_never_assessed_is_not_clearable(self):
        state = _eligibility(COUNTS, [])
        self.assertFalse(state["eligible"])
        self.assertIn("No typhoon", state["reason"])

    def test_six_days_after_last_bulletin_is_too_early(self):
        state = _eligibility(COUNTS, [_typhoon(6)])
        self.assertFalse(state["eligible"])
        self.assertEqual(state["eligible_at"], NOW + timedelta(days=1))

    def test_seven_days_after_last_bulletin_is_clearable(self):
        state = _eligibility(COUNTS, [_typhoon(7)])
        self.assertTrue(state["eligible"])
        self.assertEqual(state["label"], "OPONG 2025")

    def test_latest_typhoon_sets_the_wait(self):
        state = _eligibility(COUNTS, [_typhoon(20, 1, "OPONG"), _typhoon(3, 2, "RAMIL")])
        self.assertFalse(state["eligible"])
        self.assertEqual(state["eligible_at"], NOW + timedelta(days=4))
        self.assertEqual(state["label"], "OPONG 2025, RAMIL 2025")


class ArchiveAndClearTests(unittest.TestCase):
    def _run(self, copied):
        db = MagicMock()
        db.execute.return_value.scalar_one.return_value = 5
        writer = MagicMock()
        conn = writer.begin.return_value.__enter__.return_value
        conn.execute.return_value.scalar_one.return_value = 5
        backup = MagicMock(file_name="agrisure_archive.dump", gdrive_file_id="drive-1", gdrive_error=None)
        with (
            patch.object(archive_service, "eligibility",
                         return_value={"eligible": True, "reason": None, "typhoons": [_typhoon(10)],
                                       "label": "OPONG 2025"}),
            patch.object(archive_service, "archive_writer_engine", return_value=writer),
            patch.object(archive_service, "run_backup", return_value=backup) as run_backup,
            patch.object(archive_service, "_copy_table", return_value=copied),
            patch.object(archive_service, "refresh_farm_latest_insurance_view"),
            patch.object(archive_service, "invalidate_farms_cache"),
        ):
            try:
                return db, run_backup, archive_service.archive_and_clear(db, _user())
            except ArchiveError as exc:
                return db, run_backup, exc

    @staticmethod
    def _deletes(db):
        return [str(c.args[0]) for c in db.execute.call_args_list if str(c.args[0]).startswith("DELETE")]

    def test_copy_mismatch_aborts_without_deleting(self):
        db, run_backup, outcome = self._run(copied=4)

        self.assertIsInstance(outcome, ArchiveError)
        self.assertEqual(self._deletes(db), [])
        db.commit.assert_not_called()
        db.rollback.assert_called()
        run_backup.assert_called_once()  # the safety dump still happened first

    def test_successful_copy_deletes_children_before_parents_then_commits(self):
        db, _, result = self._run(copied=5)

        self.assertEqual(self._deletes(db), [f"DELETE FROM {t}" for t in archive_service._LIVE_DELETE_ORDER])
        db.commit.assert_called_once()
        self.assertEqual(result["label"], "OPONG 2025")
        self.assertTrue(result["gdrive_uploaded"])

    def test_not_eligible_never_dumps_or_deletes(self):
        db = MagicMock()
        with (
            patch.object(archive_service, "eligibility",
                         return_value={"eligible": False, "reason": "Too early.", "typhoons": [], "label": ""}),
            patch.object(archive_service, "run_backup") as run_backup,
        ):
            with self.assertRaises(ArchiveError):
                archive_service.archive_and_clear(db, _user())
        run_backup.assert_not_called()
        db.execute.assert_not_called()

    def test_second_concurrent_run_is_refused(self):
        archive_service._archive_lock.acquire()
        try:
            with self.assertRaises(archive_service.ArchiveBusyError):
                archive_service.archive_and_clear(MagicMock(), _user())
        finally:
            archive_service._archive_lock.release()


class ArchivedTyphoonRowsTests(unittest.TestCase):
    """Assessment & Reporting's read-only view of an archived typhoon."""

    _ROW = {
        "assessment_id": 41, "insurance_records_id": 7, "matrix_id": None, "period_of_exposure": 12,
        "wind_velocity": 3, "crop_stage": "Flowering", "final_indemnity_payment": 3650, "assessment_date": NOW,
        "typhoon_id": 1, "typhoon_name": "OPONG", "policy_no": "P-001", "amount_cover": 25000,
        "csv_farm_reference": "1979999", "area_size": 1.5, "province": "BUKIDNON", "municipality": "TALAKAG",
        "barangay": "SAN ISIDRO", "farmers_id": "111", "last_name": "CRUZ", "first_name": "ANA", "middle_name": None,
    }

    def test_rows_come_back_in_the_live_pabs_shape(self):
        archived = {"archive_id": 2, "label": "OPONG 2026", "archived_at": NOW, "max_winds": 150, "rows": [self._ROW]}
        with patch.object(archives_api.archive_service, "archived_typhoon_assessments", return_value=archived):
            result = archives_api.get_archived_typhoon_rows(1, db=MagicMock())

        (row,) = result["data"]["rows"]
        self.assertEqual(result["data"]["archive_id"], 2)
        self.assertEqual(row["CIC_NO"], "P-001")
        self.assertEqual(row["AC"], 25000.0)
        self.assertEqual(row["WIND_VELOCITY"], 150)
        self.assertEqual(row["wind_signal"], 3)
        self.assertEqual(row["FARMID"], "1979999")
        self.assertTrue(row["FARMER_NAME"].startswith("CRUZ"))

    def test_never_archived_typhoon_is_404(self):
        with patch.object(archives_api.archive_service, "archived_typhoon_assessments", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                archives_api.get_archived_typhoon_rows(99, db=MagicMock())
        self.assertEqual(ctx.exception.status_code, 404)

    def test_archive_not_configured_lists_no_archived_typhoons(self):
        with patch.object(archives_api, "archive_configured", return_value=False):
            self.assertEqual(archives_api.list_archived_typhoons()["data"], [])


class ArchiveRouteTests(unittest.TestCase):
    def test_wrong_confirmation_word_is_rejected_before_anything_runs(self):
        with patch.object(archives_api.archive_service, "archive_and_clear") as run:
            with self.assertRaises(HTTPException) as ctx:
                archives_api.archive_and_clear(archives_api.ArchiveRequest(confirm="clear it"),
                                               db=MagicMock(), user=_user())
        self.assertEqual(ctx.exception.status_code, 400)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
