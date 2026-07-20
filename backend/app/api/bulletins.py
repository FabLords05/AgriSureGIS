from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
import os
import shutil

from app.core.database import get_db
from app.services.bulletin_parser import BulletinParserService
from app.models.models import TropicalCycloneBulletin, TcbSignal, Typhoon

router = APIRouter(prefix="/bulletins", tags=["bulletins"])

TEMP_DIR = "temp_bulletins"

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
        results.append({
            "tcb_id": b.tcb_id,
            "title": b.title,
            "bulletin_count": b.bulletin_count,
            "category": b.category,
            "typhoon_name": typhoon.name if typhoon else "Unknown",
            "max_sustained_winds": b.max_sustained_winds,
            "gustiness": b.gustiness,
            "issued_at": b.issued_at
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

    parsed_count = 0
    bulletins_created = []
    for link in links:
        try:
            pdf_path = await BulletinParserService.download_bulletin_pdf(link, TEMP_DIR)
            parsed_data = BulletinParserService.parse_bulletin_text(pdf_path)
            bulletin = BulletinParserService.save_bulletin_to_db(parsed_data, db)
            
            # Remove temp file
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
                
            bulletins_created.append({
                "tcb_id": bulletin.tcb_id,
                "title": bulletin.title,
                "bulletin_count": bulletin.bulletin_count
            })
            parsed_count += 1
        except Exception as e:
            print(f"Error processing PDF link {link}: {e}")

    return {
        "status": "success",
        "parsed_count": parsed_count,
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
