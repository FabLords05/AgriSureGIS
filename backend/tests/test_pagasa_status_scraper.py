import unittest
from unittest.mock import patch, AsyncMock, MagicMock

from app.services.pagasa_status_scraper import PagasaStatusService
from app.services.bulletin_parser import PagasaScrapeError, BulletinParserService
from app.models.models import Typhoon


def _fake_httpx_client(response=None, get_side_effect=None):
    mock_client = AsyncMock()
    if get_side_effect is not None:
        mock_client.get.side_effect = get_side_effect
    else:
        mock_client.get.return_value = response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False
    return mock_client


class FetchActiveStormNamesTests(unittest.IsolatedAsyncioTestCase):
    async def test_raises_pagasa_scrape_error_on_non_200_response(self):
        mock_client = _fake_httpx_client(response=MagicMock(status_code=503))
        with patch("httpx.AsyncClient", return_value=mock_client):
            with self.assertRaises(PagasaScrapeError):
                await PagasaStatusService.fetch_active_storm_names()

    async def test_raises_pagasa_scrape_error_on_network_exception(self):
        mock_client = _fake_httpx_client(get_side_effect=Exception("connection reset"))
        with patch("httpx.AsyncClient", return_value=mock_client):
            with self.assertRaises(PagasaScrapeError):
                await PagasaStatusService.fetch_active_storm_names()

    async def test_returns_empty_list_when_no_swb_tabs_present(self):
        html = "<html><body><div id='swb'>No bulletin</div></body></html>"
        mock_client = _fake_httpx_client(response=MagicMock(status_code=200, text=html))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await PagasaStatusService.fetch_active_storm_names()

        self.assertEqual(result, [])

    async def test_extracts_name_from_swb_tab_with_category_keyword(self):
        # Real markup shape (confirmed against the live PAGASA page): each active
        # cyclone is a tab, with `<a class="swb">` holding its category + quoted
        # name, e.g. `<a class="swb">Tropical Depression "Luis"</a>`.
        html = (
            '<ul class="nav nav-tabs">'
            '<li><a href="#tcwb-1" class="swb">Tropical Depression &quot;Luis&quot;</a></li>'
            "</ul>"
        )
        mock_client = _fake_httpx_client(response=MagicMock(status_code=200, text=html))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await PagasaStatusService.fetch_active_storm_names()

        self.assertEqual(result, ["LUIS"])

    async def test_extracts_multiple_names_when_multiple_tabs_present(self):
        # PAGASA's status page can list more than one concurrently active system.
        html = (
            '<ul class="nav nav-tabs">'
            '<li><a class="swb">Tropical Storm &quot;Ambo&quot;</a></li>'
            '<li><a class="swb">Typhoon &quot;Bagyo&quot;</a></li>'
            "</ul>"
        )
        mock_client = _fake_httpx_client(response=MagicMock(status_code=200, text=html))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await PagasaStatusService.fetch_active_storm_names()

        self.assertEqual(result, ["AMBO", "BAGYO"])

    async def test_recognizes_super_typhoon_category(self):
        # "Super Typhoon" must not be short-circuited by the bare "Typhoon"
        # alternative matching partway through it.
        html = '<a class="swb">Super Typhoon &quot;Marina&quot;</a>'
        mock_client = _fake_httpx_client(response=MagicMock(status_code=200, text=html))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await PagasaStatusService.fetch_active_storm_names()

        self.assertEqual(result, ["MARINA"])

    async def test_ignores_swb_tab_without_recognized_category_word(self):
        # Defensive: a tab carrying the "swb" class but no recognized category
        # word isn't treated as an active cyclone.
        html = '<a class="swb">Weather Advisory</a>'
        mock_client = _fake_httpx_client(response=MagicMock(status_code=200, text=html))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await PagasaStatusService.fetch_active_storm_names()

        self.assertEqual(result, [])

    async def test_ignores_category_word_outside_swb_tabs(self):
        # Regression guard: a stray "Typhoon" mention elsewhere on the page (nav,
        # footer, unrelated article teaser) must not be picked up -- only text
        # inside a "swb"-classed tab label counts. Mirrors the exact false-
        # positive bug bulletin_parser.py's own category regex was rewritten to
        # avoid.
        html = (
            '<div class="footer">Read about Typhoon Yolanda\'s history</div>'
            '<a class="swb">Tropical Depression &quot;Luis&quot;</a>'
        )
        mock_client = _fake_httpx_client(response=MagicMock(status_code=200, text=html))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await PagasaStatusService.fetch_active_storm_names()

        self.assertEqual(result, ["LUIS"])


class SyncActiveTyphoonsTests(unittest.TestCase):
    def _build_mock_db(self, currently_active):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = currently_active
        return mock_db

    @patch.object(BulletinParserService, "get_or_create_typhoon")
    def test_sets_is_active_true_for_matched_name(self, mock_get_or_create):
        typhoon = Typhoon(name="LUIS", year=2026, is_active=False)
        typhoon.typhoon_id = 1
        mock_get_or_create.return_value = typhoon
        mock_db = self._build_mock_db(currently_active=[])

        result = PagasaStatusService.sync_active_typhoons(["LUIS"], mock_db)

        self.assertTrue(typhoon.is_active)
        self.assertEqual(result, [typhoon])

    @patch.object(BulletinParserService, "get_or_create_typhoon")
    def test_closes_typhoons_not_in_active_names(self, mock_get_or_create):
        stale = Typhoon(name="GARDO", year=2026, is_active=True)
        stale.typhoon_id = 5
        mock_db = self._build_mock_db(currently_active=[stale])

        PagasaStatusService.sync_active_typhoons([], mock_db)

        self.assertFalse(stale.is_active)
        mock_get_or_create.assert_not_called()

    @patch.object(BulletinParserService, "get_or_create_typhoon")
    def test_matched_typhoon_is_excluded_from_the_closing_pass(self, mock_get_or_create):
        # The typhoon just matched via get_or_create_typhoon must not also get
        # closed by the "everything still active but unmatched" pass right
        # after it, even though the (mocked) query returns it as "currently
        # active" too.
        typhoon = Typhoon(name="LUIS", year=2026, is_active=True)
        typhoon.typhoon_id = 1
        mock_get_or_create.return_value = typhoon
        mock_db = self._build_mock_db(currently_active=[typhoon])

        PagasaStatusService.sync_active_typhoons(["LUIS"], mock_db)

        self.assertTrue(typhoon.is_active)

    @patch.object(BulletinParserService, "get_or_create_typhoon")
    def test_empty_active_names_closes_everything(self, mock_get_or_create):
        # A successful check that found zero active cyclones is a real signal --
        # every currently is_active=True typhoon should close.
        stale_a = Typhoon(name="GARDO", year=2026, is_active=True)
        stale_a.typhoon_id = 5
        stale_b = Typhoon(name="FRANCISCO", year=2026, is_active=True)
        stale_b.typhoon_id = 6
        mock_db = self._build_mock_db(currently_active=[stale_a, stale_b])

        result = PagasaStatusService.sync_active_typhoons([], mock_db)

        self.assertEqual(result, [])
        self.assertFalse(stale_a.is_active)
        self.assertFalse(stale_b.is_active)
        mock_get_or_create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
