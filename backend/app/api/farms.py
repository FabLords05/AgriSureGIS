from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.farms_cache import cache_farms_page, get_cached_farms_page
from app.core.farms_view import fetch_latest_insurance_from_view, materialized_view_available
from app.core.security import get_current_user
from app.models.models import AdminBoundary, Farm, InsuranceRecord

router = APIRouter(prefix="/farms", tags=["farms"], dependencies=[Depends(get_current_user)])


@router.get("/")
def list_farms(
    db: Session = Depends(get_db),
    limit: int | None = Query(None, ge=1, le=1000),
    after_id: int = Query(0, ge=0),
    active_only: bool = Query(False),
    municipality: str | None = Query(None),
):
    """
    Lists farms with farmer/boundary identity, insurance coverage dates (from
    the farm's most recent InsuranceRecord, if any), and a `has_geometry`
    flag for whether a GPX boundary has been uploaded.

    `has_geometry` (2026-08-18, stage 2 of the on-demand-pagination redesign
    -- see .claude/FUNCTION_CHANGES.md) replaces what used to be a full
    `location_geom` GeoJSON blob per row here. This endpoint's only
    consumer of geometry content was a Yes/No "Surveyed" badge
    (SpatialAnalysisModule.tsx) -- nothing here ever drew a polygon with
    it. Skipping `to_shape()`/`shapely.mapping()` per row (real per-row CPU
    cost, not DB I/O -- `Farm.location_geom` is still selected as part of
    the ORM row either way) is a straightforward win at 100k-1M farm scale.
    Actual polygon geometry now comes exclusively from GET /farms/geometry
    below, which the map calls directly.

    Runs 2 queries total per request regardless of farm count: `farmer`/
    `boundary` are eager-loaded via joinedload (they default to lazy/per-row
    loading), and the "most recent InsuranceRecord per farm" for this page
    -- instead of the old 1 (farms) + up to 3 per farm (farmer + boundary +
    insurance) queries, which was ~1,770 queries for the 589 farms
    originally in the table. That second query is a single indexed lookup
    against mv_farm_latest_insurance (app/core/farms_view.py) once
    backend/migrations/2026-08-09_farms_perf.sql has been applied; until
    then it falls back to bulk-fetching every InsuranceRecord for this
    page's farms and reducing to "most recent per farm" in Python, same as
    before that migration existed. A third query (COUNT) is added only for
    the *first* page of a paginated walk (`after_id == 0`) -- see
    `total`/`has_more` below.

    `limit`/`after_id` are both optional. Omitting `limit` preserves the
    original unpaginated behavior (every farm, in one `data` array, no
    `total`/`has_more` query) -- existing callers that don't pass these
    params (e.g. MonitoringModule.tsx) are unaffected.

    `active_only=True` restricts results to farms with at least one
    InsuranceRecord currently bracketing today (effectivity_date <= today <=
    expiry_date) -- the same "active" definition SpatialAnalysisModule.tsx's
    isActiveInsurance() already applies client-side, now pushed into the
    query so an all-inactive farm is never fetched in the first place.

    `municipality` (2026-08-17, part of the on-demand-pagination redesign --
    see .claude/FUNCTION_CHANGES.md) restricts results to farms whose
    AdminBoundary.municipality exactly matches -- pushes what was previously
    a client-side filter over the fully-loaded array into the query, since
    the redesign no longer loads the full array client-side to filter over.

    Pagination is keyset (cursor), not OFFSET/LIMIT: `after_id` is the
    highest `farm_id` already seen by the caller (0 to start from the
    beginning), and each page filters `Farm.farm_id > after_id` instead of
    skipping a row count. This replaced OFFSET/LIMIT because OFFSET's cost
    grows with how deep into a walk you are -- Postgres has to walk past
    every prior row even with an index on the ordering column, measured at
    54ms at offset=0 vs 264ms at offset=48000 on Fabio's real ~48,588-farm
    dev DB (2026-08-09). Keyset pagination costs about the same at any
    depth, since farm_id's primary-key index lets Postgres jump straight to
    the right starting point.

    `total`/`has_more`: a full paginated walk (frontend/src/lib/useFarmsData.ts)
    re-requests this endpoint hundreds of times in a row -- recomputing a
    COUNT on every single one of those, as a prior version of this endpoint
    did, was pure waste against a total that can't change mid-walk in
    practice. `total` is only computed (via `base_query`, deliberately built
    *without* the farmer/boundary joinedload options above -- a count
    doesn't need those JOINs) when `after_id == 0`, i.e. the first page of a
    walk; every subsequent page leaves `total` `None`. `has_more` never
    needs `total` at all under keyset pagination -- it's just "did a full
    page come back" (`len(data) == limit`), since there's no offset+total
    arithmetic to do; at worst this causes one extra, cheaply-detected empty
    final request right at a page-count boundary, never a wrong/missing farm.

    Page-level caching: see app/core/farms_cache.py. A no-op unless
    REDIS_URL is configured -- when it is, identical requests (same
    limit/after_id/active_only) from *any* user are served from Redis
    instead of re-running these queries, since this listing doesn't change
    on every request the way a live feed would.
    """
    cached = get_cached_farms_page(
        limit=limit, after_id=after_id, active_only=active_only, municipality=municipality
    )
    if cached is not None:
        return cached

    base_query = db.query(Farm)

    if active_only:
        today = date.today()
        active_farm_ids = (
            db.query(InsuranceRecord.farm_id)
            .filter(
                InsuranceRecord.effectivity_date <= today,
                InsuranceRecord.expiry_date >= today,
            )
            .distinct()
            # A bare Query object isn't a valid .in_() operand in SQLAlchemy
            # 2.x -- scalar_subquery() turns it into the embeddable
            # ScalarSelect the outer filter below actually needs.
            .scalar_subquery()
        )
        base_query = base_query.filter(Farm.farm_id.in_(active_farm_ids))

    if municipality:
        # Plain join (not joinedload) purely to filter -- Farm.boundary_id ->
        # AdminBoundary.boundary_id is many-to-one, so this can never
        # duplicate a Farm row, meaning base_query.count() below (and the
        # LIMIT'd page after it) both stay correct without any DISTINCT.
        base_query = base_query.join(AdminBoundary, Farm.boundary_id == AdminBoundary.boundary_id).filter(
            AdminBoundary.municipality == municipality
        )

    total: int | None = None
    if limit is not None and after_id == 0:
        total = base_query.count()

    if after_id:
        base_query = base_query.filter(Farm.farm_id > after_id)

    farms_query = (
        base_query.options(joinedload(Farm.farmer), joinedload(Farm.boundary))
        .order_by(Farm.farm_id.asc())
    )
    if limit is not None:
        farms_query = farms_query.limit(limit)

    farms = farms_query.all()

    farm_ids = [farm.farm_id for farm in farms]
    latest_insurance_by_farm_id: dict[int, InsuranceRecord] = {}
    if farm_ids:
        if materialized_view_available(db):
            # Precomputed by mv_farm_latest_insurance (see
            # app/core/farms_view.py) -- one indexed lookup instead of
            # bulk-fetching every InsuranceRecord for this page's farms and
            # reducing to "most recent per farm" in Python on every request.
            latest_insurance_by_farm_id = fetch_latest_insurance_from_view(db, farm_ids)
        else:
            # Fallback until backend/migrations/2026-08-09_farms_perf.sql has
            # been applied -- same logic the view itself encodes. Ordered
            # desc by effectivity_date, so the first record seen per farm_id
            # is the most recent -- same "latest" semantics as the old
            # per-farm .order_by(...).first(), just computed for everyone at
            # once.
            insurance_records = (
                db.query(InsuranceRecord)
                .filter(InsuranceRecord.farm_id.in_(farm_ids))
                # .nullslast() matters as soon as a farm has more than one
                # InsuranceRecord: Postgres's default for DESC is NULLS
                # FIRST (null sorts as "larger than any value"), so without
                # this, a legacy record with no dates set sorts *ahead of* a
                # real dated one -- picking the undated record as "most
                # recent" over an actually-dated (possibly
                # currently-active) one. Invisible until a farm could have
                # 2+ records (seed_active_insurance.py was the first thing
                # to create that situation).
                .order_by(InsuranceRecord.farm_id, InsuranceRecord.effectivity_date.desc().nullslast())
                .all()
            )
            for record in insurance_records:
                latest_insurance_by_farm_id.setdefault(record.farm_id, record)

    data = []
    for farm in farms:
        insurance = latest_insurance_by_farm_id.get(farm.farm_id)
        data.append(
            {
                "farm_id": farm.farm_id,
                "farmer_id": farm.farmer_id,
                "farmer_name": (
                    f"{farm.farmer.first_name} {farm.farmer.last_name}".strip()
                    if farm.farmer
                    else None
                ),
                "province": farm.boundary.province if farm.boundary else None,
                "municipality": farm.boundary.municipality if farm.boundary else None,
                "barangay": farm.boundary.barangay if farm.boundary else None,
                "area_size": float(farm.area_size) if farm.area_size is not None else None,
                "csv_farm_reference": farm.csv_farm_reference,
                "georef_id": farm.georef_id,
                "has_geometry": farm.location_geom is not None,
                "policy_no": insurance.policy_no if insurance else None,
                "effectivity_date": insurance.effectivity_date.strftime("%m/%d/%Y") if insurance and insurance.effectivity_date else None,
                "expiry_date": insurance.expiry_date.strftime("%m/%d/%Y") if insurance and insurance.expiry_date else None,
            }
        )

    if limit is not None:
        has_more = len(data) == limit
        result = {
            "status": "success",
            "data": data,
            "total": total,
            "limit": limit,
            "after_id": after_id,
            "has_more": has_more,
        }
    else:
        result = {
            "status": "success",
            "data": data,
            "total": len(data),
            "limit": None,
            "after_id": 0,
            "has_more": False,
        }

    cache_farms_page(
        limit=limit, after_id=after_id, active_only=active_only, municipality=municipality, result=result
    )
    return result


@router.get("/geometry")
def get_farms_geometry(
    bbox: str | None = Query(
        None,
        description="minLon,minLat,maxLon,maxLat (WGS84) -- the map's current visible bounds. Required unless farm_id is given.",
    ),
    farm_id: int | None = Query(
        None,
        description="When set, ignores bbox/active_only/municipality entirely and returns just this one farm's geometry, if it has one.",
    ),
    active_only: bool = Query(False),
    municipality: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """
    Viewport-based geometry for the map (2026-08-17, on-demand-pagination
    redesign -- see .claude/FUNCTION_CHANGES.md). Returns only
    `farm_id`/`location_geom` for farms whose geometry actually intersects
    the given bbox, via a real PostGIS ST_Intersects query -- replaces
    GISLeafletMap.tsx's previous approach of computing bbox intersection
    client-side over every farm's geometry already sitting in the shared
    `farms` array, which required the *entire* dataset's geometry to be
    loaded into the browser first regardless of what was actually visible.

    Deliberately a separate, lightweight endpoint from GET /farms/ -- the
    map never needs farmer/insurance/crop-stage fields, and GET /farms/'s
    consumers (the Farm Records table) don't need this on every row either;
    keeping them separate means the map's requests stay cheap.

    No pagination/limit here: a single screen's viewport is expected to
    intersect a small enough number of farms that a full result set is
    fine (matches PostGIS's own strength -- an indexed bbox query, not a
    walk). If real-world testing ever shows a viewport spanning enough
    farms to make this expensive, the fix is a tighter bbox from the
    frontend (don't fetch below a certain zoom level), not pagination here.

    `farm_id` (2026-08-18, stage 2) is a separate, bbox-independent lookup
    path for GISLeafletMap.tsx's FlyToSelectedFarm: a farm selected from a
    table row can be outside the map's current viewport fetch, so its
    geometry wouldn't be in the bbox result set yet -- this lets the map
    resolve that one farm's geometry directly, reusing this endpoint/route
    instead of adding a second one.
    """
    if farm_id is not None:
        row = (
            db.query(Farm.farm_id, Farm.location_geom)
            .filter(Farm.farm_id == farm_id, Farm.location_geom.isnot(None))
            .first()
        )
        data = [{"farm_id": row.farm_id, "location_geom": mapping(to_shape(row.location_geom))}] if row else []
        return {"status": "success", "data": data}

    if bbox is None:
        raise HTTPException(status_code=400, detail="bbox is required unless farm_id is provided")

    try:
        min_lon, min_lat, max_lon, max_lat = (float(part) for part in bbox.split(","))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="bbox must be minLon,minLat,maxLon,maxLat") from exc

    query = db.query(Farm.farm_id, Farm.location_geom).filter(Farm.location_geom.isnot(None))

    if active_only:
        today = date.today()
        active_farm_ids = (
            db.query(InsuranceRecord.farm_id)
            .filter(
                InsuranceRecord.effectivity_date <= today,
                InsuranceRecord.expiry_date >= today,
            )
            .distinct()
            .scalar_subquery()
        )
        query = query.filter(Farm.farm_id.in_(active_farm_ids))

    if municipality:
        query = query.join(AdminBoundary, Farm.boundary_id == AdminBoundary.boundary_id).filter(
            AdminBoundary.municipality == municipality
        )

    # ST_MakeEnvelope(..., 4326) builds the bbox as a real PostGIS geometry;
    # ST_Intersects lets Postgres use location_geom's spatial (GiST) index
    # instead of pulling every row into Python to test intersection there.
    envelope = func.ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)
    query = query.filter(func.ST_Intersects(Farm.location_geom, envelope))

    rows = query.all()
    data = [
        {"farm_id": farm_id, "location_geom": mapping(to_shape(geom))}
        for farm_id, geom in rows
    ]

    return {"status": "success", "data": data}


@router.get("/municipalities")
def list_farm_municipalities(db: Session = Depends(get_db)):
    """
    Distinct municipality names, for the Farm Records search box's
    suggestion list (2026-08-18, stage 2 of the on-demand-pagination
    redesign -- see .claude/FUNCTION_CHANGES.md).

    Sourced from tbl_admin_boundaries, not tbl_farms -- this stage removes
    GET /farms/'s old "load everything, then let the user filter/search
    client-side" default view, so the municipality list the search box used
    to derive from whatever farms happened to already be loaded would
    otherwise be permanently empty before a first search: nothing to
    suggest, nothing to pick, nothing loads. AdminBoundary is a small,
    fixed reference table (real municipalities in the covered region), so
    this is safe to return in full regardless of how large tbl_farms gets.
    """
    rows = (
        db.query(AdminBoundary.municipality)
        .filter(AdminBoundary.municipality.isnot(None))
        .distinct()
        .order_by(AdminBoundary.municipality.asc())
        .all()
    )
    return {"status": "success", "data": [row.municipality for row in rows]}
