import functools
import io
import logging
import os
import re
import shutil
import tempfile
import threading
import time
import unicodedata
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

from app.core import upload_jobs
from app.core.activity_log import note_activity, plural, record_activity
from app.core.database import SessionLocal, get_db
from app.core.farms_cache import invalidate_farms_cache
from app.core.farms_view import refresh_farm_latest_insurance_view
from app.core.security import get_current_user
from app.core.system_settings import COVERAGE_RATE_KEY, DEFAULTS, get_coverage_rate
from app.models import models
from app.services.crop_stage_resolver import CropStageResolver
from app.services.gpkg_parser import GpkgParserService
from app.services.gpx_farmer_matcher import GpxFarmerMatcherService
from app.services.gpx_parser import GpxParserService

router = APIRouter(prefix="/api/upload", tags=["upload"], dependencies=[Depends(get_current_user)])

logger = logging.getLogger(__name__)

_PSGC_LOOKUP_PATH = Path(__file__).resolve().parent.parent / "data" / "psgc_nationwide_boundaries.csv"

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


def _fold_upper(name: str) -> str:
    """Accent-insensitive comparison key: PCIC's Region II export writes
    'SANTO NINO' where the PSGC reference has 'SANTO NIÑO' (2026-10-22)."""
    name = unicodedata.normalize("NFKD", name)
    return "".join(ch for ch in name if not unicodedata.combining(ch)).upper().strip()


@functools.lru_cache(maxsize=1)
def _load_psgc_lookup() -> dict[tuple[str, str, str], str]:
    """Same reference file backend/seed_database.py already uses. Loaded once per
    process (it's small and static) rather than re-read per row."""
    lookup_df = pd.read_csv(_PSGC_LOOKUP_PATH)
    return {
        _boundary_key(row["province"], row["municipality"], row["barangay"]): str(row["psgc_code"])
        for _, row in lookup_df.iterrows()
    }


@functools.lru_cache(maxsize=1)
def _load_psgc_names() -> dict[str, tuple[str, str, str]]:
    """psgc_code -> the reference file's own (province, municipality, barangay)
    spelling, which is what tbl_admin_boundaries is seeded with."""
    lookup_df = pd.read_csv(_PSGC_LOOKUP_PATH)
    return {
        str(row["psgc_code"]): (row["province"], row["municipality"], row["barangay"])
        for _, row in lookup_df.iterrows()
    }


_TRAILING_PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _strip_trailing_parenthetical(name: str) -> str:
    """Drops a trailing '(...)' qualifier, e.g. 'POBLACION (TUBOD)' -> 'POBLACION',
    'DIAZ (ROMUALDEZ)' -> 'DIAZ'. Only ever tried as a fallback after an exact match
    already failed -- confirmed against the full psgc_nationwide_boundaries.csv that no
    municipality has two distinct barangays whose only difference is such a suffix,
    so this can't accidentally collapse two real places into one."""
    return _TRAILING_PARENTHETICAL_RE.sub("", name).strip()


def _municipality_alias_variants(municipality: str) -> list[str]:
    """Real PABS exports and psgc_nationwide_boundaries.csv disagree on a couple of
    common PH municipality-naming conventions ('Surigao City' vs 'City of Surigao',
    'Sta. Josefa' vs 'Santa Josefa') -- generate the alternate spelling(s) so a
    lookup miss on the literal name gets another shot before being reported as a
    genuinely missing PSGC entry."""
    variants = []
    if municipality.endswith(" CITY"):
        variants.append(f"CITY OF {municipality[: -len(' CITY')]}")
    elif municipality.startswith("CITY OF "):
        variants.append(f"{municipality[len('CITY OF '):]} CITY")
    else:
        # PCIC's Region II export writes a component city bare ('ILAGAN');
        # PSGC has 'CITY OF ILAGAN'. Still scoped to the row's own province.
        variants.append(f"CITY OF {municipality}")
    variants.extend(_saint_abbrev_variants(municipality))
    return variants


def _saint_abbrev_variants(name: str) -> list[str]:
    """'Sta. Ana' <-> 'Santa Ana', 'Sto. Niño' <-> 'Santo Niño'. Used for
    barangays too (2026-10-22): the Region II export writes Gattaran's
    'SANTA ANA' where PSGC has 'Sta. Ana'."""
    for abbrev, full in (("STA. ", "SANTA "), ("STO. ", "SANTO ")):
        if name.startswith(abbrev):
            return [full + name[len(abbrev):]]
        if name.startswith(full):
            return [abbrev + name[len(full):]]
    return []


@functools.lru_cache(maxsize=1)
def _load_folded_psgc_lookup() -> dict[tuple[str, str, str], str]:
    """_load_psgc_lookup() keyed on accent-folded names. A folded key that two
    different PSGC codes share is left out rather than guessed."""
    folded: dict[tuple[str, str, str], str] = {}
    ambiguous: set[tuple[str, str, str]] = set()
    for key, code in _load_psgc_lookup().items():
        fkey = tuple(_fold_upper(part) for part in key)
        if fkey in folded and folded[fkey] != code:
            ambiguous.add(fkey)
        folded[fkey] = code
    for fkey in ambiguous:
        del folded[fkey]
    return folded


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
    for b in list(barangay_candidates):
        barangay_candidates.extend(_saint_abbrev_variants(b))

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

    # Accent-insensitive retry over the same candidates (Santo Nino/Niño).
    # Only when `lookup` is the reference file itself -- unit tests pass
    # their own small lookup.
    if lookup is _load_psgc_lookup():
        folded = _load_folded_psgc_lookup()
        for muni in municipality_candidates:
            for m in {muni, _strip_trailing_parenthetical(muni)}:
                for b in barangay_candidates:
                    psgc_code = folded.get((_fold_upper(province), _fold_upper(m), _fold_upper(b)))
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


def _is_blank(value: Any) -> bool:
    """True for the "nothing really stored here" values this ingest can leave behind
    on a row it created earlier: None, or a string that's empty once trimmed.

    tbl_farmers_profile.last_name/first_name are NOT NULL, so a CSV layout whose
    name columns this parser didn't yet recognize stored '' rather than failing --
    which is exactly how 952 nameless farmers landed in the database before the
    'FARMER NAME' alias existed (2026-10-09). See _backfill_blank_fields().
    """
    if value is None:
        return True
    return isinstance(value, str) and value.strip() == ""


def _backfill_blank_fields(instance: Any, payload: dict[str, Any], field_names: Iterable[str]) -> list[str]:
    """Copies payload values onto an ALREADY-PERSISTENT instance, but only for the
    fields currently blank on it -- never overwriting a value that's really there.

    Why this exists: _ingest_row() resolves an existing farmer/farm purely as a
    lookup and then used the row for nothing else, so any field this parser
    couldn't read at the time that row was first created stayed wrong forever --
    re-uploading the same CSV after the parser was fixed matched the broken row by
    farmers_id and changed nothing. That made ingestion non-idempotent, which is
    the root cause of blank farmer names in Spatial Analysis (2026-10-09).

    Deliberately blank-only rather than "CSV always wins" (Fabio's call,
    2026-10-09): the newer PABS export carries the farmer as one combined
    'FARMER NAME' field, so letting it overwrite a non-blank name would let a
    derived value clobber the legacy export's three discrete columns. Repairing a
    blank can't lose information; overwriting can.

    Returns the names of the fields actually changed, for the caller to log.
    No db.add() is needed -- `instance` is already persistent, so SQLAlchemy's
    dirty tracking emits the UPDATE within the caller's existing per-row SAVEPOINT.
    """
    changed = []
    for name in field_names:
        new_value = payload.get(name)
        if _is_blank(new_value):
            continue
        if _is_blank(getattr(instance, name, None)):
            setattr(instance, name, new_value)
            changed.append(name)
    return changed


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


# Columns a row cannot be ingested without. Each tuple is one required field and
# lists every header alias prepare_row_payload() already accepts for it (legacy
# pabs_results.csv layout and the newer PABS export), so a legitimate file of
# either layout passes. Everything else (names, dates, stage, amounts) stays
# optional, exactly as prepare_row_payload() treats it.
_REQUIRED_CSV_COLUMNS: tuple[tuple[str, ...], ...] = (
    # "... Address" is PCIC's "List of Farms with GPX File" export (Region II,
    # 2026-10-22); without these aliases that file was rejected outright.
    ("Province", "Province Address"),
    ("Municipality", "Municipality Address"),
    ("Barangay", "Barangay Address"),
    ("Policy No.", "CIC NO"),
    ("FARMID", "Farm ID"),
)


def _missing_csv_columns(columns: Iterable[Any]) -> list[str]:
    """Returns a readable label for each required column group absent from the CSV
    header. Checked in upload_csv() BEFORE the background job starts: a missing
    column never raises in prepare_row_payload() (get() just returns None), so
    without this a wrong file was only reported after every row had failed
    one by one in _ingest_row()."""
    present = {_normalize_header(str(c)) for c in columns}
    return [
        " / ".join(aliases)
        for aliases in _REQUIRED_CSV_COLUMNS
        if not any(_normalize_header(a) in present for a in aliases)
    ]


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
        _normalize_value(get("Province", "Province Address")) or "",
        _normalize_value(get("Municipality", "Municipality Address")) or "",
        _normalize_value(get("Barangay", "Barangay Address")) or "",
    )
    boundary = {
        "province": province,
        "municipality": municipality,
        "barangay": barangay,
    }

    # The newer PABS/GPX export carries one combined "FARMER NAME" ('ABANES, ALFONSO F.')
    # where the legacy export has three columns. Split it with the SAME parser the
    # GeoPackage path uses on the same field, so a farmer created here and the .gpkg
    # feature that later carries its boundary agree on the name -- that agreement is
    # what makes GpxFarmerMatcherService's name-based fallback work.
    last_name = _normalize_text_upper(get("Surname"))
    first_name = _normalize_text_upper(get("Firstname"))
    middle_name = _normalize_text_upper(get("Middlename"))
    if not last_name and not first_name:
        combined = _normalize_value(get("FARMER NAME"))
        if combined:
            parsed_last, parsed_first, parsed_middle = GpxFarmerMatcherService.parse_farmer_name(str(combined))
            last_name = _normalize_text_upper(parsed_last)
            first_name = _normalize_text_upper(parsed_first)
            middle_name = middle_name or _normalize_text_upper(parsed_middle)

    farmer = {
        "farmers_id": _stringify_id(_normalize_value(get("FarmersID", "FARMERSID"))),
        "rsbsa_no": _stringify_id(_normalize_value(get("RSBSA No."))),
        "last_name": last_name or "",
        "first_name": first_name or "",
        "middle_name": middle_name,
    }

    farm = {
        "csv_farm_reference": _stringify_id(_normalize_value(get("FARMID", "Farm ID"))),
        "georef_id": _stringify_id(_normalize_value(get("Georef ID"))),
        "area_size": _parse_decimal(get("AreaInsured", "AREA")),
        # The exact GPX file PCIC walked for this farm -- the most reliable
        # CSV<->GPX link (matches 1,434 of 1,456 Region II rows); see
        # GpxFarmerMatcherService.match().
        "track_file_name": _normalize_value(get("trackFileName", "Track File Name")),
    }

    insurance = {
        # The newer export calls the policy number "CIC NO".
        "policy_no": _stringify_id(_normalize_value(get("Policy No.", "CIC NO"))) or "",
        "program_type": _normalize_value(get("Program Type")),
        "product_name": _normalize_value(get("Product Name", "VARIETY NAME")),
        # "Date Effectivity"/"Date Expiry": Region II export. Without them both
        # dates were NULL and AssessmentService never found the policy in effect.
        "effectivity_date": _parse_date(get("Effectivity Date", "Date Effectivity")),
        "expiry_date": _parse_date(get("Expiry Date", "Date Expiry")),
        "amount_cover": _parse_decimal(get("AmountofCover", "AMOUNT OF COVER")),
    }

    # Not a real computed assessment -- just carries the CSV's own crop-stage/damage
    # figures forward so AssessmentService.calculate_for_bulletin() has a crop stage
    # to read for this policy once a real typhoon is assessed. risk_exposure_amount
    # is kept only to cross-check against estimated_damage, never persisted.
    # Stage values are carried through RAW and translated in _ingest_row() via
    # CropStageResolver -- this function stays DB-free so it remains unit-testable.
    # "Stage No." is the legacy export's PCIC 0-9 agronomic code, NOT the Table 11
    # 1/2/3 scale AssessmentService reads; writing it straight through (as this did
    # before 2026-10-09) silently mis-staged every assessable row.
    crop_stage_seed = {
        "stage_code": _normalize_value(get("Stage No.")),
        "stage_label": _normalize_value(get("Stage of Crop")),
        "crop_stage": _normalize_value(get("Stage", "Stage of Crop")),
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
    # Read-only for the whole upload, unlike the four above -- tbl_crop_stage_mapping
    # is a ~17-row lookup nothing in this path writes to, so it is loaded once and
    # never invalidated per row.
    crop_stage: CropStageResolver | None = None
    # Admin Panel's default RSBSA rate, ₱/ha (2026-10-22) -- the Amount of Cover
    # for a row whose AmountofCover is blank or zero. Read once per upload.
    coverage_rate_per_ha: Decimal = Decimal(DEFAULTS[COVERAGE_RATE_KEY])


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
    caches.crop_stage = CropStageResolver.load(db)
    caches.coverage_rate_per_ha = Decimal(str(get_coverage_rate(db)))

    # tbl_admin_boundaries now covers the whole country (~42k barangay-level
    # rows as of the nationwide PSGC expansion, 2026-08-20) -- still cheaper to
    # load it whole once per upload (a few MB, one query) than to build a
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
    # True when amount_cover came from the default rate, not the CSV.
    defaulted_ac: bool = False


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
                    "app/data/psgc_nationwide_boundaries.csv before ingesting this row."
                )
            # A name miss that _resolve_psgc_code() still resolved (e.g. 'POBLACION
            # (ALEGRIA)' -> 'POBLACION') usually points at a boundary that already
            # exists under the reference file's own spelling -- tbl_admin_boundaries
            # is preloaded nationwide -- so reuse it rather than insert a second row
            # that would violate tbl_admin_boundaries_psgc_code_key.
            boundary = (
                db.query(models.AdminBoundary)
                .filter(models.AdminBoundary.psgc_code == psgc_code)
                .first()
            )
            if boundary is None:
                # Spelled as the reference file spells it (2026-10-22), not in
                # the CSV's ALL CAPS: a 'CAGAYAN / PAMPLONA' barangay next to
                # the seeded 'Cagayan / Pamplona' ones split that municipality
                # in two for exposure. Lookups here compare upper() anyway.
                fields = dict(payload["boundary"])
                names = _load_psgc_names().get(psgc_code)
                if names is not None:
                    fields["province"], fields["municipality"], fields["barangay"] = names
                boundary = models.AdminBoundary(psgc_code=psgc_code, **fields)
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
    else:
        # Repair a farmer this ingest created earlier under a CSV layout whose name
        # columns weren't recognized yet -- without this, an existing-but-blank
        # profile is matched by farmers_id and kept blank no matter how many times
        # the corrected file is re-uploaded. Blank-only; see _backfill_blank_fields().
        filled = _backfill_blank_fields(farmer, farmer_payload, ("last_name", "first_name", "middle_name"))
        if filled:
            logger.info(
                "Backfilled %s on existing farmer farmers_id=%s", ", ".join(filled), farmer.farmers_id
            )

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
            track_file_name=farm_payload["track_file_name"],
            area_size=farm_payload["area_size"] or 0,
            location_geom=None,
        )
        db.add(farm)
        db.flush()
    else:
        # The GPX links (2026-10-22) for a farm imported before they were read.
        _backfill_blank_fields(farm, farm_payload, ("georef_id", "track_file_name"))
    if farm_payload["area_size"] and not farm.area_size:
        # Same repair as the farmer above, for the one Farm field that has the same
        # problem. Not routed through _backfill_blank_fields() because "blank" here
        # is 0, not None/'' -- area_size is NOT NULL and the create path above
        # coerces an unreadable AreaInsured/AREA column to 0, so 0 is this column's
        # "never actually read" marker. A real farm is never 0 ha.
        farm.area_size = farm_payload["area_size"]
        logger.info(
            "Backfilled area_size=%s on existing farm csv_farm_reference=%s",
            farm.area_size, farm.csv_farm_reference,
        )

    def _result(outcome: str, defaulted_ac: bool = False) -> _RowIngestResult:
        return _RowIngestResult(
            outcome=outcome,
            defaulted_ac=defaulted_ac,
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

    # CSV value always wins. Only a blank/zero AmountofCover falls back to the
    # Admin Panel's RSBSA rate x farm area (2026-10-22) -- it used to become
    # ₱0, which silently made every payout for that policy ₱0.
    amount_cover = payload["insurance"]["amount_cover"]
    defaulted_ac = not amount_cover
    if defaulted_ac:
        amount_cover = (caches.coverage_rate_per_ha * Decimal(str(farm.area_size or 0))).quantize(Decimal("0.01"))

    insurance = models.InsuranceRecord(
        farmer_id=farmer.farmer_id,
        farm_id=farm.farm_id,
        policy_no=payload["insurance"]["policy_no"],
        program_type=payload["insurance"]["program_type"],
        product_name=payload["insurance"]["product_name"],
        effectivity_date=payload["insurance"]["effectivity_date"],
        expiry_date=payload["insurance"]["expiry_date"],
        amount_cover=amount_cover,
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
    # Translate whichever stage vocabulary this CSV layout uses into the Table 11
    # crop_stage_no and the Table 1 stage_group. Both can legitimately come back
    # None -- an ineligible stage (tillering, harvested) or the deliberately
    # unresolved PI/BS pairing -- in which case the row still ingests and simply
    # never produces an assessment.
    resolver = caches.crop_stage or CropStageResolver.load(db)
    resolved = resolver.resolve(stage_code=seed["stage_code"], stage_label=seed["stage_label"])

    db.add(
        models.RiskAssessment(
            insurance_records_id=insurance.insurance_records_id,
            crop_stage_no=resolved.crop_stage_no,
            crop_stage=seed["crop_stage"],
            stage_group=resolved.stage_group,
            estimated_damage=estimated_damage,
            final_indemnity_payment=estimated_damage,
        )
    )
    return _result("inserted", defaulted_ac)


# How many individual rejected rows/features a remark spells out before
# summarising the rest as "... and N more".
_REMARKS_FAILURE_EXAMPLES = 5


def _describe_failures(failures: list[dict[str, Any]], label) -> str:
    shown = "; ".join(label(f) for f in failures[:_REMARKS_FAILURE_EXAMPLES])
    extra = len(failures) - _REMARKS_FAILURE_EXAMPLES
    return shown + (f"; and {extra:,} more" if extra > 0 else "")


def _csv_failure_label(failure: dict[str, Any]) -> str:
    policy = f" (policy {failure['policy_no']})" if failure.get("policy_no") else ""
    return f"row {failure['row']}{policy}: {failure['error']}"


def _log_csv_outcome(user_id: int | None, status_code: int, remarks: str) -> None:
    """The INGEST Activity Log entry for a finished background CSV job. The
    POST /csv entry itself is written when the request returns, before any
    row is processed -- so the real accepted/rejected counts need their own
    entry. Own session: the job's session may be mid-rollback here."""
    db = SessionLocal()
    try:
        record_activity(db, user_id, "INGEST", "/api/upload/csv", status_code, remarks)
    finally:
        db.close()


def _run_csv_ingestion(job_id: str, filename: str, dataframe: pd.DataFrame, user_id: int | None = None) -> None:
    """
    The actual row-by-row ingestion work, moved off the request thread
    (2026-08-16) so the frontend can poll GET /csv/status/{job_id} for a
    real percentage instead of the request just hanging until it's all
    done. Runs in its own background thread with its own DB session --
    the request's `Depends(get_db)` session is closed the moment
    upload_csv() below returns, long before this finishes for a real
    multi-thousand-row export.

    Logic here is unchanged from before this split, just no longer able to
    raise HTTPException (there's no request to raise it into) -- caught and
    turned into upload_jobs.mark_error() instead.
    """
    db = SessionLocal()
    try:
        total_rows = len(dataframe)
        logger.info("CSV ingestion started: %s (%d row(s))", filename, total_rows)
        start_time = time.monotonic()

        processed_rows = 0
        inserted_rows = 0
        skipped_rows = 0
        failed_rows = 0
        defaulted_ac_rows = 0
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
            filename, len(caches.boundaries), len(caches.farmers_by_farmers_id),
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
                        defaulted_ac_rows += result.defaulted_ac
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

                # Every row, not gated by _PROGRESS_LOG_EVERY -- this is just an
                # in-memory dict write behind a lock (see upload_jobs.py), cheap
                # enough to do every row for a smooth-looking progress bar, unlike
                # the log line below which stays throttled to avoid log spam.
                upload_jobs.update_progress(job_id, progress_count)

                if progress_count % _PROGRESS_LOG_EVERY == 0 or progress_count == len(prepared_rows):
                    elapsed = time.monotonic() - start_time
                    rate = progress_count / elapsed if elapsed > 0 else 0.0
                    logger.info(
                        "CSV ingestion progress for %s: %d/%d row(s) (%.1f rows/sec) -- %d inserted, %d skipped, %d failed",
                        filename, progress_count, total_rows, rate, inserted_rows, skipped_rows, failed_rows,
                    )

            db.commit()
        except Exception as exc:
            db.rollback()
            logger.exception("CSV ingestion for %s failed and was rolled back", filename)
            upload_jobs.mark_error(job_id, f"CSV ingestion failed: {exc}")
            _log_csv_outcome(
                user_id, 500,
                f'CSV ingestion of "{filename}" ({plural(total_rows, "row")}) failed and was rolled back; '
                f"nothing was imported. Error: {exc}",
            )
            return

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
            filename, elapsed, processed_rows, inserted_rows, skipped_rows, failed_rows,
        )

        message = "CSV data ingested successfully."
        if failed_rows:
            message = f"CSV data ingested with {failed_rows} row(s) skipped due to errors."

        remarks = (
            f'CSV ingestion of "{filename}" finished in {elapsed:.0f}s: {plural(processed_rows, "row")} processed -- '
            f"{inserted_rows:,} accepted (new policies imported), "
            f"{skipped_rows:,} skipped (already on file), {failed_rows:,} rejected."
        )
        if defaulted_ac_rows:
            remarks += (
                f" {plural(defaulted_ac_rows, 'policy', 'policies')} had no Amount of Cover and used the default "
                f"₱{caches.coverage_rate_per_ha:,.2f}/ha x farm area."
            )
        if failures:
            remarks += " Rejected: " + _describe_failures(failures, _csv_failure_label) + "."
        _log_csv_outcome(user_id, 200, remarks)

        upload_jobs.mark_done(job_id, {
            "status": "success",
            "message": message,
            "rows_processed": processed_rows,
            "rows_inserted": inserted_rows,
            "rows_skipped": skipped_rows,
            # Every skip is a duplicate: the (policy, farm) pair was already on
            # file, or repeated earlier in this same file.
            "rows_duplicate": skipped_rows,
            "rows_failed": failed_rows,
            "rows_defaulted_ac": defaulted_ac_rows,
            "failures": failures[:50],
        })
    except Exception as exc:
        # Catch-all -- nothing else will surface an unexpected failure in a
        # background thread; an unhandled exception here would otherwise just
        # vanish into the thread's stderr and leave the job stuck "processing"
        # forever from the frontend's point of view.
        logger.exception("CSV ingestion for %s crashed unexpectedly", filename)
        upload_jobs.mark_error(job_id, str(exc))
        _log_csv_outcome(user_id, 500, f'CSV ingestion of "{filename}" crashed; nothing was imported. Error: {exc}')
    finally:
        db.close()


_CSV_CONTENT_TYPES = {"application/vnd.ms-excel", "text/plain", "application/octet-stream"}


@router.post("/csv", status_code=status.HTTP_200_OK)
def upload_csv(
    file: UploadFile = File(...),
    current_user: models.SystemUser = Depends(get_current_user),
):
    """
    Validates and parses the file synchronously (fast), then hands the slow
    row-by-row ingestion off to a background thread (see
    _run_csv_ingestion above) and returns immediately with a job_id --
    poll GET /csv/status/{job_id} for real progress instead of the request
    blocking until a large export finishes.
    """
    note_activity(f'CSV upload "{file.filename}".')
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file.")

    # Browsers on Windows with Excel installed report a .csv as
    # application/vnd.ms-excel; others send text/plain or octet-stream.
    if file.content_type and not (
        "csv" in file.content_type or file.content_type in _CSV_CONTENT_TYPES
    ):
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

    missing_columns = _missing_csv_columns(dataframe.columns)
    if missing_columns:
        raise HTTPException(
            status_code=400,
            detail=(
                "This doesn't look like a PABS insurance export -- missing column(s): "
                + ", ".join(missing_columns)
                + ". No rows were imported."
            ),
        )

    if dataframe.empty:
        job_id = upload_jobs.create_job(total=0)
        upload_jobs.mark_done(job_id, {
            "status": "success",
            "message": "No rows were found in the uploaded CSV.",
            "rows_processed": 0,
            "rows_inserted": 0,
            "rows_skipped": 0,
            "rows_failed": 0,
            "failures": [],
        })
        note_activity(f'Uploaded CSV "{file.filename}": no data rows found, nothing imported.')
        return {"status": "processing", "job_id": job_id, "total_rows": 0}

    total_rows = len(dataframe)
    job_id = upload_jobs.create_job(total=total_rows)
    threading.Thread(
        target=_run_csv_ingestion,
        args=(job_id, file.filename, dataframe, current_user.user_id),
        daemon=True,
    ).start()
    note_activity(
        f'Uploaded CSV "{file.filename}" ({plural(total_rows, "row")}, {len(raw_bytes) / 1024:,.0f} KB); '
        "ingestion started -- see the INGEST entry for accepted/rejected counts."
    )

    return {"status": "processing", "job_id": job_id, "total_rows": total_rows}


@router.get("/csv/status/{job_id}")
def get_csv_upload_status(job_id: str):
    job = upload_jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown upload job (may have been since a backend restart).")
    return {
        "status": job.status,
        "processed": job.processed,
        "total": job.total,
        "result": job.result,
        "error": job.error,
    }


@router.post("/gpx", status_code=status.HTTP_200_OK)
def upload_gpx(
    file: UploadFile = File(...),
    farmer_id: int | None = Form(default=None),
    farm_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
):
    mode = f"manually assigned to farm #{farm_id}" if farm_id is not None else "auto-matched by filename"
    note_activity(f'GPX upload "{file.filename}" ({mode}).')
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
        match = GpxFarmerMatcherService.match_file(file.filename, db)
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

    had_boundary = farm.location_geom is not None
    farm.location_geom = location_geom
    db.commit()
    db.refresh(farm)

    farmer_name = f"{farm.farmer.first_name} {farm.farmer.last_name}".strip() if farm.farmer else "unknown farmer"
    place = f", Brgy. {farm.boundary.barangay}, {farm.boundary.municipality}" if farm.boundary else ""
    note_activity(
        f'Uploaded GPX "{file.filename}": boundary of farm #{farm.farm_id} '
        f"(FARMID {farm.csv_farm_reference or 'n/a'}, {farmer_name}{place}) "
        f"{'replaced' if had_boundary else 'saved for the first time'}; matched {matched_by}."
    )

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


@router.post("/gpkg", status_code=status.HTTP_200_OK)
def upload_gpkg(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    GeoPackage counterpart to upload_gpx() above -- one .gpkg holds many farm
    boundaries (the client's real export has 1,113), one feature per originally
    walked GPX file. Each feature is matched to an EXISTING farm via the same
    GpxFarmerMatcherService rules, fed from its FARMERSID/FARMID/FARMER NAME
    attributes, and only that farm's location_geom is updated -- nothing new is
    created (per Fabio, 2026-10-08: unmatched features are reported so the
    matching CSV can be imported first and the file re-uploaded).
    """
    note_activity(f'GeoPackage upload "{file.filename}".')
    if not file.filename or not file.filename.lower().endswith(".gpkg"):
        raise HTTPException(status_code=400, detail="Please upload a GeoPackage (.gpkg) file.")

    if file.file.seekable():
        file.file.seek(0)

    # sqlite3 can only open a real path, not an in-memory upload stream.
    with tempfile.NamedTemporaryFile(suffix=".gpkg", delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
    try:
        try:
            features = GpkgParserService.parse_gpkg_features(tmp_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Unable to read GeoPackage file: {exc}") from exc
    finally:
        os.remove(tmp_path)

    kept, duplicates = GpkgParserService.dedupe_by_farm_reference(features)

    updated = 0
    failures: list[dict[str, Any]] = []
    # Guards against two different features landing on the same farm in one
    # upload -- _pick_farm() falls back to a farmer's only farm on file, so a
    # farmer with two GPKG farms but just one imported would otherwise have
    # one polygon silently overwrite the other.
    updated_farm_ids: dict[int, str] = {}

    for feature in kept:
        # Per-feature SAVEPOINT, same reasoning as _run_csv_ingestion(): one
        # unmatched/bad feature shouldn't discard every good one in the file.
        savepoint = db.begin_nested()
        try:
            location_geom = feature.to_location_geom()
            match = GpxFarmerMatcherService.match_parsed(feature.to_match_input(), db)
            if match.farm is None:
                if match.candidates:
                    raise ValueError("Multiple farmer records match by name; no unique farm found.")
                raise ValueError(
                    f"No matching farm found (FARMID {feature.farm_reference}, FARMERSID {feature.farmers_id}). "
                    "Import its CSV record first."
                )
            if match.farm.farm_id in updated_farm_ids:
                raise ValueError(
                    f"Matched farm {match.farm.farm_id} was already updated from {updated_farm_ids[match.farm.farm_id]}."
                )
            match.farm.location_geom = location_geom
            db.flush()
            savepoint.commit()
            updated_farm_ids[match.farm.farm_id] = feature.label
            updated += 1
        except Exception as exc:
            savepoint.rollback()
            failures.append({
                "feature": feature.fid,
                "file_name": feature.label,
                "farm_reference": feature.farm_reference,
                "error": str(exc),
            })

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("GPKG ingestion for %s failed and was rolled back", file.filename)
        raise HTTPException(status_code=500, detail=f"GeoPackage ingestion failed: {exc}") from exc

    # A no-op unless REDIS_URL is configured -- see app/core/farms_cache.py.
    invalidate_farms_cache()

    logger.info(
        "GPKG ingestion finished: %s -- %d feature(s), %d updated, %d failed, %d duplicate(s) skipped",
        file.filename, len(features), updated, len(failures), len(duplicates),
    )

    remarks = (
        f'Uploaded GeoPackage "{file.filename}": {plural(len(features), "feature")} -- '
        f"{updated:,} accepted (farm boundaries updated), {len(failures):,} rejected, "
        f"{len(duplicates):,} duplicate(s) skipped."
    )
    if failures:
        remarks += " Rejected: " + _describe_failures(
            failures, lambda f: f'"{f["file_name"]}" (FARMID {f["farm_reference"] or "n/a"}): {f["error"]}'
        ) + "."
    note_activity(remarks)

    message = f"Updated {updated} farm boundary(ies) from GeoPackage."
    if failures:
        message = f"Updated {updated} farm boundary(ies) from GeoPackage; {len(failures)} feature(s) not applied."

    return {
        "status": "success",
        "message": message,
        "features_total": len(features),
        "features_updated": updated,
        "features_failed": len(failures),
        "duplicates_skipped": len(duplicates),
        "failures": failures[:200],
    }
