"""
"Verify Farm Planted" (Use Case Diagram: an <<include>> of Conduct Parametric
Damage Assessment, against Google Earth Engine) -- Phase 1, 2026-10-12.

- POST /sar/layer: pre-event Sentinel-1 VV/VH colour layer over the farms the
  "Affected Only" filter selects for a bulletin (app/services/gee_sar_service.py).
- /sar/verifications: the GIS Specialist's recorded Planted / Not planted
  verdict per farm per typhoon (tbl_planted_verification).

The verdict is recorded and shown only -- AssessmentService and the PABS/PCIC
export never read it (per Fabio: record, don't gate).
"""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.farms import _affected_farm_ids
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Farm, PlantedVerification, SystemUser, TropicalCycloneBulletin
from app.services import gee_sar_service
from app.services.gee_sar_service import GeeNotConfiguredError, NoScenesError

router = APIRouter(prefix="/sar", tags=["sar"], dependencies=[Depends(get_current_user)])

# Upper bound on polygons sent to Earth Engine in one request -- GEE rejects
# very large request payloads. Hitting it is reported, never silent.
MAX_LAYER_FARMS = 5000


class LayerRequest(BaseModel):
    bulletin_id: int


class VerificationRequest(BaseModel):
    typhoon_id: int
    is_planted: bool
    notes: str | None = None


def _event_date(db: Session, bulletin: TropicalCycloneBulletin):
    """The typhoon's first bulletin date -- the pre-event window ends the day
    before it. Falls back to this bulletin's own date if it has no typhoon."""
    if bulletin.typhoon_id is None:
        return bulletin.issued_at.date()
    first = (
        db.query(func.min(TropicalCycloneBulletin.issued_at))
        .filter(TropicalCycloneBulletin.typhoon_id == bulletin.typhoon_id)
        .scalar()
    )
    return (first or bulletin.issued_at).date()


def _load_affected_polygons(db: Session, bulletin_id: int) -> tuple[list[tuple[int, dict]], int]:
    """(farm_id, GeoJSON) for the bulletin's affected farms that have a GPX
    polygon, capped at MAX_LAYER_FARMS + 1 so the caller can tell the cap was
    hit, plus how many affected farms were skipped for having no polygon."""
    affected = _affected_farm_ids(db, bulletin_id)
    rows = (
        db.query(Farm.farm_id, func.ST_AsGeoJSON(Farm.location_geom, 6))
        .filter(Farm.farm_id.in_(affected), Farm.location_geom.isnot(None))
        .order_by(Farm.farm_id)
        .limit(MAX_LAYER_FARMS + 1)
        .all()
    )
    skipped = (
        db.query(func.count(Farm.farm_id))
        .filter(Farm.farm_id.in_(affected), Farm.location_geom.is_(None))
        .scalar()
    ) or 0
    return [(farm_id, json.loads(geojson)) for farm_id, geojson in rows], skipped


@router.post("/layer")
def get_planted_layer(body: LayerRequest, db: Session = Depends(get_db)):
    """
    Pre-event VV/VH-ratio tile layer clipped to the bulletin's affected farm
    polygons (TCWS signal >= 2 municipalities, same set as the Spatial
    Analysis "Affected Only" button). 503 if Earth Engine isn't configured,
    422 if there's nothing to draw, 502 if Earth Engine itself fails.
    """
    bulletin = db.get(TropicalCycloneBulletin, body.bulletin_id)
    if bulletin is None:
        raise HTTPException(status_code=404, detail="Bulletin not found.")
    if not gee_sar_service.gee_configured():
        raise HTTPException(status_code=503, detail="Google Earth Engine is not configured on the server.")

    polygons, skipped_no_geom = _load_affected_polygons(db, body.bulletin_id)
    if not polygons:
        raise HTTPException(
            status_code=422,
            detail="No affected farms with a surveyed (GPX) polygon for this bulletin.",
        )
    capped = len(polygons) > MAX_LAYER_FARMS
    polygons = polygons[:MAX_LAYER_FARMS]

    event_date = _event_date(db, bulletin)
    farm_ids = tuple(farm_id for farm_id, _ in polygons)
    cache_key = (body.bulletin_id, event_date.isoformat(), hash(farm_ids))
    try:
        layer = gee_sar_service.build_planted_layer(cache_key, [g for _, g in polygons], event_date)
    except GeeNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except NoScenesError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # Earth Engine computation/quota errors
        raise HTTPException(status_code=502, detail=f"Earth Engine request failed: {exc}")

    return {
        "status": "success",
        "data": {
            **layer,
            "bulletin_id": body.bulletin_id,
            "event_date": event_date.isoformat(),
            "farm_count": len(polygons),
            "capped": capped,
            "skipped_no_geom": skipped_no_geom,
        },
    }


def _verification_to_dict(v: PlantedVerification) -> dict:
    return {
        "farm_id": v.farm_id,
        "typhoon_id": v.typhoon_id,
        "is_planted": v.is_planted,
        "verified_by": f"{v.verifier.firstname} {v.verifier.lastname}".strip() if v.verifier else None,
        "verified_at": v.verified_at.isoformat() if v.verified_at else None,
        "notes": v.notes,
    }


@router.get("/verifications")
def list_verifications(typhoon_id: int = Query(...), db: Session = Depends(get_db)):
    """Every recorded planted verdict for one typhoon."""
    rows = db.query(PlantedVerification).filter(PlantedVerification.typhoon_id == typhoon_id).all()
    return {"status": "success", "data": [_verification_to_dict(v) for v in rows]}


@router.put("/verifications/{farm_id}")
def set_verification(
    farm_id: int,
    body: VerificationRequest,
    db: Session = Depends(get_db),
    current_user: SystemUser = Depends(get_current_user),
):
    """Record (or change) the Specialist's verdict for one farm and typhoon."""
    if db.get(Farm, farm_id) is None:
        raise HTTPException(status_code=404, detail="Farm not found.")
    row = (
        db.query(PlantedVerification)
        .filter(PlantedVerification.farm_id == farm_id, PlantedVerification.typhoon_id == body.typhoon_id)
        .first()
    )
    if row is None:
        row = PlantedVerification(farm_id=farm_id, typhoon_id=body.typhoon_id)
        db.add(row)
    row.is_planted = body.is_planted
    row.notes = body.notes
    row.verified_by = current_user.user_id
    row.verified_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return {"status": "success", "data": _verification_to_dict(row)}


@router.delete("/verifications/{farm_id}")
def clear_verification(farm_id: int, typhoon_id: int = Query(...), db: Session = Depends(get_db)):
    """Back to unchecked."""
    deleted = (
        db.query(PlantedVerification)
        .filter(PlantedVerification.farm_id == farm_id, PlantedVerification.typhoon_id == typhoon_id)
        .delete()
    )
    db.commit()
    return {"status": "success", "deleted": deleted}
