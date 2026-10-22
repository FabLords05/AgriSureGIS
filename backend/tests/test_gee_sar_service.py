import os
import sys
import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services import gee_sar_service as svc


def _fake_ee(orbit_histogram, scene_ms=()):
    """A stand-in `ee` module whose ImageCollection chain returns itself, so
    build_planted_layer() can run end to end without Earth Engine."""
    ee = MagicMock()
    coll = ee.ImageCollection.return_value
    for method in ("filterBounds", "filterDate", "filter"):
        getattr(coll, method).return_value = coll
    coll.aggregate_histogram.return_value.getInfo.return_value = orbit_histogram
    coll.aggregate_array.return_value.getInfo.return_value = list(scene_ms)

    composite = coll.select.return_value.map.return_value.median.return_value
    ratio = composite.select.return_value.subtract.return_value.rename.return_value
    ratio.clipToCollection.return_value.getMapId.return_value = {
        "tile_fetcher": SimpleNamespace(url_format="https://earthengine.example/tiles/{z}/{x}/{y}"),
    }
    return ee, ratio


class _ServiceStateTestCase(unittest.TestCase):
    """Resets the module's process-wide init/cache state around each test."""

    def setUp(self):
        svc._layer_cache.clear()
        self._state = patch.multiple(svc, _initialized=False, _last_error=None, _last_failed_attempt=None)
        self._state.start()

    def tearDown(self):
        self._state.stop()
        svc._layer_cache.clear()


class PickRelativeOrbitTests(unittest.TestCase):
    def test_most_frequent_orbit_wins(self):
        self.assertEqual(svc.pick_relative_orbit({"32": 1, "105": 3}), 105)

    def test_tie_goes_to_lowest_orbit_number(self):
        self.assertEqual(svc.pick_relative_orbit({"105": 2, "32": 2}), 32)

    def test_float_keys_from_ee_histogram(self):
        self.assertEqual(svc.pick_relative_orbit({"105.0": 2}), 105)

    def test_no_scenes_is_none(self):
        self.assertIsNone(svc.pick_relative_orbit({}))


class PreEventWindowTests(unittest.TestCase):
    def test_window_ends_before_the_event(self):
        start, end = svc.pre_event_window(date(2026, 9, 25))
        self.assertEqual(start, date(2026, 9, 1))
        self.assertEqual(end, date(2026, 9, 25))  # exclusive in filterDate


class UnconfiguredTests(_ServiceStateTestCase):
    def test_status_without_key_path_never_touches_ee(self):
        with patch.dict(os.environ, {"GEE_SERVICE_ACCOUNT_KEY_PATH": ""}), \
             patch.dict(sys.modules, {"ee": None}):
            status = svc.gee_status()
        self.assertFalse(status["configured"])
        self.assertFalse(status["connected"])

    def test_build_layer_without_key_path_raises_not_configured(self):
        with patch.dict(os.environ, {"GEE_SERVICE_ACCOUNT_KEY_PATH": ""}):
            with self.assertRaises(svc.GeeNotConfiguredError):
                svc.build_planted_layer(("k",), [{"type": "Polygon", "coordinates": []}], date(2026, 9, 25))

    def test_failed_init_is_not_retried_on_every_status_poll(self):
        ee = MagicMock()
        ee.Initialize.side_effect = RuntimeError("service account not registered")
        with patch.dict(os.environ, {"GEE_SERVICE_ACCOUNT_KEY_PATH": "key.json"}), \
             patch.dict(sys.modules, {"ee": ee}), \
             patch.object(svc, "_key_identity", return_value={"service_account": "sa@x", "project_id": "p"}):
            first = svc.gee_status()
            second = svc.gee_status()
        self.assertFalse(first["connected"])
        self.assertIn("service account not registered", second["last_error"])
        self.assertEqual(ee.Initialize.call_count, 1)


class BuildPlantedLayerTests(_ServiceStateTestCase):
    def _run(self, ee, cache_key=("bulletin", 1)):
        with patch.dict(os.environ, {"GEE_SERVICE_ACCOUNT_KEY_PATH": "key.json"}), \
             patch.dict(sys.modules, {"ee": ee}), \
             patch.object(svc, "_initialized", True):
            return svc.build_planted_layer(cache_key, [{"type": "Polygon", "coordinates": []}], date(2026, 9, 25))

    def test_no_pre_event_scenes_raises(self):
        ee, _ = _fake_ee(orbit_histogram={})
        with self.assertRaises(svc.NoScenesError):
            self._run(ee)

    def test_filters_to_the_most_frequent_descending_orbit_before_the_event(self):
        ms = [
            datetime(2026, 9, 6, tzinfo=timezone.utc).timestamp() * 1000,
            datetime(2026, 9, 18, tzinfo=timezone.utc).timestamp() * 1000,
        ]
        ee, ratio = _fake_ee(orbit_histogram={"32": 1, "105": 2}, scene_ms=ms)

        layer = self._run(ee)

        coll = ee.ImageCollection.return_value
        coll.filterDate.assert_called_once_with("2026-09-01", "2026-09-25")
        ee.Filter.eq.assert_any_call("orbitProperties_pass", "DESCENDING")
        ee.Filter.eq.assert_any_call("relativeOrbitNumber_start", 105)
        self.assertEqual(layer["relative_orbit"], 105)
        self.assertEqual(layer["scene_dates"], ["2026-09-06", "2026-09-18"])
        self.assertEqual(layer["window_end"], "2026-09-24")
        self.assertEqual(layer["tile_url"], "https://earthengine.example/tiles/{z}/{x}/{y}")
        vis = ratio.clipToCollection.return_value.getMapId.call_args.args[0]
        self.assertEqual((vis["min"], vis["max"]), (svc.RATIO_MIN_DB, svc.RATIO_MAX_DB))

    def test_same_cache_key_reuses_the_layer(self):
        ee, ratio = _fake_ee(orbit_histogram={"105": 1})
        self._run(ee)
        self._run(ee)
        self.assertEqual(ratio.clipToCollection.return_value.getMapId.call_count, 1)


if __name__ == "__main__":
    unittest.main()
