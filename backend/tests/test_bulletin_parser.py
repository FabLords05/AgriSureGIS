import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock
from app.services.bulletin_parser import BulletinParserService
from app.models.models import Typhoon, TropicalCycloneBulletin, TcbSignal, AdminBoundary

REAL_SAMPLE_PDF = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "TCB#11_kiyapo.pdf")


def _mock_pdf(text, tables=None):
    """Builds a fake pdfplumber.open(...) context manager with one page."""
    mock_page = MagicMock()
    mock_page.extract_text.return_value = text
    mock_page.extract_tables.return_value = tables or []
    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page]
    return mock_pdf


class BulletinParserTests(unittest.TestCase):
    @patch("pdfplumber.open")
    def test_parse_bulletin_text_extracts_correct_metadata(self, mock_pdf_open):
        text = (
            "Tropical Cyclone Bulletin No. 5\n"
            "TYPHOON \"LEON\"\n"
            "maximum sustained winds of 155 km/h\n"
            "gustiness of up to 190 km/h\n"
            "at 16.2°N, 123.5°E\n"
        )
        mock_pdf_open.return_value.__enter__.return_value = _mock_pdf(text)

        result = BulletinParserService.parse_bulletin_text("dummy_path.pdf")

        self.assertEqual(result["typhoon_name"], "LEON")
        self.assertEqual(result["bulletin_count"], 5)
        self.assertEqual(result["category"], "Typhoon")
        self.assertEqual(result["max_sustained_winds"], 155)
        self.assertEqual(result["gustiness"], 190)
        self.assertEqual(result["latitude"], 16.2)
        self.assertEqual(result["longitude"], 123.5)
        self.assertEqual(result["signals"], {})  # no TCWS table on this mock page

    def test_parse_bulletin_text_name_does_not_swallow_trailing_issued_at(self):
        # Regression test: when the name isn't quoted in the source PDF, the old
        # [A-Z\s\-]+ capture group ran on through the following word(s), producing
        # names like "GARDO Issued at" instead of "GARDO".
        text = (
            "Tropical Cyclone Bulletin No. 10\n"
            "TYPHOON GARDO Issued at 5:00 PM, 15 October 2024\n"
        )
        with patch("pdfplumber.open") as mock_pdf_open:
            mock_pdf_open.return_value.__enter__.return_value = _mock_pdf(text)
            result = BulletinParserService.parse_bulletin_text("dummy_path.pdf")

        self.assertEqual(result["typhoon_name"], "GARDO")

    def test_parse_bulletin_text_extracts_bulletin_number_with_nr_abbreviation(self):
        # Real bulletins abbreviate to "NR." (e.g. "TROPICAL CYCLONE BULLETIN NR. 11"),
        # not just "No." — confirmed against docs/TCB#11_kiyapo.pdf.
        text = "Tropical Cyclone Bulletin NR. 11\nTROPICAL STORM KIYAPO (NOUL)\n"
        with patch("pdfplumber.open") as mock_pdf_open:
            mock_pdf_open.return_value.__enter__.return_value = _mock_pdf(text)
            result = BulletinParserService.parse_bulletin_text("dummy_path.pdf")

        self.assertEqual(result["bulletin_count"], 11)
        self.assertEqual(result["typhoon_name"], "KIYAPO")
        self.assertEqual(result["international_name"], "NOUL")
        self.assertEqual(result["category"], "Tropical Storm")

    def test_parse_bulletin_text_category_is_not_fooled_by_the_word_elsewhere_in_the_text(self):
        # Regression test: the old category logic was `"Typhoon" if "typhoon" in
        # text.lower() else "Tropical Storm"` — a bare substring check that
        # misfired whenever the word "typhoon" appeared anywhere else in the
        # bulletin's forecast prose (e.g. "may be upgraded... reach typhoon
        # category"), even though the storm's *current* category was something
        # else. Category must come from the title line itself.
        text = (
            "Tropical Cyclone Bulletin No. 11\n"
            "TROPICAL STORM KIYAPO (NOUL)\n"
            "KIYAPO may be upgraded and reach typhoon category before landfall.\n"
        )
        with patch("pdfplumber.open") as mock_pdf_open:
            mock_pdf_open.return_value.__enter__.return_value = _mock_pdf(text)
            result = BulletinParserService.parse_bulletin_text("dummy_path.pdf")

        self.assertEqual(result["category"], "Tropical Storm")

    def test_parse_bulletin_text_extracts_coordinates_with_degree_symbol_and_no_at_prefix(self):
        # Real phrasing has no "at <lat>°N" right next to each other — there's a
        # full clause in between, and the fallback regex used to lack the °
        # symbol entirely, so neither pattern matched real bulletins at all.
        text = (
            "Tropical Cyclone Bulletin No. 11\n"
            "TROPICAL STORM KIYAPO (NOUL)\n"
            "The center of Tropical Storm KIYAPO was estimated based on\n"
            "all available data at over the coastal waters of Camiguin\n"
            "Island, Calayan, Cagayan (18.8°N, 122.0°E).\n"
        )
        with patch("pdfplumber.open") as mock_pdf_open:
            mock_pdf_open.return_value.__enter__.return_value = _mock_pdf(text)
            result = BulletinParserService.parse_bulletin_text("dummy_path.pdf")

        self.assertEqual(result["latitude"], 18.8)
        self.assertEqual(result["longitude"], 122.0)

    def test_parse_bulletin_text_extracts_issued_at(self):
        text = (
            "Tropical Cyclone Bulletin No. 5\n"
            "TYPHOON \"LEON\"\n"
            "Issued at 5:00 PM, 15 October 2024\n"
        )
        with patch("pdfplumber.open") as mock_pdf_open:
            mock_pdf_open.return_value.__enter__.return_value = _mock_pdf(text)
            result = BulletinParserService.parse_bulletin_text("dummy_path.pdf")

        self.assertIsNotNone(result["issued_at"])
        self.assertEqual(result["issued_at"].year, 2024)
        self.assertEqual(result["issued_at"].month, 10)
        self.assertEqual(result["issued_at"].day, 15)
        self.assertEqual(result["issued_at"].hour, 17)

    def test_parse_bulletin_text_issued_at_missing_defaults_to_none(self):
        text = "Tropical Cyclone Bulletin No. 5\nTYPHOON \"LEON\"\n"
        with patch("pdfplumber.open") as mock_pdf_open:
            mock_pdf_open.return_value.__enter__.return_value = _mock_pdf(text)
            result = BulletinParserService.parse_bulletin_text("dummy_path.pdf")

        self.assertIsNone(result["issued_at"])

    def test_parse_bulletin_text_extracts_mindanao_signals_from_table(self):
        # Modeled on docs/TCB#11_kiyapo.pdf's real TCWS table shape: a section
        # title row, a header row (TCWS No. | Luzon | Visayas | Mindanao), then
        # one row per signal level plus a "Warning lead time..." continuation
        # row (first cell blank) that must stay attributed to the same level.
        table = [
            ["TROPICAL CYCLONE WIND SIGNALS (TCWS) IN EFFECT", None, None, None],
            ["TCWS No.", "Luzon", "Visayas", "Mindanao"],
            ["2\nWind threat:\nGale-force\nwinds", "Batanes area text", "-",
             "The northern portion of Bukidnon (Talakag)"],
            [None, "Warning lead time: 24 hours", None, None],
            ["1\nWind threat:\nStrong\nwinds", "Some Luzon area", "-", "-"],
            [None, "Warning lead time: 36 hours", None, None],
        ]
        text = "Tropical Cyclone Bulletin No. 11\nTROPICAL STORM KIYAPO (NOUL)\n"
        with patch("pdfplumber.open") as mock_pdf_open:
            mock_pdf_open.return_value.__enter__.return_value = _mock_pdf(text, tables=[table])
            result = BulletinParserService.parse_bulletin_text("dummy_path.pdf")

        # Only the Mindanao column is extracted (this project is Region X/Mindanao-scoped);
        # Signal 1's Mindanao cell was "-", so it should not appear at all.
        self.assertEqual(set(result["signals"].keys()), {2})
        self.assertIn("Talakag", result["signals"][2])

    def test_parse_bulletin_text_against_real_sample_pdf(self):
        # End-to-end regression test against a real PAGASA bulletin (Tropical
        # Storm KIYAPO, Bulletin NR. 11) provided by Fabio. KIYAPO only affected
        # Luzon, so an empty `signals` dict here is the CORRECT result for this
        # Mindanao-scoped project, not a bug.
        result = BulletinParserService.parse_bulletin_text(REAL_SAMPLE_PDF)

        self.assertEqual(result["typhoon_name"], "KIYAPO")
        self.assertEqual(result["international_name"], "NOUL")
        self.assertEqual(result["bulletin_count"], 11)
        self.assertEqual(result["category"], "Tropical Storm")
        self.assertEqual(result["max_sustained_winds"], 75)
        self.assertEqual(result["gustiness"], 90)
        self.assertEqual(result["latitude"], 18.8)
        self.assertEqual(result["longitude"], 122.0)
        self.assertEqual(result["issued_at"], datetime(2026, 7, 24, 14, 0, tzinfo=timezone.utc))
        self.assertEqual(result["signals"], {})


class BulletinParserSaveToDbTests(unittest.TestCase):
    def _build_mock_db(self, boundaries, existing_typhoon=None):
        """Dispatches db.query(Model) to a per-model mock so typhoon/bulletin/boundary
        lookups don't collide on the same MagicMock return chain. `existing_typhoon`
        controls what the "same typhoon within the last 30 days" join query
        (db.query(Typhoon).join(...).filter(...).order_by(...).first()) returns —
        None means "no match, create a new Typhoon row"."""
        mock_db = MagicMock()

        typhoon_query = MagicMock()
        typhoon_query.join.return_value.filter.return_value.order_by.return_value.first.return_value = existing_typhoon

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

    def test_reuses_existing_typhoon_when_a_bulletin_is_within_30_days(self):
        # Bulletin No. 10 for an already-known typhoon should still land under the
        # same Typhoon row, not spawn a new one — "any bulletin number as long as
        # it can be found in the month."
        existing_typhoon = MagicMock(spec=Typhoon, typhoon_id=7)
        existing_typhoon.name = "GARDO"  # `name=` can't be set via the constructor — it's reserved by Mock itself
        mock_db = self._build_mock_db(boundaries=[], existing_typhoon=existing_typhoon)

        parsed_data = {
            "typhoon_name": "GARDO",
            "bulletin_count": 10,
            "category": "Typhoon",
            "max_sustained_winds": 155,
            "gustiness": 190,
            "latitude": 16.2,
            "longitude": 123.5,
            "issued_at": datetime(2024, 10, 15, 17, 0, tzinfo=timezone.utc),
            "signals": {},
            "raw_text": "",
        }

        BulletinParserService.save_bulletin_to_db(parsed_data, mock_db)

        created_typhoons = [
            call.args[0] for call in mock_db.add.call_args_list if isinstance(call.args[0], Typhoon)
        ]
        self.assertEqual(created_typhoons, [])  # no new Typhoon row created — reused typhoon_id=7

    def test_creates_new_typhoon_when_no_bulletin_within_30_days(self):
        # Same name, but the only existing match is stale (>30 days) — the query
        # itself (filtered to issued_at >= window_start) would return None for
        # this case in a real DB, which _build_mock_db's default already models.
        mock_db = self._build_mock_db(boundaries=[], existing_typhoon=None)

        parsed_data = {
            "typhoon_name": "GARDO",
            "bulletin_count": 1,
            "category": "Typhoon",
            "max_sustained_winds": 155,
            "gustiness": 190,
            "latitude": 16.2,
            "longitude": 123.5,
            "issued_at": datetime(2024, 12, 20, 12, 0, tzinfo=timezone.utc),
            "signals": {},
            "raw_text": "",
        }

        BulletinParserService.save_bulletin_to_db(parsed_data, mock_db)

        created_typhoons = [
            call.args[0] for call in mock_db.add.call_args_list if isinstance(call.args[0], Typhoon)
        ]
        self.assertEqual(len(created_typhoons), 1)
        self.assertEqual(created_typhoons[0].name, "GARDO")
        self.assertEqual(created_typhoons[0].year, 2024)


class ScrapeAndSaveAllTests(unittest.IsolatedAsyncioTestCase):
    """
    Covers `scrape_and_save_all`, the orchestration method extracted from
    `trigger_pagasa_scrape` (backend/app/api/bulletins.py) so both the manual
    POST /api/bulletins/parse route and the new APScheduler background job
    (backend/app/core/scheduler.py) share the same scrape-download-parse-save
    loop. Unlike the HTTP route, this method must never raise on an empty
    result — the scheduled job needs "nothing new" to be a normal, quiet
    outcome, not an error.
    """

    async def test_returns_empty_list_when_no_links_found(self):
        with patch.object(BulletinParserService, "fetch_active_bulletin_links", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = []
            result = await BulletinParserService.scrape_and_save_all(MagicMock())

        self.assertEqual(result, [])

    async def test_skips_failed_link_and_still_processes_the_rest(self):
        with patch.object(BulletinParserService, "fetch_active_bulletin_links", new_callable=AsyncMock) as mock_fetch, \
             patch.object(BulletinParserService, "download_bulletin_pdf", new_callable=AsyncMock) as mock_download, \
             patch.object(BulletinParserService, "parse_bulletin_text") as mock_parse, \
             patch.object(BulletinParserService, "save_bulletin_to_db") as mock_save, \
             patch("os.path.exists", return_value=False):
            mock_fetch.return_value = ["https://pagasa.example/bad.pdf", "https://pagasa.example/good.pdf"]
            mock_download.side_effect = [Exception("download failed"), "temp_bulletins/good.pdf"]
            mock_parse.return_value = {"raw_text": ""}
            saved_bulletin = MagicMock(tcb_id=100, title="Bulletin No. 5 for LEON", bulletin_count=5)
            mock_save.return_value = saved_bulletin

            result = await BulletinParserService.scrape_and_save_all(MagicMock())

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tcb_id"], 100)

    async def test_returns_created_bulletin_dicts_on_happy_path(self):
        with patch.object(BulletinParserService, "fetch_active_bulletin_links", new_callable=AsyncMock) as mock_fetch, \
             patch.object(BulletinParserService, "download_bulletin_pdf", new_callable=AsyncMock) as mock_download, \
             patch.object(BulletinParserService, "parse_bulletin_text") as mock_parse, \
             patch.object(BulletinParserService, "save_bulletin_to_db") as mock_save, \
             patch("os.path.exists", return_value=False):
            mock_fetch.return_value = ["https://pagasa.example/tcb5.pdf"]
            mock_download.return_value = "temp_bulletins/tcb5.pdf"
            mock_parse.return_value = {"raw_text": ""}
            mock_save.return_value = MagicMock(tcb_id=100, title="Bulletin No. 5 for LEON", bulletin_count=5)

            result = await BulletinParserService.scrape_and_save_all(MagicMock())

        self.assertEqual(result, [{"tcb_id": 100, "title": "Bulletin No. 5 for LEON", "bulletin_count": 5}])


if __name__ == "__main__":
    unittest.main()
