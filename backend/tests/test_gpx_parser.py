import unittest

from app.services.gpx_parser import GpxParserService

SAMPLE_GPX_TRACK = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test">
  <trk>
    <trkseg>
      <trkpt lat="8.000" lon="125.000"></trkpt>
      <trkpt lat="8.000" lon="125.001"></trkpt>
      <trkpt lat="8.001" lon="125.001"></trkpt>
      <trkpt lat="8.001" lon="125.000"></trkpt>
    </trkseg>
  </trk>
</gpx>"""

SAMPLE_GPX_TOO_FEW_POINTS = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test">
  <trk>
    <trkseg>
      <trkpt lat="8.000" lon="125.000"></trkpt>
      <trkpt lat="8.001" lon="125.001"></trkpt>
    </trkseg>
  </trk>
</gpx>"""

SAMPLE_GPX_ROUTE_ONLY = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test">
  <rte>
    <rtept lat="8.000" lon="125.000"></rtept>
    <rtept lat="8.000" lon="125.001"></rtept>
    <rtept lat="8.001" lon="125.001"></rtept>
  </rte>
</gpx>"""


class GpxParserServiceTests(unittest.TestCase):
    def test_parse_gpx_to_polygon_returns_closed_multipolygon(self):
        result = GpxParserService.parse_gpx_to_polygon(SAMPLE_GPX_TRACK)

        self.assertEqual(result.srid, 4326)
        self.assertTrue(result.data.startswith("MULTIPOLYGON (((125 8,"))
        # Ring must be closed: the first point repeats at the end.
        self.assertTrue(result.data.endswith("125 8)))"))

    def test_parse_gpx_falls_back_to_route_points(self):
        result = GpxParserService.parse_gpx_to_polygon(SAMPLE_GPX_ROUTE_ONLY)

        self.assertTrue(result.data.startswith("MULTIPOLYGON"))

    def test_parse_gpx_too_few_points_raises_value_error(self):
        with self.assertRaises(ValueError):
            GpxParserService.parse_gpx_to_polygon(SAMPLE_GPX_TOO_FEW_POINTS)


if __name__ == "__main__":
    unittest.main()
