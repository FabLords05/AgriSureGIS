import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.api import sar
from app.api.sar import (
    LayerRequest,
    VerificationRequest,
    clear_verification,
    get_planted_layer,
    list_verifications,
    set_verification,
)
from app.models.models import Farm, PlantedVerification
from app.services.gee_sar_service import NoScenesError

_POLYGON = {"type": "MultiPolygon", "coordinates": [[[[124.6, 8.5], [124.7, 8.5], [124.7, 8.6], [124.6, 8.5]]]]}
_LAYER = {"tile_url": "https://ee/{z}/{x}/{y}", "scene_dates": ["2026-09-18"], "relative_orbit": 105}


_FIRST_BULLETIN = datetime(2026, 9, 24, 23, 0, tzinfo=timezone.utc)


def _layer_db(first_issued_at=_FIRST_BULLETIN):
    """The typhoon's earliest bulletin issued_at -- None = no such typhoon."""
    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.return_value = first_issued_at
    return db


class GetPlantedLayerTests(unittest.TestCase):
    def setUp(self):
        self._configured = patch.object(sar.gee_sar_service, "gee_configured", return_value=True)
        self._configured.start()

    def tearDown(self):
        self._configured.stop()

    def test_typhoon_without_bulletins_is_404(self):
        with self.assertRaises(HTTPException) as ctx:
            get_planted_layer(LayerRequest(typhoon_id=1), db=_layer_db(None))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_gee_not_configured_is_503(self):
        with patch.object(sar.gee_sar_service, "gee_configured", return_value=False):
            with self.assertRaises(HTTPException) as ctx:
                get_planted_layer(LayerRequest(typhoon_id=7), db=_layer_db())
        self.assertEqual(ctx.exception.status_code, 503)

    def test_no_affected_polygons_is_422(self):
        with patch.object(sar, "_load_affected_polygons", return_value=([], 4)):
            with self.assertRaises(HTTPException) as ctx:
                get_planted_layer(LayerRequest(typhoon_id=7), db=_layer_db())
        self.assertEqual(ctx.exception.status_code, 422)

    def test_builds_layer_for_the_typhoon_from_its_first_bulletin_date(self):
        with patch.object(sar, "_load_affected_polygons", return_value=([(1, _POLYGON), (2, _POLYGON)], 3)) as load, \
             patch.object(sar.gee_sar_service, "build_planted_layer", return_value=_LAYER) as build:
            result = get_planted_layer(LayerRequest(typhoon_id=7), db=_layer_db())

        self.assertEqual(load.call_args.args[1:], (7, date(2026, 9, 24)))  # typhoon + its event date
        _, polygons, event_date = build.call_args.args
        self.assertEqual(polygons, [_POLYGON, _POLYGON])
        self.assertEqual(event_date, date(2026, 9, 24))
        data = result["data"]
        self.assertEqual(data["tile_url"], _LAYER["tile_url"])
        self.assertEqual(data["typhoon_id"], 7)
        self.assertEqual(data["farm_count"], 2)
        self.assertEqual(data["skipped_no_geom"], 3)
        self.assertFalse(data["capped"])

    def test_polygon_cap_is_reported(self):
        with patch.object(sar, "MAX_LAYER_FARMS", 2), \
             patch.object(sar, "_load_affected_polygons", return_value=([(i, _POLYGON) for i in range(3)], 0)), \
             patch.object(sar.gee_sar_service, "build_planted_layer", return_value=_LAYER) as build:
            result = get_planted_layer(LayerRequest(typhoon_id=7), db=_layer_db())
        self.assertEqual(len(build.call_args.args[1]), 2)
        self.assertTrue(result["data"]["capped"])
        self.assertEqual(result["data"]["farm_count"], 2)

    def test_no_pre_event_scenes_is_422(self):
        with patch.object(sar, "_load_affected_polygons", return_value=([(1, _POLYGON)], 0)), \
             patch.object(sar.gee_sar_service, "build_planted_layer", side_effect=NoScenesError("none")):
            with self.assertRaises(HTTPException) as ctx:
                get_planted_layer(LayerRequest(typhoon_id=7), db=_layer_db())
        self.assertEqual(ctx.exception.status_code, 422)

    def test_earth_engine_failure_is_502(self):
        with patch.object(sar, "_load_affected_polygons", return_value=([(1, _POLYGON)], 0)), \
             patch.object(sar.gee_sar_service, "build_planted_layer", side_effect=RuntimeError("quota")):
            with self.assertRaises(HTTPException) as ctx:
                get_planted_layer(LayerRequest(typhoon_id=7), db=_layer_db())
        self.assertEqual(ctx.exception.status_code, 502)


class VerificationTests(unittest.TestCase):
    def _db(self, farm=True, existing=None):
        db = MagicMock()
        db.get.side_effect = lambda model, pk: SimpleNamespace(farm_id=pk) if (model is Farm and farm) else None
        db.query.return_value.filter.return_value.first.return_value = existing
        return db

    def test_unknown_farm_is_404(self):
        with self.assertRaises(HTTPException) as ctx:
            set_verification(5, VerificationRequest(typhoon_id=7, is_planted=True), db=self._db(farm=False),
                             current_user=SimpleNamespace(user_id=9))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_first_verdict_inserts_a_row(self):
        db = self._db()
        result = set_verification(5, VerificationRequest(typhoon_id=7, is_planted=False, notes="bare soil"),
                                  db=db, current_user=SimpleNamespace(user_id=9))

        added = db.add.call_args.args[0]
        self.assertIsInstance(added, PlantedVerification)
        self.assertEqual((added.farm_id, added.typhoon_id, added.is_planted, added.verified_by),
                         (5, 7, False, 9))
        db.commit.assert_called_once()
        self.assertFalse(result["data"]["is_planted"])
        self.assertEqual(result["data"]["notes"], "bare soil")

    def test_changing_a_verdict_updates_the_existing_row(self):
        existing = PlantedVerification(farm_id=5, typhoon_id=7, is_planted=False)
        db = self._db(existing=existing)
        set_verification(5, VerificationRequest(typhoon_id=7, is_planted=True), db=db,
                         current_user=SimpleNamespace(user_id=11))
        db.add.assert_not_called()
        self.assertTrue(existing.is_planted)
        self.assertEqual(existing.verified_by, 11)

    def test_clear_deletes_the_farm_typhoon_row(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.delete.return_value = 1
        result = clear_verification(5, typhoon_id=7, db=db)
        self.assertEqual(result["deleted"], 1)
        db.commit.assert_called_once()

    def test_list_returns_rows_for_the_typhoon(self):
        row = PlantedVerification(farm_id=5, typhoon_id=7, is_planted=True)
        row.verified_at = datetime(2026, 10, 12, tzinfo=timezone.utc)
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [row]
        result = list_verifications(typhoon_id=7, db=db)
        self.assertEqual(result["data"][0]["farm_id"], 5)
        self.assertTrue(result["data"][0]["is_planted"])
        self.assertIsNone(result["data"][0]["verified_by"])


if __name__ == "__main__":
    unittest.main()
