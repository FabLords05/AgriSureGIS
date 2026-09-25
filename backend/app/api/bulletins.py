import asyncio
import logging
import os
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

    - Enforces a 15-minute cooldown, stamped at the START of processing to prevent
      concurrent requests from racing through the check simultaneously.
    - Deduplication is handled by save_bulletin_to_db (DB-level idempotency on
      typhoon_id + bulletin_count); only newly inserted bulletins count toward
      parsed_count.
    - Adds a 1-second polite delay between sequential PDF downloads.
    - Guarantees temp file cleanup via try/finally even when parsing fails.
    - Calls db.rollback() on persistence failures to keep the session usable.
    """
    global _last_scraped_at

    elapsed = time.monotonic() - _last_scraped_at
    if elapsed < SCRAPE_COOLDOWN_SECONDS:
        remaining = int(SCRAPE_COOLDOWN_SECONDS - elapsed)
        raise HTTPException(
            status_code=429,
            detail=f"Scrape cooldown active. Try again in {remaining} seconds.",
        )

    # Stamp the cooldown immediately — before any awaits — so that concurrent
    # requests hitting this endpoint at the same time are rejected rather than
    # allowed to race, collide on filenames, or duplicate DB inserts.
    _last_scraped_at = time.monotonic()

    links = await BulletinParserService.fetch_active_bulletin_links()
    if not links:
        raise HTTPException(
            status_code=404,
            detail="No active bulletin PDFs found on PAGASA portal.",
        )

    parsed_count = 0
    skipped_count = 0
    failed_count = 0
    bulletins_created = []

    for link in links:
        pdf_path = None
        try:
            pdf_path = await BulletinParserService.download_bulletin_pdf(link, TEMP_DIR)
            parsed_data = BulletinParserService.parse_bulletin_text(pdf_path)
            bulletin, is_new = BulletinParserService.save_bulletin_to_db(parsed_data, db)

            if is_new:
                bulletins_created.append(
                    {
                        "tcb_id": bulletin.tcb_id,
                        "title": bulletin.title,
                        "bulletin_count": bulletin.bulletin_count,
                    }
                )
                parsed_count += 1
            else:
                logger.info(
                    "Bulletin already exists in DB, skipping: %s", link
                )
                skipped_count += 1

        except Exception:
            # Roll back to clear any flushed-but-uncommitted state so the
            # session remains usable for subsequent loop iterations.
            db.rollback()
            logger.exception("Error processing PDF link %s", link)
            failed_count += 1
        finally:
            # Always clean up the temp file regardless of success or failure.
            # download_bulletin_pdf already removes its file on its own errors,
            # but this guard covers parse/db failures after a successful download.
            if pdf_path and os.path.exists(pdf_path):
                os.remove(pdf_path)

        # Polite delay between sequential PDF downloads
        await asyncio.sleep(1.0)

    # Surface a clear status so callers can distinguish full success,
    # partial success, and total failure without inspecting parsed_count.
    if parsed_count == 0 and failed_count > 0:
        status = "error"
    elif failed_count > 0 or skipped_count > 0:
        status = "partial"
    else:
        status = "success"

    return {
        "status": status,
        "parsed_count": parsed_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "bulletins": bulletins_created,
    }


@router.post("/upload")
async def upload_bulletin_pdf(
    file: UploadFile = File(...), db: Session = Depends(get_db)
):
    """
    Allows manual upload of a PAGASA bulletin PDF if the scraping portal is offline.

    - Rejects filenames that do not end in .pdf (case-insensitive).
    - Sanitises the filename with os.path.basename() and validates the resolved
      path stays inside TEMP_DIR to prevent path traversal attacks.
    - Reads at most MAX_UPLOAD_BYTES + 1 bytes before the size check so an
      oversized upload never fully buffers into RAM.
    - Uses mkstemp() for a unique temp path.
    - Guarantees temp file cleanup via finally.
    """
    # Sanitise filename — reject None/empty and normalise to basename only
    raw_name = file.filename or ""
    safe_name = os.path.basename(raw_name)
    if not safe_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    # Read at most (limit + 1) bytes so we can distinguish "exactly at limit"
    # from "over limit" without pulling an unbounded payload into memory.
    contents = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large. Maximum allowed size is "
                f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
            ),
        )

    os.makedirs(TEMP_DIR, exist_ok=True)

    # mkstemp gives a guaranteed-unique path and prevents path traversal
    fd, temp_path = tempfile.mkstemp(dir=TEMP_DIR, suffix=".pdf")
    os.close(fd)

    # Verify the resolved path is still inside TEMP_DIR (defense in depth)
    if not os.path.realpath(temp_path).startswith(os.path.realpath(TEMP_DIR)):
        os.remove(temp_path)
        raise HTTPException(status_code=400, detail="Invalid file path.")

    try:
        with open(temp_path, "wb") as f:
            f.write(contents)

        parsed_data = BulletinParserService.parse_bulletin_text(temp_path)
        bulletin, _ = BulletinParserService.save_bulletin_to_db(parsed_data, db)

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
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to parse PDF: {str(e)}")
    finally:
        # Always clean up whether parsing succeeded or failed
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
