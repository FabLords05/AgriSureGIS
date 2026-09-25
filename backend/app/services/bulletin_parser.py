import re
import os
import logging
import httpx
from bs4 import BeautifulSoup
import pdfplumber
from sqlalchemy import func
from sqlalchemy.orm import Session
from geoalchemy2.elements import WKTElement
from datetime import datetime, timezone

from app.models.models import Typhoon, TropicalCycloneBulletin, TcbSignal, AdminBoundary

logger = logging.getLogger(__name__)

# Base URL for PAGASA tropical cyclone bulletins (mock or real index page)
PAGASA_INDEX_URL = "https://pubfiles.pagasa.dost.gov.ph/tamss/weather/bulletin.html"

# ---------------------------------------------------------------------------
# Island group province mappings  (0 = Luzon, 1 = Visayas, 2 = Mindanao)
# ---------------------------------------------------------------------------
LUZON_PROVINCES = {
    "Ilocos Norte", "Ilocos Sur", "La Union", "Pangasinan", "Batanes", "Cagayan",
    "Isabela", "Nueva Vizcaya", "Quirino", "Aurora", "Bataan", "Bulacan",
    "Nueva Ecija", "Pampanga", "Tarlac", "Zambales", "Metro Manila", "Rizal",
    "Laguna", "Batangas", "Cavite", "Quezon", "Marinduque", "Occidental Mindoro",
    "Oriental Mindoro", "Palawan", "Romblon", "Albay", "Camarines Norte",
    "Camarines Sur", "Catanduanes", "Masbate", "Sorsogon",
}

VISAYAS_PROVINCES = {
    "Aklan", "Antique", "Capiz", "Guimaras", "Iloilo", "Negros Occidental",
    "Bohol", "Cebu", "Negros Oriental", "Siquijor", "Biliran", "Eastern Samar",
    "Leyte", "Northern Samar", "Samar", "Southern Leyte",
}

# Ordered longest-first so "severe tropical storm" is matched before "tropical storm"
CATEGORY_KEYWORDS = {
    "severe tropical storm": "Severe Tropical Storm",
    "typhoon": "Typhoon",
    "tropical storm": "Tropical Storm",
    "tropical depression": "Tropical Depression",
}


def get_island_group(province: str) -> int:
    """Return the island group code for a given province name.

    Returns:
        0 — Luzon
        1 — Visayas
        2 — Mindanao (default / fallback)
    """
    p = province.strip()
    if p in LUZON_PROVINCES:
        return 0
    if p in VISAYAS_PROVINCES:
        return 1
    return 2


class BulletinParserService:
    @staticmethod
    async def fetch_active_bulletin_links() -> list:
        """
        Scrapes the PAGASA bulletin portal to find PDF links to active tropical cyclone bulletins.
        Returns an empty list on any network or parsing failure.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(PAGASA_INDEX_URL)
                if response.status_code != 200:
                    logger.warning(
                        "PAGASA index returned HTTP %s", response.status_code
                    )
                    return []

                soup = BeautifulSoup(response.text, "html.parser")
                base_url = PAGASA_INDEX_URL.rsplit("/", 1)[0]
                pdf_links = []

                for link in soup.find_all("a", href=True):
                    href = link["href"]
                    if href.endswith(".pdf") and "bulletin" in href.lower():
                        # Resolve relative links to absolute URLs
                        if not href.startswith("http"):
                            href = f"{base_url}/{href}"
                        pdf_links.append(href)

                return pdf_links

        except httpx.TimeoutException:
            logger.error(
                "Timed out fetching PAGASA bulletin index", exc_info=True
            )
            return []
        except Exception as e:
            logger.error("Error scraping PAGASA links: %s", e, exc_info=True)
            return []

    @staticmethod
    async def download_bulletin_pdf(pdf_url: str, output_dir: str) -> str:
        """
        Downloads the PDF from the PAGASA URL and saves it locally using chunked
        streaming to avoid loading the entire file into memory at once.

        Raises:
            ValueError: if the URL does not point to a .pdf file.
            RuntimeError: on HTTP errors or network timeouts.
        """
        filename = pdf_url.split("/")[-1]
        if not filename.endswith(".pdf"):
            raise ValueError(f"URL does not point to a PDF: {pdf_url}")

        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, filename)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream("GET", pdf_url) as response:
                    response.raise_for_status()
                    with open(filepath, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=8192):
                            f.write(chunk)
            return filepath
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Timed out downloading PDF from {pdf_url}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"HTTP {exc.response.status_code} error downloading PDF from {pdf_url}"
            ) from exc

    @staticmethod
    def parse_bulletin_text(pdf_path: str) -> dict:
        """
        Extracts raw text from the PDF and parses metadata and wind signal areas.
        """
        with pdfplumber.open(pdf_path) as pdf:
            text = ""
            for page in pdf.pages:
                text += page.extract_text() or ""

        # 1. Parse Bulletin Number
        bulletin_no_match = re.search(
            r"Tropical\s+Cyclone\s+Bulletin\s+No\.\s+(\d+)", text, re.IGNORECASE
        )
        bulletin_no = int(bulletin_no_match.group(1)) if bulletin_no_match else 1

        # 2. Parse Typhoon Name — prefer the quoted form to avoid over-capture,
        #    fall back to the first all-caps word immediately after the storm type.
        name_match = re.search(
            r'(?:TYPHOON|TROPICAL STORM|SEVERE TROPICAL STORM|TROPICAL DEPRESSION)\s+"([A-Z\-]+)"',
            text,
            re.IGNORECASE,
        )
        if not name_match:
            name_match = re.search(
                r"(?:TYPHOON|TROPICAL STORM|SEVERE TROPICAL STORM|TROPICAL DEPRESSION)\s+([A-Z][A-Z\-]+)",
                text,
                re.IGNORECASE,
            )
        typhoon_name = name_match.group(1).strip() if name_match else "UNKNOWN"

        # 3. Parse Max Winds and Gusts
        winds_match = re.search(
            r"maximum\s+sustained\s+winds\s+of\s+(\d+)\s+km/h", text, re.IGNORECASE
        )
        gusts_match = re.search(
            r"gustiness\s+of\s+up\s+to\s+(\d+)\s+km/h", text, re.IGNORECASE
        )
        max_winds = int(winds_match.group(1)) if winds_match else None
        gustiness = int(gusts_match.group(1)) if gusts_match else None

        # 4. Parse Center Coordinates — returns None if absent to avoid a
        #    silent 0.0, 0.0 fallback being stored as a valid GIS point.
        coords_match = re.search(
            r"at\s+(\d+\.\d+)\s*°?\s*N,\s*(\d+\.\d+)\s*°?\s*E", text, re.IGNORECASE
        )
        if not coords_match:
            coords_match = re.search(
                r"(\d+\.\d+)\s*N,\s*(\d+\.\d+)\s*E", text, re.IGNORECASE
            )

        if coords_match:
            lat = float(coords_match.group(1))
            lon = float(coords_match.group(2))
        else:
            logger.warning(
                "Could not parse coordinates from bulletin PDF: %s", pdf_path
            )
            lat = None
            lon = None

        # 5. Parse Category — ordered so "severe tropical storm" is checked
        #    before the shorter "tropical storm" substring it contains.
        category_match = re.search(
            r"(severe tropical storm|typhoon|tropical storm|tropical depression)",
            text,
            re.IGNORECASE,
        )
        category = (
            CATEGORY_KEYWORDS.get(category_match.group(1).lower(), "Unknown")
            if category_match
            else "Unknown"
        )

        # 6. Extract Signal Text Blocks (Signal No. 1 to 5)
        signals_data = {}
        signal_markers = []
        for level in range(1, 6):
            marker = re.search(rf"Signal\s+No\.\s+{level}", text, re.IGNORECASE)
            if marker:
                signal_markers.append((level, marker.start()))

        signal_markers.sort(key=lambda x: x[1])

        for i, (level, start_idx) in enumerate(signal_markers):
            end_idx = (
                signal_markers[i + 1][1]
                if i + 1 < len(signal_markers)
                else len(text)
            )
            signals_data[level] = text[start_idx:end_idx]

        return {
            "typhoon_name": typhoon_name,
            "bulletin_count": bulletin_no,
            "category": category,
            "max_sustained_winds": max_winds,
            "gustiness": gustiness,
            "latitude": lat,
            "longitude": lon,
            "signals": signals_data,
            "raw_text": text,
        }

    @classmethod
    def save_bulletin_to_db(
        cls, parsed_data: dict, db: Session
    ) -> TropicalCycloneBulletin:
        """
        Saves parsed bulletin data to the PostGIS database within a single
        transaction (one db.commit() at the end) to prevent partial state on failure.
        """
        year = datetime.now().year

        # 1. Get or create Typhoon — flush only, commit at end
        typhoon = (
            db.query(Typhoon)
            .filter(
                func.lower(Typhoon.name) == parsed_data["typhoon_name"].lower(),
                Typhoon.year == year,
            )
            .first()
        )

        if not typhoon:
            typhoon = Typhoon(
                name=parsed_data["typhoon_name"],
                year=year,
                is_active=True,
            )
            db.add(typhoon)
            db.flush()  # Assigns typhoon_id without committing
            db.refresh(typhoon)

        # 2. Check if this bulletin count already exists (idempotent)
        bulletin = (
            db.query(TropicalCycloneBulletin)
            .filter(
                TropicalCycloneBulletin.typhoon_id == typhoon.typhoon_id,
                TropicalCycloneBulletin.bulletin_count == parsed_data["bulletin_count"],
            )
            .first()
        )

        if not bulletin:
            # Build geometry only when coordinates are available
            if (
                parsed_data["latitude"] is not None
                and parsed_data["longitude"] is not None
            ):
                center_geom = WKTElement(
                    f"POINT({parsed_data['longitude']} {parsed_data['latitude']})",
                    srid=4326,
                )
            else:
                center_geom = None

            bulletin = TropicalCycloneBulletin(
                typhoon_id=typhoon.typhoon_id,
                title=f"Bulletin No. {parsed_data['bulletin_count']} for {typhoon.name}",
                bulletin_count=parsed_data["bulletin_count"],
                category=parsed_data["category"],
                max_sustained_winds=parsed_data["max_sustained_winds"],
                gustiness=parsed_data["gustiness"],
                issued_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc),
                center_geom=center_geom,
            )
            db.add(bulletin)
            db.flush()  # Assigns tcb_id without committing
            db.refresh(bulletin)

            # 3. Match signal areas against admin boundaries
            boundaries = db.query(AdminBoundary).all()
            seen_areas: set = set()

            for level, signal_text in parsed_data["signals"].items():
                # Pre-lowercase once per block to avoid repeated .lower() calls
                signal_text_lower = signal_text.lower()
                for b in boundaries:
                    if (
                        b.province.lower() in signal_text_lower
                        and b.municipality.lower() in signal_text_lower
                    ):
                        area_key = (level, b.municipality)
                        if area_key not in seen_areas:
                            seen_areas.add(area_key)
                            db.add(
                                TcbSignal(
                                    tcb_id=bulletin.tcb_id,
                                    signal_level=level,
                                    island_group=get_island_group(b.province),
                                    area_name=b.municipality,
                                )
                            )

            # Single commit for the entire typhoon → bulletin → signals chain
            db.commit()

        return bulletin
