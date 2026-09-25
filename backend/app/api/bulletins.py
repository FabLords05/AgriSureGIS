import asyncio
import logging
import os
import shutil
import tempfile
import time

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.services.bulletin_parser import BulletinParserService
from app.models.models import TropicalCycloneBulletin, TcbSignal, Typhoon

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bulletins", tags=["bulletins"])

# Absolute temp directory — avoids CWD-relative path issues across launch dirs
TEMP_DIR = os.path.join(tempfile.gettempdir(), "agrisure_bulletins")

# Cooldown guard: minimum seconds between scrape triggers (15 minutes)
SCRAPE_COOLDOWN_SECONDS = 900
_last_scraped_at: float = 0.0

# Maximum allowed size for manual PDF uploads (10 MB)
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@router.get("/")
def list_bulletins(db: Session = Depends(get_db)):
    """
    Lists all parsed bulletins.
    Uses joinedload to avoid N+1 queries when resolving typhoon names.
    """
    bulletins = (
        db.query(TropicalCycloneBulletin)
        .options(joinedload(TropicalCycloneBulletin.typhoon))
        .order_by(TropicalCycloneBulletin.bulletin_count.desc())
        .all()
    )
    return [
        {
            "tcb_id": b.tcb_id,
            "title": b.title,
            "bulletin_count": b.bulletin_count,
            "category": b.category,
            "typhoon_name": b.typhoon.name if b.typhoon else "Unknown",
            "max_sustained_winds": b.max_sustained_winds,
            "gustiness": b.gustiness,
            "issued_at": b.issued_at,
        }
        for b in bulletins
    ]


@router.post("/parse")
async def trigger_pagasa_scrape(db: Session = Depends(get_db)):
    """
    Triggers web scraping of the PAGASA portal to download and parse any active bulletins.

    - Enforces a 15-minute cooldown between triggers to avoid flooding the PAGASA server.
    - Skips bulletins already present in the database (deduplication).
    - Adds a 1-second polite delay between sequential PDF downloads.
    - Guarantees temp file cleanup via try/finally even when parsing fails.
    """
    global _last_scraped_at

    elapsed = time.monotonic() - _last_scraped_at
    if elapsed < SCRAPE_COOLDOWN_SECONDS:
        remaining = int(SCRAPE_COOLDOWN_SECONDS - elapsed)
        raise HTTPException(
            status_code=429,
            detail=f"Scrape cooldown active. Try again in {remaining} seconds.",
        )

    links = await BulletinParserService.fetch_active_bulletin_links()
    if not links:
        raise HTTPException(
            status_code=404,
            detail="No active bulletin PDFs found on PAGASA portal.",
        )

    # Deduplication: build a set of already-saved bulletin titles
    existing_titles = {
        row.title
        for row in db.query(TropicalCycloneBulletin).with_entities(
            TropicalCycloneBulletin.title
        )
    }

    parsed_count = 0
    bulletins_created = []

    for link in links:
        filename_stem = link.split("/")[-1].replace(".pdf", "")
        if any(filename_stem in title for title in existing_titles):
            logger.info("Skipping already-parsed bulletin: %s", link)
            continue

        pdf_path = None
        try:
            pdf_path = await BulletinParserService.download_bulletin_pdf(link, TEMP_DIR)
            parsed_data = BulletinParserService.parse_bulletin_text(pdf_path)
            bulletin = BulletinParserService.save_bulletin_to_db(parsed_data, db)
            bulletins_created.append(
                {
                    "tcb_id": bulletin.tcb_id,
                    "title": bulletin.title,
                    "bulletin_count": bulletin.bulletin_count,
                }
            )
            parsed_count += 1
        except Exception as e:
            logger.error("Error processing PDF link %s: %s", link, e, exc_info=True)
        finally:
            # Always clean up the temp file regardless of success or failure
            if pdf_path and os.path.exists(pdf_path):
                os.remove(pdf_path)

        # Polite delay between sequential PDF downloads
        await asyncio.sleep(1.0)

    _last_scraped_at = time.monotonic()

    return {
        "status": "success",
        "parsed_count": parsed_count,
        "bulletins": bulletins_created,
    }


@router.post("/upload")
async def upload_bulletin_pdf(
    file: UploadFile = File(...), db: Session = Depends(get_db)
):
    """
    Allows manual upload of a PAGASA bulletin PDF if the scraping portal is offline.
    Enforces a 10 MB file size limit and guarantees temp file cleanup.
    """
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    # Read and validate size before touching the filesystem
    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large. Maximum allowed size is "
                f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
            ),
        )

    os.makedirs(TEMP_DIR, exist_ok=True)
    temp_path = os.path.join(TEMP_DIR, file.filename)

    try:
        with open(temp_path, "wb") as f:
            f.write(contents)

        parsed_data = BulletinParserService.parse_bulletin_text(temp_path)
        bulletin = BulletinParserService.save_bulletin_to_db(parsed_data, db)

        return {
            "status": "success",
            "message": "Manual bulletin successfully parsed and saved.",
            "bulletin": {
                "tcb_id": bulletin.tcb_id,
                "title": bulletin.title,
                "bulletin_count": bulletin.bulletin_count,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse PDF: {str(e)}")
    finally:
        # Always clean up the temp file whether parsing succeeded or failed
        if os.path.exists(temp_path):
            os.remove(temp_path)


@router.get("/{tcb_id}/signals")
def get_bulletin_signals(tcb_id: int, db: Session = Depends(get_db)):
    """
    Retrieves the parsed wind signals and affected municipalities for a bulletin.
    """
    signals = db.query(TcbSignal).filter(TcbSignal.tcb_id == tcb_id).all()
    return [
        {
            "signal_id": s.signal_id,
            "signal_level": s.signal_level,
            "island_group": s.island_group,
            "area_name": s.area_name,
        }
        for s in signals
    ]
