import io
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.api.upload import upload_gpx
from app.services.gpx_farmer_matcher import GpxMatchResult

SAMPLE_GPX = """<?xml version="1.0" encoding="UTF-8"?>
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


def _fake_gpx_file(filename="TAB_ABAO , JONEL  J._120961_1148107_2024-08-06.gpx"):
    return SimpleNamespace(filename=filename, file=io.BytesIO(SAMPLE_GPX.encode("utf-8")))


class UploadGpxApiTests(unittest.TestCase):
    @patch("app.api.upload.GpxFarmerMatcherService.match")
    def test_auto_detect_success_returns_matched_by_and_farmer_name(self, mock_match):
        farmer = MagicMock(first_name="Jonel", last_name="Abao")
        farm = MagicMock(farm_id=42, farmer=farmer)
        mock_match.return_value = GpxMatchResult(farm=farm, farmer=farmer, matched_by="farmers_id")
        mock_db = MagicMock()

        result = upload_gpx(file=_fake_gpx_file(), farmer_id=None, farm_id=None, db=mock_db)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["farm_id"], 42)
        self.assertEqual(result["matched_by"], "farmers_id")
        self.assertEqual(result["farmer_name"], "Jonel Abao")
        mock_db.commit.assert_called_once()

    @patch("app.api.upload.GpxFarmerMatcherService.match")
    def test_auto_detect_no_match_raises_404(self, mock_match):
        # Mirrors the real, confirmed case where the sample GPX matches nothing.
        mock_match.return_value = GpxMatchResult()
        mock_db = MagicMock()

        with self.assertRaises(HTTPException) as ctx:
            upload_gpx(file=_fake_gpx_file(), farmer_id=None, farm_id=None, db=mock_db)
        self.assertEqual(ctx.exception.status_code, 404)

    @patch("app.api.upload.GpxFarmerMatcherService.match")
    def test_auto_detect_ambiguous_match_raises_400(self, mock_match):
        mock_match.return_value = GpxMatchResult(candidates=[MagicMock(), MagicMock()])
        mock_db = MagicMock()

        with self.assertRaises(HTTPException) as ctx:
            upload_gpx(file=_fake_gpx_file(), farmer_id=None, farm_id=None, db=mock_db)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_manual_mode_with_both_ids_is_unchanged(self):
        farm = MagicMock(farm_id=7, farmer=MagicMock(first_name="Ana", last_name="Cruz"))
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = farm

        result = upload_gpx(file=_fake_gpx_file(), farmer_id=1, farm_id=7, db=mock_db)

        self.assertEqual(result["farm_id"], 7)
        self.assertEqual(result["matched_by"], "manual")

    def test_manual_mode_farm_not_found_raises_404(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with self.assertRaises(HTTPException) as ctx:
            upload_gpx(file=_fake_gpx_file(), farmer_id=1, farm_id=7, db=mock_db)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_exactly_one_id_provided_raises_400(self):
        mock_db = MagicMock()

        with self.assertRaises(HTTPException) as ctx:
            upload_gpx(file=_fake_gpx_file(), farmer_id=1, farm_id=None, db=mock_db)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_non_gpx_filename_rejected(self):
        mock_db = MagicMock()

        with self.assertRaises(HTTPException) as ctx:
            upload_gpx(file=_fake_gpx_file(filename="not_a_gpx.txt"), farmer_id=None, farm_id=None, db=mock_db)
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
