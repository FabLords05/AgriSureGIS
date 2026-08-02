import re
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.models.models import Typhoon
from app.services.bulletin_parser import BulletinParserService, PagasaScrapeError

PAGASA_STATUS_URL = "https://www.pagasa.dost.gov.ph/tropical-cyclone/severe-weather-bulletin"

# Longest phrase first so "Super Typhoon" can't be short-circuited by a bare
# "Typhoon" match. Includes "Super Typhoon", which bulletin_parser.py's own
# TCB-title regex doesn't (no real sample bulletin carrying it was available
# when that regex was written); this page can show one.
CATEGORY_NAME_RE = re.compile(
    r"(SUPER TYPHOON|SEVERE TROPICAL STORM|TROPICAL STORM|TROPICAL DEPRESSION|TYPHOON)"
    r"\s+[\"']?([A-Z][A-Z\-]*)[\"']?",
    re.IGNORECASE,
)


class PagasaStatusService:
    """
    Determines "is there a currently active typhoon" from PAGASA's public
    severe-weather-bulletin status page — not from TCB PDF parsing. Per
    Fabio's decision, this is now the sole source of truth for
    Typhoon.is_active; TCB parsing (bulletin_parser.py) no longer touches it
    at all, and only decides when to finalize the exposure summary (the "F"
    final-bulletin marker).

    Each active cyclone appears on the page as a tab, e.g.
    `<a class="swb">Tropical Depression &quot;Luis&quot;</a>` (confirmed
    against the live page). The `swb` class is a stable template anchor, so
    the keyword search is scoped to just these tab labels instead of the full
    page — a stray mention of "typhoon" elsewhere (nav, footer, an unrelated
    article teaser) can't cause a false positive. This is the same failure
    mode bulletin_parser.py's own category regex was previously rewritten to
    avoid (see its comment on scanning the title line only, not the whole
    document).
    """

    @staticmethod
    async def fetch_active_storm_names() -> list[str]:
        """
        Returns the uppercased names of every cyclone PAGASA's status page
        currently lists (each backed by a recognized category word in its tab
        label), or [] if none are currently listed — a page with no `.swb` tabs
        at all is a legitimate "nothing active" result, not an error. Raises
        `PagasaScrapeError` if the page itself couldn't be reached, mirroring
        `BulletinParserService.fetch_active_bulletin_links`'s same distinction
        and for the same reason: a failed check must never be treated as
        "confirmed nothing active".
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(PAGASA_STATUS_URL)
        except Exception as e:
            raise PagasaScrapeError(f"Error fetching PAGASA severe weather bulletin page: {e}") from e

        if response.status_code != 200:
            raise PagasaScrapeError(f"PAGASA severe weather bulletin page returned HTTP {response.status_code}")

        soup = BeautifulSoup(response.text, "html.parser")
        names = []
        for anchor in soup.find_all("a", class_="swb"):
            match = CATEGORY_NAME_RE.search(anchor.get_text(" ", strip=True))
            if match:
                names.append(match.group(2).upper())
        return names

    @classmethod
    def sync_active_typhoons(cls, active_names: list[str], db: Session) -> list[Typhoon]:
        """
        Sets Typhoon.is_active to match `active_names` exactly: True for the
        Typhoon each name resolves to (via the same get_or_create_typhoon
        lookup TCB ingestion uses, so both sides of the PAGASA site agree on
        which row a name refers to), False for every other Typhoon still
        marked active. Only ever called with a successfully-fetched
        `active_names` (see `PagasaScrapeError` above) — an empty-but-successful
        list correctly means "close everything still marked active."
        """
        now = datetime.now(timezone.utc)
        matched_ids = set()
        active_typhoons = []
        for name in active_names:
            typhoon = BulletinParserService.get_or_create_typhoon(name, now, db)
            if not typhoon.is_active:
                typhoon.is_active = True
            matched_ids.add(typhoon.typhoon_id)
            active_typhoons.append(typhoon)

        for typhoon in db.query(Typhoon).filter(Typhoon.is_active.is_(True)).all():
            if typhoon.typhoon_id not in matched_ids:
                typhoon.is_active = False

        db.commit()
        return active_typhoons
