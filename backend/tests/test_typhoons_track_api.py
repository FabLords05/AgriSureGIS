import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from fastapi import HTTPException
from geoalchemy2.elements import WKTElement

from app.api.typhoons import PAR_CORNERS, build_track, get_typhoon_track, inside_par
from app.models.models import TropicalCycloneBulletin, Typhoon


def _bulletin(count, lat=None, lon=None, category="Typhoon", wind_radius_km=None, storm_force_radius_km=None, forecast_track=None):
    b = TropicalCycloneBulletin(title=f"Bulletin No. {count}", bulletin_count=count, category=category)
    b.tcb_id = 100 + count
    b.is_final = False
    b.issued_at = datetime(2026, 9, 25, count, 0, tzinfo=timezone.utc)
    b.max_sustained_winds = 120
    b.center_geom = WKTElement(f"POINT({lon} {lat})", srid=4326) if lat is not None else None
    b.wind_radius_km = wind_radius_km
    b.storm_force_radius_km = storm_force_radius_km
    b.forecast_track = forecast_track
    return b


class InsideParTests(unittest.TestCase):
    def test_points_inside_and_outside_par(self):
        self.assertTrue(inside_par(12.3, 125.3))   # Eastern Visayas
        self.assertTrue(inside_par(8.5, 124.6))    # Region X
        self.assertFalse(inside_par(18.3, 108.6))  # Gulf of Tonkin
        self.assertFalse(inside_par(17.0, 116.0))  # west of the 21N/120E notch
        self.assertFalse(inside_par(10.0, 136.0))  # east of 135E

    def test_point_on_par_line_counts_as_inside(self):
        self.assertTrue(inside_par(25.0, 130.0))


class BuildTrackTests(unittest.TestCase):
    def test_every_bulletin_with_a_center_becomes_a_point_in_order(self):
        bulletins = [
            _bulletin(1, 10.6, 131.2, category="Tropical Storm", wind_radius_km=300),
            _bulletin(2, 12.3, 125.3, wind_radius_km=500, storm_force_radius_km=150),
            _bulletin(3, 14.3, 120.9),
        ]

        track = build_track(bulletins)

        self.assertEqual([p["bulletin_count"] for p in track["points"]], [1, 2, 3])
        self.assertEqual(track["points"][0]["category"], "Tropical Storm")
        self.assertEqual(track["points"][1]["wind_radius_km"], 500)
        self.assertEqual(track["points"][1]["storm_force_radius_km"], 150)
        self.assertAlmostEqual(track["points"][2]["lat"], 14.3)
        self.assertAlmostEqual(track["points"][2]["lng"], 120.9)
        self.assertTrue(track["in_par"])

    def test_missing_and_zero_centers_are_skipped(self):
        bulletins = [_bulletin(1, 10.6, 131.2), _bulletin(2), _bulletin(3, 0.0, 0.0)]

        track = build_track(bulletins)

        self.assertEqual([p["bulletin_count"] for p in track["points"]], [1])

    def test_in_par_follows_latest_center(self):
        track = build_track([_bulletin(1, 14.3, 120.9), _bulletin(2, 18.3, 108.6)])

        self.assertFalse(track["in_par"])

    def test_forecast_comes_from_latest_bulletin_only(self):
        old = [{"label": "12-Hour Forecast", "lat": 11.0, "lon": 128.0, "location": None}]
        new = [{"label": "24-Hour Forecast", "lat": 18.3, "lon": 108.6, "location": None}]

        track = build_track([_bulletin(1, 10.6, 131.2, forecast_track=old), _bulletin(2, 12.3, 125.3, forecast_track=new)])

        self.assertEqual(track["forecast"], [{**new[0], "inside_par": False}])

    def test_no_bulletins(self):
        self.assertEqual(build_track([]), {"points": [], "forecast": [], "in_par": None})


class GetTyphoonTrackTests(unittest.TestCase):
    def test_unknown_typhoon_is_404(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with self.assertRaises(HTTPException) as ctx:
            get_typhoon_track(999, mock_db)

        self.assertEqual(ctx.exception.status_code, 404)

    def test_response_shape(self):
        typhoon = Typhoon(name="OPONG", year=2026, is_active=True)
        typhoon.typhoon_id = 7
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = typhoon
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [_bulletin(1, 12.3, 125.3)]

        result = get_typhoon_track(7, mock_db)

        self.assertEqual(result["typhoon_name"], "OPONG")
        self.assertTrue(result["is_active"])
        self.assertEqual(result["par_polygon"], [[lat, lon] for lat, lon in PAR_CORNERS])
        self.assertEqual(len(result["points"]), 1)
        self.assertTrue(result["in_par"])


if __name__ == "__main__":
    unittest.main()
