from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from geoalchemy2.shape import to_shape
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import os
import shutil

from app.core.database import get_db
from app.core.scheduler import reschedule_bulletin_job
from app.services.bulletin_parser import BulletinParserService
from app.services.exposure_calculator import ExposureCalculatorService
from app.models.models import ParserSettings, TropicalCycloneBulletin, TcbSignal, Typhoon

router = APIRouter(prefix="/bulletins", tags=["bulletins"])

TEMP_DIR = "temp_bulletins"


class ParserSettingsUpdate(BaseModel):
    polling_interval_hours: int = Field(..., ge=1, le=24)


def _get_or_create_settings(db: Session) -> ParserSettings:
    settings = db.query(ParserSettings).first()
    if not settings:
        settings = ParserSettings(polling_interval_hours=3)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


@router.get("/settings")
def get_parser_settings(db: Session = Depends(get_db)):
    """
    Returns the currently persisted TCB polling interval (hours) that drives
    the background PAGASA scraper — backs the Calibration screen's "TCB
    Polling Interval" field.
    """
    settings = _get_or_create_settings(db)
    return {"polling_interval_hours": settings.polling_interval_hours}


@router.put("/settings")
def update_parser_settings(payload: ParserSettingsUpdate, request: Request, db: Session = Depends(get_db)):
    """
    Persists a new TCB polling interval and reschedules the already-running
    background scraper job to match, without requiring a backend restart.
    """
    settings = _get_or_create_settings(db)
    settings.polling_interval_hours = payload.polling_interval_hours
    db.commit()
    db.refresh(settings)

    reschedule_bulletin_job(request.app.state.scheduler, settings.polling_interval_hours)

    return {"polling_interval_hours": settings.polling_interval_hours}


@router.get("/")
def list_bulletins(db: Session = Depends(get_db)):
    """
    Lists all parsed bulletins.
    """
    bulletins = db.query(TropicalCycloneBulletin).order_by(TropicalCycloneBulletin.bulletin_count.desc()).all()
    # Format response simply
    results = []
    for b in bulletins:
        typhoon = db.query(Typhoon).filter(Typhoon.typhoon_id == b.typhoon_id).first()
        center_point = to_shape(b.center_geom) if b.center_geom is not None else None
        results.append({
            "tcb_id": b.tcb_id,
            "typhoon_id": b.typhoon_id,
            "title": b.title,
            "bulletin_count": b.bulletin_count,
            "category": b.category,
            "typhoon_name": typhoon.name if typhoon else "Unknown",
            "max_sustained_winds": b.max_sustained_winds,
            "gustiness": b.gustiness,
            "issued_at": b.issued_at,
            "center_lat": center_point.y if center_point else None,
            "center_lng": center_point.x if center_point else None,
        })
    return results

@router.post("/parse")
async def trigger_pagasa_scrape(db: Session = Depends(get_db)):
    """
    Triggers web scraping of the PAGASA portal to download and parse any active bulletins.
    """
    links = await BulletinParserService.fetch_active_bulletin_links()
    if not links:
        # Fallback for testing: return empty success or check if there is an active file
        raise HTTPException(status_code=404, detail="No active bulletin PDFs found on PAGASA portal.")

    bulletins_created = await BulletinParserService.scrape_and_save_all(db, TEMP_DIR)

    return {
        "status": "success",
        "parsed_count": len(bulletins_created),
        "bulletins": bulletins_created
    }

@router.post("/upload")
async def upload_bulletin_pdf(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Allows manual upload of a PAGASA bulletin PDF if the scraping portal is offline.
    """
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
        
    os.makedirs(TEMP_DIR, exist_ok=True)
    temp_path = os.path.join(TEMP_DIR, file.filename)
    
    try:
        # Save uploaded file temporarily
        with open(temp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
            
        # Parse and save
        parsed_data = BulletinParserService.parse_bulletin_text(temp_path)
        bulletin = BulletinParserService.save_bulletin_to_db(parsed_data, db)
        
        # Clean up
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
        return {
            "status": "success",
            "message": "Manual bulletin successfully parsed and saved.",
            "bulletin": {
                "tcb_id": bulletin.tcb_id,
                "title": bulletin.title,
                "bulletin_count": bulletin.bulletin_count
            }
        }
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise HTTPException(status_code=500, detail=f"Failed to parse PDF: {str(e)}")

@router.post("/{tcb_id}/compute-exposure")
def compute_exposure(tcb_id: int, db: Session = Depends(get_db)):
    """
    Recomputes per-municipality exposure-duration summaries (tbl_area_exposure_summary)
    for the typhoon this bulletin belongs to, using all of that typhoon's bulletins
    parsed so far. Sprint 3 scope only — does not compute yield loss or payouts
    (that depends on Sprint 4's RecsapMatrix/RiskAssessment work).
    """
    bulletin = db.query(TropicalCycloneBulletin).filter(TropicalCycloneBulletin.tcb_id == tcb_id).first()
    if bulletin is None:
        raise HTTPException(status_code=404, detail="Bulletin not found.")

    summaries = ExposureCalculatorService.compute_for_typhoon(bulletin.typhoon_id, db)

    return {
        "status": "success",
        "typhoon_id": bulletin.typhoon_id,
        "boundaries_computed": len(summaries),
        "summaries": [
            {
                "summary_id": s.summary_id,
                "boundary_id": s.boundary_id,
                "province": s.province,
                "municipality": s.municipality,
                "max_signal_level": s.max_signal_level,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "total_exposure_hours": float(s.total_exposure_hours),
                "is_eligible_6hr": s.is_eligible_6hr,
            }
            for s in summaries
        ],
    }


@router.get("/{tcb_id}/signals")
def get_bulletin_signals(tcb_id: int, db: Session = Depends(get_db)):
    """
    Retrieves the parsed wind signals and affected municipalities for a bulletin.
    """
    signals = db.query(TcbSignal).filter(TcbSignal.tcb_id == tcb_id).all()
    results = []
    for s in signals:
        results.append({
            "signal_id": s.signal_id,
            "signal_level": s.signal_level,
            "island_group": s.island_group,
            "area_name": s.area_name
        })
    return results
