import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.api import sar
from app.api.sar import CheckRequest, _needs_fetch, list_planted_checks, run_planted_check
from app.models.models import SarFetchCoverage, SarPlantedCheck
from app.services import sar_planted_classifier as c
from app.services.sar_planted_classifier import Observation, classify, in_planting_window, pick_orbit_series

# OPONG-like event: first bulletin 2025-09-24, so W = 2025-04-27 .. 2025-09-23.
EVENT = date(2025, 9, 24)
FIRST_SCENE = date(2025, 4, 28)
SCENES = [FIRST_SCENE + timedelta(days=12 * i) for i in range(13)]  # 04-28 .. 09-19


def _series(t0_index=4, vh_rise=3.0, ratio_drop=1.9, vv_min_index=None):
    """A wet-season rice curve: VH dips at the flood (t0) then climbs; the
    VV/VH ratio falls as the canopy closes. Before t0 the field is fallow.
    VV's own minimum lands on t0 naturally; vv_min_index forces it elsewhere."""
    out = []
    for i, d in enumerate(SCENES):
        if i < t0_index:
            vh, ratio = -15.5, 6.8
        else:
            grown = min(1.0, (i - t0_index) / 5)  # full canopy ~60 days after t0
            vh = -18.0 + vh_rise * grown
            ratio = 7.2 - ratio_drop * grown
        vv = vh + ratio
        if i == vv_min_index:
            vv = -20.0
        out.append(Observation(scene_date=d, vv_db=vv, vh_db=vh))
    return out


class ClassifyTests(unittest.TestCase):
    def test_rice_signature_is_planted(self):
        result = classify(_series(), EVENT)
        self.assertEqual(result.status, c.STATUS_PLANTED)
        self.assertEqual(result.reason_code, c.REASON_PLANTED)
        self.assertEqual(result.t0_date, SCENES[4])
        self.assertGreaterEqual(result.vh_rise_db, c.RISE_VH_DB)
        self.assertGreaterEqual(result.ratio_drop_db, c.DROP_RATIO_DB)
        self.assertEqual(result.scene_count, 13)

    def test_scenes_outside_the_window_are_ignored(self):
        late = Observation(scene_date=EVENT, vv_db=-30.0, vh_db=-40.0)  # on the event day itself
        self.assertEqual(classify(_series() + [late], EVENT).t0_date, SCENES[4])

    def test_too_few_scenes(self):
        result = classify(_series()[:c.MIN_OBSERVATIONS - 1], EVENT)
        self.assertEqual((result.status, result.reason_code), (c.STATUS_FIELD_VERIFY, "too_few_scenes"))

    def test_minimum_at_window_edge_is_no_flood_minimum(self):
        self.assertEqual(classify(_series(t0_index=0), EVENT).reason_code, "no_flood_minimum")

    def test_flood_too_recent_to_confirm(self):
        self.assertEqual(classify(_series(t0_index=11), EVENT).reason_code, "crop_too_young")

    def test_flat_vh_is_no_biomass_rise(self):
        self.assertEqual(classify(_series(vh_rise=1.0), EVENT).reason_code, "no_biomass_rise")

    def test_ratio_not_dropping_is_no_canopy_closure(self):
        self.assertEqual(classify(_series(ratio_drop=0.5), EVENT).reason_code, "no_canopy_closure")

    def test_vv_minimum_far_from_t0_disagrees(self):
        self.assertEqual(classify(_series(vv_min_index=10), EVENT).reason_code, "vv_vh_disagree")

    def test_crop_older_than_maturity_is_outside_window(self):
        # t0 = 2025-05-10, 137 days before the event -- already harvested.
        self.assertEqual(classify(_series(t0_index=1), EVENT).reason_code, "outside_planting_window")

    def test_region_x_planting_window(self):
        self.assertTrue(in_planting_window(date(2025, 6, 15)))   # Sem 2 start
        self.assertTrue(in_planting_window(date(2026, 1, 10)))   # Sem 1, crosses New Year
        self.assertFalse(in_planting_window(date(2025, 3, 20)))  # between seasons

    def test_orbit_with_most_scenes_wins(self):
        obs = Observation(scene_date=date(2025, 6, 1), vv_db=-10, vh_db=-16)
        orbit, series = pick_orbit_series([(32, obs), (105, obs), (105, obs)])
        self.assertEqual((orbit, len(series)), (105, 2))
        self.assertEqual(pick_orbit_series([]), (None, []))


START, END = c.observation_window(EVENT)
_POLY = '{"type":"Polygon","coordinates":[[[124.6,8.5],[124.7,8.5],[124.7,8.6],[124.6,8.5]]]}'


def _db(coverages=()):
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = list(coverages)
    return db


_USER = SimpleNamespace(user_id=9)
_FARMS = [
    (1, _POLY, "hash1", 5000.0),   # sampled
    (2, None, None, None),         # no GPX boundary
    (3, _POLY, "hash3", 0.0),      # gone after the inward buffer
]


class NeedsFetchTests(unittest.TestCase):
    def _cov(self, start=START, end=END, geom_hash="h"):
        return SarFetchCoverage(farm_id=1, covered_start=start, covered_end=end, geom_hash=geom_hash)

    def test_cached_window_needs_no_fetch(self):
        self.assertFalse(_needs_fetch(self._cov(start=START - timedelta(days=30)), "h", START, END))

    def test_missing_partial_or_reshaped_needs_fetch(self):
        self.assertTrue(_needs_fetch(None, "h", START, END))
        self.assertTrue(_needs_fetch(self._cov(end=END - timedelta(days=1)), "h", START, END))
        self.assertTrue(_needs_fetch(self._cov(geom_hash="old"), "h", START, END))


class RunPlantedCheckTests(unittest.TestCase):
    def setUp(self):
        self._patches = [
            patch.object(sar, "_load_affected_farms", return_value=_FARMS),
            patch.object(sar, "_event_date", return_value=EVENT),
            patch.object(sar, "_load_observations", return_value={1: [(105, o) for o in _series()]}),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def test_no_affected_farms_is_422(self):
        with patch.object(sar, "_load_affected_farms", return_value=[]):
            with self.assertRaises(HTTPException) as ctx:
                run_planted_check(CheckRequest(typhoon_id=7), db=_db(), current_user=_USER)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_fully_cached_run_never_calls_earth_engine(self):
        cov = SarFetchCoverage(farm_id=1, covered_start=START, covered_end=END, geom_hash="hash1")
        cov3 = SarFetchCoverage(farm_id=3, covered_start=START, covered_end=END, geom_hash="hash3")
        db = _db(coverages=[cov, cov3])
        with patch.object(sar.gee_sar_service, "gee_configured", return_value=False), \
             patch.object(sar.gee_sar_service, "fetch_backscatter_series") as fetch:
            result = run_planted_check(CheckRequest(typhoon_id=7), db=db, current_user=_USER)

        # Scoped to the typhoon itself -- every bulletin's affected farms.
        self.assertEqual(sar._load_affected_farms.call_args.args[1], 7)
        self.assertEqual(sar._event_date.call_args.args[1], 7)
        fetch.assert_not_called()
        summary = result["data"]["summary"]
        self.assertEqual((summary["fetched_from_gee"], summary["from_cache"]), (0, 1))
        self.assertEqual((summary["checked"], summary["planted"], summary["field_verify"]), (3, 1, 2))
        by_farm = {r["farm_id"]: r for r in result["data"]["results"]}
        self.assertEqual(by_farm[1]["status"], "planted")
        self.assertEqual(by_farm[1]["relative_orbit"], 105)
        self.assertEqual(by_farm[2]["reason_code"], "no_boundary")
        self.assertEqual(by_farm[3]["reason_code"], "too_small")

    def test_uncached_farm_without_gee_is_503(self):
        with patch.object(sar.gee_sar_service, "gee_configured", return_value=False):
            with self.assertRaises(HTTPException) as ctx:
                run_planted_check(CheckRequest(typhoon_id=7), db=_db(), current_user=_USER)
        self.assertEqual(ctx.exception.status_code, 503)

    def test_uncached_farm_is_fetched_once_and_stored(self):
        db = _db()
        series = {1: [{"scene_date": SCENES[0], "relative_orbit": 105, "vv_db": -9.0, "vh_db": -16.0}]}
        with patch.object(sar.gee_sar_service, "gee_configured", return_value=True), \
             patch.object(sar.gee_sar_service, "fetch_backscatter_series", return_value=series) as fetch, \
             patch.object(sar, "_store_fetched") as store:
            result = run_planted_check(CheckRequest(typhoon_id=7), db=db, current_user=_USER)

        farms_sent, start, end_exclusive = fetch.call_args.args
        self.assertEqual([fid for fid, _ in farms_sent], [1])  # never the no-boundary / too-small farms
        self.assertEqual((start, end_exclusive), (START, EVENT))
        self.assertEqual(store.call_args.args[1], {1: "hash1"})
        self.assertIs(store.call_args.args[3], series)
        self.assertEqual(result["data"]["summary"]["fetched_from_gee"], 1)
        added = db.add_all.call_args.args[0]
        self.assertTrue(all(isinstance(r, SarPlantedCheck) and r.typhoon_id == 7 for r in added))

    def test_earth_engine_failure_is_502(self):
        with patch.object(sar.gee_sar_service, "gee_configured", return_value=True), \
             patch.object(sar.gee_sar_service, "fetch_backscatter_series", side_effect=RuntimeError("quota")):
            with self.assertRaises(HTTPException) as ctx:
                run_planted_check(CheckRequest(typhoon_id=7), db=_db(), current_user=_USER)
        self.assertEqual(ctx.exception.status_code, 502)


class ListPlantedChecksTests(unittest.TestCase):
    def test_never_run_has_no_summary(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        self.assertEqual(list_planted_checks(typhoon_id=7, db=db)["data"], {"summary": None, "results": []})

    def test_summary_counts_reasons(self):
        def row(farm_id, status, reason):
            return SarPlantedCheck(farm_id=farm_id, typhoon_id=7, status=status, reason_code=reason,
                                   scene_count=12, window_start=START, window_end=END,
                                   checked_at=datetime(2026, 10, 12, tzinfo=timezone.utc))
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            row(1, "planted", c.REASON_PLANTED),
            row(2, "field_verify", "no_canopy_closure"),
            row(3, "field_verify", "no_canopy_closure"),
            row(4, "field_verify", "no_boundary"),
        ]
        summary = list_planted_checks(typhoon_id=7, db=db)["data"]["summary"]
        self.assertEqual((summary["planted"], summary["field_verify"]), (1, 3))
        self.assertEqual(summary["reasons"][0], {"code": "no_canopy_closure", "label": "No canopy closure (C3)", "count": 2})


if __name__ == "__main__":
    unittest.main()
