from datetime import date

from fastapi import APIRouter, Depends, Query
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.models.models import Farm, InsuranceRecord

router = APIRouter(prefix="/farms", tags=["farms"])


@router.get("/")
def list_farms(
    db: Session = Depends(get_db),
    limit: int | None = Query(None, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    active_only: bool = Query(False),
):
    """
    Lists farms with farmer/boundary identity, insurance coverage dates (from
    the farm's most recent InsuranceRecord, if any), and, where a GPX
    boundary has been uploaded, the farm's geometry as GeoJSON.

    Runs 2 queries total per request regardless of farm count: `farmer`/
    `boundary` are eager-loaded via joinedload (they default to lazy/per-row
    loading), and insurance records are bulk-fetched once -- scoped to
    whichever page of farms this request resolved to -- and reduced to "most
    recent per farm" in Python -- instead of the old 1 (farms) + up to 3 per
    farm (farmer + boundary + insurance) queries, which was ~1,770 queries
    for the 589 farms currently in the table. A third query (COUNT) is added
    only when `limit` is given, to report `total`/`has_more`.

    `limit`/`offset` are both optional. Omitting `limit` preserves the
    original unpaginated behavior (every farm, in one `data` array, no
    `total`/`has_more` query) -- existing callers that don't pass these
    params (e.g. MonitoringModule.tsx) are unaffected.

    `active_only=True` restricts results to farms with at least one
    InsuranceRecord currently bracketing today (effectivity_date <= today <=
    expiry_date) -- the same "active" definition SpatialAnalysisModule.tsx's
    isActiveInsurance() already applies client-side, now pushed into the
    query so an all-inactive farm is never fetched in the first place.
    """
    farms_query = (
        db.query(Farm)
        .options(joinedload(Farm.farmer), joinedload(Farm.boundary))
        .order_by(Farm.farm_id.asc())
    )

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
        farms_query = farms_query.filter(Farm.farm_id.in_(active_farm_ids))

    total: int | None = None
    if limit is not None:
        total = farms_query.order_by(None).count()
        farms_query = farms_query.offset(offset).limit(limit)

    farms = farms_query.all()

    farm_ids = [farm.farm_id for farm in farms]
    latest_insurance_by_farm_id: dict[int, InsuranceRecord] = {}
    if farm_ids:
        # Ordered desc by effectivity_date, so the first record seen per
        # farm_id is the most recent -- same "latest" semantics as the old
        # per-farm .order_by(...).first(), just computed for everyone at once.
        insurance_records = (
            db.query(InsuranceRecord)
            .filter(InsuranceRecord.farm_id.in_(farm_ids))
            .order_by(InsuranceRecord.farm_id, InsuranceRecord.effectivity_date.desc())
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
        has_more = offset + len(data) < total
        return {
            "status": "success",
            "data": data,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": has_more,
        }

    return {
        "status": "success",
        "data": data,
        "total": len(data),
        "limit": None,
        "offset": 0,
        "has_more": False,
    }
