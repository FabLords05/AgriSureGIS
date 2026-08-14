import functools
import io
import logging
import re
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.farms_cache import invalidate_farms_cache
from app.core.farms_view import refresh_farm_latest_insurance_view
from app.models import models
from app.services.gpx_farmer_matcher import GpxFarmerMatcherService
from app.services.gpx_parser import GpxParserService

router = APIRouter(prefix="/api/upload", tags=["upload"])

logger = logging.getLogger(__name__)

_PSGC_LOOKUP_PATH = Path(__file__).resolve().parent.parent / "data" / "psgc_region10_boundaries.csv"

# Batch size for the prefetch WHERE ... IN (...) queries below -- keeps a single
# query's parameter list bounded even for a very large CSV, instead of one
# giant IN(...) covering every distinct value in the file.
_PREFETCH_CHUNK_SIZE = 1000

# How often (in rows) to emit a progress log line while ingesting -- frequent
# enough that a real stall/slowdown is visible in the logs within a reasonable
# window, without spamming a line per row.
_PROGRESS_LOG_EVERY = 1000


def _chunked(items: Iterable[str], size: int) -> Iterator[list[str]]:
    chunk: list[str] = []
    for item in items:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _boundary_key(province: str, municipality: str, barangay: str) -> tuple[str, str, str]:
    """Real PABS exports are inconsistent about case (e.g. the legacy CSV format
    uses Title Case municipality/barangay names, the newer export uses ALL CAPS) --
    normalize before comparing/keying on these so a boundary/PSGC code isn't missed
    over casing alone."""
    return (province.strip().upper(), municipality.strip().upper(), barangay.strip().upper())


@functools.lru_cache(maxsize=1)
def _load_psgc_lookup() -> dict[tuple[str, str, str], str]:
    """Same reference file backend/seed_database.py already uses. Loaded once per
    process (it's small and static) rather than re-read per row."""
    lookup_df = pd.read_csv(_PSGC_LOOKUP_PATH)
    return {
        _boundary_key(row["province"], row["municipality"], row["barangay"]): str(row["psgc_code"])
        for _, row in lookup_df.iterrows()
    }


_TRAILING_PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _strip_trailing_parenthetical(name: str) -> str:
    """Drops a trailing '(...)' qualifier, e.g. 'POBLACION (TUBOD)' -> 'POBLACION',
    'DIAZ (ROMUALDEZ)' -> 'DIAZ'. Only ever tried as a fallback after an exact match
    already failed -- confirmed against the full psgc_region10_boundaries.csv that no
    municipality has two distinct barangays whose only difference is such a suffix,
    so this can't accidentally collapse two real places into one."""
    return _TRAILING_PARENTHETICAL_RE.sub("", name).strip()


def _municipality_alias_variants(municipality: str) -> list[str]:
    """Real PABS exports and psgc_region10_boundaries.csv disagree on a couple of
    common PH municipality-naming conventions ('Surigao City' vs 'City of Surigao',
    'Sta. Josefa' vs 'Santa Josefa') -- generate the alternate spelling(s) so a
    lookup miss on the literal name gets another shot before being reported as a
    genuinely missing PSGC entry."""
    variants = []
    if municipality.endswith(" CITY"):
        variants.append(f"CITY OF {municipality[: -len(' CITY')]}")
    elif municipality.startswith("CITY OF "):
        variants.append(f"{municipality[len('CITY OF '):]} CITY")
    for abbrev, full in (("STA. ", "SANTA "), ("STO. ", "SANTO ")):
        if municipality.startswith(abbrev):
            variants.append(full + municipality[len(abbrev):])
        elif municipality.startswith(full):
            variants.append(abbrev + municipality[len(full):])
    return variants


def _resolve_psgc_code(boundary_key: tuple[str, str, str], lookup: dict[tuple[str, str, str], str]) -> str | None:
    """Looks up a PSGC code for (province, municipality, barangay), retrying a
    handful of known PABS-export naming variants -- city/municipality form, Sta./
    Santo abbreviations, a trailing '(...)' qualifier on municipality and/or
    barangay -- before reporting a genuine miss. Every fallback stays scoped to
    the row's own province (and, for the parenthetical strip, its own municipality
    once that's resolved) -- this never matches across two different provinces or
    municipalities."""
    if boundary_key in lookup:
        return lookup[boundary_key]

    province, municipality, barangay = boundary_key
    municipality_candidates = [municipality, *_municipality_alias_variants(municipality)]
    barangay_candidates = [barangay]
    stripped_barangay = _strip_trailing_parenthetical(barangay)
    if stripped_barangay != barangay:
        barangay_candidates.append(stripped_barangay)

    for muni in municipality_candidates:
        muni_candidates = [muni]
        stripped_muni = _strip_trailing_parenthetical(muni)
        if stripped_muni != muni:
            muni_candidates.append(stripped_muni)
        for m in muni_candidates:
            for b in barangay_candidates:
                psgc_code = lookup.get((province, m, b))
                if psgc_code is not None:
                    return psgc_code
    return None


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


def _normalize_text_upper(value: Any) -> str | None:
    """Same cleanup as _normalize_value, plus uppercasing -- applied to farmer-name
    fields so casing is consistent regardless of how the source CSV typed them (real
    PABS exports mix ALL CAPS and Title Case surnames within the same file)."""
    normalized = _normalize_value(value)
    if isinstance(normalized, str):
        return normalized.upper()
    return normalized


def _stringify_id(value: Any) -> str | None:
    """Coerces a pandas-inferred numeric ID column to text. Applies to every
    VARCHAR-mapped identifier read from the CSV (Policy No., FARMID, FarmersID,
    RSBSA No., Georef ID) -- any of these can be all-digits in a given export
    (confirmed for real: Policy No. is pure-digit in the actual PABS CSV, which
    made Postgres reject `policy_no = 1192155` with "operator does not exist:
    character varying = integer" since these columns are never used
    arithmetically and must stay text for comparison against a VARCHAR column."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


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


def _normalize_header(key: str) -> str:
    """Collapses a CSV header down to bare alphanumerics so e.g. 'Farm ID' (legacy
    pabs_results.csv layout) and 'FARMID' (the newer PABS export layout) both
    resolve to the same lookup key, along with any other casing/spacing drift."""
    return re.sub(r"[^a-z0-9]", "", key.lower())


def prepare_row_payload(row: Any) -> dict[str, Any]:
    raw = row.to_dict() if hasattr(row, "to_dict") else dict(row)
    normalized = {_normalize_header(k): v for k, v in raw.items()}

    def get(*header_names: str) -> Any:
        for name in header_names:
            key = _normalize_header(name)
            if key in normalized:
                return normalized[key]
        return None

    # Store the boundary fields pre-normalized via _boundary_key() itself, rather than
    # separately re-deriving the same casing -- guarantees the persisted row always
    # matches the case used to look it up, instead of two parallel normalizations that
    # can (and did) diverge.
    province, municipality, barangay = _boundary_key(
        _normalize_value(get("Province")) or "",
        _normalize_value(get("Municipality")) or "",
        _normalize_value(get("Barangay")) or "",
    )
    boundary = {
        "province": province,
        "municipality": municipality,
        "barangay": barangay,
    }

    farmer = {
        "farmers_id": _stringify_id(_normalize_value(get("FarmersID"))),
        "rsbsa_no": _stringify_id(_normalize_value(get("RSBSA No."))),
        "last_name": _normalize_text_upper(get("Surname")) or "",
        "first_name": _normalize_text_upper(get("Firstname")) or "",
        "middle_name": _normalize_text_upper(get("Middlename")),
    }

    farm = {
        "csv_farm_reference": _stringify_id(_normalize_value(get("FARMID", "Farm ID"))),
        "georef_id": _stringify_id(_normalize_value(get("Georef ID"))),
        "area_size": _parse_decimal(get("AreaInsured")),
    }

    insurance = {
        "policy_no": _stringify_id(_normalize_value(get("Policy No."))) or "",
        "program_type": _normalize_value(get("Program Type")),
        "product_name": _normalize_value(get("Product Name")),
        "effectivity_date": _parse_date(get("Effectivity Date")),
        "expiry_date": _parse_date(get("Expiry Date")),
        "amount_cover": _parse_decimal(get("AmountofCover")),
    }

    # Not a real computed assessment -- just carries the CSV's own crop-stage/damage
    # figures forward so AssessmentService.calculate_for_bulletin() has a crop stage
    # to read for this policy once a real typhoon is assessed. risk_exposure_amount
    # is kept only to cross-check against estimated_damage, never persisted.
    crop_stage_seed = {
        "crop_stage_no": _normalize_value(get("Stage No.")),
        "crop_stage": _normalize_value(get("Stage")),
        "estimated_damage": _parse_decimal(get("EstimatedDamage")),
        "risk_exposure_amount": _parse_decimal(get("RiskExposureAmount")),
    }

    return {
        "boundary": boundary,
        "farmer": farmer,
        "farm": farm,
        "insurance": insurance,
        "crop_stage_seed": crop_stage_seed,
    }


@dataclass
class _IngestCaches:
    """Per-upload, in-process caches so a repeated boundary/farmer/farm across many
    rows of the same CSV (e.g. the same barangay appears in ~10-20 rows on average)
    is only ever queried once. Populated by the caller ONLY after a row's SAVEPOINT
    successfully commits -- a rolled-back row's newly-created objects must never
    leak into a later row's lookups."""

    boundaries: dict[tuple[str, str, str], models.AdminBoundary] = field(default_factory=dict)
    farmers_by_farmers_id: dict[str, models.FarmerProfile] = field(default_factory=dict)
    farmers_by_rsbsa_no: dict[str, models.FarmerProfile] = field(default_factory=dict)
    farms_by_reference: dict[str, models.Farm] = field(default_factory=dict)


def _prefetch_caches(prepared_rows: list[tuple[int, dict[str, Any]]], db: Session) -> _IngestCaches:
    """Primes _IngestCaches with everything this upload's rows are going to look
    up, in a handful of bulk queries, instead of the per-row SELECT that used to
    run for every single row.

    This is what actually fixes the root cause of slow/stalled ingestion: before
    this, `tbl_farms.csv_farm_reference` had no DB index, so every never-before-seen
    farm reference (i.e. almost every row on a first-time import) triggered an
    unindexed full table scan of tbl_farms -- and that table grows by one row for
    every farm this same upload has already inserted, making a large CSV
    effectively O(n^2). Bulk-loading the rows that already exist up front removes
    the scan from the hot per-row path entirely; the (now indexed, see
    init_schema.sql) per-row fallback query in _ingest_row only ever fires for a
    genuinely new value not covered by this prefetch or by a still-open savepoint
    within this same run.
    """
    caches = _IngestCaches()

    # tbl_admin_boundaries is small (bounded by the number of barangays in one
    # PSGC region, ~2-3k rows) -- cheaper to load it whole once than to build a
    # composite IN(...) filter per distinct (province, municipality, barangay)
    # combination in the file.
    for boundary in db.query(models.AdminBoundary).all():
        key = _boundary_key(boundary.province, boundary.municipality, boundary.barangay)
        caches.boundaries[key] = boundary

    farmers_ids = {p["farmer"]["farmers_id"] for _, p in prepared_rows if p["farmer"]["farmers_id"]}
    rsbsa_nos = {p["farmer"]["rsbsa_no"] for _, p in prepared_rows if p["farmer"]["rsbsa_no"]}
    farm_refs = {p["farm"]["csv_farm_reference"] for _, p in prepared_rows if p["farm"]["csv_farm_reference"]}

    for chunk in _chunked(farmers_ids, _PREFETCH_CHUNK_SIZE):
        for farmer in db.query(models.FarmerProfile).filter(models.FarmerProfile.farmers_id.in_(chunk)).all():
            caches.farmers_by_farmers_id[farmer.farmers_id] = farmer

    for chunk in _chunked(rsbsa_nos, _PREFETCH_CHUNK_SIZE):
        for farmer in db.query(models.FarmerProfile).filter(models.FarmerProfile.rsbsa_no.in_(chunk)).all():
            caches.farmers_by_rsbsa_no[farmer.rsbsa_no] = farmer
            # Same identity, so a farmer reached via rsbsa_no here should also
            # satisfy a later row that looks the same farmer up by farmers_id.
            if farmer.farmers_id and farmer.farmers_id not in caches.farmers_by_farmers_id:
                caches.farmers_by_farmers_id[farmer.farmers_id] = farmer

    for chunk in _chunked(farm_refs, _PREFETCH_CHUNK_SIZE):
        for farm in db.query(models.Farm).filter(models.Farm.csv_farm_reference.in_(chunk)).all():
            caches.farms_by_reference[farm.csv_farm_reference] = farm

    return caches


@dataclass
class _RowIngestResult:
    outcome: str  # "inserted" or "skipped"
    boundary_key: tuple[str, str, str]
    boundary: models.AdminBoundary
    farmers_id: str | None
    rsbsa_no: str | None
    farmer: models.FarmerProfile
    farm_reference: str | None
    farm: models.Farm


def _ingest_row(payload: dict[str, Any], db: Session, caches: _IngestCaches) -> _RowIngestResult:
    """Processes one already-parsed CSV row. Raises on any unrecoverable per-row
    problem (e.g. no PSGC code on file) -- the caller is responsible for the
    per-row SAVEPOINT and for committing this row's results into `caches`."""
    boundary_key = _boundary_key(
        payload["boundary"]["province"], payload["boundary"]["municipality"], payload["boundary"]["barangay"]
    )
    boundary = caches.boundaries.get(boundary_key)
    if boundary is None:
        boundary = (
            db.query(models.AdminBoundary)
            .filter(
                func.upper(models.AdminBoundary.province) == boundary_key[0],
                func.upper(models.AdminBoundary.municipality) == boundary_key[1],
                func.upper(models.AdminBoundary.barangay) == boundary_key[2],
            )
            .first()
        )
        if boundary is None:
            psgc_code = _resolve_psgc_code(boundary_key, _load_psgc_lookup())
            if psgc_code is None:
                raise ValueError(
                    f"No PSGC code on file for {boundary_key}. Add it to "
                    "app/data/psgc_region10_boundaries.csv before ingesting this row."
                )
            boundary = models.AdminBoundary(psgc_code=psgc_code, **payload["boundary"])
            db.add(boundary)
            db.flush()

    # Farmer identity: prefer farmers_id (100% populated in real PABS exports)
    # over rsbsa_no (blank on ~29% of real rows). Never match on a blank/None
    # key in either case -- that would silently collapse distinct farmers who
    # both happen to have no RSBSA number onto the same profile.
    farmer_payload = payload["farmer"]
    farmer = None
    if farmer_payload["farmers_id"]:
        farmer = caches.farmers_by_farmers_id.get(farmer_payload["farmers_id"])
        if farmer is None:
            farmer = (
                db.query(models.FarmerProfile)
                .filter(models.FarmerProfile.farmers_id == farmer_payload["farmers_id"])
                .first()
            )
    if farmer is None and farmer_payload["rsbsa_no"]:
        farmer = caches.farmers_by_rsbsa_no.get(farmer_payload["rsbsa_no"])
        if farmer is None:
            farmer = (
                db.query(models.FarmerProfile)
                .filter(models.FarmerProfile.rsbsa_no == farmer_payload["rsbsa_no"])
                .first()
            )
        if farmer is not None and farmer.farmers_id is None and farmer_payload["farmers_id"]:
            farmer.farmers_id = farmer_payload["farmers_id"]
    if farmer is None:
        farmer = models.FarmerProfile(**farmer_payload)
        db.add(farmer)
        db.flush()

    # Farm identity: same never-match-on-blank rule as farmer identity above.
    farm_payload = payload["farm"]
    farm = None
    if farm_payload["csv_farm_reference"]:
        farm = caches.farms_by_reference.get(farm_payload["csv_farm_reference"])
        if farm is None:
            farm = (
                db.query(models.Farm)
                .filter(models.Farm.csv_farm_reference == farm_payload["csv_farm_reference"])
                .first()
            )
    if farm is None:
        farm = models.Farm(
            farmer_id=farmer.farmer_id,
            boundary_id=boundary.boundary_id,
            csv_farm_reference=farm_payload["csv_farm_reference"],
            georef_id=farm_payload["georef_id"],
            area_size=farm_payload["area_size"] or 0,
            location_geom=None,
        )
        db.add(farm)
        db.flush()

    def _result(outcome: str) -> _RowIngestResult:
        return _RowIngestResult(
            outcome=outcome,
            boundary_key=boundary_key,
            boundary=boundary,
            farmers_id=farmer_payload["farmers_id"],
            rsbsa_no=farmer_payload["rsbsa_no"],
            farmer=farmer,
            farm_reference=farm_payload["csv_farm_reference"],
            farm=farm,
        )

    # Duplicate check is (policy_no, farm_id), not policy_no alone -- real PABS
    # exports have one Policy No. (a batch/program policy) legitimately covering
    # many different farmers/farms, each of which needs its own InsuranceRecord.
    insurance = (
        db.query(models.InsuranceRecord)
        .filter(
            models.InsuranceRecord.policy_no == payload["insurance"]["policy_no"],
            models.InsuranceRecord.farm_id == farm.farm_id,
        )
        .first()
    )
    if insurance is not None:
        return _result("skipped")

    insurance = models.InsuranceRecord(
        farmer_id=farmer.farmer_id,
        farm_id=farm.farm_id,
        policy_no=payload["insurance"]["policy_no"],
        program_type=payload["insurance"]["program_type"],
        product_name=payload["insurance"]["product_name"],
        effectivity_date=payload["insurance"]["effectivity_date"],
        expiry_date=payload["insurance"]["expiry_date"],
        amount_cover=payload["insurance"]["amount_cover"] or 0,
    )
    db.add(insurance)
    db.flush()

    # Crop-stage seed row -- not a real computed assessment (no matrix_id/
    # wind_velocity/summary_id set). It exists only so
    # AssessmentService.calculate_for_bulletin() has a crop_stage_no to read
    # for this policy once a real typhoon is assessed; export_assessments_csv()
    # already filters these out via `matrix_id IS NOT NULL`. final_indemnity_payment
    # is seeded from estimated_damage (not a real payout yet) -- the same
    # placeholder convention backend/seed_database.py already uses.
    seed = payload["crop_stage_seed"]
    estimated_damage = seed["estimated_damage"] or Decimal("0.00")
    risk_exposure_amount = seed["risk_exposure_amount"]
    if risk_exposure_amount is not None and abs(risk_exposure_amount - estimated_damage) > Decimal("0.01"):
        logger.warning(
            "Policy %s: RiskExposureAmount (%s) differs from EstimatedDamage (%s)",
            payload["insurance"]["policy_no"],
            risk_exposure_amount,
            estimated_damage,
        )
    db.add(
        models.RiskAssessment(
            insurance_records_id=insurance.insurance_records_id,
            crop_stage_no=seed["crop_stage_no"],
            crop_stage=seed["crop_stage"],
            estimated_damage=estimated_damage,
            final_indemnity_payment=estimated_damage,
        )
    )
    return _result("inserted")


@router.post("/csv", status_code=status.HTTP_200_OK)
def upload_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file.")

    if not file.content_type or "csv" not in file.content_type:
        raise HTTPException(status_code=400, detail="The uploaded file must be a CSV.")

    if file.file.seekable():
        file.file.seek(0)
    raw_bytes = file.file.read()

    # Real PABS exports have shown up as ISO-8859-1/cp1252 (e.g. names like "SEÑERES"),
    # not UTF-8. Try UTF-8 first (with BOM tolerance) since that's still the common
    # case, then fall back to cp1252, which covers the same byte range as
    # ISO-8859-1 and never raises UnicodeDecodeError on real Windows-exported text.
    dataframe = None
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            dataframe = pd.read_csv(io.BytesIO(raw_bytes), encoding=encoding)
            break
        except UnicodeDecodeError as exc:
            last_error = exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Unable to parse CSV file: {exc}") from exc
    if dataframe is None:
        raise HTTPException(status_code=400, detail=f"Unable to decode CSV file: {last_error}")

    if dataframe.empty:
        return {
            "status": "success",
            "message": "No rows were found in the uploaded CSV.",
            "rows_processed": 0,
            "rows_inserted": 0,
            "rows_skipped": 0,
            "rows_failed": 0,
            "failures": [],
        }

    total_rows = len(dataframe)
    logger.info("CSV ingestion started: %s (%d row(s))", file.filename, total_rows)
    start_time = time.monotonic()

    processed_rows = 0
    inserted_rows = 0
    skipped_rows = 0
    failed_rows = 0
    failures: list[dict[str, Any]] = []

    # Parsing a row (prepare_row_payload) never touches the DB, so failures here
    # are recorded up front without spending a SAVEPOINT on them. This also gives
    # _prefetch_caches() every row's lookup keys before any DB work starts.
    prepared_rows: list[tuple[int, dict[str, Any]]] = []
    for row_number, (_, row) in enumerate(dataframe.iterrows(), start=1):
        processed_rows += 1
        try:
            prepared_rows.append((row_number, prepare_row_payload(row)))
        except Exception as exc:
            failed_rows += 1
            failures.append({"row": row_number, "policy_no": None, "error": str(exc)})

    caches = _prefetch_caches(prepared_rows, db)
    logger.info(
        "CSV ingestion prefetch complete for %s: %d boundary(ies), %d farmer(s) by ID, "
        "%d farmer(s) by RSBSA, %d farm(s) cached",
        file.filename, len(caches.boundaries), len(caches.farmers_by_farmers_id),
        len(caches.farmers_by_rsbsa_no), len(caches.farms_by_reference),
    )

    try:
        for progress_count, (row_number, payload) in enumerate(prepared_rows, start=1):
            # Per-row SAVEPOINT: an unresolvable row (unmappable boundary, etc.) is
            # rolled back and recorded without discarding every other
            # already-processed row in this same upload -- a 23,917-row real
            # export isn't going to be perfectly clean, and one bad row shouldn't
            # cost every good one.
            savepoint = db.begin_nested()
            try:
                result = _ingest_row(payload, db, caches)
                if result.outcome == "inserted":
                    inserted_rows += 1
                else:
                    skipped_rows += 1
                savepoint.commit()
                caches.boundaries[result.boundary_key] = result.boundary
                if result.farmers_id:
                    caches.farmers_by_farmers_id[result.farmers_id] = result.farmer
                if result.rsbsa_no:
                    caches.farmers_by_rsbsa_no[result.rsbsa_no] = result.farmer
                if result.farm_reference:
                    caches.farms_by_reference[result.farm_reference] = result.farm
            except Exception as exc:
                savepoint.rollback()
                failed_rows += 1
                failures.append(
                    {
                        "row": row_number,
                        "policy_no": payload["insurance"]["policy_no"],
                        "error": str(exc),
                    }
                )
                logger.warning("CSV ingestion row %d failed: %s", row_number, exc)

            if progress_count % _PROGRESS_LOG_EVERY == 0 or progress_count == len(prepared_rows):
                elapsed = time.monotonic() - start_time
                rate = progress_count / elapsed if elapsed > 0 else 0.0
                logger.info(
                    "CSV ingestion progress for %s: %d/%d row(s) (%.1f rows/sec) -- %d inserted, %d skipped, %d failed",
                    file.filename, progress_count, total_rows, rate, inserted_rows, skipped_rows, failed_rows,
                )

        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("CSV ingestion for %s failed and was rolled back", file.filename)
        raise HTTPException(status_code=500, detail=f"CSV ingestion failed: {exc}") from exc

    # A no-op unless REDIS_URL is configured -- see app/core/farms_cache.py.
    # Without this, a page cached before this ingest could keep serving
    # stale data for up to the cache's TTL after a CSV upload just changed it.
    invalidate_farms_cache()
    # A no-op unless the migration in backend/migrations/2026-08-09_farms_perf.sql
    # has been applied -- see app/core/farms_view.py. This CSV ingest can
    # insert/update InsuranceRecord rows, which the view precomputes "most
    # recent per farm" from.
    refresh_farm_latest_insurance_view(db)

    elapsed = time.monotonic() - start_time
    logger.info(
        "CSV ingestion finished: %s in %.1fs -- %d processed, %d inserted, %d skipped, %d failed",
        file.filename, elapsed, processed_rows, inserted_rows, skipped_rows, failed_rows,
    )

    message = "CSV data ingested successfully."
    if failed_rows:
        message = f"CSV data ingested with {failed_rows} row(s) skipped due to errors."

    return {
        "status": "success",
        "message": message,
        "rows_processed": processed_rows,
        "rows_inserted": inserted_rows,
        "rows_skipped": skipped_rows,
        "rows_failed": failed_rows,
        "failures": failures[:50],
    }


@router.post("/gpx", status_code=status.HTTP_200_OK)
def upload_gpx(
    file: UploadFile = File(...),
    farmer_id: int | None = Form(default=None),
    farm_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith(".gpx"):
        raise HTTPException(status_code=400, detail="Please upload a GPX file.")

    matched_by = "manual"
    if farmer_id is not None and farm_id is not None:
        farm = (
            db.query(models.Farm)
            .filter(models.Farm.farm_id == farm_id, models.Farm.farmer_id == farmer_id)
            .first()
        )
        if farm is None:
            raise HTTPException(
                status_code=404,
                detail="Farm not found for the given farmer_id and farm_id.",
            )
    elif farmer_id is None and farm_id is None:
        match = GpxFarmerMatcherService.match(file.filename, db)
        if match.farm is None:
            if match.candidates:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f'Multiple farmer records match "{file.filename}" by name; '
                        "select the correct farm row manually."
                    ),
                )
            raise HTTPException(
                status_code=404,
                detail=(
                    f'No matching farmer/farm found for "{file.filename}". '
                    "Select the correct farm row manually."
                ),
            )
        farm = match.farm
        matched_by = match.matched_by
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide both farmer_id and farm_id for manual mode, or omit both to auto-detect from the filename.",
        )

    if file.file.seekable():
        file.file.seek(0)
    raw_bytes = file.file.read()

    try:
        gpx_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="GPX file must be UTF-8 encoded.") from exc

    try:
        location_geom = GpxParserService.parse_gpx_to_polygon(gpx_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to parse GPX file: {exc}") from exc

    farm.location_geom = location_geom
    db.commit()
    db.refresh(farm)

    # A no-op unless REDIS_URL is configured -- see app/core/farms_cache.py.
    # location_geom is part of the cached farms list response.
    invalidate_farms_cache()

    return {
        "status": "success",
        "message": "Farm boundary geometry updated from GPX file.",
        "farm_id": farm.farm_id,
        "matched_by": matched_by,
        "farmer_name": (f"{farm.farmer.first_name} {farm.farmer.last_name}".strip() if farm.farmer else None),
    }
