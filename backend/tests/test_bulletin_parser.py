import unittest
from unittest.mock import patch, MagicMock
from app.services.bulletin_parser import BulletinParserService
from app.models.models import Typhoon, TropicalCycloneBulletin, TcbSignal, AdminBoundary

class BulletinParserTests(unittest.TestCase):
    @patch("pdfplumber.open")
    def test_parse_bulletin_text_extracts_correct_metadata(self, mock_pdf_open):
        # Create a mock PDF structure containing text
        mock_page = MagicMock()
        mock_page.extract_text.return_value = """
        Tropical Cyclone Bulletin No. 5
        TYPHOON "LEON"
        maximum sustained winds of 155 km/h
        gustiness of up to 190 km/h
        at 16.2°N, 123.5°E

        SIGNAL NO. 3
        Luzon:
        Batanes

        SIGNAL NO. 2
        Mindanao:
        The northern portion of Bukidnon (Talakag), Misamis Oriental (Claveria)
        """
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf_open.return_value.__enter__.return_value = mock_pdf

        # Run the parser on a mock path
        result = BulletinParserService.parse_bulletin_text("dummy_path.pdf")

        # Assert correct metadata parsing
        self.assertEqual(result["typhoon_name"], "LEON")
        self.assertEqual(result["bulletin_count"], 5)
        self.assertEqual(result["category"], "Typhoon")
        self.assertEqual(result["max_sustained_winds"], 155)
        self.assertEqual(result["gustiness"], 190)
        self.assertEqual(result["latitude"], 16.2)
        self.assertEqual(result["longitude"], 123.5)

        # Assert signal block segmentation
        self.assertIn(3, result["signals"])
        self.assertIn(2, result["signals"])
        self.assertIn("Batanes", result["signals"][3])
        self.assertIn("Talakag", result["signals"][2])

    def test_parse_bulletin_text_extracts_issued_at(self):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = (
            "Tropical Cyclone Bulletin No. 5\n"
            "TYPHOON \"LEON\"\n"
            "Issued at 5:00 PM, 15 October 2024\n"
        )
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]

        with patch("pdfplumber.open") as mock_pdf_open:
            mock_pdf_open.return_value.__enter__.return_value = mock_pdf
            result = BulletinParserService.parse_bulletin_text("dummy_path.pdf")

        self.assertIsNotNone(result["issued_at"])
        self.assertEqual(result["issued_at"].year, 2024)
        self.assertEqual(result["issued_at"].month, 10)
        self.assertEqual(result["issued_at"].day, 15)
        self.assertEqual(result["issued_at"].hour, 17)

    def test_parse_bulletin_text_issued_at_missing_defaults_to_none(self):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Tropical Cyclone Bulletin No. 5\nTYPHOON \"LEON\"\n"
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]

        with patch("pdfplumber.open") as mock_pdf_open:
            mock_pdf_open.return_value.__enter__.return_value = mock_pdf
            result = BulletinParserService.parse_bulletin_text("dummy_path.pdf")

        self.assertIsNone(result["issued_at"])


class BulletinParserSaveToDbTests(unittest.TestCase):
    def _build_mock_db(self, boundaries):
        """Dispatches db.query(Model) to a per-model mock so typhoon/bulletin/boundary
        lookups don't collide on the same MagicMock return chain."""
        mock_db = MagicMock()

        typhoon_query = MagicMock()
        typhoon_query.filter.return_value.first.return_value = None

        bulletin_query = MagicMock()
        bulletin_query.filter.return_value.first.return_value = None

        admin_query = MagicMock()
        admin_query.all.return_value = boundaries

        def query_side_effect(model):
            if model is Typhoon:
                return typhoon_query
            if model is TropicalCycloneBulletin:
                return bulletin_query
            if model is AdminBoundary:
                return admin_query
            raise AssertionError(f"Unexpected model queried in test: {model}")

        mock_db.query.side_effect = query_side_effect

        def refresh_side_effect(obj):
            if isinstance(obj, Typhoon):
                obj.typhoon_id = 1
            elif isinstance(obj, TropicalCycloneBulletin):
                obj.tcb_id = 100

        mock_db.refresh.side_effect = refresh_side_effect
        return mock_db

    def test_save_bulletin_to_db_creates_bulletin_and_signals(self):
        # Regression test for the missing `sqlalchemy.func` import, which made this
        # method raise NameError on every call before the fix.
        boundary = MagicMock()
        boundary.province = "Misamis Oriental"
        boundary.municipality = "Claveria"

        mock_db = self._build_mock_db(boundaries=[boundary])
        created_objects = []
        mock_db.add.side_effect = created_objects.append

        parsed_data = {
            "typhoon_name": "LEON",
            "bulletin_count": 5,
            "category": "Typhoon",
            "max_sustained_winds": 155,
            "gustiness": 190,
            "latitude": 16.2,
            "longitude": 123.5,
            "issued_at": None,
            "signals": {
                2: "SIGNAL NO. 2\nMindanao:\nThe northern portion of Misamis Oriental (Claveria)",
            },
            "raw_text": "",
        }

        result = BulletinParserService.save_bulletin_to_db(parsed_data, mock_db)

        self.assertEqual(result.tcb_id, 100)
        self.assertEqual(result.title, "Bulletin No. 5 for LEON")

        signal_rows = [obj for obj in created_objects if isinstance(obj, TcbSignal)]
        self.assertEqual(len(signal_rows), 1)
        self.assertEqual(signal_rows[0].area_name, "Claveria")
        self.assertEqual(signal_rows[0].signal_level, 2)


if __name__ == "__main__":
    unittest.main()
