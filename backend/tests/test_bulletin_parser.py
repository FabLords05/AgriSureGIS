import unittest
from unittest.mock import patch, MagicMock
from app.services.bulletin_parser import BulletinParserService

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

if __name__ == "__main__":
    unittest.main()
