import re
import os
import httpx
from bs4 import BeautifulSoup
import pdfplumber
from sqlalchemy.orm import Session
from geoalchemy2.elements import WKTElement
from datetime import datetime, timezone

from app.models.models import Typhoon, TropicalCycloneBulletin, TcbSignal, AdminBoundary

# Base URL for PAGASA tropical cyclone bulletins (mock or real index page)
PAGASA_INDEX_URL = "https://pubfiles.pagasa.dost.gov.ph/tamss/weather/bulletin.html"

class BulletinParserService:
    @staticmethod
    async def fetch_active_bulletin_links() -> list:
        """
        Scrapes the PAGASA bulletin portal to find PDF links to active tropical cyclone bulletins.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(PAGASA_INDEX_URL)
                if response.status_code != 200:
                    return []
                
                soup = BeautifulSoup(response.text, "html.parser")
                pdf_links = []
                for link in soup.find_all("a", href=True):
                    href = link["href"]
                    if href.endswith(".pdf") and "bulletin" in href.lower():
                        # Resolve relative links to absolute URLs if necessary
                        if not href.startswith("http"):
                            base_url = PAGASA_INDEX_URL.rsplit("/", 1)[0]
                            href = f"{base_url}/{href}"
                        pdf_links.append(href)
                return pdf_links
        except Exception as e:
            print(f"Error scraping PAGASA links: {e}")
            return []

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
        """
        with pdfplumber.open(pdf_path) as pdf:
            text = ""
            for page in pdf.pages:
                text += page.extract_text() or ""
                
        # 1. Parse Bulletin Number
        bulletin_no_match = re.search(r"Tropical\s+Cyclone\s+Bulletin\s+No\.\s+(\d+)", text, re.IGNORECASE)
        bulletin_no = int(bulletin_no_match.group(1)) if bulletin_no_match else 1

        # 2. Parse Typhoon Name
        # Standard: TYPHOON "LEON" or TROPICAL STORM "KRISTINE"
        name_match = re.search(
            r"(?:TYPHOON|TROPICAL STORM|SEVERE TROPICAL STORM|TROPICAL DEPRESSION)\s+[\"']?([A-Z\s\-]+)[\"']?", 
            text, 
            re.IGNORECASE
        )
        typhoon_name = name_match.group(1).strip() if name_match else "UNKNOWN"

        # 3. Parse Max Winds and Gusts
        winds_match = re.search(r"maximum\s+sustained\s+winds\s+of\s+(\d+)\s+km/h", text, re.IGNORECASE)
        gusts_match = re.search(r"gustiness\s+of\s+up\s+to\s+(\d+)\s+km/h", text, re.IGNORECASE)
        
        max_winds = int(winds_match.group(1)) if winds_match else None
        gustiness = int(gusts_match.group(1)) if gusts_match else None

        # 4. Parse Center Coordinates (Lat, Lon)
        # Standard: "at 15.4°N, 122.3°E" or "15.4 N, 122.3 E"
        coords_match = re.search(r"at\s+(\d+\.\d+)\s*°?\s*N,\s*(\d+\.\d+)\s*°?\s*E", text, re.IGNORECASE)
        if not coords_match:
            coords_match = re.search(r"(\d+\.\d+)\s*N,\s*(\d+\.\d+)\s*E", text, re.IGNORECASE)
            
        lat = float(coords_match.group(1)) if coords_match else 0.0
        lon = float(coords_match.group(2)) if coords_match else 0.0

        # 5. Extract Signal Text Blocks (Signal 1 to 5)
        signals_data = {}
        # Find start indices of signal blocks
        signal_markers = []
        for level in range(1, 6):
            # Matches "Signal No. 2" or "SIGNAL NO. 2"
            marker = re.search(rf"Signal\s+No\.\s+{level}", text, re.IGNORECASE)
            if marker:
                signal_markers.append((level, marker.start()))
                
        signal_markers.sort(key=lambda x: x[1])
        
        for i, (level, start_idx) in enumerate(signal_markers):
            end_idx = signal_markers[i+1][1] if i+1 < len(signal_markers) else len(text)
            signal_text = text[start_idx:end_idx]
            signals_data[level] = signal_text

        return {
            "typhoon_name": typhoon_name,
            "bulletin_count": bulletin_no,
            "category": "Typhoon" if "typhoon" in text.lower() else "Tropical Storm",
            "max_sustained_winds": max_winds,
            "gustiness": gustiness,
            "latitude": lat,
            "longitude": lon,
            "signals": signals_data,
            "raw_text": text
        }

    @classmethod
    def save_bulletin_to_db(cls, parsed_data: dict, db: Session) -> TropicalCycloneBulletin:
        """
        Saves parsed bulletin data to the PostGIS database.
        """
        # 1. Get or Create Typhoon
        year = datetime.now().year
        typhoon = db.query(Typhoon).filter(
            func.lower(Typhoon.name) == parsed_data["typhoon_name"].lower(),
            Typhoon.year == year
        ).first()
        
        if not typhoon:
            typhoon = Typhoon(
                name=parsed_data["typhoon_name"],
                year=year,
                is_active=True
            )
            db.add(typhoon)
            db.commit()
            db.refresh(typhoon)

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
                issued_at=datetime.now(timezone.utc),  # Placeholder, PAGASA date parsing optional
                expires_at=datetime.now(timezone.utc),  # Expiry date placeholder
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
