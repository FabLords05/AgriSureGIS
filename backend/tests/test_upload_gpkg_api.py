import io
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.api.upload import upload_gpkg
from app.services.gpkg_parser import GpkgFeature
from app.services.gpx_farmer_matcher import GpxMatchResult


def _fake_gpkg_file(filename="PCICX GPX_EXISTING IC AFFECTED BY TY TINO_11-05-2025.gpkg"):
    return SimpleNamespace(filename=filename, file=io.BytesIO(b"stub -- parser is patched"))


def _feature(fid, farm_reference, file_name=None):
    return GpkgFeature(
        fid=fid,
        file_name=file_name or f"TAB_FARMER, A._{fid}_{farm_reference}_2024-01-01.gpx",
        farmers_id=str(fid),
        farm_reference=farm_reference,
        farmer_name="FARMER, A.",
        geom_blob=None,
    )


@patch("app.api.upload.invalidate_farms_cache")
@patch.object(GpkgFeature, "to_location_geom", return_value="GEOM")
@patch("app.api.upload.GpkgParserService.parse_gpkg_features")
@patch("app.api.upload.GpxFarmerMatcherService.match_parsed")
class UploadGpkgApiTests(unittest.TestCase):
    def test_updates_every_matched_feature(self, mock_match, mock_parse, _geom, _cache):
        farm_a, farm_b = MagicMock(farm_id=1), MagicMock(farm_id=2)
        mock_parse.return_value = [_feature(1, "100"), _feature(2, "200")]
        mock_match.side_effect = [GpxMatchResult(farm=farm_a), GpxMatchResult(farm=farm_b)]
        mock_db = MagicMock()

        result = upload_gpkg(file=_fake_gpkg_file(), db=mock_db)

        self.assertEqual(result["features_updated"], 2)
        self.assertEqual(result["features_failed"], 0)
        self.assertEqual(farm_a.location_geom, "GEOM")
        self.assertEqual(farm_b.location_geom, "GEOM")
        mock_db.commit.assert_called_once()

    def test_unmatched_feature_is_reported_not_fatal(self, mock_match, mock_parse, _geom, _cache):
        farm_a = MagicMock(farm_id=1)
        mock_parse.return_value = [_feature(1, "100"), _feature(2, "200")]
        mock_match.side_effect = [GpxMatchResult(farm=farm_a), GpxMatchResult()]
        mock_db = MagicMock()

        result = upload_gpkg(file=_fake_gpkg_file(), db=mock_db)

        self.assertEqual(result["features_updated"], 1)
        self.assertEqual(result["features_failed"], 1)
        self.assertEqual(result["failures"][0]["farm_reference"], "200")
        mock_db.begin_nested.return_value.rollback.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_two_features_on_same_farm_second_is_rejected(self, mock_match, mock_parse, _geom, _cache):
        farm = MagicMock(farm_id=1)
        mock_parse.return_value = [_feature(1, "100"), _feature(2, "200")]
        mock_match.side_effect = [GpxMatchResult(farm=farm), GpxMatchResult(farm=farm)]

        result = upload_gpkg(file=_fake_gpkg_file(), db=MagicMock())

        self.assertEqual(result["features_updated"], 1)
        self.assertEqual(result["features_failed"], 1)
        self.assertIn("already updated", result["failures"][0]["error"])

    def test_older_duplicate_walk_is_skipped(self, mock_match, mock_parse, _geom, _cache):
        newer = _feature(1, "100", file_name="TAB_X, A._1_100_2025-02-20.gpx")
        older = _feature(2, "100", file_name="TAB_X, A._1_100_2024-09-18.gpx")
        mock_parse.return_value = [newer, older]
        mock_match.return_value = GpxMatchResult(farm=MagicMock(farm_id=1))

        result = upload_gpkg(file=_fake_gpkg_file(), db=MagicMock())

        self.assertEqual(result["features_updated"], 1)
        self.assertEqual(result["duplicates_skipped"], 1)
        self.assertEqual(mock_match.call_count, 1)

    def test_unreadable_geopackage_raises_400(self, mock_match, mock_parse, _geom, _cache):
        mock_parse.side_effect = ValueError("File is not a valid GeoPackage.")

        with self.assertRaises(HTTPException) as ctx:
            upload_gpkg(file=_fake_gpkg_file(), db=MagicMock())
        self.assertEqual(ctx.exception.status_code, 400)

    def test_non_gpkg_filename_rejected(self, mock_match, mock_parse, _geom, _cache):
        with self.assertRaises(HTTPException) as ctx:
            upload_gpkg(file=_fake_gpkg_file(filename="boundaries.gpx"), db=MagicMock())
        self.assertEqual(ctx.exception.status_code, 400)
        mock_parse.assert_not_called()


if __name__ == "__main__":
    unittest.main()
