import os
import tempfile
import unittest
import httpx
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock
from app.services.bulletin_parser import PHT, BulletinParserService, PagasaScrapeError, match_tcws_cell
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
        self.assertFalse(result["no_signal_hoisted"])  # and no explicit "no signal" statement either

    def test_parse_bulletin_text_detects_no_wind_signal_hoisted(self):
        # Wording from the real TCB#11_pilandok.pdf (storm 1,105 km east of
        # Extreme Northern Luzon, 2026-09-01).
        text = (
            "TROPICAL CYCLONE BULLETIN NR. 11\n"
            "Tropical Storm PILANDOK (KROVANH)\n"
            "TROPICAL CYCLONE WIND SIGNALS (TCWS) IN EFFECT\n"
            "No Wind Signal is currently hoisted\n"
        )
        with patch("pdfplumber.open") as mock_pdf_open:
            mock_pdf_open.return_value.__enter__.return_value = _mock_pdf(text)
            result = BulletinParserService.parse_bulletin_text("dummy_path.pdf")

        self.assertTrue(result["no_signal_hoisted"])
        self.assertEqual(result["signals"], {})

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
        self.assertFalse(result["is_final"])

    def test_parse_bulletin_text_detects_final_bulletin_marker(self):
        # PAGASA appends a trailing "F" to the bulletin number on a typhoon's
        # last bulletin (e.g. "NR. 21F" for Francisco) — the actual, confirmed
        # signal that no more bulletins will follow.
        text = "Tropical Cyclone Bulletin NR. 21F\nTROPICAL STORM FRANCISCO\n"
        with patch("pdfplumber.open") as mock_pdf_open:
            mock_pdf_open.return_value.__enter__.return_value = _mock_pdf(text)
            result = BulletinParserService.parse_bulletin_text("dummy_path.pdf")

        self.assertEqual(result["bulletin_count"], 21)
        self.assertTrue(result["is_final"])

    def test_parse_bulletin_text_extracts_super_typhoon_category(self):
        # "SUPER TYPHOON" is a real PAGASA category (above Typhoon) that was
        # missing from the category alternation entirely -- would previously
        # fall through to a literal "UNKNOWN" typhoon/category.
        text = "Tropical Cyclone Bulletin NR. 8\nSUPER TYPHOON LUIS\n"
        with patch("pdfplumber.open") as mock_pdf_open:
            mock_pdf_open.return_value.__enter__.return_value = _mock_pdf(text)
            result = BulletinParserService.parse_bulletin_text("dummy_path.pdf")

        self.assertEqual(result["category"], "Super Typhoon")
        self.assertEqual(result["typhoon_name"], "LUIS")

    def test_parse_bulletin_text_recognizes_low_pressure_area_formerly_title(self):
        # Regression test: a storm's final bulletin can be titled "Low
        # Pressure Area (formerly "NAME")" once it weakens below tropical
        # depression strength -- confirmed against a live PAGASA bulletin
        # (TCB#13_luis.pdf, NR. 13F). This didn't match any of the
        # TYPHOON/TROPICAL STORM/etc. categories at all, so it used to fall
        # back to a literal "UNKNOWN" typhoon name, silently forking LUIS's
        # final bulletin onto a fake shared "UNKNOWN" Typhoon row instead of
        # reuniting with the real one.
        #
        # Uses real Unicode smart quotes (“/”), not straight ASCII
        # quotes -- `pdftotext` on the actual PDF confirmed PAGASA renders
        # curly quotes here, which an ["']? character class does not match at
        # all (a first version of this fix used straight quotes and still
        # silently failed against the real bulletin).
        text = (
            "Tropical Cyclone Bulletin NR. 13F\n"
            "Low Pressure Area (formerly “LUIS”)\n"
            "Issued at 11:00 PM, 03 August 2026\n"
        )
        with patch("pdfplumber.open") as mock_pdf_open:
            mock_pdf_open.return_value.__enter__.return_value = _mock_pdf(text)
            result = BulletinParserService.parse_bulletin_text("dummy_path.pdf")

        self.assertEqual(result["typhoon_name"], "LUIS")
        self.assertEqual(result["category"], "Low Pressure Area")
        self.assertTrue(result["is_final"])

    def test_parse_bulletin_text_recognizes_low_pressure_area_with_straight_quotes(self):
        # Same as above but with straight ASCII quotes, in case a future PDF
        # (or a different PAGASA export tool) uses them instead of curly ones.
        text = (
            'Tropical Cyclone Bulletin NR. 13F\n'
            'Low Pressure Area (formerly "LUIS")\n'
            "Issued at 11:00 PM, 03 August 2026\n"
        )
        with patch("pdfplumber.open") as mock_pdf_open:
            mock_pdf_open.return_value.__enter__.return_value = _mock_pdf(text)
            result = BulletinParserService.parse_bulletin_text("dummy_path.pdf")

        self.assertEqual(result["typhoon_name"], "LUIS")
        self.assertEqual(result["category"], "Low Pressure Area")

    def test_parse_bulletin_text_low_pressure_area_is_final_even_without_f_suffix(self):
        # A storm that weakened into an LPA gets no further TCBs, so its LPA
        # bulletin must be marked final even if PAGASA omits the "F" suffix.
        text = (
            "Tropical Cyclone Bulletin NR. 13\n"
            "Low Pressure Area (formerly “LUIS”)\n"
            "Issued at 11:00 PM, 03 August 2026\n"
        )
        with patch("pdfplumber.open") as mock_pdf_open:
            mock_pdf_open.return_value.__enter__.return_value = _mock_pdf(text)
            result = BulletinParserService.parse_bulletin_text("dummy_path.pdf")

        self.assertEqual(result["typhoon_name"], "LUIS")
        self.assertEqual(result["bulletin_count"], 13)
        self.assertTrue(result["is_final"])

    def test_parse_bulletin_text_unrecognized_title_still_falls_back_to_unknown(self):
        # Neither a recognized category nor the LPA-formerly pattern -- the
        # UNKNOWN fallback must still exist for genuinely unparseable titles.
        text = "Tropical Cyclone Bulletin NR. 1\nSOMETHING ELSE ENTIRELY\n"
        with patch("pdfplumber.open") as mock_pdf_open:
            mock_pdf_open.return_value.__enter__.return_value = _mock_pdf(text)
            result = BulletinParserService.parse_bulletin_text("dummy_path.pdf")

        self.assertEqual(result["typhoon_name"], "UNKNOWN")
        self.assertEqual(result["category"], "UNKNOWN")

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

    def test_parse_bulletin_text_extracts_signals_from_all_island_columns(self):
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

        # All three island columns are extracted now (island_group 0=Luzon,
        # 1=Visayas, 2=Mindanao); a "-" cell means that island is absent for
        # that level, not the whole level being dropped.
        self.assertEqual(set(result["signals"].keys()), {1, 2})
        self.assertIn("Talakag", result["signals"][2][2])
        self.assertIn("Batanes area text", result["signals"][2][0])
        self.assertNotIn(1, result["signals"][2])  # Visayas cell was "-"
        self.assertIn("Some Luzon area", result["signals"][1][0])
        self.assertNotIn(2, result["signals"][1])  # Signal 1's Mindanao cell was "-"

    def test_parse_bulletin_text_against_real_sample_pdf(self):
        # End-to-end regression test against a real PAGASA bulletin (Tropical
        # Storm KIYAPO, Bulletin NR. 11) provided by Fabio. KIYAPO only
        # affected Luzon — no Mindanao text at either signal level is still
        # correct for this project's Region X-scoped exposure calculations,
        # but the real Luzon signal text is now captured too (previously
        # discarded entirely since only the Mindanao column was ever read).
        result = BulletinParserService.parse_bulletin_text(REAL_SAMPLE_PDF)

        self.assertEqual(result["typhoon_name"], "KIYAPO")
        self.assertEqual(result["international_name"], "NOUL")
        self.assertEqual(result["bulletin_count"], 11)
        self.assertFalse(result["is_final"])  # KIYAPO #11 is not final — "next bulletin at 5:00 PM today"
        self.assertEqual(result["category"], "Tropical Storm")
        self.assertEqual(result["max_sustained_winds"], 75)
        self.assertEqual(result["gustiness"], 90)
        self.assertEqual(result["latitude"], 18.8)
        self.assertEqual(result["longitude"], 122.0)
        self.assertEqual(result["issued_at"], datetime(2026, 7, 24, 14, 0, tzinfo=PHT))
        self.assertEqual(set(result["signals"].keys()), {1, 2})
        self.assertNotIn(2, result["signals"][2])  # no Mindanao text at Signal No. 2
        self.assertNotIn(2, result["signals"][1])  # no Mindanao text at Signal No. 1
        self.assertIn("Batanes", result["signals"][2][0])
        self.assertIn("Isabela", result["signals"][1][0])

    # `_split_named_areas()` and its free-text Luzon/Visayas fallback were
    # removed 2026-08-20 as part of the nationwide PSGC expansion -- every
    # island group now goes through the same precise AdminBoundary match as
    # Mindanao previously did (see BulletinParserSaveToDbTests below).


class BulletinParserSaveToDbTests(unittest.TestCase):
    def _build_mock_db(self, boundaries, existing_typhoon=None, existing_bulletin=None, existing_signal=None):
        """Dispatches db.query(Model) to a per-model mock so typhoon/bulletin/boundary
        lookups don't collide on the same MagicMock return chain. `existing_typhoon`
        controls what the "same typhoon within the last 30 days" join query
        (db.query(Typhoon).join(...).filter(...).order_by(...).first()) returns —
        None means "no match, create a new Typhoon row". `boundaries` are
        (province, municipality) tuples, as returned by
        db.query(AdminBoundary.province, AdminBoundary.municipality).distinct().all()."""
        mock_db = MagicMock()

        typhoon_query = MagicMock()
        typhoon_query.join.return_value.filter.return_value.order_by.return_value.first.return_value = existing_typhoon

        bulletin_query = MagicMock()
        bulletin_query.filter.return_value.first.return_value = existing_bulletin

        admin_query = MagicMock()
        admin_query.distinct.return_value.all.return_value = boundaries

        signal_query = MagicMock()
        signal_query.filter.return_value.first.return_value = existing_signal

        def query_side_effect(*entities):
            model = entities[0]
            if model is Typhoon:
                return typhoon_query
            if model is TropicalCycloneBulletin:
                return bulletin_query
            if model is AdminBoundary.province:
                return admin_query
            if model is TcbSignal:
                return signal_query
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
        mock_db = self._build_mock_db(boundaries=[("Misamis Oriental", "Claveria")])
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
                2: {2: "SIGNAL NO. 2\nMindanao:\nThe northern portion of Misamis Oriental (Claveria)"},
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
        self.assertEqual(signal_rows[0].island_group, 2)
        self.assertEqual(signal_rows[0].province, "Misamis Oriental")

    def test_save_bulletin_to_db_matches_luzon_visayas_against_admin_boundary_too(self):
        # As of the nationwide PSGC expansion (2026-08-20), Luzon/Visayas go
        # through the same precise province+municipality AdminBoundary match
        # Mindanao always used -- no more free-text fallback.
        mock_db = self._build_mock_db(boundaries=[("Cagayan", "Santa Ana")])
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
                2: {0: "Batanes, the northern portion of Cagayan (Santa Ana, Gonzaga)"},
            },
            "raw_text": "",
        }

        BulletinParserService.save_bulletin_to_db(parsed_data, mock_db)

        signal_rows = [obj for obj in created_objects if isinstance(obj, TcbSignal)]
        self.assertEqual(len(signal_rows), 1)
        self.assertEqual(signal_rows[0].area_name, "Santa Ana")
        self.assertEqual(signal_rows[0].island_group, 0)
        self.assertEqual(signal_rows[0].signal_level, 2)
        self.assertEqual(signal_rows[0].province, "Cagayan")

    def test_save_bulletin_to_db_drops_unmatched_area_with_no_fallback(self):
        # A cell whose provinces aren't in AdminBoundary at all yields zero
        # tbl_tcb_signals rows -- no free-text fallback there (the raw text is
        # kept on the bulletin's tcws_areas column instead, for display).
        mock_db = self._build_mock_db(boundaries=[])
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
                2: {0: "Batanes, the northern portion of Cagayan (Santa Ana, Gonzaga)"},
            },
            "raw_text": "",
        }

        BulletinParserService.save_bulletin_to_db(parsed_data, mock_db)

        signal_rows = [obj for obj in created_objects if isinstance(obj, TcbSignal)]
        self.assertEqual(signal_rows, [])

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
        # is_active is no longer decided at creation time -- PagasaStatusService's
        # status-page check is the sole source of truth for it now.
        self.assertFalse(created_typhoons[0].is_active)

    def test_save_bulletin_to_db_does_not_touch_is_active_even_when_final(self):
        # A bulletin number with a trailing "F" (e.g. "NR. 21F") is still PAGASA's
        # signal that no more bulletins will follow -- but that now only gates
        # whether the exposure summary/assessment gets computed (see
        # ScrapeAndSaveAllTests below), not is_active. PagasaStatusService's
        # severe-weather-bulletin page check is the sole source of truth for
        # is_active now; TCB parsing must leave it alone regardless of is_final.
        existing_typhoon = Typhoon(name="FRANCISCO", year=2026, is_active=True)
        existing_typhoon.typhoon_id = 9
        mock_db = self._build_mock_db(boundaries=[], existing_typhoon=existing_typhoon)

        parsed_data = {
            "typhoon_name": "FRANCISCO",
            "bulletin_count": 21,
            "is_final": True,
            "category": "Tropical Storm",
            "max_sustained_winds": 45,
            "gustiness": 60,
            "latitude": 10.0,
            "longitude": 125.0,
            "issued_at": datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc),
            "signals": {},
            "raw_text": "",
        }

        BulletinParserService.save_bulletin_to_db(parsed_data, mock_db)

        self.assertTrue(existing_typhoon.is_active)

    def _luzon_parsed_data(self):
        return {
            "typhoon_name": "KIYAPO",
            "bulletin_count": 11,
            "category": "Tropical Storm",
            "max_sustained_winds": 75,
            "gustiness": 90,
            "latitude": 18.8,
            "longitude": 122.0,
            "issued_at": None,
            "signals": {
                2: {0: "Batanes, the northern portion of Cagayan (Santa Ana, Gonzaga)"},
                1: {0: "Isabela"},
            },
            "raw_text": "",
        }

    def test_save_bulletin_to_db_stores_raw_tcws_even_when_no_boundary_matches(self):
        # 2026-09-30: the TCB viewer showed "No Signal Data" because the signal
        # number came only from boundary-matched tbl_tcb_signals rows. The raw
        # TCWS is now kept on the bulletin itself, unvalidated.
        mock_db = self._build_mock_db(boundaries=[])
        created_objects = []
        mock_db.add.side_effect = created_objects.append

        result = BulletinParserService.save_bulletin_to_db(self._luzon_parsed_data(), mock_db)

        self.assertEqual(result.max_signal_level, 2)
        self.assertEqual(result.tcws_areas, {
            "2": {"0": "Batanes, the northern portion of Cagayan (Santa Ana, Gonzaga)"},
            "1": {"0": "Isabela"},
        })
        self.assertEqual([o for o in created_objects if isinstance(o, TcbSignal)], [])

    def test_save_bulletin_to_db_leaves_raw_tcws_null_when_bulletin_has_no_signals(self):
        mock_db = self._build_mock_db(boundaries=[])
        parsed_data = {**self._luzon_parsed_data(), "signals": {}}

        result = BulletinParserService.save_bulletin_to_db(parsed_data, mock_db)

        self.assertIsNone(result.max_signal_level)
        self.assertIsNone(result.tcws_areas)

    def test_save_bulletin_to_db_stores_level_zero_when_pagasa_says_no_signal_hoisted(self):
        mock_db = self._build_mock_db(boundaries=[])
        parsed_data = {**self._luzon_parsed_data(), "signals": {}, "no_signal_hoisted": True}

        result = BulletinParserService.save_bulletin_to_db(parsed_data, mock_db)

        self.assertEqual(result.max_signal_level, 0)
        self.assertIsNone(result.tcws_areas)

    def test_save_bulletin_to_db_expands_whole_province_to_all_its_municipalities(self):
        mock_db = self._build_mock_db(boundaries=[
            ("Batanes", "Basco"), ("Batanes", "Itbayat"),
            ("Cagayan", "Santa Ana"), ("Cagayan", "Gonzaga"), ("Cagayan", "Aparri"),
        ])
        created_objects = []
        mock_db.add.side_effect = created_objects.append

        BulletinParserService.save_bulletin_to_db(self._luzon_parsed_data(), mock_db)

        rows = {(o.signal_level, o.province, o.area_name) for o in created_objects if isinstance(o, TcbSignal)}
        self.assertEqual(rows, {
            (2, "Batanes", "Basco"), (2, "Batanes", "Itbayat"),  # whole province named
            (2, "Cagayan", "Santa Ana"), (2, "Cagayan", "Gonzaga"),  # only the listed towns -- not Aparri
        })

    def test_backfills_existing_bulletin_saved_before_raw_tcws_columns(self):
        existing_bulletin = TropicalCycloneBulletin(title="Bulletin No. 11 for KIYAPO", bulletin_count=11)
        existing_bulletin.tcb_id = 12
        mock_db = self._build_mock_db(
            boundaries=[("Batanes", "Basco")], existing_bulletin=existing_bulletin, existing_signal=None,
        )
        created_objects = []
        mock_db.add.side_effect = created_objects.append

        result = BulletinParserService.save_bulletin_to_db(self._luzon_parsed_data(), mock_db)

        self.assertIs(result, existing_bulletin)
        self.assertEqual(result.max_signal_level, 2)
        self.assertIn("2", result.tcws_areas)
        signal_rows = [o for o in created_objects if isinstance(o, TcbSignal)]
        self.assertEqual([(s.tcb_id, s.province, s.area_name) for s in signal_rows], [(12, "Batanes", "Basco")])

    def test_backfill_does_not_reseed_bulletin_that_already_has_signal_rows(self):
        existing_bulletin = TropicalCycloneBulletin(title="Bulletin No. 11 for KIYAPO", bulletin_count=11)
        existing_bulletin.tcb_id = 12
        mock_db = self._build_mock_db(
            boundaries=[("Batanes", "Basco")], existing_bulletin=existing_bulletin, existing_signal=MagicMock(),
        )
        created_objects = []
        mock_db.add.side_effect = created_objects.append

        BulletinParserService.save_bulletin_to_db(self._luzon_parsed_data(), mock_db)

        self.assertEqual(existing_bulletin.max_signal_level, 2)
        self.assertEqual([o for o in created_objects if isinstance(o, TcbSignal)], [])

    def test_backfill_runs_only_once_per_bulletin(self):
        existing_bulletin = TropicalCycloneBulletin(title="Bulletin No. 11 for KIYAPO", bulletin_count=11)
        existing_bulletin.tcb_id = 12
        existing_bulletin.max_signal_level = 2
        existing_bulletin.tcws_areas = {"2": {"0": "Batanes"}}
        existing_typhoon = Typhoon(name="KIYAPO", year=2026, is_active=True)
        existing_typhoon.typhoon_id = 4
        mock_db = self._build_mock_db(
            boundaries=[("Batanes", "Basco")], existing_typhoon=existing_typhoon, existing_bulletin=existing_bulletin,
        )
        created_objects = []
        mock_db.add.side_effect = created_objects.append

        BulletinParserService.save_bulletin_to_db(self._luzon_parsed_data(), mock_db)

        self.assertEqual(created_objects, [])
        mock_db.commit.assert_not_called()


class MatchTcwsCellTests(unittest.TestCase):
    BOUNDARIES = {
        "Batanes": {"Basco", "Itbayat"},
        "Cagayan": {"Santa Ana", "Gonzaga", "Aparri"},
        "Misamis Oriental": {"Claveria", "City of Gingoog"},
        "City of Cagayan De Oro": {"City of Cagayan De Oro"},  # HUC convention: province == city
        "Samar": {"Catbalogan"},
        "Northern Samar": {"Catarman"},
        "Laguna": {"Santa Cruz"},
        "Marinduque": {"Santa Cruz"},
    }

    def test_province_name_inside_parenthetical_is_not_a_province_mention(self):
        result = match_tcws_cell("The northern portion of Misamis Oriental (Claveria, Cagayan de Oro City)", self.BOUNDARIES)
        self.assertNotIn("Cagayan", {p for p, _ in result})
        self.assertIn(("City of Cagayan De Oro", "City of Cagayan De Oro"), result)
        self.assertIn(("Misamis Oriental", "Claveria"), result)

    def test_city_of_prefix_matches_pagasa_city_suffix_spelling(self):
        result = match_tcws_cell("Misamis Oriental (Gingoog City)", self.BOUNDARIES)
        self.assertEqual(result, [("Misamis Oriental", "City of Gingoog")])

    def test_longer_province_name_is_not_also_matched_as_its_substring(self):
        self.assertEqual(match_tcws_cell("Northern Samar", self.BOUNDARIES), [("Northern Samar", "Catarman")])

    def test_same_named_towns_in_different_provinces_are_both_kept(self):
        result = match_tcws_cell("the southern portion of Laguna (Santa Cruz), Marinduque", self.BOUNDARIES)
        self.assertEqual(result, [("Laguna", "Santa Cruz"), ("Marinduque", "Santa Cruz")])

    def test_whole_province_does_not_borrow_next_unloaded_provinces_list(self):
        # Regression: with Cagayan not a loaded boundary, "Batanes" used to
        # take "(Santa Ana, Gonzaga)" as its own list and match nothing.
        result = match_tcws_cell(
            "Batanes, the northern portion of Cagayan (Santa Ana, Gonzaga)", {"Batanes": {"Basco", "Itbayat"}},
        )
        self.assertEqual(result, [("Batanes", "Basco"), ("Batanes", "Itbayat")])


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

        self.assertEqual(
            result,
            [{"tcb_id": 100, "title": "Bulletin No. 5 for LEON", "bulletin_count": 5, "is_final": False}],
        )

    async def test_final_bulletin_triggers_assessment_calculation(self):
        with patch.object(BulletinParserService, "fetch_active_bulletin_links", new_callable=AsyncMock) as mock_fetch, \
             patch.object(BulletinParserService, "download_bulletin_pdf", new_callable=AsyncMock) as mock_download, \
             patch.object(BulletinParserService, "parse_bulletin_text") as mock_parse, \
             patch.object(BulletinParserService, "save_bulletin_to_db") as mock_save, \
             patch("app.services.bulletin_parser.AssessmentService.calculate_for_bulletin") as mock_calc, \
             patch("os.path.exists", return_value=False):
            mock_fetch.return_value = ["https://pagasa.example/tcb21f.pdf"]
            mock_download.return_value = "temp_bulletins/tcb21f.pdf"
            mock_parse.return_value = {"raw_text": "", "is_final": True}
            mock_save.return_value = MagicMock(tcb_id=200, title="Bulletin No. 21 for FRANCISCO", bulletin_count=21, typhoon_id=9)
            mock_db = MagicMock()

            result = await BulletinParserService.scrape_and_save_all(mock_db)

        mock_calc.assert_called_once_with(9, 200, mock_db)
        self.assertTrue(result[0]["is_final"])

    async def test_non_final_bulletin_does_not_trigger_assessment_calculation(self):
        with patch.object(BulletinParserService, "fetch_active_bulletin_links", new_callable=AsyncMock) as mock_fetch, \
             patch.object(BulletinParserService, "download_bulletin_pdf", new_callable=AsyncMock) as mock_download, \
             patch.object(BulletinParserService, "parse_bulletin_text") as mock_parse, \
             patch.object(BulletinParserService, "save_bulletin_to_db") as mock_save, \
             patch("app.services.bulletin_parser.AssessmentService.calculate_for_bulletin") as mock_calc, \
             patch("os.path.exists", return_value=False):
            mock_fetch.return_value = ["https://pagasa.example/tcb11.pdf"]
            mock_download.return_value = "temp_bulletins/tcb11.pdf"
            mock_parse.return_value = {"raw_text": "", "is_final": False}
            mock_save.return_value = MagicMock(tcb_id=100, title="Bulletin No. 11 for KIYAPO", bulletin_count=11, typhoon_id=3)

            await BulletinParserService.scrape_and_save_all(MagicMock())

        mock_calc.assert_not_called()

    async def test_propagates_pagasa_scrape_error(self):
        # A real fetch failure must not be treated as "confirmed nothing active" —
        # it should propagate (the scheduler job's own try/except handles it) and
        # never reach the assessment-calculation step.
        with patch.object(BulletinParserService, "fetch_active_bulletin_links", new_callable=AsyncMock) as mock_fetch, \
             patch("app.services.bulletin_parser.AssessmentService.calculate_for_bulletin") as mock_calc:
            mock_fetch.side_effect = PagasaScrapeError("network down")

            with self.assertRaises(PagasaScrapeError):
                await BulletinParserService.scrape_and_save_all(MagicMock())

        mock_calc.assert_not_called()


def _fake_httpx_client(response=None, get_side_effect=None):
    mock_client = AsyncMock()
    if get_side_effect is not None:
        mock_client.get.side_effect = get_side_effect
    else:
        mock_client.get.return_value = response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False
    return mock_client


class FetchActiveBulletinLinksTests(unittest.IsolatedAsyncioTestCase):
    async def test_raises_pagasa_scrape_error_on_non_200_response(self):
        mock_client = _fake_httpx_client(response=MagicMock(status_code=503))
        with patch("httpx.AsyncClient", return_value=mock_client):
            with self.assertRaises(PagasaScrapeError):
                await BulletinParserService.fetch_active_bulletin_links()

    async def test_raises_pagasa_scrape_error_on_network_exception(self):
        mock_client = _fake_httpx_client(get_side_effect=Exception("connection reset"))
        with patch("httpx.AsyncClient", return_value=mock_client):
            with self.assertRaises(PagasaScrapeError):
                await BulletinParserService.fetch_active_bulletin_links()

    async def test_returns_empty_list_on_successful_response_with_no_pdf_links(self):
        mock_client = _fake_httpx_client(
            response=MagicMock(status_code=200, text="<html><body>no links here</body></html>")
        )
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await BulletinParserService.fetch_active_bulletin_links()

        self.assertEqual(result, [])

    async def test_keeps_only_tcb_links_and_drops_non_bulletin_pdfs(self):
        # Mirrors the live PAGASA index (2026-09-30): alongside real TCBs it
        # hosts a Tropical Cyclone Warning for Shipping ("IWS#2_pilandok.pdf")
        # and a Tropical Cyclone Advisory ("TCB#unknown.pdf"). Parsing either
        # as a bulletin saved a fake "UNKNOWN" TCB No. 1 -- they must be skipped.
        html = (
            '<a href="IWS%232_pilandok.pdf">IWS#2_pilandok.pdf</a>'
            '<a href="TCB%23unknown.pdf">TCB#unknown.pdf</a>'
            '<a href="TCB%2311_kiyapo.pdf">TCB#11_kiyapo.pdf</a>'
            '<a href="TCB%2321F_francisco.pdf">TCB#21F_francisco.pdf</a>'
        )
        mock_client = _fake_httpx_client(response=MagicMock(status_code=200, text=html))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await BulletinParserService.fetch_active_bulletin_links()

        self.assertEqual([link.rsplit("/", 1)[-1] for link in result],
                         ["TCB%2311_kiyapo.pdf", "TCB%2321F_francisco.pdf"])


class DownloadBulletinPdfTests(unittest.IsolatedAsyncioTestCase):
    """PAGASA's file server is slow (live httpx.ReadTimeouts on 2026-09-30) --
    a timed-out download is retried once before giving up."""

    async def test_retries_once_after_timeout_then_saves_pdf(self):
        mock_client = _fake_httpx_client(get_side_effect=[
            httpx.ReadTimeout("slow"),
            MagicMock(status_code=200, content=b"%PDF-1.4"),
        ])
        with tempfile.TemporaryDirectory() as tmp, \
             patch("httpx.AsyncClient", return_value=mock_client), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            path = await BulletinParserService.download_bulletin_pdf("https://pagasa.example/TCB%2311_inday.pdf", tmp)
            with open(path, "rb") as f:
                self.assertEqual(f.read(), b"%PDF-1.4")

        self.assertEqual(mock_client.get.call_count, 2)

    async def test_raises_timeout_when_retry_also_times_out(self):
        mock_client = _fake_httpx_client(get_side_effect=[httpx.ReadTimeout("slow"), httpx.ConnectTimeout("down")])
        with tempfile.TemporaryDirectory() as tmp, \
             patch("httpx.AsyncClient", return_value=mock_client), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            with self.assertRaises(httpx.TimeoutException):
                await BulletinParserService.download_bulletin_pdf("https://pagasa.example/TCB%2311_inday.pdf", tmp)

        self.assertEqual(mock_client.get.call_count, 2)

    async def test_scrape_logs_one_line_warning_on_timeout_and_continues(self):
        with patch.object(BulletinParserService, "fetch_active_bulletin_links", new_callable=AsyncMock) as mock_fetch, \
             patch.object(BulletinParserService, "download_bulletin_pdf", new_callable=AsyncMock) as mock_download, \
             patch.object(BulletinParserService, "parse_bulletin_text") as mock_parse, \
             patch.object(BulletinParserService, "save_bulletin_to_db") as mock_save, \
             patch("os.path.exists", return_value=False):
            mock_fetch.return_value = ["https://pagasa.example/TCB%2311_inday.pdf", "https://pagasa.example/good.pdf"]
            mock_download.side_effect = [httpx.ReadTimeout("slow"), "temp_bulletins/good.pdf"]
            mock_parse.return_value = {"raw_text": ""}
            mock_save.return_value = MagicMock(tcb_id=100, title="Bulletin No. 5 for LEON", bulletin_count=5)

            with self.assertLogs("app.services.bulletin_parser", level="WARNING") as logs:
                result = await BulletinParserService.scrape_and_save_all(MagicMock())

        self.assertEqual(len(result), 1)
        self.assertEqual(len(logs.records), 1)
        self.assertIn("TCB#11_inday.pdf", logs.output[0])
        self.assertIsNone(logs.records[0].exc_info)  # no traceback


if __name__ == "__main__":
    unittest.main()
