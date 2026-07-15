from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import models

router = APIRouter(prefix="/api/upload", tags=["upload"])


def _normalize_value(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, float) and pd.isna(value):
        return None

    if hasattr(value, "item"):
        value = value.item()

    if isinstance(value, str):
        value = value.strip()
        if value == "" or value.lower() in {"nan", "none", "null"}:
            return None
        return value

    return value


def _parse_decimal(value: Any) -> Decimal | None:
    normalized = _normalize_value(value)
    if normalized is None:
        return None

    if isinstance(normalized, (int, float)):
        return Decimal(str(normalized))

    text = str(normalized).replace(",", "").strip()
    if text == "":
        return None

    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _parse_date(value: Any) -> date | None:
    normalized = _normalize_value(value)
    if normalized is None:
        return None

    try:
        parsed = pd.to_datetime(normalized, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.date()
    except Exception:
        return None


def prepare_row_payload(row: Any) -> dict[str, Any]:
    data = row.to_dict() if hasattr(row, "to_dict") else dict(row)

    boundary = {
        "province": _normalize_value(data.get("Province")) or "",
        "municipality": _normalize_value(data.get("Municipality")) or "",
        "barangay": _normalize_value(data.get("Barangay")) or "",
    }

    farmer = {
        "rsbsa_no": _normalize_value(data.get("RSBSA No.")) or "",
        "last_name": _normalize_value(data.get("Surname")) or "",
        "first_name": _normalize_value(data.get("Firstname")) or "",
        "middle_name": _normalize_value(data.get("Middlename")),
    }

    farm = {
        "csv_farm_reference": _normalize_value(data.get("Farm ID")),
        "georef_id": _normalize_value(data.get("Georef ID")),
        "area_size": _parse_decimal(data.get("AreaInsured")),
    }

    insurance = {
        "policy_no": _normalize_value(data.get("Policy No.")) or "",
        "program_type": _normalize_value(data.get("Program Type")),
        "effectivity_date": _parse_date(data.get("Effectivity Date")),
        "expiry_date": _parse_date(data.get("Expiry Date")),
        "amount_cover": _parse_decimal(data.get("AmountofCover")),
    }

    assessment = {
        "crop_stage_no": _normalize_value(data.get("Stage No.")),
        "crop_stage": _normalize_value(data.get("Stage")),
        "estimated_damage": _parse_decimal(data.get("EstimatedDamage")),
        "adjuster_calculation": _normalize_value(data.get("Adjuster's Stage of Crop Calculation")),
    }

    return {
        "boundary": boundary,
        "farmer": farmer,
        "farm": farm,
        "insurance": insurance,
        "assessment": assessment,
    }


@router.post("/csv", status_code=status.HTTP_200_OK)
def upload_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file.")

    if not file.content_type or "csv" not in file.content_type:
        raise HTTPException(status_code=400, detail="The uploaded file must be a CSV.")

    try:
        if file.file.seekable():
            file.file.seek(0)
        dataframe = pd.read_csv(file.file)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to parse CSV file: {exc}") from exc

    if dataframe.empty:
        return {
            "status": "success",
            "message": "No rows were found in the uploaded CSV.",
            "rows_processed": 0,
            "rows_inserted": 0,
            "rows_skipped": 0,
        }

    processed_rows = 0
    inserted_rows = 0
    skipped_rows = 0

    try:
        for _, row in dataframe.iterrows():
            processed_rows += 1
            payload = prepare_row_payload(row)

            boundary = (
                db.query(models.AdminBoundary)
                .filter(
                    models.AdminBoundary.province == payload["boundary"]["province"],
                    models.AdminBoundary.municipality == payload["boundary"]["municipality"],
                    models.AdminBoundary.barangay == payload["boundary"]["barangay"],
                )
                .first()
            )
            if boundary is None:
                boundary = models.AdminBoundary(**payload["boundary"])
                db.add(boundary)
                db.flush()

            farmer = (
                db.query(models.FarmerProfile)
                .filter(models.FarmerProfile.rsbsa_no == payload["farmer"]["rsbsa_no"])
                .first()
            )
            if farmer is None:
                farmer = models.FarmerProfile(**payload["farmer"])
                db.add(farmer)
                db.flush()

            existing_farm = (
                db.query(models.Farm)
                .filter(models.Farm.csv_farm_reference == payload["farm"]["csv_farm_reference"])
                .first()
            )
            farm = existing_farm
            if farm is None:
                farm = models.Farm(
                    farmer_id=farmer.farmer_id,
                    boundary_id=boundary.boundary_id,
                    csv_farm_reference=payload["farm"]["csv_farm_reference"],
                    georef_id=payload["farm"]["georef_id"],
                    area_size=payload["farm"]["area_size"] or 0,
                    location_geom=None,
                )
                db.add(farm)
                db.flush()

            insurance = (
                db.query(models.InsuranceRecord)
                .filter(models.InsuranceRecord.policy_no == payload["insurance"]["policy_no"])
                .first()
            )
            if insurance is None:
                insurance = models.InsuranceRecord(
                    farm_id=farm.farm_id,
                    policy_no=payload["insurance"]["policy_no"],
                    program_type=payload["insurance"]["program_type"],
                    effectivity_date=payload["insurance"]["effectivity_date"],
                    expiry_date=payload["insurance"]["expiry_date"],
                    amount_cover=payload["insurance"]["amount_cover"] or 0,
                )
                db.add(insurance)
                db.flush()
                inserted_rows += 1
            else:
                skipped_rows += 1
                continue

            assessment = models.RiskAssessment(
                insurance_records_id=insurance.insurance_records_id,
                crop_stage_no=payload["assessment"]["crop_stage_no"],
                crop_stage=payload["assessment"]["crop_stage"],
                estimated_damage=payload["assessment"]["estimated_damage"],
                adjuster_calculation=payload["assessment"]["adjuster_calculation"],
            )
            db.add(assessment)

        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"CSV ingestion failed: {exc}") from exc

    return {
        "status": "success",
        "message": "CSV data ingested successfully.",
        "rows_processed": processed_rows,
        "rows_inserted": inserted_rows,
        "rows_skipped": skipped_rows,
    }
