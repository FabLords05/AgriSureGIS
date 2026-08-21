import unittest
from collections import deque
from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.models.models import AdminBoundary, AreaExposureSummary, TcbSignal, TropicalCycloneBulletin
from app.services.exposure_calculator import ExposureCalculatorService


class ExposureCalculatorServiceTests(unittest.TestCase):
    def _build_mock_db(self, bulletins, boundaries, signals_per_bulletin):
        """Dispatches db.query(Model) per-model, and hands out one TcbSignal
        queryset per bulletin in the same order compute_for_typhoon iterates them."""
        mock_db = MagicMock()

        bulletin_query = MagicMock()
        bulletin_query.filter.return_value.order_by.return_value.all.return_value = bulletins

        admin_query = MagicMock()
        admin_query.all.return_value = boundaries

        summary_query = MagicMock()
        summary_query.filter.return_value.first.return_value = None

        signal_queues = deque(signals_per_bulletin)

        def query_side_effect(model):
            if model is TropicalCycloneBulletin:
                return bulletin_query
            if model is AdminBoundary:
                return admin_query
            if model is AreaExposureSummary:
                return summary_query
            if model is TcbSignal:
                signal_query = MagicMock()
                signal_query.filter.return_value.all.return_value = signal_queues.popleft()
                return signal_query
            raise AssertionError(f"Unexpected model queried in test: {model}")

        mock_db.query.side_effect = query_side_effect
        return mock_db

    def test_compute_for_typhoon_aggregates_exposure_across_bulletins(self):
        boundary = MagicMock()
        boundary.boundary_id = 5
        boundary.province = "Misamis Oriental"
        boundary.municipality = "Claveria"

        bulletin_1 = MagicMock(tcb_id=10, issued_at=datetime(2024, 10, 15, 8, 0, tzinfo=timezone.utc))
        bulletin_2 = MagicMock(tcb_id=11, issued_at=datetime(2024, 10, 15, 14, 0, tzinfo=timezone.utc))

        signal_1 = MagicMock(area_name="Claveria", province="Misamis Oriental", signal_level=2)
        signal_2 = MagicMock(area_name="Claveria", province="Misamis Oriental", signal_level=3)

        mock_db = self._build_mock_db(
            bulletins=[bulletin_1, bulletin_2],
            boundaries=[boundary],
            signals_per_bulletin=[[signal_1], [signal_2]],
        )

        results = ExposureCalculatorService.compute_for_typhoon(1, mock_db)

        self.assertEqual(len(results), 1)
        summary = results[0]
        self.assertEqual(summary.boundary_id, 5)
        self.assertEqual(summary.province, "Misamis Oriental")
        self.assertEqual(summary.municipality, "Claveria")
        self.assertEqual(summary.max_signal_level, 3)
        self.assertEqual(summary.total_exposure_hours, 6.0)
        self.assertTrue(summary.is_eligible_6hr)

    def test_compute_for_typhoon_single_bulletin_is_not_eligible(self):
        boundary = MagicMock()
        boundary.boundary_id = 5
        boundary.province = "Bukidnon"
        boundary.municipality = "Talakag"

        bulletin_1 = MagicMock(tcb_id=20, issued_at=datetime(2024, 10, 15, 8, 0, tzinfo=timezone.utc))
        signal_1 = MagicMock(area_name="Talakag", province="Bukidnon", signal_level=2)

        mock_db = self._build_mock_db(
            bulletins=[bulletin_1],
            boundaries=[boundary],
            signals_per_bulletin=[[signal_1]],
        )

        results = ExposureCalculatorService.compute_for_typhoon(1, mock_db)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].total_exposure_hours, 0.0)
        self.assertFalse(results[0].is_eligible_6hr)

    def test_compute_for_typhoon_disambiguates_same_named_municipality_by_province(self):
        # Regression test for the nationwide-scale collision bug (2026-08-20):
        # keying boundaries by municipality name alone silently mismatched a
        # signal to the wrong province's boundary once AdminBoundary covers
        # the whole country and duplicate municipality names exist across
        # provinces (e.g. multiple "Santa Cruz").
        boundary_a = MagicMock(boundary_id=1, province="Laguna", municipality="Santa Cruz")
        boundary_b = MagicMock(boundary_id=2, province="Marinduque", municipality="Santa Cruz")

        bulletin_1 = MagicMock(tcb_id=10, issued_at=datetime(2024, 10, 15, 8, 0, tzinfo=timezone.utc))
        signal_1 = MagicMock(area_name="Santa Cruz", province="Marinduque", signal_level=2)

        mock_db = self._build_mock_db(
            bulletins=[bulletin_1],
            boundaries=[boundary_a, boundary_b],
            signals_per_bulletin=[[signal_1]],
        )

        results = ExposureCalculatorService.compute_for_typhoon(1, mock_db)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].boundary_id, 2)  # Marinduque's, not Laguna's
        self.assertEqual(results[0].province, "Marinduque")

    def test_compute_for_typhoon_skips_signal_with_no_province_recorded(self):
        # Signals saved before the 2026-08-20 migration have province=None --
        # can't disambiguate safely, so they're skipped rather than guessed.
        boundary = MagicMock(boundary_id=5, province="Misamis Oriental", municipality="Claveria")
        bulletin_1 = MagicMock(tcb_id=10, issued_at=datetime(2024, 10, 15, 8, 0, tzinfo=timezone.utc))
        signal_1 = MagicMock(area_name="Claveria", province=None, signal_level=2)

        mock_db = self._build_mock_db(
            bulletins=[bulletin_1],
            boundaries=[boundary],
            signals_per_bulletin=[[signal_1]],
        )

        results = ExposureCalculatorService.compute_for_typhoon(1, mock_db)

        self.assertEqual(results, [])

    def test_compute_for_typhoon_no_bulletins_returns_empty(self):
        mock_db = self._build_mock_db(bulletins=[], boundaries=[], signals_per_bulletin=[])

        results = ExposureCalculatorService.compute_for_typhoon(1, mock_db)

        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
