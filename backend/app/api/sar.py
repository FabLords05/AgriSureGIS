"""
"Verify Farm Planted" (Use Case Diagram: an <<include>> of Conduct Parametric
Damage Assessment, against Google Earth Engine) -- Phase 1, 2026-10-12.

- POST /sar/layer: pre-event Sentinel-1 VV/VH colour layer over the farms the
  "Affected by" filter selects for a typhoon (app/services/gee_sar_service.py).

Everything here is per typhoon, not per bulletin (per Cristian, 2026-10-12):
the AOI is every farm under signal 2+ in any of the typhoon's bulletins
(app/api/farms.py's _affected_farm_ids), and the imagery window ends the day
before its first bulletin.
- /sar/verifications: the GIS Specialist's recorded Planted / Not planted
  verdict per farm per typhoon (tbl_planted_verification). No longer used
  by the frontend since the automatic check below (2026-10-12); kept so
  verdicts already recorded stay readable.
- POST /sar/check, GET /sar/checks (Phase 2, 2026-10-12): the automatic
  planted check -- every affected farm GREEN "planted" or YELLOW
  "field_verify" (app/services/sar_planted_classifier.py), stored per
  typhoon in tbl_sar_planted_check. The Earth Engine series behind it is
  cached in tbl_sar_observation / tbl_sar_fetch_coverage, so only farms and
  dates not already stored are fetched.

Neither the verdict nor the check result gates anything -- AssessmentService
and the PABS/PCIC export never read them (per Fabio: record, don't gate).
"""
import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2 import Geography
from pydantic import BaseModel
from sqlalchemy import cast, func
from sqlalchemy.orm import Session

from app.api.farms import _affected_farm_ids
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import (
    Farm,
    PlantedVerification,
    SarFetchCoverage,
    SarObservation,
    SarPlantedCheck,
    SystemUser,
    TropicalCycloneBulletin,
)
from app.services import gee_sar_service
from app.services import sar_planted_classifier as classifier
from app.services.gee_sar_service import INWARD_BUFFER_M, GeeNotConfiguredError, NoScenesError

router = APIRouter(prefix="/sar", tags=["sar"], dependencies=[Depends(get_current_user)])

# Upper bound on polygons sent to Earth Engine in one request -- GEE rejects
# very large request payloads. Hitting it is reported, never silent.
MAX_LAYER_FARMS = 5000

# Days a Sentinel-1 scene can take to appear in COPERNICUS/S1_GRD after
# acquisition. The planted-check cache never claims those days as covered.
SCENE_INGEST_LAG_DAYS = 3


class LayerRequest(BaseModel):
    typhoon_id: int


class CheckRequest(BaseModel):
    typhoon_id: int


class VerificationRequest(BaseModel):
    typhoon_id: int
    is_planted: bool
    notes: str | None = None


def _event_date(db: Session, typhoon_id: int) -> date:
    """The typhoon's first bulletin date -- the pre-event window ends the day
    before it. 404 if the typhoon has no bulletins (or doesn't exist)."""
    first = (
        db.query(func.min(TropicalCycloneBulletin.issued_at))
        .filter(TropicalCycloneBulletin.typhoon_id == typhoon_id)
        .scalar()
    )
    if first is None:
        raise HTTPException(status_code=404, detail="Typhoon not found, or it has no bulletins.")
    return first.date()


def _load_affected_polygons(db: Session, typhoon_id: int) -> tuple[list[tuple[int, dict]], int]:
    """(farm_id, GeoJSON) for the typhoon's affected farms that have a GPX
    polygon, capped at MAX_LAYER_FARMS + 1 so the caller can tell the cap was
    hit, plus how many affected farms were skipped for having no polygon."""
    affected = _affected_farm_ids(db, typhoon_id)
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
    Pre-event VV/VH-ratio tile layer clipped to the typhoon's affected farm
    polygons (TCWS signal >= 2 municipalities in any bulletin, same set as
    the Spatial Analysis "Affected by" filter). 404 unknown typhoon, 503 if
    Earth Engine isn't configured, 422 if there's nothing to draw, 502 if
    Earth Engine itself fails.
    """
    event_date = _event_date(db, body.typhoon_id)
    if not gee_sar_service.gee_configured():
        raise HTTPException(status_code=503, detail="Google Earth Engine is not configured on the server.")

    polygons, skipped_no_geom = _load_affected_polygons(db, body.typhoon_id)
    if not polygons:
        raise HTTPException(
            status_code=422,
            detail="No affected farms with a surveyed (GPX) polygon for this typhoon.",
        )
    capped = len(polygons) > MAX_LAYER_FARMS
    polygons = polygons[:MAX_LAYER_FARMS]

    farm_ids = tuple(farm_id for farm_id, _ in polygons)
    cache_key = (body.typhoon_id, event_date.isoformat(), hash(farm_ids))
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
            "typhoon_id": body.typhoon_id,
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


# ---------------------------------------------------------------------------
# Automatic planted check (Phase 2, 2026-10-12)
# ---------------------------------------------------------------------------

def _load_affected_farms(db: Session, typhoon_id: int) -> list[tuple]:
    """(farm_id, GeoJSON, geom md5, area left after the inward buffer in m²)
    for every farm the typhoon affected. The last three are None for a farm
    with no GPX polygon. The buffered area is computed here, in PostGIS, so
    farms too small to sample are never sent to Earth Engine."""
    affected = _affected_farm_ids(db, typhoon_id)
    return (
        db.query(
            Farm.farm_id,
            func.ST_AsGeoJSON(Farm.location_geom, 6),
            func.md5(func.ST_AsEWKB(Farm.location_geom)),
            func.ST_Area(func.ST_Buffer(cast(Farm.location_geom, Geography), -INWARD_BUFFER_M)),
        )
        .filter(Farm.farm_id.in_(affected))
        .order_by(Farm.farm_id)
        .all()
    )


def _needs_fetch(coverage: SarFetchCoverage | None, geom_hash: str, start: date, end: date) -> bool:
    """Whether a farm's [start, end] series must come from Earth Engine
    rather than tbl_sar_observation."""
    return (
        coverage is None
        or coverage.geom_hash != geom_hash
        or coverage.covered_start > start
        or coverage.covered_end < end
    )


def _store_fetched(
    db: Session,
    fetch: dict[int, str],
    coverages: dict[int, SarFetchCoverage],
    series: dict[int, list[dict]],
    start: date,
    end: date,
) -> None:
    """Replace the cached [start, end] observations of the farms in `fetch`
    (farm_id -> geom md5) with what Earth Engine returned, and extend their
    coverage. A changed boundary drops the farm's whole cached series."""
    reshaped = [fid for fid, h in fetch.items() if fid in coverages and coverages[fid].geom_hash != h]
    if reshaped:
        db.query(SarObservation).filter(SarObservation.farm_id.in_(reshaped)).delete(synchronize_session=False)
    db.query(SarObservation).filter(
        SarObservation.farm_id.in_(list(fetch)),
        SarObservation.scene_date.between(start, end),
    ).delete(synchronize_session=False)

    db.add_all([
        SarObservation(farm_id=farm_id, **row)
        for farm_id in fetch
        for row in series.get(farm_id, [])
        if start <= row["scene_date"] <= end
    ])

    now = datetime.now(timezone.utc)
    # Scenes of the last few days may not be in Earth Engine yet; don't mark
    # them covered, so the next run picks them up.
    covered_until = min(end, now.date() - timedelta(days=SCENE_INGEST_LAG_DAYS))
    for farm_id, geom_hash in fetch.items():
        cov = coverages.get(farm_id)
        if cov is None:
            db.add(SarFetchCoverage(farm_id=farm_id, covered_start=start, covered_end=covered_until,
                                    geom_hash=geom_hash, fetched_at=now))
            continue
        # Only merge ranges that touch -- a gap between them was never fetched.
        touches = cov.geom_hash == geom_hash and \
            cov.covered_start <= end + timedelta(days=1) and cov.covered_end >= start - timedelta(days=1)
        cov.covered_start = min(cov.covered_start, start) if touches else start
        cov.covered_end = max(cov.covered_end, covered_until) if touches else covered_until
        cov.geom_hash = geom_hash
        cov.fetched_at = now


def _load_observations(db: Session, farm_ids: list[int], start: date, end: date):
    """{farm_id: [(relative_orbit, Observation)]} from the cache."""
    rows = (
        db.query(SarObservation.farm_id, SarObservation.relative_orbit, SarObservation.scene_date,
                 SarObservation.vv_db, SarObservation.vh_db)
        .filter(SarObservation.farm_id.in_(farm_ids), SarObservation.scene_date.between(start, end))
        .all()
    )
    out: dict[int, list] = {}
    for farm_id, orbit, scene_date, vv, vh in rows:
        out.setdefault(farm_id, []).append(
            (orbit, classifier.Observation(scene_date=scene_date, vv_db=float(vv), vh_db=float(vh)))
        )
    return out


def _num(value):
    return float(value) if value is not None else None


def _check_to_dict(row: SarPlantedCheck) -> dict:
    return {
        "farm_id": row.farm_id,
        "status": row.status,
        "reason_code": row.reason_code,
        "reason": classifier.REASON_LABELS.get(row.reason_code, row.reason_code),
        "t0_date": row.t0_date.isoformat() if row.t0_date else None,
        "tp_date": row.tp_date.isoformat() if row.tp_date else None,
        "vh_rise_db": _num(row.vh_rise_db),
        "ratio_drop_db": _num(row.ratio_drop_db),
        "relative_orbit": row.relative_orbit,
        "scene_count": row.scene_count,
    }


def _summary(rows: list[SarPlantedCheck]) -> dict | None:
    if not rows:
        return None
    first = rows[0]
    reasons = Counter(r.reason_code for r in rows if r.status == classifier.STATUS_FIELD_VERIFY)
    checked_at = max((r.checked_at for r in rows if r.checked_at), default=None)
    return {
        "typhoon_id": first.typhoon_id,
        "window_start": first.window_start.isoformat(),
        "window_end": first.window_end.isoformat(),
        "checked_at": checked_at.isoformat() if checked_at else None,
        "checked": len(rows),
        "planted": sum(1 for r in rows if r.status == classifier.STATUS_PLANTED),
        "field_verify": sum(reasons.values()),
        "reasons": [
            {"code": code, "label": classifier.REASON_LABELS.get(code, code), "count": count}
            for code, count in reasons.most_common()
        ],
    }


@router.post("/check")
def run_planted_check(
    body: CheckRequest,
    db: Session = Depends(get_db),
    current_user: SystemUser = Depends(get_current_user),
):
    """
    Classify every farm the typhoon affected (signal 2+ in any of its
    bulletins -- the "Affected by" filter's set) as GREEN "planted" or
    YELLOW "field_verify" (method doc §3), and store the result for the
    typhoon -- replacing any earlier run for it.

    Earth Engine is only called for farms whose 150-day window isn't
    already in tbl_sar_observation, so a re-run with nothing new is served
    entirely from the database (and works even with GEE unconfigured).
    404 unknown typhoon / no bulletins; 422 no affected farms; 503 GEE
    needed but not configured; 502 Earth Engine failure.
    """
    typhoon_id = body.typhoon_id
    event_date = _event_date(db, typhoon_id)

    farms = _load_affected_farms(db, typhoon_id)
    if not farms:
        raise HTTPException(status_code=422, detail="No affected farms for this typhoon.")

    start, end = classifier.observation_window(event_date)

    pre_results: dict[int, classifier.CheckResult] = {}
    candidates: dict[int, tuple[dict, str]] = {}
    for farm_id, geojson, geom_hash, buffered_area in farms:
        if geojson is None:
            pre_results[farm_id] = classifier.CheckResult(classifier.STATUS_FIELD_VERIFY, "no_boundary")
        elif not buffered_area:
            pre_results[farm_id] = classifier.CheckResult(classifier.STATUS_FIELD_VERIFY, "too_small")
        else:
            candidates[farm_id] = (json.loads(geojson), geom_hash)

    coverages = {
        c.farm_id: c
        for c in db.query(SarFetchCoverage).filter(SarFetchCoverage.farm_id.in_(list(candidates))).all()
    } if candidates else {}
    fetch = {
        farm_id: geom_hash
        for farm_id, (_, geom_hash) in candidates.items()
        if _needs_fetch(coverages.get(farm_id), geom_hash, start, end)
    }

    if fetch:
        if not gee_sar_service.gee_configured():
            raise HTTPException(status_code=503, detail="Google Earth Engine is not configured on the server.")
        try:
            series = gee_sar_service.fetch_backscatter_series(
                [(farm_id, candidates[farm_id][0]) for farm_id in fetch], start, end + timedelta(days=1),
            )
        except GeeNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        except Exception as exc:  # Earth Engine computation/quota errors
            raise HTTPException(status_code=502, detail=f"Earth Engine request failed: {exc}")
        _store_fetched(db, fetch, coverages, series, start, end)
        db.commit()  # keep the fetched series even if the steps below fail

    observations = _load_observations(db, list(candidates), start, end) if candidates else {}
    db.query(SarPlantedCheck).filter(SarPlantedCheck.typhoon_id == typhoon_id).delete(
        synchronize_session=False
    )
    now = datetime.now(timezone.utc)
    rows = []
    for farm_id, *_ in farms:
        orbit = None
        result = pre_results.get(farm_id)
        if result is None:
            orbit, series_for_orbit = classifier.pick_orbit_series(observations.get(farm_id, []))
            result = classifier.classify(series_for_orbit, event_date)
        rows.append(SarPlantedCheck(
            farm_id=farm_id,
            typhoon_id=typhoon_id,
            status=result.status,
            reason_code=result.reason_code,
            t0_date=result.t0_date,
            tp_date=result.tp_date,
            vh_rise_db=result.vh_rise_db,
            ratio_drop_db=result.ratio_drop_db,
            relative_orbit=orbit,
            scene_count=result.scene_count,
            window_start=start,
            window_end=end,
            checked_by=current_user.user_id,
            checked_at=now,
        ))
    db.add_all(rows)
    db.commit()

    summary = _summary(rows)
    summary["fetched_from_gee"] = len(fetch)
    summary["from_cache"] = len(candidates) - len(fetch)
    return {"status": "success", "data": {"summary": summary, "results": [_check_to_dict(r) for r in rows]}}


@router.get("/checks")
def list_planted_checks(typhoon_id: int = Query(...), db: Session = Depends(get_db)):
    """The stored planted-check results for one typhoon; summary is null if
    it has never been run."""
    rows = (
        db.query(SarPlantedCheck)
        .filter(SarPlantedCheck.typhoon_id == typhoon_id)
        .order_by(SarPlantedCheck.farm_id)
        .all()
    )
    return {"status": "success", "data": {"summary": _summary(rows), "results": [_check_to_dict(r) for r in rows]}}
