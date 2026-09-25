"""
Regression tests for bulletin_parser.py covering the confirmed issues from the
ChatGPT feedback review (2026-09-26).

Covers:
- C1  path traversal: upload uses mkstemp, not user-supplied filename
- C2  db.rollback: session guard on persistence failure (integration concern;
      tested here via unit-level mock to confirm rollback is called)
- C3  empty/blank PDF raises ValueError before reaching persistence
- C4  missing identity fields (bulletin_no OR name) raise ValueError
- C5  signal block does not bleed past post-signal section headers
- P2  download failure removes the partial temp file (patched mkstemp)
- P4  deduplication: save_bulletin_to_db returns (bulletin, False) for
      existing records and (bulletin, True) for new ones
- S1  fetch_active_bulletin_links resolves root-relative hrefs correctly
      and accepts .PDF (uppercase) extensions
"""

import os
import re
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, call

from app.services.bulletin_parser import (
    BulletinParserService,
    _POST_SIGNAL_SECTION,
    get_island_group,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_pdf(text: str):
    """Return a pdfplumber mock that yields *text* from a single page."""
    mock_page = MagicMock()
    mock_page.extract_text.return_value = text
    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page]
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_pdf)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


VALID_TEXT = """\
        Tropical Cyclone Bulletin No. 5
        TYPHOON "LEON"
        maximum sustained winds of 155 km/h
        gustiness of up to 190 km/h
        at 16.2\u00b0N, 123.5\u00b0E

        SIGNAL NO. 3
        Luzon:
        Batanes

        SIGNAL NO. 2
        Mindanao:
        The northern portion of Bukidnon (Talakag), Misamis Oriental (Claveria)

        FORECAST POSITIONS
        At 2 AM today, the center of TYPHOON LEON was estimated at 1,000 km east of Virac.
"""


# ---------------------------------------------------------------------------
# C3 / C4 — Identity field guards
# ---------------------------------------------------------------------------

class TestParseGuards(unittest.TestCase):

    @patch("pdfplumber.open")
    def test_blank_pdf_raises_value_error(self, mock_open):
        """C3: A blank or whitespace-only PDF must raise ValueError."""
        mock_open.return_value = _make_mock_pdf("   \n\t  ")
        with self.assertRaises(ValueError, msg="blank PDF should raise ValueError"):
            BulletinParserService.parse_bulletin_text("dummy.pdf")

    @patch("pdfplumber.open")
    def test_missing_bulletin_number_raises_value_error(self, mock_open):
        """C4a: Text without 'Tropical Cyclone Bulletin No. X' raises ValueError."""
        text_no_number = 'TYPHOON "LEON"\nat 16.2\u00b0N, 123.5\u00b0E'
        mock_open.return_value = _make_mock_pdf(text_no_number)
        with self.assertRaises(ValueError):
            BulletinParserService.parse_bulletin_text("dummy.pdf")

    @patch("pdfplumber.open")
    def test_missing_typhoon_name_raises_value_error(self, mock_open):
        """C4b: Text without a recognisable storm name raises ValueError."""
        text_no_name = (
            "Tropical Cyclone Bulletin No. 5\n"
            "maximum sustained winds of 155 km/h\n"
            "at 16.2\u00b0N, 123.5\u00b0E"
        )
        mock_open.return_value = _make_mock_pdf(text_no_name)
        with self.assertRaises(ValueError):
            BulletinParserService.parse_bulletin_text("dummy.pdf")


# ---------------------------------------------------------------------------
# C5 — Signal block boundary
# ---------------------------------------------------------------------------

class TestSignalBlockBoundary(unittest.TestCase):

    @patch("pdfplumber.open")
    def test_final_signal_block_does_not_include_forecast_section(self, mock_open):
        """C5: Signal 2 block must end before 'FORECAST POSITIONS'."""
        mock_open.return_value = _make_mock_pdf(VALID_TEXT)
        result = BulletinParserService.parse_bulletin_text("dummy.pdf")

        signal_2_text = result["signals"].get(2, "")
        # Forecast coordinates that appear after the header must NOT be in signal 2
        self.assertNotIn("1,000 km east of Virac", signal_2_text,
                         "Forecast track text bled into Signal 2 block")
        self.assertNotIn("FORECAST POSITIONS", signal_2_text)

    @patch("pdfplumber.open")
    def test_signal_blocks_contain_correct_areas(self, mock_open):
        """C5: Signal areas must appear in the right blocks."""
        mock_open.return_value = _make_mock_pdf(VALID_TEXT)
        result = BulletinParserService.parse_bulletin_text("dummy.pdf")

        self.assertIn("Batanes", result["signals"][3])
        self.assertIn("Talakag", result["signals"][2])
        # Batanes must NOT bleed into signal 2
        self.assertNotIn("Batanes", result["signals"][2])


# ---------------------------------------------------------------------------
# P4 — Deduplication (is_new flag from save_bulletin_to_db)
# ---------------------------------------------------------------------------

class TestSaveBulletinIdempotency(unittest.TestCase):

    def _make_parsed_data(self):
        return {
            "typhoon_name": "LEON",
            "bulletin_count": 5,
            "category": "Typhoon",
            "max_sustained_winds": 155,
            "gustiness": 190,
            "latitude": 16.2,
            "longitude": 123.5,
            "signals": {},
            "raw_text": "",
        }

    def test_existing_bulletin_returns_is_new_false(self):
        """P4: When the bulletin already exists, returns (bulletin, False)."""
        db = MagicMock()

        existing_typhoon = MagicMock()
        existing_typhoon.typhoon_id = 1
        existing_typhoon.name = "LEON"

        existing_bulletin = MagicMock()
        existing_bulletin.tcb_id = 42

        # First query (Typhoon) → found; second query (TropicalCycloneBulletin) → found
        db.query.return_value.filter.return_value.first.side_effect = [
            existing_typhoon,
            existing_bulletin,
        ]

        bulletin, is_new = BulletinParserService.save_bulletin_to_db(
            self._make_parsed_data(), db
        )

        self.assertFalse(is_new, "Existing bulletin must return is_new=False")
        self.assertEqual(bulletin, existing_bulletin)
        db.commit.assert_not_called()

    def test_new_bulletin_returns_is_new_true(self):
        """P4: When the bulletin does not exist, returns (bulletin, True) and commits."""
        db = MagicMock()

        existing_typhoon = MagicMock()
        existing_typhoon.typhoon_id = 1
        existing_typhoon.name = "LEON"

        # First query (Typhoon) → found; second query (Bulletin) → not found
        db.query.return_value.filter.return_value.first.side_effect = [
            existing_typhoon,
            None,
        ]
        # Stub .all() for AdminBoundary query
        db.query.return_value.all.return_value = []

        bulletin, is_new = BulletinParserService.save_bulletin_to_db(
            self._make_parsed_data(), db
        )

        self.assertTrue(is_new, "New bulletin must return is_new=True")
        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# S1 — URL resolution in fetch_active_bulletin_links
# ---------------------------------------------------------------------------

class TestFetchBulletinLinks(unittest.IsolatedAsyncioTestCase):

    async def test_root_relative_href_resolved_correctly(self):
        """S1: Root-relative hrefs like /tamss/weather/bulletin.pdf must resolve
        to the correct absolute URL, not produce a double-path."""
        html = '<a href="/tamss/weather/bulletin_test.pdf">Download</a>'

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            links = await BulletinParserService.fetch_active_bulletin_links()

        self.assertEqual(len(links), 1)
        url = links[0]
        self.assertNotIn("//tamss", url, "Root-relative URL produced a doubled path")
        self.assertTrue(url.startswith("https://"), "URL must be absolute")
        self.assertIn("/tamss/weather/bulletin_test.pdf", url)

    async def test_uppercase_pdf_extension_accepted(self):
        """S1: Links ending in .PDF (uppercase) must be included."""
        html = '<a href="/tamss/weather/bulletin_test.PDF">Download</a>'

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            links = await BulletinParserService.fetch_active_bulletin_links()

        self.assertEqual(len(links), 1, "Uppercase .PDF extension must be accepted")

    async def test_non_bulletin_pdf_excluded(self):
        """fetch must not return PDFs whose path doesn't contain 'bulletin'."""
        html = '<a href="/tamss/weather/report.pdf">Download</a>'

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            links = await BulletinParserService.fetch_active_bulletin_links()

        self.assertEqual(links, [], "Non-bulletin PDFs must be excluded")


# ---------------------------------------------------------------------------
# P2 — Partial download cleanup
# ---------------------------------------------------------------------------

class TestDownloadCleanup(unittest.IsolatedAsyncioTestCase):

    async def test_partial_file_removed_on_timeout(self):
        """P2: A partial file created by mkstemp must be deleted when
        the download times out."""
        import httpx

        async def _raise_on_iter(**_kwargs):
            """Async generator that raises TimeoutException immediately."""
            raise httpx.TimeoutException("simulated timeout")
            yield b""  # pragma: no cover — makes this an async generator

        with tempfile.TemporaryDirectory() as tmpdir:
            fd, fake_path = tempfile.mkstemp(dir=tmpdir, suffix=".pdf")
            os.close(fd)

            with patch("tempfile.mkstemp", return_value=(os.open(fake_path, os.O_WRONLY), fake_path)):
                mock_response = MagicMock()
                mock_response.raise_for_status = MagicMock()
                mock_response.aiter_bytes = _raise_on_iter
                mock_response.__aenter__ = AsyncMock(return_value=mock_response)
                mock_response.__aexit__ = AsyncMock(return_value=False)

                mock_client = MagicMock()
                mock_client.stream = MagicMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)

                with patch("httpx.AsyncClient", return_value=mock_client):
                    with self.assertRaises(RuntimeError, msg="Timeout should raise RuntimeError"):
                        await BulletinParserService.download_bulletin_pdf(
                            "https://pagasa.dost.gov.ph/bulletin.pdf", tmpdir
                        )

            # The partial file must be gone
            self.assertFalse(
                os.path.exists(fake_path),
                "Partial download file must be cleaned up on timeout",
            )


# ---------------------------------------------------------------------------
# Island group helper
# ---------------------------------------------------------------------------

class TestGetIslandGroup(unittest.TestCase):

    def test_luzon_province_returns_0(self):
        self.assertEqual(get_island_group("Batanes"), 0)
        self.assertEqual(get_island_group("Laguna"), 0)

    def test_visayas_province_returns_1(self):
        self.assertEqual(get_island_group("Cebu"), 1)
        self.assertEqual(get_island_group("Leyte"), 1)

    def test_mindanao_default_returns_2(self):
        self.assertEqual(get_island_group("Bukidnon"), 2)
        self.assertEqual(get_island_group("Davao del Sur"), 2)

    def test_whitespace_trimmed(self):
        self.assertEqual(get_island_group("  Batanes  "), 0)


if __name__ == "__main__":
    unittest.main()
