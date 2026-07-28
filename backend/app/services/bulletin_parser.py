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
from app.services.exposure_calculator import ExposureCalculatorService

# Base URL for PAGASA tropical cyclone bulletins (mock or real index page)
PAGASA_INDEX_URL = "https://pubfiles.pagasa.dost.gov.ph/tamss/weather/bulletin/"

# Real PAGASA bulletin filenames follow this pattern (e.g. "TCB#11_kiyapo.pdf",
# or "TCB#21F_francisco.pdf" for a typhoon's final bulletin — the same trailing
# "F" convention used in the bulletin number inside the PDF text itself).
ACTIVE_LINK_NAME_RE = re.compile(r"TCB#\d+[A-Za-z]?_([A-Za-z]+)\.pdf", re.IGNORECASE)


class PagasaScrapeError(Exception):
    """
    Raised when the PAGASA bulletin index couldn't actually be checked (network
    failure, non-200 response) — distinct from a successful check that found
    zero active bulletins, which returns an empty list instead. This
    distinction matters for reconciliation (see `_reconcile_active_typhoons`):
    treating a failed check the same as "confirmed nothing active" would wrongly
    auto-close every genuinely ongoing typhoon on a transient network hiccup.
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
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                issued_at = None

        # 5. Extract wind-signal areas from PAGASA's actual TCWS table (per
        # signal level, Mindanao column only — this project is scoped to PCIC
        # Region X / Mindanao per PROJECT_CONTEXT.md, and every AdminBoundary
        # row seeded here is Mindanao by definition). This replaces the old
        # approach of regex-scanning the flattened prose for "Signal No. X"
        # markers, which had no way to distinguish the real TCWS table from a
        # narrative sentence merely *mentioning* a signal number (e.g. "The
        # hoisting of Wind Signal No. 3 is not ruled out should KIYAPO
        # intensify...") — confirmed against docs/TCB#11_kiyapo.pdf, whose real
        # TCWS table is `TCWS No. | Luzon | Visayas | Mindanao`, one row per
        # signal level, with "-" in a column when no areas apply there.
        signals_data: dict[int, str] = {}
        for table in tables:
            mindanao_col = None
            header_row_idx = None
            for row_idx, row in enumerate(table[:3]):  # header is within the first couple of rows
                cells = [(cell or "").strip().lower() for cell in row]
                if any("mindanao" in cell for cell in cells):
                    mindanao_col = next(i for i, cell in enumerate(cells) if "mindanao" in cell)
                    header_row_idx = row_idx
                    break
            if mindanao_col is None:
                continue  # not the TCWS table

            current_level = None
            for row in table[header_row_idx + 1:]:
                if not row:
                    continue
                first_cell = (row[0] or "").strip()
                level_match = re.match(r"(\d)", first_cell)
                if level_match:
                    current_level = int(level_match.group(1))
                if current_level is None or mindanao_col >= len(row):
                    continue
                cell_text = (row[mindanao_col] or "").strip()
                if not cell_text or cell_text == "-":
                    continue
                signals_data[current_level] = (signals_data.get(current_level, "") + "\n" + cell_text).strip()

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
        deliberately not caught here, since that also skips the reconciliation step
        below rather than risk treating "couldn't check" the same as "confirmed empty."
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

                # A final bulletin ("NR. 21F") means no more TCBs will follow for
                # this typhoon — auto-run the exposure summary and the assessment/
                # payout calculation now, instead of waiting on the manual
                # POST /api/bulletins/{tcb_id}/compute-exposure and
                # POST /api/assessments/calculate clicks. Matches the manuscript's
                # database dictionary (p.41: closing a typhoon "triggers the final
                # payout computation").
                if parsed_data.get("is_final"):
                    ExposureCalculatorService.compute_for_typhoon(bulletin.typhoon_id, db)
                    AssessmentService.calculate_for_bulletin(bulletin.typhoon_id, bulletin.tcb_id, db)

                bulletins_created.append({
                    "tcb_id": bulletin.tcb_id,
                    "title": bulletin.title,
                    "bulletin_count": bulletin.bulletin_count,
                    "is_final": parsed_data.get("is_final", False),
                })
            except Exception as e:
                print(f"Error processing PDF link {link}: {e}")

        cls._reconcile_active_typhoons(links, db)
        return bulletins_created

    @classmethod
    def _reconcile_active_typhoons(cls, active_links: list[str], db: Session) -> list[Typhoon]:
        """
        Cross-checks every Typhoon still marked is_active=True against PAGASA's
        current active-bulletin listing (storm name parsed from each link's
        filename — see ACTIVE_LINK_NAME_RE). Closes (is_active=False + auto-runs
        the exposure summary and assessment/payout calculation) any typhoon no
        longer represented there, even if we never saw an explicit final ("F")
        bulletin for it — PAGASA doesn't guarantee one is always published before
        a storm drops off the active list. Only ever called with a
        successfully-fetched `active_links` (see `PagasaScrapeError` above) — an
        empty-but-successful list correctly means "close everything still marked
        active."

        Each typhoon's closing actions are individually try/excepted so one
        typhoon failing to close (e.g. it has no bulletins at all, an edge case)
        doesn't stop the rest of the reconciliation loop from closing others.
        """
        currently_active_names = set()
        for link in active_links:
            match = ACTIVE_LINK_NAME_RE.search(link)
            if match:
                currently_active_names.add(match.group(1).upper())

        closed = []
        for typhoon in db.query(Typhoon).filter(Typhoon.is_active.is_(True)).all():
            if typhoon.name.upper() not in currently_active_names:
                typhoon.is_active = False
                db.commit()
                try:
                    ExposureCalculatorService.compute_for_typhoon(typhoon.typhoon_id, db)
                    latest_bulletin = (
                        db.query(TropicalCycloneBulletin)
                        .filter(TropicalCycloneBulletin.typhoon_id == typhoon.typhoon_id)
                        .order_by(TropicalCycloneBulletin.issued_at.desc())
                        .first()
                    )
                    if latest_bulletin is not None:
                        AssessmentService.calculate_for_bulletin(typhoon.typhoon_id, latest_bulletin.tcb_id, db)
                except Exception as e:
                    print(f"Error closing out typhoon {typhoon.name!r} ({typhoon.typhoon_id}): {e}")
                closed.append(typhoon)
        return closed

    @classmethod
    def save_bulletin_to_db(cls, parsed_data: dict, db: Session) -> TropicalCycloneBulletin:
        """
        Saves parsed bulletin data to the PostGIS database.
        """
        # 1. Get or Create Typhoon
        # Grouped by name (case-insensitive) AND recency, not just calendar year:
        # a bulletin only joins an existing Typhoon if that typhoon has a bulletin
        # within the last 30 days — PAGASA's local-name list rotates and reuses
        # names across separate seasons, so a bare name match across arbitrary
        # time spans would wrongly merge unrelated storm events. Any bulletin
        # number (1, 2, ... 10, ...) for an active typhoon still lands well inside
        # this rolling window, since consecutive bulletins for the same event are
        # issued every few hours, not weeks apart.
        reference_time = parsed_data.get("issued_at") or datetime.now(timezone.utc)
        window_start = reference_time - timedelta(days=30)

        typhoon = (
            db.query(Typhoon)
            .join(TropicalCycloneBulletin, TropicalCycloneBulletin.typhoon_id == Typhoon.typhoon_id)
            .filter(
                func.lower(Typhoon.name) == parsed_data["typhoon_name"].lower(),
                TropicalCycloneBulletin.issued_at >= window_start,
            )
            .order_by(TropicalCycloneBulletin.issued_at.desc())
            .first()
        )

        if not typhoon:
            typhoon = Typhoon(
                name=parsed_data["typhoon_name"],
                year=reference_time.year,
                is_active=True
            )
            db.add(typhoon)
            db.commit()
            db.refresh(typhoon)

        # 1b. A bulletin number with a trailing "F" (e.g. "NR. 21F") is PAGASA's
        # own signal that no more bulletins will follow for this typhoon.
        if parsed_data.get("is_final") and typhoon.is_active:
            typhoon.is_active = False
            db.commit()

        # 2. Check if this Bulletin count already exists for this typhoon
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

            # 3. Parse and seed tcb_signals
            # Load boundaries to check for affected provinces & municipalities
            boundaries = db.query(AdminBoundary).all()
            
            for level, signal_text in parsed_data["signals"].items():
                seen_areas = set()
                for b in boundaries:
                    # If province and municipality appear in the signal block, it is under signal
                    prov_match = b.province.lower() in signal_text.lower()
                    mun_match = b.municipality.lower() in signal_text.lower()
                    
                    if prov_match and mun_match:
                        # Determine island group (Luzon = 0, Visayas = 1, Mindanao = 2)
                        # Bukidnon, Misamis Oriental, Lanao del Norte etc. belong to Mindanao (Region X)
                        island_group = 2 
                        
                        area_key = (level, b.municipality)
                        if area_key not in seen_areas:
                            seen_areas.add(area_key)
                            tcb_signal = TcbSignal(
                                tcb_id=bulletin.tcb_id,
                                signal_level=level,
                                island_group=island_group,
                                area_name=b.municipality
                            )
                            db.add(tcb_signal)
            db.commit()
            
        return bulletin
