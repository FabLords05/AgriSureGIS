"""
"Verify Farm Planted" (Use Case Diagram: an <<include>> of Conduct Parametric
Damage Assessment, against Google Earth Engine) -- Phase 1, 2026-10-12.

- POST /sar/layer: pre-event Sentinel-1 VV/VH colour layer over the farms the
  "Affected by" filter selects for a typhoon (app/services/gee_sar_service.py).

Everything here is per typhoon, not per bulletin (per Cristian, 2026-10-12):
the AOI is every farm under signal 2+ in any of the typhoon's bulletins
(app/api/farms.py's _affected_farm_ids) that was insured when it hit
(_insured_at_event_farm_ids), and the imagery window ends the day
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
- GET /sar/field-verify, GET /sar/field-verify/export (2026-10-13): the
  typhoon's YELLOW farms with farmer/policy/location, as JSON for the
  Assessment & Reporting preview and as a CSV for field verification.

Neither the verdict nor the check result gates anything -- AssessmentService
and the PABS/PCIC export never read them (per Fabio: record, don't gate).
"""
import io
import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from geoalchemy2 import Geography
from pydantic import BaseModel
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session, joinedload

from app.api.assessments import _export_filename
from app.api.farms import _affected_farm_ids
from app.core.database import get_db
from app.core.farmer_name import format_surname_first
from app.core.security import get_current_user
from app.models.models import (
    AreaExposureSummary,
    Farm,
    InsuranceRecord,
    InsuranceUsage,
    PlantedVerification,
    RiskAssessment,
    SarFetchCoverage,
    SarObservation,
    SarPlantedCheck,
    SystemUser,
    TropicalCycloneBulletin,
    Typhoon,
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


def _insured_at_event_farm_ids(typhoon_id: int, event_date: date):
    """
    Farms with a policy in force on the typhoon's first-bulletin date that
    isn't already spent on a DIFFERENT typhoon by a final PABS export.

    Per Cristian (2026-10-12): SAR only checks affected farms that were
    insured, so Earth Engine is never asked about the 100K+ farms with no
    usable cover. Dated to the typhoon, not to today (unlike _active_farm_ids
    in farms.py), so a past typhoon's farms still count after their policy
    expires, and a policy already exported for THIS typhoon still counts --
    those are exactly the farms being paid for it.
    """
    used_elsewhere = select(InsuranceUsage.insurance_records_id).where(
        InsuranceUsage.is_used.is_(True),
        InsuranceUsage.finalized_at.isnot(None),
        InsuranceUsage.typhoon_id != typhoon_id,
    )
    return select(InsuranceRecord.farm_id).where(
        InsuranceRecord.effectivity_date <= event_date,
        InsuranceRecord.expiry_date >= event_date,
        InsuranceRecord.insurance_records_id.not_in(used_elsewhere),
    )


def _sar_farm_filter(db: Session, typhoon_id: int, event_date: date):
    """The SAR AOI: affected by the typhoon AND insured at it."""
    return (
        Farm.farm_id.in_(_affected_farm_ids(db, typhoon_id)),
        Farm.farm_id.in_(_insured_at_event_farm_ids(typhoon_id, event_date)),
    )


def _load_affected_polygons(db: Session, typhoon_id: int, event_date: date) -> tuple[list[tuple[int, dict]], int]:
    """(farm_id, GeoJSON) for the typhoon's affected, insured farms that have
    a GPX polygon, capped at MAX_LAYER_FARMS + 1 so the caller can tell the
    cap was hit, plus how many such farms were skipped for having no polygon."""
    aoi = _sar_farm_filter(db, typhoon_id, event_date)
    rows = (
        db.query(Farm.farm_id, func.ST_AsGeoJSON(Farm.location_geom, 6))
        .filter(*aoi, Farm.location_geom.isnot(None))
        .order_by(Farm.farm_id)
        .limit(MAX_LAYER_FARMS + 1)
        .all()
    )
    skipped = (
        db.query(func.count(Farm.farm_id))
        .filter(*aoi, Farm.location_geom.is_(None))
        .scalar()
    ) or 0
    return [(farm_id, json.loads(geojson)) for farm_id, geojson in rows], skipped


@router.post("/layer")
def get_planted_layer(body: LayerRequest, db: Session = Depends(get_db)):
    """
    Pre-event VV/VH-ratio tile layer clipped to the typhoon's affected farm
    polygons that were insured at it (TCWS signal >= 2 municipalities in any
    bulletin -- the Spatial Analysis "Affected by" set -- narrowed by
    _insured_at_event_farm_ids). 404 unknown typhoon, 503 if Earth Engine
    isn't configured, 422 if there's nothing to draw, 502 if Earth Engine
    itself fails.
    """
    event_date = _event_date(db, body.typhoon_id)
    if not gee_sar_service.gee_configured():
        raise HTTPException(status_code=503, detail="Google Earth Engine is not configured on the server.")

    polygons, skipped_no_geom = _load_affected_polygons(db, body.typhoon_id, event_date)
    if not polygons:
        raise HTTPException(
            status_code=422,
            detail="No affected, insured farms with a surveyed (GPX) polygon for this typhoon.",
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

def _load_affected_farms(db: Session, typhoon_id: int, event_date: date) -> list[tuple]:
    """(farm_id, GeoJSON, geom md5, area left after the inward buffer in m²)
    for every farm the typhoon affected that was insured at it
    (_insured_at_event_farm_ids). The last three are None for a farm with no
    GPX polygon. The buffered area is computed here, in PostGIS, so farms too
    small to sample are never sent to Earth Engine."""
    return (
        db.query(
            Farm.farm_id,
            func.ST_AsGeoJSON(Farm.location_geom, 6),
            func.md5(func.ST_AsEWKB(Farm.location_geom)),
            func.ST_Area(func.ST_Buffer(cast(Farm.location_geom, Geography), -INWARD_BUFFER_M)),
        )
        .filter(*_sar_farm_filter(db, typhoon_id, event_date))
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
    bulletins -- the "Affected by" set) that was insured when it hit
    (_insured_at_event_farm_ids) as GREEN "planted" or
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

    farms = _load_affected_farms(db, typhoon_id, event_date)
    if not farms:
        raise HTTPException(status_code=422, detail="No affected farms were insured when this typhoon hit.")

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


# ---------------------------------------------------------------------------
# Field verification list (2026-10-13, per Cristian)
# ---------------------------------------------------------------------------

# Row key -> CSV header, in export order. Farmer/farm/policy headers are
# spelled like the PABS export's (assessments.PABS_CSV_HEADERS).
FIELD_VERIFY_CSV_HEADERS = {
    "FARMER_NAME": "FARMER NAME",
    "FARMERID": "FARMERSID",
    "FARMID": "FARMID",
    "CIC_NO": "CIC NO",
    "PROVINCE": "PROVINCE",
    "MUNICIPALITY": "MUNICIPALITY",
    "BARANGAY": "BARANGAY",
    "AREA": "AREA",
    "TYPHOON_NAME": "TYPHOON_NAME",
    "SAR_REASON": "SAR REASON",
}


def _field_verify_list(db: Session, typhoon_id: int) -> dict:
    """
    The typhoon's YELLOW "field_verify" farms from its stored planted check,
    with farmer, policy and location -- limited to farms eligible for
    insurance on this typhoon, i.e. with a computed assessment for it (the
    Assessment & Reporting / PABS rows; per Cristian, 2026-10-13). The check
    itself covers every affected farm insured at the event, which is wider
    (no signal/exposure/crop-stage/matrix rule). CIC NO and the farmer come
    from the assessed policy. `checked` is every farm the check covered
    (0 = never run); `assessed` is how many farms have an assessment
    (0 = Compute Assessments not run). Read-only: nothing is locked.
    """
    typhoon = db.get(Typhoon, typhoon_id)
    if typhoon is None:
        raise HTTPException(status_code=404, detail="Typhoon not found.")

    checks = db.query(SarPlantedCheck).filter(SarPlantedCheck.typhoon_id == typhoon_id).all()
    checked_at = max((c.checked_at for c in checks if c.checked_at), default=None)

    # Same "computed" filter as the PABS rows (matrix_id set).
    policies: dict[int, InsuranceRecord] = {
        a.insurance_record.farm_id: a.insurance_record
        for a in db.query(RiskAssessment)
        .join(AreaExposureSummary, RiskAssessment.summary_id == AreaExposureSummary.summary_id)
        .options(joinedload(RiskAssessment.insurance_record).joinedload(InsuranceRecord.farmer))
        .filter(AreaExposureSummary.typhoon_id == typhoon_id, RiskAssessment.matrix_id.isnot(None))
        .all()
        if a.insurance_record is not None
    }
    flagged = sorted(
        (c for c in checks if c.status == classifier.STATUS_FIELD_VERIFY and c.farm_id in policies),
        key=lambda c: c.farm_id,
    )
    rows: list[dict] = []
    if flagged:
        farms = {
            f.farm_id: f
            for f in db.query(Farm)
            .options(joinedload(Farm.farmer), joinedload(Farm.boundary))
            .filter(Farm.farm_id.in_([c.farm_id for c in flagged]))
            .all()
        }

        for check in flagged:
            farm = farms.get(check.farm_id)
            policy = policies.get(check.farm_id)
            # The policy's farmer, as in the PABS export; the farm's otherwise.
            farmer = (policy.farmer if policy else None) or (farm.farmer if farm else None)
            boundary = farm.boundary if farm else None
            rows.append({
                "farm_id": check.farm_id,
                "FARMER_NAME": format_surname_first(farmer, with_middle_initial=True) if farmer else None,
                "FARMERID": farmer.farmers_id if farmer else None,
                "FARMID": farm.csv_farm_reference if farm else None,
                "CIC_NO": policy.policy_no if policy else None,
                "PROVINCE": boundary.province if boundary else None,
                "MUNICIPALITY": boundary.municipality if boundary else None,
                "BARANGAY": boundary.barangay if boundary else None,
                "AREA": float(farm.area_size) if farm and farm.area_size is not None else None,
                "TYPHOON_NAME": typhoon.name,
                "SAR_REASON": classifier.REASON_LABELS.get(check.reason_code, check.reason_code),
            })

    return {
        "typhoon_id": typhoon_id,
        "typhoon_name": typhoon.name,
        "checked": len(checks),
        "assessed": len(policies),
        "checked_at": checked_at.isoformat() if checked_at else None,
        "rows": rows,
    }


@router.get("/field-verify")
def get_field_verify_list(typhoon_id: int = Query(...), db: Session = Depends(get_db)):
    """JSON version of the field verification list, for the on-screen preview."""
    return {"status": "success", "data": _field_verify_list(db, typhoon_id)}


@router.get("/field-verify/export")
def export_field_verify_csv(typhoon_id: int = Query(...), db: Session = Depends(get_db)):
    """The same list as a CSV download. 422 if the planted check has never
    been run for the typhoon."""
    data = _field_verify_list(db, typhoon_id)
    if data["checked"] == 0:
        raise HTTPException(status_code=422, detail="The SAR planted check hasn't been run for this typhoon yet.")
    dataframe = pd.DataFrame(data["rows"], columns=list(FIELD_VERIFY_CSV_HEADERS)).rename(
        columns=FIELD_VERIFY_CSV_HEADERS
    )
    buffer = io.StringIO()
    dataframe.to_csv(buffer, index=False, float_format="%.2f")
    filename = _export_filename([data["typhoon_name"]], "SAR_Field_Verification")
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
