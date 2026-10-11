import re
import asyncio
import logging
import os
import unicodedata
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

# TCWS table parsing (see parse_bulletin_text step 5). A signal cell reads
# "2\nWind threat:\nGale-force\nwinds"; the (?!\d) keeps "12-Hour Forecast"
# out, and a bare "2" (older layout) is still accepted.
_TCWS_SIGNAL_CELL_RE = re.compile(r"^([1-5])(?!\d)(?:\s*$|\D.*?(?:winds?|hours\)))", re.IGNORECASE | re.DOTALL)
_LEAD_TIME_RE = re.compile(r"Warning\s+lead\s+time\b", re.IGNORECASE)
_DEFAULT_TCWS_COLUMNS = {0: 1, 1: 2, 2: 3}  # island_group -> column, when no header row was seen


def _tcws_header_columns(cells: list[str]) -> dict[int, int] | None:
    lowered = [cell.lower() for cell in cells]
    if not all(name in lowered for name in ("luzon", "visayas", "mindanao")):
        return None
    return {group: lowered.index(name) for name, group in (("luzon", 0), ("visayas", 1), ("mindanao", 2))}


# Wind circulation radius (see parse_bulletin_text step 7), PAGASA's
# "Extent of tropical cyclone winds" line, e.g. "Strong to gale-force winds
# extend outwards up to 500 km from the center" -- "Strong to typhoon-force"
# at a typhoon's peak (OPONG TCB#13-14, 22-23). The storm-force pattern's
# lookbehind keeps "Strong to storm-force winds" from being read as a
# separate storm-force radius.
_WIND_RADIUS_RE = re.compile(
    r"strong(?:\s+to\s+(?:gale|storm|typhoon)[-\s]force)?\s+winds\s+extend\s+outwards?\s+up\s+to\s+([\d,]+)\s*km",
    re.IGNORECASE,
)
_STORM_FORCE_RADIUS_RE = re.compile(
    r"(?<!to\s)(?<!to\n)\b(?:storm|typhoon)[-\s]force\s+winds\s+extend\s+outwards?\s+up\s+to\s+([\d,]+)\s*km",
    re.IGNORECASE,
)
# Track and Intensity Outlook rows: ["12-Hour Forecast\n2:00 AM", "9.7",
# "134.4", "980 km East of Northeastern Mindanao"] (OPONG TCB#1-4).
_FORECAST_ROW_RE = re.compile(r"^\s*\d+\s*-\s*Hour\s+Forecast", re.IGNORECASE)
_COORD_CELL_RE = re.compile(r"^\s*(\d{1,3}(?:\.\d+)?)\s*°?\s*([NSEW])?\s*$", re.IGNORECASE)


def _radius_km(pattern: re.Pattern, text: str) -> int | None:
    match = pattern.search(text)
    return int(match.group(1).replace(",", "")) if match else None


def _forecast_track(tables: list) -> list[dict]:
    """
    Forecast positions from the bulletin's Track and Intensity Outlook table,
    in table order: [{"label", "lat", "lon", "location"}]. A row counts only
    when its first cell is "<N>-Hour Forecast" and it has a lat and a lon cell
    in range for the western Pacific, so other tables (TCWS, hazards) never
    contribute points.
    """
    points = []
    for table in tables:
        for row in table:
            cells = [(cell or "").strip() for cell in (row or [])]
            if not cells or not _FORECAST_ROW_RE.match(cells[0]):
                continue
            numbers = []
            location = None
            for cell in cells[1:]:
                coord = _COORD_CELL_RE.match(cell)
                if coord:
                    numbers.append(float(coord.group(1)))
                elif cell:
                    location = " ".join(cell.split())
            if len(numbers) < 2:
                continue
            lat, lon = numbers[0], numbers[1]
            if not (0 <= lat <= 45 and 90 <= lon <= 180):
                continue
            points.append({
                "label": " ".join(cells[0].split()),
                "lat": lat,
                "lon": lon,
                "location": location,
            })
    return points


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

        # 5. Extract wind-signal areas from PAGASA's TCWS table
        # (`TCWS No. | Luzon | Visayas | Mindanao`, one row per signal level,
        # "-" where no areas apply) -- confirmed against docs/TCB#11_kiyapo.pdf.
        # Rows are found by their signal cell ("2 / Wind threat: / Gale-force
        # winds"), the way @pagasa-parser/source-pdf does, NOT by requiring a
        # header row in the same table: pdfplumber splits the table at page
        # breaks, and a continuation table with no header row used to be
        # skipped whole (OPONG TCB#13-16 lost their entire Signal No. 2 row).
        # Requiring all three island names as header cells also stops the
        # track-forecast table ("980 km East of Northeastern Mindanao") from
        # being read as signals 1-9 (OPONG TCB#1-4). Verified 2026-10-11 on
        # OPONG TCB#1-23, MAYMAY TCB#1-17 and KIYAPO TCB#11.
        # signals_data: level -> {island_group: cell_text}, island_group
        # 0=Luzon, 1=Visayas, 2=Mindanao (PAGASA's fixed column order).
        signals_data: dict[int, dict[int, str]] = {}
        island_cols = dict(_DEFAULT_TCWS_COLUMNS)
        for table in tables:
            current_level = None
            for row in table:
                if not row:
                    continue
                cells = [(cell or "").strip() for cell in row]
                header_cols = _tcws_header_columns(cells)
                if header_cols:
                    island_cols = header_cols
                    current_level = None
                    continue
                signal_match = _TCWS_SIGNAL_CELL_RE.match(cells[0])
                if signal_match:
                    current_level = int(signal_match.group(1))
                elif cells[0]:
                    current_level = None  # some other row/table, not a signal level
                if current_level is None:
                    continue
                for group, col in island_cols.items():
                    if col >= len(cells):
                        continue
                    # The "Warning lead time / Range of wind speeds / Potential
                    # impacts" lines share the cell (or the row under it) and
                    # are not areas.
                    cell_text = _LEAD_TIME_RE.split(cells[col])[0].strip()
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

        # 7. Wind circulation radius and forecast track, for the Spatial
        # Analysis typhoon track overlay (2026-10-12). None / [] when the
        # bulletin doesn't state them.
        wind_radius_km = _radius_km(_WIND_RADIUS_RE, text)
        storm_force_radius_km = _radius_km(_STORM_FORCE_RADIUS_RE, text)
        forecast_track = _forecast_track(tables)

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
            "wind_radius_km": wind_radius_km,
            "storm_force_radius_km": storm_force_radius_km,
            "forecast_track": forecast_track,
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
                wind_radius_km=parsed_data.get("wind_radius_km"),
                storm_force_radius_km=parsed_data.get("storm_force_radius_km"),
                forecast_track=parsed_data.get("forecast_track") or None,
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

        # Same idea for the track overlay columns (2026-10-12): fills them in
        # on a re-scrape/re-upload of a bulletin saved before they existed.
        # Only NULL columns are filled, so a later poll never overwrites them.
        track_backfill = {
            "wind_radius_km": parsed_data.get("wind_radius_km"),
            "storm_force_radius_km": parsed_data.get("storm_force_radius_km"),
            "forecast_track": parsed_data.get("forecast_track") or None,
        }
        changed = False
        for column, value in track_backfill.items():
            if value is not None and getattr(bulletin, column) is None:
                setattr(bulletin, column, value)
                changed = True
        if changed:
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

        Levels are matched highest first, and an LGU is only ever added at
        the highest signal it appears under: "the rest of Abra" at Signal 1
        means the Abra LGUs NOT already under Signal 2 (Cristian's decision,
        2026-10-11). Text that resolves to no boundary is logged, never
        dropped silently.
        """
        if not signals:
            return
        pairs = db.query(AdminBoundary.province, AdminBoundary.municipality).distinct().all()
        municipalities_by_province: dict[str, set[str]] = {}
        for province, municipality in pairs:
            municipalities_by_province.setdefault(province, set()).add(municipality)

        for level, group, province, municipality in resolve_tcws_signals(
            signals, municipalities_by_province, log_label=f"TCB {bulletin.tcb_id}",
        ):
            db.add(TcbSignal(
                tcb_id=bulletin.tcb_id,
                signal_level=level,
                island_group=group,
                area_name=municipality,
                province=province,
            ))


def resolve_tcws_signals(
    signals: dict, municipalities_by_province: dict[str, set[str]], log_label: str = "TCB",
) -> list[tuple[int, int, str, str]]:
    """parse_bulletin_text()'s {level: {island_group: text}} ->
    [(signal_level, island_group, province, municipality), ...], one per LGU at
    the highest signal it appears under (see _seed_tcb_signals). Keys may be
    ints or the str keys stored in tcws_areas."""
    rows: list[tuple[int, int, str, str]] = []
    assigned: set[tuple[str, str]] = set()
    for level in sorted(signals, key=int, reverse=True):
        higher = frozenset(assigned)
        for group, cell_text in sorted(signals[level].items(), key=lambda item: int(item[0])):
            if not cell_text:
                continue
            unresolved: list[str] = []
            # Pairs keep their province, so same-named towns in different
            # provinces (e.g. multiple "Santa Cruz") are both kept.
            for pair in match_tcws_cell(cell_text, municipalities_by_province, higher, unresolved):
                if pair not in assigned:
                    assigned.add(pair)
                    rows.append((int(level), int(group), *pair))
            if unresolved:
                logger.warning(
                    "%s Signal No. %s (island group %s): PAGASA text not resolved to a boundary: %s",
                    log_label, level, group, "; ".join(unresolved),
                )
    return rows


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


# ── TCWS area text -> AdminBoundary (province, municipality) ────────────────
# Two steps, after @pagasa-parser/pagasa-parser's AreaExtractor: a cell is
# first split into clauses ("the rest of Abra", "the northern portion of
# Zambales (Candelaria, Masinloc)", "mainland Cagayan", "Masbate including
# Ticao Island"), then each clause's head name is resolved as a province,
# island group or city, and its parenthetical towns only within that
# province. The previous matcher searched the whole cell for every boundary
# name in the country, so "San Juan" listed under La Union also matched City
# of San Juan (NCR), "Isabela" under Negros Occidental matched City of Isabela
# (Basilan), and "the rest of" / "mainland" / island names had no meaning.
# Measured 2026-10-11 against a clause-by-clause reading of OPONG TCB#1-23 and
# MAYMAY TCB#1-17.


def _pairs(province: str, *municipalities: str) -> tuple[tuple[str, str], ...]:
    return tuple((province, municipality) for municipality in municipalities)


# Island groups PAGASA names that are not PSGC provinces, keyed by _fold()ed
# word ("Siargao Island", "Siargao Islands" and "Siargao Isl." all hit
# "siargao"). Their LGUs are also what "mainland {province}" leaves out.
_ISLAND_GROUPS: dict[str, tuple[tuple[str, str], ...]] = {
    "babuyan": _pairs("Cagayan", "Calayan"),
    "calamian": _pairs("Palawan", "Busuanga", "Coron", "Culion", "Linapacan"),
    "cuyo": _pairs("Palawan", "Cuyo", "Agutaya", "Magsaysay"),
    "kalayaan": _pairs("Palawan", "Kalayaan"),
    "lubang": _pairs("Occidental Mindoro", "Lubang", "Looc"),
    "ticao": _pairs("Masbate", "Monreal", "San Jacinto", "San Fernando", "Batuan"),
    "burias": _pairs("Masbate", "San Pascual", "Claveria"),
    "caluya": _pairs("Antique", "Caluya"),
    "polillo": _pairs("Quezon", "Polillo", "Burdeos", "Panukulan", "Patnanungan", "Jomalig"),
    "alabat": _pairs("Quezon", "Alabat", "Perez", "Quezon"),
    "camotes": _pairs("Cebu", "Pilar", "Poro", "San Francisco", "Tudela"),
    "bantayan": _pairs("Cebu", "Bantayan", "Madridejos", "Santa Fe"),
    "mactan": _pairs("Cebu", "Cordova") + _pairs("City of Lapu-Lapu", "City of Lapu-Lapu"),
    "siargao": _pairs(
        "Surigao del Norte", "Burgos", "Dapa", "Del Carmen", "General Luna",
        "Pilar", "San Benito", "San Isidro", "Santa Monica",
    ),
    "bucas grande": _pairs("Surigao del Norte", "Socorro"),
}

# Other PAGASA area names that are not PSGC provinces. NCR LGUs are stored
# with province == municipality (scripts/convert_psgc_publication.py).
_NCR = tuple((lgu, lgu) for lgu in (
    "City of Caloocan", "City of Las Piñas", "City of Makati", "City of Malabon",
    "City of Mandaluyong", "City of Manila", "City of Marikina", "City of Muntinlupa",
    "City of Navotas", "City of Parañaque", "Pasay City", "City of Pasig", "Pateros",
    "Quezon City", "City of San Juan", "City of Taguig", "City of Valenzuela",
))
_NAMED_AREAS: dict[str, tuple[tuple[str, str], ...]] = {
    "metro manila": _NCR,
    "national capital region": _NCR,
    "ncr": _NCR,
    "corregidor": _pairs("Cavite", "City of Cavite"),
}

# PAGASA spellings that differ from PSGC beyond case/accents/hyphens
# (_fold()ed PAGASA name -> PSGC municipality). Seen in OPONG/MAYMAY 2026.
_PAGASA_SPELLINGS = {
    "pinamungahan": "Pinamungajan",
    "pres carlos p garcia": "President Carlos P. Garcia",
    "baliuag": "City of Baliwag",
    "pio v corpuz": "Pio V. Corpus",
}

_DIRECTION = r"(?:(?:extreme|far)\s+)?(?:(?:north|south|east|west){1,2}ern|central)"
_DIRECTION_ONLY_RE = re.compile(rf"^(?:the\s+)?{_DIRECTION}(?:\s*(?:,|and|&)?\s*{_DIRECTION})*$", re.IGNORECASE)
_CLAUSE_RE = re.compile(
    r"^(?:the\s+)?"
    r"(?P<rest>(?:rest|remaining\s+(?:parts?|portions?))\s+of\s+(?:the\s+)?)?"
    # "the northern portion of X"; also "northern mainland Palawan" (OPONG TCB#12)
    rf"(?:(?P<section>{_DIRECTION}(?:\s*(?:,|and|&)?\s*{_DIRECTION})*)\s+(?:(?:portions?|parts?|regions?|sections?)\s+of\s+(?:the\s+)?|(?=mainland\s)))?"
    r"(?P<mainland>mainland\s+)?"
    r"(?P<name>[^()]*?)\s*(?:\((?P<listed>.*)\))?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_COMMA_RE = re.compile(r"[,;]")
_AND_RE = re.compile(r"\s+(?:and|&)\s+", re.IGNORECASE)
_INCLUDING_RE = re.compile(r"\s+including\s+", re.IGNORECASE)
_ISLAND_SUFFIX_RE = re.compile(r"\s+(?:is|isl|islands?)\.?$", re.IGNORECASE)


def _fold(name: str) -> str:
    """Comparison key: case, accents (Castañeda/Castaneda), hyphens
    (Sanchez-Mira/Sanchez Mira), periods (Pres./Pres) and PSGC's "Sto."/"Sta."
    (PSGC "City of Sto. Tomas", PAGASA "Santo Tomas") don't matter."""
    name = unicodedata.normalize("NFKD", name)
    name = "".join(ch for ch in name if not unicodedata.combining(ch)).lower().replace(".", "")
    name = re.sub(r"\bsto\b", "santo", re.sub(r"\bsta\b", "santa", name))
    return re.sub(r"[\s\-]+", " ", name).strip()


def _repair_tcws_text(text: str) -> str:
    # pdfplumber keeps PAGASA's line wraps: "Dinagat\nIslands", "Can-\nAvid".
    text = re.sub(r"-\s*\n\s*", "-", text)
    return re.sub(r"\s+", " ", text).strip().rstrip(".")


def _split_outside_parens(text: str, separator: re.Pattern) -> list[str]:
    depth_at, depth = [], 0
    for ch in text:
        depth_at.append(depth)
        depth = depth + 1 if ch == "(" else max(depth - 1, 0) if ch == ")" else depth
    parts, start = [], 0
    for m in separator.finditer(text):
        if depth_at[m.start()] == 0:
            parts.append(text[start:m.start()])
            start = m.end()
    parts.append(text[start:])
    return [part.strip() for part in parts if part.strip()]


def _merge_dangling_directions(parts: list[str], joiner: str) -> list[str]:
    # "the northern and central portions of X" / "the northern, central and
    # southern portions of X" must not split at the "and" / commas.
    merged: list[str] = []
    for part in parts:
        if merged and _DIRECTION_ONLY_RE.match(merged[-1]):
            merged[-1] = f"{merged[-1]}{joiner}{part}"
        else:
            merged.append(part)
    return merged


def _clauses(cell_text: str) -> list[str]:
    clauses = []
    for item in _merge_dangling_directions(_split_outside_parens(cell_text, _COMMA_RE), ", "):
        item = re.sub(r"^(?:and|&)(?:\s+|$)", "", item, flags=re.IGNORECASE)  # also a stray "and , and" (OPONG TCB#15)
        for part in _merge_dangling_directions(_split_outside_parens(item, _AND_RE), " and "):
            # "Masbate including Ticao Island" -> "Masbate", "Ticao Island"
            head, *included = _split_outside_parens(part, _INCLUDING_RE)
            # "the northern portion of Palawan including Cuyo Islands (Dumaran,
            # ..., El Nido)" (OPONG TCB#20): the list is the portion's, not
            # the islands'.
            moved = re.search(r"\s*(\([^()]*\))$", included[-1]) if included else None
            if moved and "(" not in head and _CLAUSE_RE.match(head).group("section"):
                head = f"{head} {moved.group(1)}"
                included[-1] = included[-1][:moved.start()]
            clauses.extend([head, *included])
    return clauses


def _municipality_aliases(municipality: str) -> list[str]:
    # PSGC spells cities "City of Gingoog" (sometimes "Tuguegarao City");
    # PAGASA writes either form, or just "Gingoog".
    aliases = [municipality]
    city_of = re.search(r"\bCity of (.+)$", municipality, re.IGNORECASE)
    city_suffix = re.match(r"(.+) City$", municipality, re.IGNORECASE)
    if city_of:
        aliases += [f"{city_of.group(1)} City", city_of.group(1)]
    elif city_suffix:
        aliases += [f"City of {city_suffix.group(1)}", city_suffix.group(1)]
    return aliases


class _BoundaryIndex:
    """_fold()ed lookups over one bulletin's (province, municipality) universe."""

    def __init__(self, municipalities_by_province: dict[str, set[str]]):
        # tbl_admin_boundaries can hold one province under two spellings
        # (seen 2026-10-11: "SURIGAO DEL NORTE" / "ALEGRIA" next to "Surigao
        # del Norte" / "Alegria"). Merge them under one spelling, preferring
        # the non-all-caps one -- otherwise the 3-town variant shadowed the
        # 21-town one. exposure_calculator matches case-insensitively, so
        # either spelling reaches the same boundary.
        merged: dict[str, dict[str, str]] = {}  # fold(province) -> fold(municipality) -> municipality
        spelling: dict[str, str] = {}  # fold(province) -> province
        for province in sorted(municipalities_by_province, key=str.isupper):
            key = _fold(province)
            spelling.setdefault(key, province)
            for municipality in sorted(municipalities_by_province[province], key=str.isupper):
                merged.setdefault(key, {}).setdefault(_fold(municipality), municipality)
        self.municipalities_by_province = {spelling[key]: set(muns.values()) for key, muns in merged.items()}

        self.provinces = {_fold(p): p for p in self.municipalities_by_province}
        for province in self.municipalities_by_province:  # "Dinagat Isl." -> Dinagat Islands
            self.provinces.setdefault(_fold(_ISLAND_SUFFIX_RE.sub("", province)), province)
        self.exact: dict[str, dict[str, str]] = {}  # province -> fold(name) -> municipality
        self.alias: dict[str, dict[str, str]] = {}  # province -> fold(alias) -> municipality
        self.cities: dict[str, list[str]] = {}  # fold(alias) -> province==municipality LGUs (HUCs, NCR)
        for province, municipalities in self.municipalities_by_province.items():
            for municipality in municipalities:
                self.exact.setdefault(province, {})[_fold(municipality)] = municipality
                for alias in _municipality_aliases(municipality)[1:]:
                    self.alias.setdefault(province, {}).setdefault(_fold(alias), municipality)
            if municipalities == {province}:
                for alias in _municipality_aliases(province):
                    self.cities.setdefault(_fold(alias), []).append(province)

    def known(self, pairs) -> set[tuple[str, str]]:
        return {(p, m) for p, m in pairs if m in self.municipalities_by_province.get(p, ())}

    def municipality(self, province: str, name: str) -> str | None:
        key = _fold(_ISLAND_SUFFIX_RE.sub("", name))
        key = _fold(_PAGASA_SPELLINGS.get(key, key))
        return self.exact.get(province, {}).get(key) or self.alias.get(province, {}).get(key)

    def city(self, name: str) -> list[str]:
        return self.cities.get(_fold(name), [])

    def area_group(self, name: str) -> set[tuple[str, str]] | None:
        key = _fold(name)
        named = _NAMED_AREAS.get(key) or _NAMED_AREAS.get(_fold(_ISLAND_SUFFIX_RE.sub("", name)))
        if named:
            return self.known(named)
        hits = [pairs for word, pairs in _ISLAND_GROUPS.items() if re.search(rf"\b{word}\b", key)]
        if not hits:
            return None
        return self.known(pair for pairs in hits for pair in pairs)

    def island_lgus(self, province: str) -> set[tuple[str, str]]:
        return {pair for pairs in _ISLAND_GROUPS.values() for pair in pairs if pair[0] == province}


def _listed_names(listed: str) -> list[str]:
    names = []
    for item in _split_outside_parens(listed, _COMMA_RE):
        item = re.sub(r"^(?:and|&)\s+", "", item, flags=re.IGNORECASE)
        names.extend(_split_outside_parens(item, _AND_RE))
    return names


def _resolve_clause(clause: str, index: _BoundaryIndex, higher: frozenset, unresolved: list[str]) -> list[tuple[str, str]]:
    m = _CLAUSE_RE.match(clause)
    name = (m.group("name") if m else "").strip()
    if not m or not name:
        unresolved.append(clause)
        return []
    listed = _listed_names(m.group("listed")) if m.group("listed") else []

    province = index.provinces.get(_fold(name)) or index.provinces.get(_fold(_ISLAND_SUFFIX_RE.sub("", name)))
    if province is not None:
        if listed:
            found = []
            for item in listed:
                municipality = index.municipality(province, item)
                if municipality:
                    found.append((province, municipality))
                elif index.city(item):
                    # An HUC listed under its geographic province, e.g.
                    # "Misamis Oriental (Cagayan de Oro City)" -- PSGC stores
                    # it as its own province.
                    found.extend((city, city) for city in index.city(item))
                elif index.area_group(item):
                    # "Cavite (Corregidor Island, Ternate, ...)" (OPONG TCB#22)
                    found.extend(sorted(index.area_group(item)))
                else:
                    unresolved.append(f"{item} ({province})")
            return found
        pairs = {(province, mun) for mun in index.municipalities_by_province[province]}
        if m.group("mainland"):
            pairs -= index.island_lgus(province)
        if m.group("rest"):
            pairs -= higher
        return sorted(pairs)

    group = index.area_group(name)
    if group is not None:
        if not group:
            unresolved.append(clause)
        elif listed and len({mun for _, mun in group}) > 1:
            # "the southern portion of Siargao Island (Dapa, General Luna)"
            found = []
            for item in listed:
                hit = [(p, mun) for p, mun in group if index.municipality(p, item) == mun]
                if hit:
                    found.extend(hit)
                else:
                    unresolved.append(f"{item} ({name})")
            return found
        # A one-LGU group: every listed island ("Calayan Is., Fuga Is.") is in it.
        return sorted(group - higher if m.group("rest") else group)

    cities = index.city(name)
    if cities:
        return [(city, city) for city in cities]

    unresolved.append(clause)
    return []


def match_tcws_cell(
    cell_text: str,
    municipalities_by_province: dict[str, set[str]],
    higher: frozenset = frozenset(),
    unresolved: list[str] | None = None,
) -> list[tuple[str, str]]:
    """
    Resolves one TCWS table cell to AdminBoundary (province, municipality)
    pairs. PAGASA's cell phrasing is a comma-separated list of clauses:

    - "Batanes" -> ALL of the province's municipalities.
    - "the northern portion of Cagayan (Santa Ana, Gonzaga)" -> only the
      listed municipalities, looked up within that province only (an HUC
      listed there, e.g. "Cagayan de Oro City" under Misamis Oriental, is
      matched as its own province-level city).
    - "the rest of Abra" -> Abra minus `higher` (the pairs already under a
      higher signal in the same bulletin).
    - "mainland Cagayan" -> Cagayan minus its island LGUs (_ISLAND_GROUPS).
    - "Calamian Islands", "Metro Manila", "Masbate including Ticao Island"
      -> the LGUs in _ISLAND_GROUPS / _NAMED_AREAS.
    - "Bacolod City" -> an independent city stored with province ==
      municipality (see scripts/convert_psgc_publication.py).

    Anything that resolves to no boundary is appended to `unresolved` (if
    given) instead of disappearing silently.
    """
    index = _BoundaryIndex(municipalities_by_province)
    unresolved = unresolved if unresolved is not None else []
    results: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for clause in _clauses(_repair_tcws_text(cell_text)):
        for pair in _resolve_clause(clause, index, higher, unresolved):
            if pair not in seen:
                seen.add(pair)
                results.append(pair)
    return results
