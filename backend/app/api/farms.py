from fastapi import APIRouter, Depends
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import Farm

router = APIRouter(prefix="/farms", tags=["farms"])


@router.get("/")
def list_farms(db: Session = Depends(get_db)):
    """
    Lists all farms with farmer/boundary identity and, where a GPX boundary has
    been uploaded, the farm's geometry as GeoJSON.
    """
    farms = db.query(Farm).order_by(Farm.farm_id.asc()).all()

    data = []
    for farm in farms:
        location_geom = (
            mapping(to_shape(farm.location_geom)) if farm.location_geom is not None else None
        )
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
            }
        )

    return {"status": "success", "data": data}
