import re
import asyncio
import functools
import logging
import os
import httpx
from urllib.parse import unquote
from bs4 import BeautifulSoup
import pdfplumber
from sqlalchemy import func
from sqlalchemy.orm import Session
from geoalchemy2.elements import WKTElement
from datetime import datetime, timedelta, timezone

from app.models.models import Typhoon, TropicalCycloneBulletin, TcbSignal, AdminBoundary
from app.services.assessment_service import AssessmentService

# Base URL for PAGASA tropical cyclone bulletins (mock or real index page)
PAGASA_INDEX_URL = "https://pubfiles.pagasa.dost.gov.ph/tamss/weather/bulletin/"

# Real Tropical Cyclone Bulletin filenames on the PAGASA index (e.g.
# "TCB#11_kiyapo.pdf", "TCB#21F_francisco.pdf"). The same index also hosts
# PDFs that are NOT bulletins -- confirmed on the live index 2026-09-30:
# "IWS#2_pilandok.pdf" (a Tropical Cyclone Warning for Shipping) and
# "TCB#unknown.pdf" (a Tropical Cyclone Advisory for a storm still outside
# PAR). Neither has a "Tropical Cyclone Bulletin NR." header or a named title,
# so parsing them fell through to bulletin_count=1 / "UNKNOWN" / issued_at=now
# and saved a fake "UNKNOWN" typhoon row.
TCB_LINK_NAME_RE = re.compile(r"TCB#\d+[A-Za-z]?_[A-Za-z\-]+\.pdf$", re.IGNORECASE)

# pubfiles.pagasa.dost.gov.ph is often slow to send bulletin PDFs -- the old
# flat 15s timeout failed most downloads with httpx.ReadTimeout (seen live
# 2026-09-30), so those bulletins were never saved. Longer read window, plus
# one retry in download_bulletin_pdf().
PDF_DOWNLOAD_TIMEOUT = httpx.Timeout(60.0, connect=15.0)
PDF_DOWNLOAD_RETRY_DELAY_SECONDS = 2.0

# PAGASA states every bulletin's "Issued at" timestamp in Philippine Standard
# Time, not UTC -- a fixed UTC+8 offset (the Philippines observes no DST).
PHT = timezone(timedelta(hours=8))

logger = logging.getLogger(__name__)


class PagasaScrapeError(Exception):
    """
    Raised when a PAGASA page couldn't actually be checked (network failure,
    non-200 response) — distinct from a successful check that found nothing
    (e.g. zero active bulletins), which returns an empty list/result instead.
    This distinction matters to callers like PagasaStatusService's active-
    typhoon sync: treating a failed check the same as "confirmed nothing
    active" would wrongly close every genuinely ongoing typhoon on a
    transient network hiccup. Shared across PAGASA-facing scrapers in this
    package (bulletin index, severe-weather-bulletin status page) rather than
    duplicated per scraper.
    """


class BulletinParserService:
    @staticmethod
    async def fetch_active_bulletin_links() -> list:
        """
        Scrapes the PAGASA bulletin portal to find PDF links to active tropical
        cyclone bulletins. Raises `PagasaScrapeError` if the portal couldn't be
        reached/read at all; returns `[]` only for a successful check that found
        no active bulletins.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(PAGASA_INDEX_URL)
        except Exception as e:
            raise PagasaScrapeError(f"Error scraping PAGASA links: {e}") from e

        if response.status_code != 200:
            raise PagasaScrapeError(f"PAGASA index returned HTTP {response.status_code}")

        soup = BeautifulSoup(response.text, "html.parser")
        pdf_links = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            # Only real TCBs -- see TCB_LINK_NAME_RE above. hrefs are
            # URL-encoded on the live index ("TCB%2311_kiyapo.pdf").
            filename = unquote(href.rsplit("/", 1)[-1])
            if TCB_LINK_NAME_RE.fullmatch(filename):
                # Resolve relative links to absolute URLs if necessary
                if not href.startswith("http"):
                    base_url = PAGASA_INDEX_URL.rsplit("/", 1)[0]
                    href = f"{base_url}/{href}"
                pdf_links.append(href)
        return pdf_links

    @staticmethod
    async def download_bulletin_pdf(pdf_url: str, output_dir: str = "temp_bulletins") -> str:
        """
        Downloads the PDF from the PAGASA URL and saves it locally.
        """
        os.makedirs(output_dir, exist_ok=True)
        filename = pdf_url.split("/")[-1]
        filepath = os.path.join(output_dir, filename)

        async with httpx.AsyncClient(timeout=PDF_DOWNLOAD_TIMEOUT) as client:
            try:
                response = await client.get(pdf_url)
            except httpx.TimeoutException:
                # One retry after a short pause -- see PDF_DOWNLOAD_TIMEOUT.
                # A second timeout propagates to scrape_and_save_all().
                await asyncio.sleep(PDF_DOWNLOAD_RETRY_DELAY_SECONDS)
                response = await client.get(pdf_url)
            if response.status_code == 200:
                with open(filepath, "wb") as f:
                    f.write(response.content)
                return filepath
        raise Exception(f"Failed to download PDF from {pdf_url}")

    @staticmethod
    def parse_bulletin_text(pdf_path: str) -> dict:
        """
        Extracts raw text from the PDF and parses metadata and wind signal areas.

        Regex patterns for bulletin number, name/category, and coordinates are
        modeled on the `@pagasa-parser/source-pdf` reference implementation
        (github.com/pagasa-parser/source-pdf), adapted to Python and verified
        against a real sample bulletin (docs/TCB#11_kiyapo.pdf — Tropical Storm
        KIYAPO, Bulletin NR. 11).
        """
        with pdfplumber.open(pdf_path) as pdf:
            text = ""
            tables = []
            for page in pdf.pages:
                text += page.extract_text() or ""
                tables.extend(page.extract_tables())

        # 1. Parse Bulletin Number (and final-bulletin marker)
        # Real bulletins abbreviate to "NR." (e.g. "BULLETIN NR. 11"), not just "No."
        # PAGASA appends a trailing "F" to the number on a typhoon's last bulletin
        # (e.g. "NR. 21F" for Francisco) — this is the actual, confirmed signal that
        # no more bulletins will follow, not any particular closing-sentence wording.
        bulletin_no_match = re.search(r"Tropical\s+Cyclone\s+Bulletin\s+N[ro]\.\s+(\d+)([A-Za-z]?)", text, re.IGNORECASE)
        bulletin_no = int(bulletin_no_match.group(1)) if bulletin_no_match else 1
        is_final = bool(bulletin_no_match and bulletin_no_match.group(2).upper() == "F")

        # 2. Parse Category, Typhoon Name, and International Name from the title
        # line itself (e.g. "Tropical Storm KIYAPO (NOUL)" or 'TYPHOON "LEON"'),
        # rather than scanning the whole document for a category keyword — the
        # word "typhoon" can legitimately appear elsewhere in the forecast prose
        # (e.g. "may be upgraded... reach typhoon category") even when the storm's
        # *current* category is something else, which used to misclassify it.
        # Philippine local storm names are always a single word — bounded to one
        # word (no \s) so a following word on the same line can't be swallowed
        # into the name (this used to capture e.g. "GARDO Issued at" as the name).
        # Real PAGASA PDFs quote names with Unicode "smart quotes" (“/”),
        # not straight ASCII quotes -- confirmed via `pdftotext` on a live
        # bulletin, where a bare ["']? here silently failed to match at all
        # (the curly quote isn't in that class, and since it directly precedes
        # the name, the whole match fails rather than just skipping it).
        QUOTES = "[\"'“”‘’]?"
        title_match = re.search(
            r"^\s*(SUPER TYPHOON|TYPHOON|TROPICAL STORM|SEVERE TROPICAL STORM|TROPICAL DEPRESSION)"
            r"\s+" + QUOTES + r"([A-Z][A-Z\-]*)" + QUOTES + r"(?:\s*\(([A-Z][A-Z\-]*)\))?",
            text,
            re.IGNORECASE | re.MULTILINE,
        )
        # A storm's final bulletin can instead be titled "Low Pressure Area
        # (formerly "NAME")" once it's weakened below tropical depression
        # strength — doesn't match any of the categories above at all, which
        # used to fall through to a literal "UNKNOWN" typhoon/category,
        # silently forking that storm's later bulletins onto a fake shared
        # "UNKNOWN" Typhoon row instead of reuniting with its real one.
        # Confirmed against a live PAGASA bulletin (TCB#13_luis.pdf, NR. 13F,
        # "Low Pressure Area (formerly “LUIS”)").
        lpa_match = None if title_match else re.search(
            r"^\s*Low\s+Pressure\s+Area\s*\(formerly\s+" + QUOTES + r"([A-Z][A-Z\-]*)" + QUOTES + r"\)",
            text,
            re.IGNORECASE | re.MULTILINE,
        )
        if title_match:
            category = title_match.group(1).title()
            typhoon_name = title_match.group(2).strip()
            international_name = title_match.group(3) if title_match.group(3) else None
        elif lpa_match:
            category = "Low Pressure Area"
            typhoon_name = lpa_match.group(1).strip()
            international_name = None
            # A storm that has weakened into an LPA gets no further TCBs, so
            # this is always its last bulletin -- mark it final even if the
            # "F" suffix is missing. Every LPA bulletin on the live index so
            # far (LUIS 13F, MAYMAY 17F, JOSIE 3F, NENENG 9F) also carries
            # the "F", so this only matters if PAGASA ever omits it.
            is_final = True
        else:
            category = "UNKNOWN"
            typhoon_name = "UNKNOWN"
            international_name = None

        # 3. Parse Max Winds and Gusts
        winds_match = re.search(r"maximum\s+sustained\s+winds\s+of\s+(\d+)\s+km/h", text, re.IGNORECASE)
        gusts_match = re.search(r"gustiness\s+of\s+up\s+to\s+(\d+)\s+km/h", text, re.IGNORECASE)

        max_winds = int(winds_match.group(1)) if winds_match else None
        gustiness = int(gusts_match.group(1)) if gusts_match else None

        # 4. Parse Center Coordinates (Lat, Lon)
        # Real phrasing is a parenthesized "(18.8°N, 122.0°E)" pair, not
        # necessarily immediately preceded by the word "at" — there can be a
        # full clause in between (e.g. "...estimated based on all available
        # data at over the coastal waters of ... (18.8°N, 122.0°E)").
        coords_match = re.search(r"([0-9.]+)\s*°\s*([NS]),\s*([0-9.]+)\s*°\s*([EW])", text, re.IGNORECASE)
        lat = float(coords_match.group(1)) if coords_match else 0.0
        lon = float(coords_match.group(3)) if coords_match else 0.0

        # 4b. Parse Issued-At Timestamp
        # Standard PAGASA phrasing: "Issued at 5:00 PM, 15 October 2024" (wording around
        # the date varies between bulletins, so this is intentionally loose — falls back
        # to None, which callers treat as "use the current time" rather than guessing).
        # The stated time is always Philippine Standard Time (PHT/UTC+8), never UTC.
        issued_at = None
        issued_match = re.search(
            r"Issued\s+at\s+(\d{1,2}):(\d{2})\s*(AM|PM)[^,\d]*,?\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
            text,
            re.IGNORECASE,
        )
        if issued_match:
            hour, minute, meridiem, day, month_name, year = issued_match.groups()
            try:
                issued_at = datetime.strptime(
                    f"{day} {month_name} {year} {hour}:{minute} {meridiem.upper()}",
                    "%d %B %Y %I:%M %p",
                ).replace(tzinfo=PHT)
            except ValueError:
                issued_at = None

        # 5. Extract wind-signal areas from PAGASA's actual TCWS table (per
        # signal level, ALL THREE island columns — Luzon, Visayas, Mindanao).
        # Only Mindanao is matched against AdminBoundary / feeds exposure and
        # indemnity calculations (this project's insured farms are all PCIC
        # Region X per PROJECT_CONTEXT.md); Luzon/Visayas are captured too, for
        # a GIS specialist to see a typhoon's full national footprint, even
        # though they're outside the insured area. This replaces the old
        # approach of regex-scanning the flattened prose for "Signal No. X"
        # markers, which had no way to distinguish the real TCWS table from a
        # narrative sentence merely *mentioning* a signal number (e.g. "The
        # hoisting of Wind Signal No. 3 is not ruled out should KIYAPO
        # intensify...") — confirmed against docs/TCB#11_kiyapo.pdf, whose real
        # TCWS table is `TCWS No. | Luzon | Visayas | Mindanao`, one row per
        # signal level, with "-" in a column when no areas apply there.
        # signals_data: level -> {island_group: cell_text}, island_group
        # 0=Luzon, 1=Visayas, 2=Mindanao (PAGASA's fixed column order).
        signals_data: dict[int, dict[int, str]] = {}
        for table in tables:
            header_row_idx = None
            island_cols: dict[int, int] = {}  # island_group -> column index
            for row_idx, row in enumerate(table[:3]):  # header is within the first couple of rows
                cells = [(cell or "").strip().lower() for cell in row]
                if any("mindanao" in cell for cell in cells):
                    header_row_idx = row_idx
                    for name, group in (("luzon", 0), ("visayas", 1), ("mindanao", 2)):
                        for i, cell in enumerate(cells):
                            if name in cell:
                                island_cols[group] = i
                                break
                    break
            if header_row_idx is None:
                continue  # not the TCWS table

            current_level = None
            for row in table[header_row_idx + 1:]:
                if not row:
                    continue
                first_cell = (row[0] or "").strip()
                level_match = re.match(r"(\d)", first_cell)
                if level_match:
                    current_level = int(level_match.group(1))
                if current_level is None:
                    continue
                for group, col in island_cols.items():
                    if col >= len(row):
                        continue
                    cell_text = (row[col] or "").strip()
                    if not cell_text or cell_text == "-":
                        continue
                    level_signals = signals_data.setdefault(current_level, {})
                    level_signals[group] = (level_signals.get(group, "") + "\n" + cell_text).strip()

        # 6. PAGASA's explicit "no signal" statement -- a bulletin for a storm
        # far from land has no TCWS table rows, only this sentence (confirmed
        # on TCB#11_pilandok.pdf, 2026-09-30). Lets the viewer say "No Wind
        # Signal Is Raised" instead of the ambiguous "No Signal Data".
        no_signal_hoisted = not signals_data and bool(
            re.search(r"No\s+Wind\s+Signal\s+is\s+currently\s+hoisted", text, re.IGNORECASE)
        )

        return {
            "typhoon_name": typhoon_name,
            "international_name": international_name,
            "bulletin_count": bulletin_no,
            "is_final": is_final,
            "category": category,
            "max_sustained_winds": max_winds,
            "gustiness": gustiness,
            "latitude": lat,
            "longitude": lon,
            "issued_at": issued_at,
            "signals": signals_data,
            "no_signal_hoisted": no_signal_hoisted,
            "raw_text": text
        }

    @classmethod
    async def scrape_and_save_all(cls, db: Session, temp_dir: str = "temp_bulletins") -> list[dict]:
        """
        Fetches all active PAGASA bulletin PDF links, downloads/parses/saves each one,
        and returns [{"tcb_id", "title", "bulletin_count"}, ...] for whichever were
        processed. Returns [] if there are no active links or every download/parse
        attempt fails — never raises for a per-link failure, since callers (the manual
        /parse route, and the scheduled background job) each decide separately whether
        an empty result is worth surfacing as an error. Does propagate
        `PagasaScrapeError` if the PAGASA portal itself couldn't be reached at all —
        deliberately not caught here, so callers know a poll attempt didn't actually
        happen rather than silently treating it as "nothing new."
        """
        links = await cls.fetch_active_bulletin_links()
        bulletins_created = []
        for link in links:
            try:
                pdf_path = await cls.download_bulletin_pdf(link, temp_dir)
                parsed_data = cls.parse_bulletin_text(pdf_path)
                bulletin = cls.save_bulletin_to_db(parsed_data, db)

                if os.path.exists(pdf_path):
                    os.remove(pdf_path)

                # Only cross-reference farms against the typhoon-wide exposure
                # summary once this typhoon's bulletins are confirmed complete
                # (a trailing "F" on the bulletin number) — not after every
                # single bulletin. Reverts the earlier "run on every bulletin"
                # behavior per Fabio's explicit decision; see FUNCTION_CHANGES.md.
                if parsed_data.get("is_final"):
                    try:
                        AssessmentService.calculate_for_bulletin(bulletin.typhoon_id, bulletin.tcb_id, db)
                    except ValueError:
                        pass  # shouldn't happen (bulletin/typhoon just saved together), but don't crash the scrape loop over it

                bulletins_created.append({
                    "tcb_id": bulletin.tcb_id,
                    "title": bulletin.title,
                    "bulletin_count": bulletin.bulletin_count,
                    "is_final": parsed_data.get("is_final", False),
                })
            except httpx.TimeoutException:
                # PAGASA being slow is expected, not a bug -- one line instead
                # of a full traceback. Retried on the next scheduled poll.
                db.rollback()
                logger.warning("PAGASA PDF download timed out (after retry): %s", unquote(link.rsplit("/", 1)[-1]))
            except Exception as e:
                db.rollback()
                logger.exception("Error processing PDF link %s", link)

        return bulletins_created

    @classmethod
    def get_or_create_typhoon(cls, name: str, reference_time: datetime, db: Session) -> Typhoon:
        """
        Finds the Typhoon `name` belongs to, scoped to one with a bulletin within
        the last 30 days of `reference_time` — not just a bare name match — since
        PAGASA's local-name list rotates and reuses names across separate seasons,
        so an unscoped match would wrongly merge unrelated storm events. Any
        bulletin number (1, 2, ... 10, ...) for an active typhoon still lands well
        inside this rolling window, since consecutive bulletins for the same event
        are issued every few hours, not weeks apart.

        Creates a new Typhoon row (is_active=False) if no such match exists —
        is_active is no longer set here; PagasaStatusService's severe-weather-
        bulletin page check is now the sole source of truth for it, and typically
        confirms/sets it True moments later in the same scrape cycle.

        Shared by TCB ingestion (save_bulletin_to_db, below) and
        PagasaStatusService's status-page sync, so both sides of the PAGASA site
        agree on which Typhoon row a given name refers to.
        """
        window_start = reference_time - timedelta(days=30)

        typhoon = (
            db.query(Typhoon)
            .join(TropicalCycloneBulletin, TropicalCycloneBulletin.typhoon_id == Typhoon.typhoon_id)
            .filter(
                func.lower(Typhoon.name) == name.lower(),
                TropicalCycloneBulletin.issued_at >= window_start,
            )
            .order_by(TropicalCycloneBulletin.issued_at.desc())
            .first()
        )

        if not typhoon:
            typhoon = Typhoon(name=name, year=reference_time.year, is_active=False)
            db.add(typhoon)
            db.commit()
            db.refresh(typhoon)

        return typhoon

    @classmethod
    def save_bulletin_to_db(cls, parsed_data: dict, db: Session) -> TropicalCycloneBulletin:
        """
        Saves parsed bulletin data to the PostGIS database.
        """
        reference_time = parsed_data.get("issued_at") or datetime.now(timezone.utc)
        typhoon = cls.get_or_create_typhoon(parsed_data["typhoon_name"], reference_time, db)

        # 1. Check if this Bulletin count already exists for this typhoon
        bulletin = db.query(TropicalCycloneBulletin).filter(
            TropicalCycloneBulletin.typhoon_id == typhoon.typhoon_id,
            TropicalCycloneBulletin.bulletin_count == parsed_data["bulletin_count"]
        ).first()

        signals = parsed_data.get("signals") or {}
        max_signal_level, tcws_areas = _raw_tcws_columns(signals, parsed_data.get("no_signal_hoisted", False))

        if not bulletin:
            # Create geometry Point
            center_geom = WKTElement(f"POINT({parsed_data['longitude']} {parsed_data['latitude']})", srid=4326)

            bulletin = TropicalCycloneBulletin(
                typhoon_id=typhoon.typhoon_id,
                title=f"Bulletin No. {parsed_data['bulletin_count']} for {typhoon.name}",
                bulletin_count=parsed_data["bulletin_count"],
                category=parsed_data["category"],
                max_sustained_winds=parsed_data["max_sustained_winds"],
                gustiness=parsed_data["gustiness"],
                issued_at=parsed_data.get("issued_at") or datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc),  # Expiry date placeholder — PAGASA bulletins don't reliably state their own expiry
                center_geom=center_geom,
                max_signal_level=max_signal_level,
                tcws_areas=tcws_areas,
                is_final=parsed_data.get("is_final", False),
            )
            db.add(bulletin)
            db.commit()
            db.refresh(bulletin)

            # 2. Parse and seed tcb_signals
            cls._seed_tcb_signals(bulletin, signals, db)
            db.commit()
        elif bulletin.max_signal_level is None and max_signal_level is not None:
            # One-time backfill for a bulletin saved before the raw TCWS
            # columns existed (2026-09-30) -- signals used to be seeded only on
            # first insert, so re-scraping/re-uploading its PDF never filled
            # them in. Guarded on max_signal_level IS NULL so this runs once
            # per bulletin, not on every scheduled poll that sees it again.
            bulletin.max_signal_level = max_signal_level
            bulletin.tcws_areas = tcws_areas
            already_seeded = db.query(TcbSignal).filter(TcbSignal.tcb_id == bulletin.tcb_id).first()
            if already_seeded is None:
                cls._seed_tcb_signals(bulletin, signals, db)
            db.commit()

        # Separate from the backfill above (not an elif): flags an
        # already-saved bulletin as final when a re-scrape/re-upload of its PDF
        # says so -- covers bulletins saved before is_final was stored
        # (2026-10-09). Only ever flips False -> True.
        if parsed_data.get("is_final") and not bulletin.is_final:
            bulletin.is_final = True
            db.commit()

        return bulletin

    @staticmethod
    def _seed_tcb_signals(bulletin: TropicalCycloneBulletin, signals: dict, db: Session) -> None:
        """
        Adds a TcbSignal row for every AdminBoundary (province, municipality)
        a TCWS cell resolves to (see match_tcws_cell). Caller commits.

        Loads distinct (province, municipality) pairs only -- not
        db.query(AdminBoundary).all(), which at nationwide scale is ~42k
        barangay rows (with geometry) per bulletin just to derive ~1.6k pairs.
        """
        if not signals:
            return
        pairs = db.query(AdminBoundary.province, AdminBoundary.municipality).distinct().all()
        municipalities_by_province: dict[str, set[str]] = {}
        for province, municipality in pairs:
            municipalities_by_province.setdefault(province, set()).add(municipality)

        for level, island_texts in signals.items():
            for group, cell_text in island_texts.items():
                if not cell_text:
                    continue
                # match_tcws_cell already dedupes on (province, municipality)
                # -- province included, so same-named towns in different
                # provinces (e.g. multiple "Santa Cruz") are both kept.
                for province, municipality in match_tcws_cell(cell_text, municipalities_by_province):
                    db.add(TcbSignal(
                        tcb_id=bulletin.tcb_id,
                        signal_level=level,
                        island_group=group,
                        area_name=municipality,
                        province=province,
                    ))


def _raw_tcws_columns(signals: dict, no_signal_hoisted: bool = False) -> tuple[int | None, dict | None]:
    """parse_bulletin_text()'s {level: {island_group: text}} -> the bulletin's
    max_signal_level / tcws_areas columns (JSON object keys must be strings).
    max_signal_level 0 = PAGASA stated no wind signal is hoisted; None = no
    signal information found at all."""
    if not signals:
        return (0 if no_signal_hoisted else None), None
    tcws_areas = {
        str(level): {str(group): text for group, text in island_texts.items()}
        for level, island_texts in signals.items()
    }
    return max(signals), tcws_areas


_PAREN_RE = re.compile(r"\(([^()]*)\)")


@functools.lru_cache(maxsize=8192)
def _name_re(name: str) -> re.Pattern:
    # Whole-name match, not substring -- nationwide, plain `in` checks give
    # false hits ("Cagayan" in "Cagayan de Oro", "Samar" in "Northern Samar",
    # "Bay" in "Bayombong").
    return re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)", re.IGNORECASE)


def _municipality_aliases(municipality: str) -> list[str]:
    # PSGC spells cities "City of Gingoog"; PAGASA writes "Gingoog City" or
    # just "Gingoog".
    aliases = [municipality]
    city_match = re.match(r"City of (.+)$", municipality, re.IGNORECASE)
    if city_match:
        base = city_match.group(1)
        aliases += [f"{base} City", base]
    return aliases


def _mentions(text: str, name: str) -> bool:
    return any(_name_re(alias).search(text) for alias in _municipality_aliases(name))


def match_tcws_cell(cell_text: str, municipalities_by_province: dict[str, set[str]]) -> list[tuple[str, str]]:
    """
    Resolves one TCWS table cell to AdminBoundary (province, municipality)
    pairs. PAGASA's cell phrasing is a comma-separated list of provinces,
    where a partially-affected province is followed by a parenthetical list
    of its municipalities, e.g.:

        "Batanes, the northern portion of Cagayan (Santa Ana, Gonzaga)"

    - Province followed by a "( ... )" list -> only the listed municipalities.
    - Province named with no list ("Batanes") -> ALL of its municipalities
      (the whole province is under the signal). Previously this matched
      nothing, since no municipality name appeared in the text.
    - Province names appearing *inside* a parenthetical are ignored as
      province mentions (e.g. "Misamis Oriental (Cagayan de Oro City)" must
      not also count as the province "Cagayan").
    - Independent/highly urbanized cities are stored with province ==
      municipality (see scripts/convert_psgc_publication.py). They are
      matched by name anywhere in the cell, including inside a parenthetical,
      since PAGASA lists them under their geographic province.
    """
    paren_spans = [(m.start(), m.end()) for m in _PAREN_RE.finditer(cell_text)]

    def in_paren(pos: int) -> bool:
        return any(start <= pos < end for start, end in paren_spans)

    # Longest names first, so "Northern Samar" claims its span before "Samar".
    claimed: list[tuple[int, int, str]] = []
    for province in sorted(municipalities_by_province, key=len, reverse=True):
        for m in _name_re(province).finditer(cell_text):
            if in_paren(m.start()):
                continue
            if any(m.start() < end and start < m.end() for start, end, _ in claimed):
                continue
            claimed.append((m.start(), m.end(), province))
    claimed.sort()

    results: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(province: str, municipality: str) -> None:
        if (province, municipality) not in seen:
            seen.add((province, municipality))
            results.append((province, municipality))

    for i, (_, end, province) in enumerate(claimed):
        # A province's own "( ... )" list sits between its name and the next
        # province mention or top-level comma/semicolon -- stopping only at
        # the next province would let "Batanes" borrow "Cagayan (Santa Ana)"'s
        # list whenever Cagayan itself isn't a loaded boundary.
        segment_end = claimed[i + 1][0] if i + 1 < len(claimed) else len(cell_text)
        for pos in range(end, segment_end):
            if cell_text[pos] in ",;" and not in_paren(pos):
                segment_end = pos
                break
        listed = ", ".join(_PAREN_RE.findall(cell_text[end:segment_end]))
        for municipality in sorted(municipalities_by_province[province]):
            if not listed or _mentions(listed, municipality):
                add(province, municipality)

    for province, municipalities in municipalities_by_province.items():
        if municipalities == {province} and _mentions(cell_text, province):
            add(province, province)

    return results
