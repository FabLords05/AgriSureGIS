from fastapi import APIRouter, Depends, HTTPException
from geoalchemy2.shape import to_shape
from shapely.geometry import Point, Polygon
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core import assessment_jobs
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import (
    AreaExposureSummary,
    InsuranceRecord,
    InsuranceUsage,
    RiskAssessment,
    TropicalCycloneBulletin,
    Typhoon,
)

router = APIRouter(prefix="/typhoons", tags=["typhoons"], dependencies=[Depends(get_current_user)])

# PAGASA's Philippine Area of Responsibility, as (lat, lon) corners in order.
# Backs the track overlay's PAR outline and its inside/outside status.
PAR_CORNERS = [(25.0, 120.0), (25.0, 135.0), (5.0, 135.0), (5.0, 115.0), (15.0, 115.0), (21.0, 120.0)]
_PAR_POLYGON = Polygon([(lon, lat) for lat, lon in PAR_CORNERS])


def inside_par(lat: float, lon: float) -> bool:
    # covers, not contains: a center exactly on the PAR line counts as inside.
    return _PAR_POLYGON.covers(Point(lon, lat))


def _track_point(bulletin: TropicalCycloneBulletin) -> dict | None:
    """
    One track point per bulletin, or None when its center is missing --
    including the parser's 0.0/0.0 fallback for a bulletin whose coordinates
    couldn't be read, which would otherwise pull the line to the Gulf of Guinea.
    """
    if bulletin.center_geom is None:
        return None
    center = to_shape(bulletin.center_geom)
    if center.x == 0 and center.y == 0:
        return None
    return {
        "tcb_id": bulletin.tcb_id,
        "bulletin_count": bulletin.bulletin_count,
        "is_final": bulletin.is_final,
        "issued_at": bulletin.issued_at,
        "category": bulletin.category,
        "max_sustained_winds": bulletin.max_sustained_winds,
        "lat": center.y,
        "lng": center.x,
        "wind_radius_km": bulletin.wind_radius_km,
        "storm_force_radius_km": bulletin.storm_force_radius_km,
        "inside_par": inside_par(center.y, center.x),
    }


def build_track(bulletins: list[TropicalCycloneBulletin]) -> dict:
    """
    Observed track (every bulletin with a center, in the given order), the
    latest bulletin's forecast positions, and whether the typhoon is inside
    PAR going by its latest center (None if it has no center at all).
    """
    points = [p for p in (_track_point(b) for b in bulletins) if p is not None]
    latest = bulletins[-1] if bulletins else None
    forecast = [
        {**f, "inside_par": inside_par(f["lat"], f["lon"])}
        for f in ((latest.forecast_track or []) if latest else [])
    ]
    return {
        "points": points,
        "forecast": forecast,
        "in_par": points[-1]["inside_par"] if points else None,
    }


@router.get("/active")
def get_active_typhoons(db: Session = Depends(get_db)):
    """
    Typhoon(s) PAGASA's severe-weather-bulletin status page currently lists as
    active (see PagasaStatusService) -- not derived from TCB bulletin parsing.
    Backs the Monitoring dashboard's "Active Typhoon" card. Usually 0 or 1
    entries; PAGASA's status page can show more than one tab at once if
    multiple cyclones are active in the PAR simultaneously.
    """
    typhoons = (
        db.query(Typhoon)
        .filter(Typhoon.is_active.is_(True))
        .order_by(Typhoon.typhoon_id.desc())
        .all()
    )
    return {
        "status": "success",
        "active_typhoons": [
            {"typhoon_id": t.typhoon_id, "name": t.name, "year": t.year}
            for t in typhoons
        ],
    }


@router.get("/{typhoon_id}/track")
def get_typhoon_track(typhoon_id: int, db: Session = Depends(get_db)):
    """
    Backs the Spatial Analysis map's typhoon track overlay (2026-10-12):
    every bulletin center of one typhoon in issue order, each with its
    category, winds and wind circulation radius, plus the latest bulletin's
    forecast path and the PAR outline.

    in_par here is geometric (latest center inside PAR_CORNERS), unlike the
    progress endpoint's in_par, which is Typhoon.is_active.
    """
    typhoon = db.query(Typhoon).filter(Typhoon.typhoon_id == typhoon_id).first()
    if typhoon is None:
        raise HTTPException(status_code=404, detail="Typhoon not found.")

    bulletins = (
        db.query(TropicalCycloneBulletin)
        .filter(TropicalCycloneBulletin.typhoon_id == typhoon_id)
        .order_by(TropicalCycloneBulletin.issued_at.asc(), TropicalCycloneBulletin.bulletin_count.asc())
        .all()
    )

    return {
        "status": "success",
        "typhoon_id": typhoon.typhoon_id,
        "typhoon_name": typhoon.name,
        "year": typhoon.year,
        "is_active": typhoon.is_active,
        "par_polygon": [[lat, lon] for lat, lon in PAR_CORNERS],
        **build_track(bulletins),
    }


@router.get("/{typhoon_id}/progress")
def get_typhoon_progress(typhoon_id: int, db: Session = Depends(get_db)):
    """
    Backs the Monitoring dashboard's typhoon progress strip (2026-10-11):
    where one typhoon is in the workflow, from bulletins collected to the
    final PABS export. Read-only counts over data other steps already store;
    nothing here triggers a compute.

    in_par is Typhoon.is_active -- PAGASA's status page only lists cyclones
    inside PAR (see PagasaStatusService), so not listed means exited. No exit
    time is stored, so none is returned.

    assessed_farms only counts RiskAssessment rows tied to this typhoon's
    exposure summaries (summary_id), which leaves out the CSV-seeded rows
    (summary_id NULL) that only carry crop stage.

    active_job (2026-10-22) is the typhoon's running assessment calculation,
    else its latest finished one since the backend started (null if none):
    stage-by-stage status, so the strip can show "Assessment calculated" as
    processing / failed instead of only done-or-not.
    """
    typhoon = db.query(Typhoon).filter(Typhoon.typhoon_id == typhoon_id).first()
    if typhoon is None:
        raise HTTPException(status_code=404, detail="Typhoon not found.")

    bulletin_count = (
        db.query(func.count(TropicalCycloneBulletin.tcb_id))
        .filter(TropicalCycloneBulletin.typhoon_id == typhoon_id)
        .scalar()
    )
    final_bulletin = (
        db.query(TropicalCycloneBulletin)
        .filter(TropicalCycloneBulletin.typhoon_id == typhoon_id, TropicalCycloneBulletin.is_final.is_(True))
        .order_by(TropicalCycloneBulletin.issued_at.desc())
        .first()
    )

    summary_ids = db.query(AreaExposureSummary.summary_id).filter(AreaExposureSummary.typhoon_id == typhoon_id)
    exposure_areas = summary_ids.count()

    assessed_farms = (
        db.query(func.count(func.distinct(InsuranceRecord.farm_id)))
        .join(RiskAssessment, RiskAssessment.insurance_records_id == InsuranceRecord.insurance_records_id)
        .filter(RiskAssessment.summary_id.in_(summary_ids))
        .scalar()
    )

    exported_policies, exported_at = (
        db.query(func.count(InsuranceUsage.usage_id), func.max(InsuranceUsage.finalized_at))
        .filter(InsuranceUsage.typhoon_id == typhoon_id, InsuranceUsage.finalized_at.isnot(None))
        .one()
    )

    return {
        "status": "success",
        "typhoon_id": typhoon.typhoon_id,
        "typhoon_name": typhoon.name,
        "in_par": typhoon.is_active,
        "bulletin_count": bulletin_count,
        "final_bulletin": (
            {"bulletin_count": final_bulletin.bulletin_count, "issued_at": final_bulletin.issued_at}
            if final_bulletin
            else None
        ),
        "exposure_areas": exposure_areas,
        "assessed_farms": assessed_farms or 0,
        "exported_policies": exported_policies,
        "exported_at": exported_at,
        "active_job": assessment_jobs.latest_job_for_typhoon(typhoon.typhoon_id),
    }
