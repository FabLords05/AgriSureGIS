import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

from app.models.models import (
    AdminBoundary,
    AreaExposureSummary,
    ExposureInterval,
    RiskAssessment,
    TcbSignal,
    TropicalCycloneBulletin,
)
from app.services.exposure_calculator import (
    BulletinSnapshot,
    ExposureCalculatorService,
    build_area_exposures,
    serialize_summary,
)

T0 = datetime(2025, 9, 23, 5, 0, tzinfo=timezone.utc)
A = ("Isabela", "Tumauini")
B = ("Cagayan", "Baggao")


def snap(count, hours_after_t0, areas, is_final=False, tcb_id=None):
    return BulletinSnapshot(
        tcb_id=tcb_id if tcb_id is not None else 100 + count,
        bulletin_count=count,
        issued_at=T0 + timedelta(hours=hours_after_t0),
        is_final=is_final,
        areas={key: (level, 0) for key, level in areas.items()},
    )


class BuildAreaExposuresTests(unittest.TestCase):
    def test_spec_example_total_is_sum_of_signal_hours(self):
        # Signal 1 for 12h, Signal 2 for 18h, Signal 3 for 24h -> 54h total,
        # not 24h (the MAX of one level).
        result = build_area_exposures([
            snap(1, 0, {A: 1}),
            snap(2, 12, {A: 2}),
            snap(3, 30, {A: 3}),
            snap(4, 54, {}),
        ])[A]
        hours = result.hours_by_level()
        self.assertEqual(hours, {1: Decimal("12.0"), 2: Decimal("18.0"), 3: Decimal("24.0"), 4: 0, 5: 0})
        self.assertEqual(result.total_hours, Decimal("54.0"))
        self.assertEqual(result.max_signal_level, 3)
        self.assertEqual(result.payout_hours, Decimal("24.0"))
        self.assertFalse(result.has_open_interval)

    def test_max_signal_uses_whole_history_not_latest_bulletin(self):
        result = build_area_exposures([
            snap(1, 0, {A: 1}), snap(2, 6, {A: 2}), snap(3, 12, {A: 3}),
            snap(4, 18, {A: 2}), snap(5, 24, {A: 1}), snap(6, 30, {}),
        ])[A]
        self.assertEqual(result.max_signal_level, 3)

    def test_returning_to_a_level_adds_to_that_level(self):
        result = build_area_exposures([
            snap(1, 0, {A: 1}), snap(2, 3, {A: 2}), snap(3, 9, {A: 1}), snap(4, 14, {}),
        ])[A]
        hours = result.hours_by_level()
        self.assertEqual(hours[1], Decimal("8.0"))  # 3h + 5h
        self.assertEqual(hours[2], Decimal("6.0"))
        self.assertEqual(result.total_hours, Decimal("14.0"))

    def test_consecutive_bulletins_at_same_level_form_one_interval(self):
        result = build_area_exposures([snap(1, 0, {A: 2}), snap(2, 6, {A: 2}), snap(3, 12, {})])[A]
        self.assertEqual(len(result.intervals), 1)
        self.assertEqual(result.hours_by_level()[2], Decimal("12.0"))

    def test_absence_from_a_bulletin_lifts_the_signal(self):
        result = build_area_exposures([
            snap(1, 0, {A: 1, B: 1}), snap(2, 6, {B: 1}), snap(3, 12, {B: 1}), snap(4, 18, {}),
        ])
        self.assertEqual(result[A].total_hours, Decimal("6.0"))
        self.assertEqual(result[B].total_hours, Decimal("18.0"))

    def test_gap_between_listings_is_not_counted(self):
        # Listed, lifted, listed again: the lifted stretch adds nothing.
        result = build_area_exposures([
            snap(1, 0, {A: 1}), snap(2, 6, {}), snap(3, 12, {A: 1}), snap(4, 18, {}),
        ])[A]
        self.assertEqual(result.total_hours, Decimal("12.0"))

    def test_final_bulletin_lifts_everything(self):
        result = build_area_exposures([snap(1, 0, {A: 2}), snap(2, 6, {A: 2}, is_final=True)])[A]
        self.assertEqual(result.total_hours, Decimal("6.0"))
        self.assertFalse(result.has_open_interval)

    def test_open_signal_newly_raised_in_latest_bulletin_has_no_hours_yet(self):
        result = build_area_exposures([snap(1, 0, {A: 1}), snap(2, 6, {A: 2})])[A]
        self.assertEqual(result.hours_by_level()[1], Decimal("6.0"))
        self.assertEqual(result.hours_by_level()[2], Decimal("0.0"))
        self.assertTrue(result.has_open_interval)
        self.assertEqual(result.max_signal_level, 2)
        self.assertEqual(result.payout_hours, Decimal("0.0"))

    def test_open_signal_is_counted_up_to_the_latest_bulletin(self):
        # Still Signal 2 at hour 12 with no later bulletin: 0h-12h is known.
        result = build_area_exposures([snap(1, 0, {A: 1}), snap(2, 6, {A: 2}), snap(3, 12, {A: 2})])[A]
        self.assertEqual(result.hours_by_level()[1], Decimal("6.0"))
        self.assertEqual(result.hours_by_level()[2], Decimal("6.0"))
        self.assertEqual(result.total_hours, Decimal("12.0"))
        self.assertEqual(result.payout_hours, Decimal("6.0"))
        self.assertTrue(result.has_open_interval)

    def test_a_later_bulletin_extends_an_open_signal_without_double_counting(self):
        ongoing = build_area_exposures([snap(1, 0, {A: 2}), snap(2, 6, {A: 2})])[A]
        closed = build_area_exposures([snap(1, 0, {A: 2}), snap(2, 6, {A: 2}), snap(3, 9, {})])[A]
        self.assertEqual(ongoing.total_hours, Decimal("6.0"))
        self.assertEqual(closed.total_hours, Decimal("9.0"))
        self.assertEqual(len(closed.intervals), 1)
        self.assertFalse(closed.has_open_interval)

    def test_single_bulletin_counts_nothing(self):
        result = build_area_exposures([snap(1, 0, {A: 2})])[A]
        self.assertEqual(result.total_hours, Decimal("0"))
        self.assertTrue(result.has_open_interval)

    def test_out_of_order_input_is_sorted_by_issue_time(self):
        ordered = build_area_exposures([snap(1, 0, {A: 1}), snap(2, 6, {A: 2}), snap(3, 12, {})])[A]
        shuffled = build_area_exposures([snap(3, 12, {}), snap(1, 0, {A: 1}), snap(2, 6, {A: 2})])[A]
        self.assertEqual(ordered.hours_by_level(), shuffled.hours_by_level())

    def test_duplicate_bulletin_does_not_add_hours(self):
        once = build_area_exposures([snap(1, 0, {A: 2}), snap(2, 6, {})])[A]
        twice = build_area_exposures([snap(1, 0, {A: 2}), snap(1, 0, {A: 2}), snap(2, 6, {})])[A]
        self.assertEqual(once.total_hours, twice.total_hours)

    def test_same_issue_time_makes_no_zero_length_interval(self):
        result = build_area_exposures([snap(1, 0, {A: 1}), snap(2, 0, {A: 2}), snap(3, 6, {})])[A]
        self.assertEqual([i.signal_level for i in result.intervals], [2])
        self.assertEqual(result.total_hours, Decimal("6.0"))

    def test_intervals_never_overlap(self):
        result = build_area_exposures([
            snap(1, 0, {A: 1}), snap(2, 3, {A: 3}), snap(3, 7, {A: 2}), snap(4, 9, {A: 3}), snap(5, 15, {}),
        ])[A]
        for earlier, later in zip(result.intervals, result.intervals[1:]):
            self.assertLessEqual(earlier.end, later.start)
        self.assertEqual(result.total_hours, Decimal("15.0"))

    def test_long_gap_is_counted_but_flagged(self):
        result = build_area_exposures([snap(1, 0, {A: 1}), snap(2, 20, {})])[A]
        self.assertEqual(result.total_hours, Decimal("20.0"))
        self.assertTrue(result.has_long_gap)

    def test_partial_hours_keep_precision(self):
        result = build_area_exposures([snap(1, 0, {A: 1}), snap(2, 2.5, {})])[A]
        self.assertEqual(result.total_hours, Decimal("2.5"))


class ComputeForTyphoonTests(unittest.TestCase):
    def _build_mock_db(self, bulletins, boundaries, signals, existing_summaries=(), referenced_ids=()):
        mock_db = MagicMock()
        added = []
        mock_db.add.side_effect = added.append
        mock_db.added = added

        queries = {
            TropicalCycloneBulletin: MagicMock(),
            AdminBoundary: MagicMock(),
            TcbSignal: MagicMock(),
            AreaExposureSummary: MagicMock(),
            ExposureInterval: MagicMock(),
        }
        queries[TropicalCycloneBulletin].filter.return_value.order_by.return_value.all.return_value = bulletins
        queries[AdminBoundary].options.return_value.order_by.return_value.all.return_value = boundaries
        queries[TcbSignal].filter.return_value.all.return_value = signals
        queries[AreaExposureSummary].filter.return_value.all.return_value = list(existing_summaries)
        referenced = MagicMock()
        referenced.filter.return_value.distinct.return_value.all.return_value = [(i,) for i in referenced_ids]

        def query_side_effect(model):
            if model is RiskAssessment.summary_id:
                return referenced
            return queries[model]

        mock_db.query.side_effect = query_side_effect
        return mock_db

    def _bulletin(self, tcb_id, count, hours, is_final=False, parsed=True):
        return MagicMock(
            tcb_id=tcb_id, bulletin_count=count, issued_at=T0 + timedelta(hours=hours),
            is_final=is_final, issued_at_parsed=parsed,
        )

    def _signal(self, tcb_id, level, province="Misamis Oriental", municipality="Claveria"):
        return MagicMock(tcb_id=tcb_id, signal_level=level, island_group=2, province=province, area_name=municipality)

    def test_persists_per_signal_hours_and_payout_hours(self):
        boundary = MagicMock(boundary_id=5, province="Misamis Oriental", municipality="Claveria")
        mock_db = self._build_mock_db(
            bulletins=[self._bulletin(10, 1, 0), self._bulletin(11, 2, 6), self._bulletin(12, 3, 18)],
            boundaries=[boundary],
            signals=[self._signal(10, 2), self._signal(11, 3)],
        )

        summaries = ExposureCalculatorService.compute_for_typhoon(1, mock_db)

        self.assertEqual(len(summaries), 1)
        s = summaries[0]
        self.assertEqual((s.province, s.municipality, s.boundary_id), ("Misamis Oriental", "Claveria", 5))
        self.assertEqual(s.max_signal_level, 3)
        self.assertEqual(s.signal_2_hours, Decimal("6.0"))
        self.assertEqual(s.signal_3_hours, Decimal("12.0"))
        self.assertEqual(s.total_exposure_hours, Decimal("18.0"))
        self.assertEqual(s.payout_hours, Decimal("12.0"))
        self.assertTrue(s.is_eligible_6hr)
        intervals = [obj for obj in mock_db.added if isinstance(obj, ExposureInterval)]
        self.assertEqual([(i.signal_level, i.start_tcb_id, i.end_tcb_id) for i in intervals], [(2, 10, 11), (3, 11, 12)])

    def test_signal_1_only_area_is_not_eligible_even_past_6_hours(self):
        boundary = MagicMock(boundary_id=5, province="Misamis Oriental", municipality="Claveria")
        mock_db = self._build_mock_db(
            bulletins=[self._bulletin(10, 1, 0), self._bulletin(11, 2, 36)],
            boundaries=[boundary],
            signals=[self._signal(10, 1)],
        )

        s = ExposureCalculatorService.compute_for_typhoon(1, mock_db)[0]

        self.assertEqual(s.max_signal_level, 1)
        self.assertEqual(s.payout_hours, Decimal("36.0"))
        self.assertFalse(s.is_eligible_6hr)

    def test_bulletin_without_parsed_issue_time_is_left_out(self):
        boundary = MagicMock(boundary_id=5, province="Misamis Oriental", municipality="Claveria")
        mock_db = self._build_mock_db(
            bulletins=[self._bulletin(10, 1, 0), self._bulletin(11, 2, 500, parsed=False), self._bulletin(12, 3, 6)],
            boundaries=[boundary],
            signals=[self._signal(10, 2), self._signal(11, 2)],
        )

        summaries = ExposureCalculatorService.compute_for_typhoon(1, mock_db)

        self.assertEqual(summaries[0].total_exposure_hours, Decimal("6.0"))

    def test_disambiguates_same_named_municipality_by_province(self):
        boundary_a = MagicMock(boundary_id=1, province="Laguna", municipality="Santa Cruz")
        boundary_b = MagicMock(boundary_id=2, province="Marinduque", municipality="Santa Cruz")
        mock_db = self._build_mock_db(
            bulletins=[self._bulletin(10, 1, 0)],
            boundaries=[boundary_a, boundary_b],
            signals=[self._signal(10, 2, "Marinduque", "Santa Cruz")],
        )

        summaries = ExposureCalculatorService.compute_for_typhoon(1, mock_db)

        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].boundary_id, 2)
        self.assertEqual(summaries[0].province, "Marinduque")

    def test_skips_signal_with_no_province_recorded(self):
        boundary = MagicMock(boundary_id=5, province="Misamis Oriental", municipality="Claveria")
        mock_db = self._build_mock_db(
            bulletins=[self._bulletin(10, 1, 0)],
            boundaries=[boundary],
            signals=[self._signal(10, 2, province=None)],
        )

        self.assertEqual(ExposureCalculatorService.compute_for_typhoon(1, mock_db), [])

    def test_stale_summary_is_deleted_unless_an_assessment_references_it(self):
        stale_free = MagicMock(summary_id=50, province="Bukidnon", municipality="Talakag")
        stale_used = MagicMock(summary_id=51, province="Bukidnon", municipality="Maramag")
        mock_db = self._build_mock_db(
            bulletins=[self._bulletin(10, 1, 0)], boundaries=[], signals=[],
            existing_summaries=[stale_free, stale_used], referenced_ids=[51],
        )

        ExposureCalculatorService.compute_for_typhoon(1, mock_db)

        mock_db.delete.assert_called_once_with(stale_free)
        self.assertEqual(stale_used.total_exposure_hours, Decimal("0"))
        self.assertFalse(stale_used.is_eligible_6hr)

    def test_case_variant_duplicate_summary_is_retired_and_kept_row_takes_boundary_spelling(self):
        boundary = MagicMock(boundary_id=3865, province="Cagayan", municipality="Pamplona")
        title_case = MagicMock(summary_id=112, province="Cagayan", municipality="Pamplona")
        upper_case = MagicMock(summary_id=1892, province="CAGAYAN", municipality="PAMPLONA")
        mock_db = self._build_mock_db(
            bulletins=[self._bulletin(10, 1, 0), self._bulletin(11, 2, 6)],
            boundaries=[boundary],
            signals=[self._signal(10, 2, "Cagayan", "Pamplona")],
            existing_summaries=[upper_case, title_case],
        )

        summaries = ExposureCalculatorService.compute_for_typhoon(1, mock_db)

        self.assertEqual(summaries, [title_case])
        mock_db.delete.assert_called_once_with(upper_case)
        self.assertEqual(title_case.total_exposure_hours, Decimal("6.0"))

    def test_case_variant_duplicate_keeps_the_row_an_assessment_references(self):
        boundary = MagicMock(boundary_id=3865, province="Cagayan", municipality="Pamplona")
        title_case = MagicMock(summary_id=112, province="Cagayan", municipality="Pamplona")
        upper_case = MagicMock(summary_id=1892, province="CAGAYAN", municipality="PAMPLONA")
        mock_db = self._build_mock_db(
            bulletins=[self._bulletin(10, 1, 0), self._bulletin(11, 2, 6)],
            boundaries=[boundary],
            signals=[self._signal(10, 2, "Cagayan", "Pamplona")],
            existing_summaries=[title_case, upper_case], referenced_ids=[1892],
        )

        summaries = ExposureCalculatorService.compute_for_typhoon(1, mock_db)

        self.assertEqual(summaries, [upper_case])
        mock_db.delete.assert_called_once_with(title_case)
        self.assertEqual((upper_case.province, upper_case.municipality), ("Cagayan", "Pamplona"))

    def test_no_bulletins_returns_empty(self):
        mock_db = self._build_mock_db(bulletins=[], boundaries=[], signals=[])
        self.assertEqual(ExposureCalculatorService.compute_for_typhoon(1, mock_db), [])


class SerializeSummaryTests(unittest.TestCase):
    def _summary(self, s1, s2, s3=0, s4=0, s5=0, max_signal_level=2):
        return AreaExposureSummary(
            summary_id=1, boundary_id=5, province="Batanes", municipality="Basco", island_group=0,
            max_signal_level=max_signal_level, signal_1_hours=Decimal(s1), signal_2_hours=Decimal(s2),
            signal_3_hours=Decimal(s3), signal_4_hours=Decimal(s4), signal_5_hours=Decimal(s5),
            total_exposure_hours=Decimal(s1) + Decimal(s2) + Decimal(s3) + Decimal(s4) + Decimal(s5),
            payout_hours=Decimal(s2), start_time=T0, end_time=T0, is_eligible_6hr=max_signal_level >= 2,
            has_open_interval=False, has_long_gap=False,
        )

    def test_tcws2_plus_exposure_leaves_out_signal_1(self):
        data = serialize_summary(self._summary("24", "30", "2.5"))
        self.assertEqual(data["total_exposure_hours"], 56.5)
        self.assertEqual(data["tcws2_plus_exposure_hours"], 32.5)

    def test_signal_1_only_area_has_zero_tcws2_plus_exposure(self):
        data = serialize_summary(self._summary("36", "0", max_signal_level=1))
        self.assertEqual(data["total_exposure_hours"], 36.0)
        self.assertEqual(data["tcws2_plus_exposure_hours"], 0)


if __name__ == "__main__":
    unittest.main()
