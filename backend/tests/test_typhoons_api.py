import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

from fastapi import HTTPException

from app.api.typhoons import get_typhoon_summary
from app.models.models import AreaExposureSummary, RiskAssessment, TropicalCycloneBulletin, Typhoon


class GetTyphoonSummaryTests(unittest.TestCase):
    def _build_mock_db(self, typhoon, bulletins, areas, assessments):
        mock_db = MagicMock()

        typhoon_query = MagicMock()
        typhoon_query.filter.return_value.first.return_value = typhoon

        bulletin_query = MagicMock()
        bulletin_query.filter.return_value.order_by.return_value.all.return_value = bulletins

        areas_query = MagicMock()
        areas_query.filter.return_value.all.return_value = areas

        assessments_query = MagicMock()
        assessments_query.join.return_value.filter.return_value.all.return_value = assessments

        def query_side_effect(model):
            if model is Typhoon:
                return typhoon_query
            if model is TropicalCycloneBulletin:
                return bulletin_query
            if model is AreaExposureSummary:
                return areas_query
            if model is RiskAssessment:
                return assessments_query
            raise AssertionError(f"Unexpected model queried in test: {model}")

        mock_db.query.side_effect = query_side_effect
        return mock_db

    def test_returns_404_when_typhoon_not_found(self):
        mock_db = self._build_mock_db(typhoon=None, bulletins=[], areas=[], assessments=[])

        with self.assertRaises(HTTPException) as ctx:
            get_typhoon_summary(typhoon_id=999, db=mock_db)

        self.assertEqual(ctx.exception.status_code, 404)

    def test_empty_areas_and_assessments_do_not_crash(self):
        typhoon = Typhoon(name="KIYAPO", year=2026, is_active=True)
        typhoon.typhoon_id = 1
        mock_db = self._build_mock_db(typhoon=typhoon, bulletins=[], areas=[], assessments=[])

        result = get_typhoon_summary(typhoon_id=1, db=mock_db)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["total_bulletins_issued"], 0)
        self.assertIsNone(result["first_issued_at"])
        self.assertIsNone(result["last_issued_at"])
        self.assertEqual(result["total_municipalities_affected"], 0)
        self.assertIsNone(result["peak_signal_level"])
        self.assertEqual(result["total_eligible_boundaries"], 0)
        self.assertEqual(result["areas_affected"], [])
        self.assertEqual(result["assessments_computed"], 0)
        self.assertEqual(result["total_indemnity_payout"], 0.0)

    def test_aggregates_areas_and_assessments_correctly(self):
        typhoon = Typhoon(name="FRANCISCO", year=2026, is_active=False)
        typhoon.typhoon_id = 9

        t1 = datetime(2026, 8, 20, 8, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 8, 22, 20, 0, tzinfo=timezone.utc)
        bulletins = [
            MagicMock(issued_at=t1),
            MagicMock(issued_at=t2),
        ]

        eligible_area = AreaExposureSummary(
            typhoon_id=9, boundary_id=1, province="Bukidnon", municipality="Talakag",
            max_signal_level=4, start_time=t1, end_time=t2,
            is_eligible_6hr=True, total_exposure_hours=Decimal("60.00"),
        )
        ineligible_area = AreaExposureSummary(
            typhoon_id=9, boundary_id=2, province="Misamis Oriental", municipality="Claveria",
            max_signal_level=2, start_time=t1, end_time=t1,
            is_eligible_6hr=False, total_exposure_hours=Decimal("2.00"),
        )
        areas = [eligible_area, ineligible_area]

        assessments = [
            RiskAssessment(final_indemnity_payment=Decimal("16500.00")),
            RiskAssessment(final_indemnity_payment=Decimal("8250.00")),
        ]

        mock_db = self._build_mock_db(typhoon=typhoon, bulletins=bulletins, areas=areas, assessments=assessments)

        result = get_typhoon_summary(typhoon_id=9, db=mock_db)

        self.assertEqual(result["typhoon_id"], 9)
        self.assertEqual(result["typhoon_name"], "FRANCISCO")
        self.assertFalse(result["is_active"])
        self.assertEqual(result["total_bulletins_issued"], 2)
        self.assertEqual(result["first_issued_at"], t1)
        self.assertEqual(result["last_issued_at"], t2)
        self.assertEqual(result["total_municipalities_affected"], 2)
        self.assertEqual(result["peak_signal_level"], 4)
        self.assertEqual(result["total_eligible_boundaries"], 1)
        self.assertEqual(len(result["areas_affected"]), 2)
        self.assertEqual(result["areas_affected"][0]["municipality"], "Talakag")
        self.assertEqual(result["assessments_computed"], 2)
        self.assertEqual(result["total_indemnity_payout"], 24750.0)


if __name__ == "__main__":
    unittest.main()
