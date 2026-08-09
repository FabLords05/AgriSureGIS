from datetime import date

from fastapi import APIRouter, Depends, Query
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.farms_cache import cache_farms_page, get_cached_farms_page
from app.core.farms_view import fetch_latest_insurance_from_view, materialized_view_available
from app.models.models import Farm, InsuranceRecord

router = APIRouter(prefix="/farms", tags=["farms"])


@router.get("/")
def list_farms(
    db: Session = Depends(get_db),
    limit: int | None = Query(None, ge=1, le=1000),
    after_id: int = Query(0, ge=0),
    active_only: bool = Query(False),
):
    """
    Lists farms with farmer/boundary identity, insurance coverage dates (from
    the farm's most recent InsuranceRecord, if any), and, where a GPX
    boundary has been uploaded, the farm's geometry as GeoJSON.

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
    cached = get_cached_farms_page(limit=limit, after_id=after_id, active_only=active_only)
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
        location_geom = (
            mapping(to_shape(farm.location_geom)) if farm.location_geom is not None else None
        )
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
                "location_geom": location_geom,
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

    cache_farms_page(limit=limit, after_id=after_id, active_only=active_only, result=result)
    return result
