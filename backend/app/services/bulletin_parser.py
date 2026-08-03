import re
import os
import httpx
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

# PAGASA states every bulletin's "Issued at" timestamp in Philippine Standard
# Time, not UTC -- a fixed UTC+8 offset (the Philippines observes no DST).
PHT = timezone(timedelta(hours=8))


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
            if href.endswith(".pdf"):
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
        
        async with httpx.AsyncClient(timeout=15.0) as client:
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
        title_match = re.search(
            r"^\s*(TYPHOON|TROPICAL STORM|SEVERE TROPICAL STORM|TROPICAL DEPRESSION)"
            r"\s+[\"']?([A-Z][A-Z\-]*)[\"']?(?:\s*\(([A-Z][A-Z\-]*)\))?",
            text,
            re.IGNORECASE | re.MULTILINE,
        )
        category = title_match.group(1).title() if title_match else "UNKNOWN"
        typhoon_name = title_match.group(2).strip() if title_match else "UNKNOWN"
        international_name = title_match.group(3) if title_match and title_match.group(3) else None

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
            except Exception as e:
                print(f"Error processing PDF link {link}: {e}")

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

    @staticmethod
    def _split_named_areas(cell_text: str) -> list[str]:
        """
        Best-effort split of a PAGASA TCWS cell's free-text area list into
        individual province/region-level phrases — used for Luzon/Visayas,
        which have no AdminBoundary data to validate matches against (unlike
        Mindanao). Strips parenthetical municipality detail (e.g. "the
        northern portion of Cagayan (Santa Ana, Gonzaga, ...)" becomes "the
        northern portion of Cagayan") since keeping it can run well past
        TcbSignal.area_name's varchar(100) limit, then splits the remainder
        on commas. Real PAGASA phrasing confirmed against
        docs/TCB#11_kiyapo.pdf.

        Every cell also carries a fixed boilerplate block after the area list
        itself ("Warning lead time: ...", "Range of wind speeds: ...",
        "Potential impacts of winds: ...") which the Mindanao path never had
        to worry about (it never string-matches a real municipality, so it
        was silently dropped there) but must be cut off here before splitting,
        or it shows up as bogus "area" entries — confirmed against a live
        PAGASA scrape of this same sample bulletin.
        """
        cell_text = re.split(r"Warning lead time", cell_text, maxsplit=1, flags=re.IGNORECASE)[0]
        no_parens = re.sub(r"\([^)]*\)", "", cell_text)
        no_parens = re.sub(r"\s+", " ", no_parens).strip()
        areas: list[str] = []
        for part in no_parens.split(","):
            area = part.strip()
            area = re.sub(r"^(and|including)\s+", "", area, flags=re.IGNORECASE)
            area = area.rstrip(".").strip()
            if area and area not in areas:
                areas.append(area[:100])
        return areas

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
                center_geom=center_geom
            )
            db.add(bulletin)
            db.commit()
            db.refresh(bulletin)

            # 2. Parse and seed tcb_signals
            # Load boundaries to check for affected provinces & municipalities
            boundaries = db.query(AdminBoundary).all()

            for level, island_texts in parsed_data["signals"].items():
                # Mindanao (island_group=2): match against seeded Region X
                # AdminBoundary rows -- unchanged from before, since this is
                # what feeds exposure/indemnity calculations and must stay
                # precise, not best-effort.
                mindanao_text = island_texts.get(2, "")
                if mindanao_text:
                    seen_areas = set()
                    for b in boundaries:
                        prov_match = b.province.lower() in mindanao_text.lower()
                        mun_match = b.municipality.lower() in mindanao_text.lower()

                        if prov_match and mun_match:
                            area_key = (level, b.municipality)
                            if area_key not in seen_areas:
                                seen_areas.add(area_key)
                                db.add(TcbSignal(
                                    tcb_id=bulletin.tcb_id,
                                    signal_level=level,
                                    island_group=2,
                                    area_name=b.municipality,
                                ))

                # Luzon/Visayas: no AdminBoundary data exists to validate
                # against outside Region X -- informational only (a GIS
                # specialist seeing the storm's full national footprint), so
                # this is a best-effort split into province/region-level
                # phrases rather than a validated municipality match.
                for group in (0, 1):
                    cell_text = island_texts.get(group, "")
                    if not cell_text:
                        continue
                    for area_name in cls._split_named_areas(cell_text):
                        db.add(TcbSignal(
                            tcb_id=bulletin.tcb_id,
                            signal_level=level,
                            island_group=group,
                            area_name=area_name,
                        ))
            db.commit()
            
        return bulletin
