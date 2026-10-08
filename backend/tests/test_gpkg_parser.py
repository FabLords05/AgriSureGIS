import os
import sqlite3
import struct
import tempfile
import unittest

import shapely
from shapely.geometry import MultiPolygon, Polygon

from app.services.gpkg_parser import GpkgParserService, _gpkg_blob_to_geometry
from app.services.gpx_farmer_matcher import GpxFarmerMatcherService

LAYER = "farm_boundaries"

SQUARE = Polygon([(125.000, 8.000), (125.001, 8.000), (125.001, 8.001), (125.000, 8.001)])
SQUARE_2 = Polygon([(125.010, 8.010), (125.011, 8.010), (125.011, 8.011), (125.010, 8.011)])


def _gpkg_blob(geometry, srs_id=4326) -> bytes:
    """GeoPackageBinary with an XY envelope (envelope type 1) -- the same header
    layout as every feature in the client's real file."""
    flags = 0b0000_0011  # little-endian header, envelope type 1
    minx, miny, maxx, maxy = geometry.bounds
    header = b"GP" + bytes([0, flags]) + struct.pack("<i", srs_id) + struct.pack("<4d", minx, maxx, miny, maxy)
    return header + shapely.to_wkb(geometry)


def _build_gpkg(path, rows, srs_id=4326):
    """rows: (fid, file_name, farmers_id, farm_id, farmer_name, geometry_or_blob)."""
    conn = sqlite3.connect(path)
    conn.executescript(
        f"""
        CREATE TABLE gpkg_spatial_ref_sys (srs_id INTEGER PRIMARY KEY, organization TEXT, organization_coordsys_id INTEGER);
        CREATE TABLE gpkg_contents (table_name TEXT PRIMARY KEY, data_type TEXT);
        CREATE TABLE gpkg_geometry_columns (table_name TEXT, column_name TEXT, srs_id INTEGER);
        CREATE TABLE {LAYER} (fid INTEGER PRIMARY KEY, geom BLOB, file_name TEXT,
                              FARMERSID TEXT, FARMID TEXT, "FARMER NAME" TEXT);
        """
    )
    conn.execute("INSERT INTO gpkg_spatial_ref_sys VALUES (?, 'EPSG', ?)", (srs_id, srs_id))
    conn.execute("INSERT INTO gpkg_contents VALUES (?, 'features')", (LAYER,))
    conn.execute("INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', ?)", (LAYER, srs_id))
    for fid, file_name, farmers_id, farm_id, farmer_name, geometry in rows:
        blob = geometry if isinstance(geometry, bytes) else _gpkg_blob(geometry, srs_id)
        conn.execute(
            f"INSERT INTO {LAYER} VALUES (?, ?, ?, ?, ?, ?)",
            (fid, blob, file_name, farmers_id, farm_id, farmer_name),
        )
    conn.commit()
    conn.close()


class GpkgParserServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        # Space in the name on purpose -- the client's real file name has spaces.
        self.path = os.path.join(self.tmpdir.name, "PCICX GPX test.gpkg")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_reads_polygon_and_multipolygon_features_as_multipolygon(self):
        _build_gpkg(self.path, [
            (1, "FAM10_ABARICO, REPARADA C._192875_957361_2024-01-29.gpx", "192875", "957361",
             "ABARICO, REPARADA C.", SQUARE),
            (2, "FAM10_ALORRO, EMY E._442277_1079599_2024-02-01.gpx", "442277", "1079599",
             "ALORRO, EMY  E.", MultiPolygon([SQUARE, SQUARE_2])),
        ])

        features = GpkgParserService.parse_gpkg_features(self.path)

        self.assertEqual([f.farm_reference for f in features], ["957361", "1079599"])
        self.assertEqual(features[0].farmers_id, "192875")
        polygon_geom = features[0].to_location_geom()
        multi_geom = features[1].to_location_geom()
        self.assertEqual(polygon_geom.srid, 4326)
        self.assertTrue(polygon_geom.data.startswith("MULTIPOLYGON"))
        self.assertEqual(len(shapely.from_wkt(multi_geom.data).geoms), 2)

    def test_to_match_input_uses_attributes(self):
        _build_gpkg(self.path, [
            (1, "x.gpx", "192875", "957361", "ABARICO, REPARADA C.", SQUARE),
        ])

        parsed = GpkgParserService.parse_gpkg_features(self.path)[0].to_match_input()

        self.assertEqual(parsed.id1, "192875")
        self.assertEqual(parsed.id2, "957361")
        self.assertEqual(parsed.last_name, "ABARICO")
        self.assertEqual(parsed.first_name, "REPARADA")
        self.assertEqual(parsed.middle_initial, "C")

    def test_dedupe_keeps_latest_walk_date_across_date_formats(self):
        _build_gpkg(self.path, [
            # Later fid, but older walk -- must lose to fid 1's 2025-8-29 walk.
            (1, "GE_ESMERALDA GAERLIE O_171071_1252499_2025-8-29.gpx", "171071", "1252499", None, SQUARE),
            (2, "TAB_ESMERALDA, GAERLIE O._171071_1252499_2024-12-05.gpx", "171071", "1252499", None, SQUARE_2),
            (3, "TAB_OTHER, FARM A._1_555_2024-01-01.gpx", "1", "555", None, SQUARE),
        ])

        kept, skipped = GpkgParserService.dedupe_by_farm_reference(
            GpkgParserService.parse_gpkg_features(self.path)
        )

        self.assertEqual([f.fid for f in kept], [1, 3])
        self.assertEqual([f.fid for f in skipped], [2])

    def test_dedupe_exact_copies_keeps_later_feature(self):
        _build_gpkg(self.path, [
            (1, "TAB_BASLAN, MA. ROSITA M._15521_1142926_2024-02-01.gpx", "15521", "1142926", None, SQUARE),
            (2, "TAB_BASLAN, MA. ROSITA M._15521_1142926_2024-02-01_b4ce0a.gpx", "15521", "1142926", None, SQUARE),
        ])

        kept, skipped = GpkgParserService.dedupe_by_farm_reference(
            GpkgParserService.parse_gpkg_features(self.path)
        )

        self.assertEqual([f.fid for f in kept], [2])
        self.assertEqual([f.fid for f in skipped], [1])

    def test_non_wgs84_layer_rejected(self):
        _build_gpkg(self.path, [(1, "x.gpx", "1", "2", None, SQUARE)], srs_id=3857)

        with self.assertRaises(ValueError):
            GpkgParserService.parse_gpkg_features(self.path)

    def test_non_geopackage_file_rejected(self):
        with open(self.path, "wb") as fh:
            fh.write(b"this is not a sqlite database at all")

        with self.assertRaises(ValueError):
            GpkgParserService.parse_gpkg_features(self.path)

    def test_bad_geometry_fails_only_that_feature(self):
        _build_gpkg(self.path, [
            (1, "good.gpx", "1", "10", None, SQUARE),
            (2, "bad.gpx", "2", "20", None, b"XX not a gpkg blob"),
        ])

        good, bad = GpkgParserService.parse_gpkg_features(self.path)

        self.assertTrue(good.to_location_geom().data.startswith("MULTIPOLYGON"))
        with self.assertRaises(ValueError):
            bad.to_location_geom()

    def test_blob_without_envelope_decodes(self):
        blob = b"GP" + bytes([0, 0b0000_0001]) + struct.pack("<i", 4326) + shapely.to_wkb(SQUARE)

        self.assertTrue(_gpkg_blob_to_geometry(blob).equals(SQUARE))


class ParseFarmerNameTests(unittest.TestCase):
    def test_splits_last_first_middle_initial(self):
        self.assertEqual(
            GpxFarmerMatcherService.parse_farmer_name("ALORRO, EMY  E."),
            ("ALORRO", "EMY", "E"),
        )

    def test_name_without_comma_yields_nothing(self):
        self.assertEqual(GpxFarmerMatcherService.parse_farmer_name("ESMERALDA GAERLIE O"), (None, None, None))


if __name__ == "__main__":
    unittest.main()
