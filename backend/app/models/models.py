from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, Boolean, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry

from app.core.database import Base


class SystemUser(Base):
    __tablename__ = "tbl_system_users"

    user_id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    firstname = Column(String(100), nullable=False)
    lastname = Column(String(100), nullable=False)
    role = Column(String(50), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    last_login = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    # Per-account idle-logout policy, admin-set from User Management,
    # enforced client-side (App.tsx) -- see
    # migrations/2026-08-16_session_timeout_minutes.sql. 0 = disabled.
    session_timeout_minutes = Column(Integer, nullable=False, default=5)


class ActivityLog(Base):
    __tablename__ = "tbl_activity_log"

    log_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("tbl_system_users.user_id", ondelete="SET NULL"), nullable=True)
    action = Column(String(20), nullable=False)  # LOGIN, LOGOUT, POST, PUT, PATCH, DELETE, GET, INGEST, SYSTEM
    endpoint = Column(String(255), nullable=False)
    status_code = Column(Integer, nullable=False)
    # Full sentence of what was done -- see app/core/activity_log.py. NULL only
    # for entries written before 2026-10-22.
    remarks = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("SystemUser")


class AdminBoundary(Base):
    __tablename__ = "tbl_admin_boundaries"

    boundary_id = Column(Integer, primary_key=True, index=True)
    psgc_code = Column(String(10), unique=True, nullable=False)
    province = Column(String(100), nullable=False)
    municipality = Column(String(100), nullable=False)
    barangay = Column(String(100), nullable=False)
    boundary_geom = Column(Geometry(geometry_type="MULTIPOLYGON", srid=4326))


class FarmerProfile(Base):
    __tablename__ = "tbl_farmers_profile"

    farmer_id = Column(Integer, primary_key=True, index=True)
    farmers_id = Column(String(20), unique=True)
    rsbsa_no = Column(String(50), unique=True)
    last_name = Column(String(50), nullable=False)
    first_name = Column(String(50), nullable=False)
    middle_name = Column(String(50))
    created_at = Column(DateTime, server_default=func.now())


class Farm(Base):
    __tablename__ = "tbl_farms"

    farm_id = Column(Integer, primary_key=True, index=True)
    farmer_id = Column(Integer, ForeignKey("tbl_farmers_profile.farmer_id", ondelete="CASCADE"))
    boundary_id = Column(Integer, ForeignKey("tbl_admin_boundaries.boundary_id", ondelete="SET NULL"))

    csv_farm_reference = Column(String(50))
    georef_id = Column(String(50))
    # PCIC's GPX file name for this farm (CSV "trackFileName", 2026-10-22) --
    # GpxFarmerMatcherService's first and most reliable match.
    track_file_name = Column(String(255))
    area_size = Column(Numeric(10, 2), nullable=False)
    location_geom = Column(Geometry(geometry_type="MULTIPOLYGON", srid=4326))
    created_at = Column(DateTime, server_default=func.now())

    farmer = relationship("FarmerProfile")
    boundary = relationship("AdminBoundary")


class InsuranceRecord(Base):
    __tablename__ = "tbl_insurance_records"

    # policy_no is NOT globally unique: real PABS exports have one Policy No.
    # (a batch/program policy) covering many different farmers/farms. The real
    # per-row unique identity is (policy_no, farm_id) -- confirmed with Fabio
    # 2026-07-30, after docs/Rice Risk Exposure Region X 04-15-2026.csv showed
    # a single Policy No. spanning 10-14 distinct farmers.
    __table_args__ = (
        UniqueConstraint("policy_no", "farm_id", name="uq_insurance_records_policy_no_farm_id"),
        # Covers backend/app/api/farms.py's active_only=True filter
        # (`WHERE effectivity_date <= :today AND expiry_date >= :today`,
        # projecting DISTINCT farm_id) -- column order puts the two range
        # filters first so Postgres can use the index for the WHERE clause,
        # with farm_id included last to make it a covering index (an
        # index-only scan, no heap lookup needed) for that exact query.
        # Without this, the filter falls back to a sequential scan that gets
        # more expensive as tbl_insurance_records grows -- not yet a problem
        # at ~49,588 rows (2026-08-09), but doesn't scale past dev size.
        Index(
            "ix_insurance_records_active_lookup",
            "effectivity_date", "expiry_date", "farm_id",
        ),
    )

    insurance_records_id = Column(Integer, primary_key=True, index=True)
    farmer_id = Column(Integer, ForeignKey("tbl_farmers_profile.farmer_id", ondelete="SET NULL"))
    farm_id = Column(Integer, ForeignKey("tbl_farms.farm_id", ondelete="CASCADE"))
    policy_no = Column(String(50), nullable=False)
    program_type = Column(String(100))
    product_name = Column(String(150))
    effectivity_date = Column(Date)
    expiry_date = Column(Date)
    amount_cover = Column(Numeric(12, 2), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    # Denormalized mirror of this record's MOST RECENT row in tbl_insurance_usage
    # (see InsuranceUsage below) -- kept in sync by AssessmentService.calculate_for_bulletin
    # every time it marks/unmarks usage. This is a convenience snapshot for "is this
    # insurance currently used, and by which typhoon", not the source of truth: a
    # policy assessed across multiple typhoons keeps its full per-typhoon history in
    # tbl_insurance_usage, since these three columns can only ever reflect one typhoon
    # at a time.
    is_used = Column(Boolean, nullable=False, default=False)
    used_for_typhoon_id = Column(Integer, ForeignKey("tbl_typhoons.typhoon_id", ondelete="SET NULL"))
    used_at = Column(DateTime)

    farmer = relationship("FarmerProfile")
    farm = relationship("Farm")
    used_for_typhoon = relationship("Typhoon", foreign_keys=[used_for_typhoon_id])


class RecsapMatrix(Base):
    __tablename__ = "tbl_recsap_matrix"

    matrix_id = Column(Integer, primary_key=True, index=True)
    crop_stage_no = Column(Integer, nullable=False)
    wind_signal_tcws = Column(Integer, nullable=False)
    exposure_hours = Column(Integer, nullable=False)
    estimated_yield_loss = Column(Numeric(5, 2), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)


class IndemnityFactorMatrix(Base):
    __tablename__ = "tbl_indemnity_factor_matrix"

    indemnity_id = Column(Integer, primary_key=True, index=True)
    crop_stage_group = Column(String(30), nullable=False)
    yield_loss_min = Column(Numeric(5, 2), nullable=False)
    yield_loss_max = Column(Numeric(5, 2), nullable=False)
    indemnity_factor = Column(Numeric(7, 2), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)


class CropStageMapping(Base):
    """Translates the crop-stage vocabulary of either real PCIC CSV export into the
    two taxonomies the lookup tables use. The legacy export keys on `source_code`
    (its integer "Stage No."), the newer PABS/GPX export on `source_label` (its
    lowercased "Stage of Crop" text); exactly one is populated per row.

    `crop_stage_no` NULL means "ingest the row but never assess it" -- Table 11
    Note 1 stages, a harvested crop, or the deliberately-unresolved PI/BS pairing.
    `stage_group` is resolved independently of `crop_stage_no`, because Milking and
    Flowering share crop_stage_no 2 while sitting in different Table 1 groups.
    See CropStageResolver and init_schema.sql's seed comment.
    """

    __tablename__ = "tbl_crop_stage_mapping"

    mapping_id = Column(Integer, primary_key=True, index=True)
    source_code = Column(Integer)
    source_label = Column(String(80))
    pcic_stage = Column(String(20), nullable=False)
    crop_stage_no = Column(Integer)
    stage_group = Column(String(30))
    notes = Column(String)
    is_active = Column(Boolean, nullable=False, default=True)


class RiskAssessment(Base):
    __tablename__ = "tbl_risk_assessment"

    assessment_id = Column(Integer, primary_key=True, index=True)
    insurance_records_id = Column(Integer, ForeignKey("tbl_insurance_records.insurance_records_id", ondelete="CASCADE"))
    summary_id = Column(Integer)
    matrix_id = Column(Integer, ForeignKey("tbl_recsap_matrix.matrix_id", ondelete="SET NULL"))
    indemnity_matrix_id = Column(Integer, ForeignKey("tbl_indemnity_factor_matrix.indemnity_id", ondelete="SET NULL"))
    crop_stage_no = Column(Integer)
    crop_stage = Column(String(150))
    # PCIC 5-stage group, resolved independently of crop_stage_no via
    # tbl_crop_stage_mapping. NULL falls back to CROP_STAGE_TO_INDEMNITY_GROUP.
    stage_group = Column(String(30))
    period_of_exposure = Column(Integer)
    wind_velocity = Column(Integer)
    indemnity_factor = Column(Numeric(7, 2))
    estimated_damage = Column(Numeric(15, 2), nullable=False)
    final_indemnity_payment = Column(Numeric(15, 2), nullable=False)
    assessment_date = Column(DateTime, server_default=func.now())
    user_id = Column(Integer, ForeignKey("tbl_system_users.user_id"))

    insurance_record = relationship("InsuranceRecord")
    matrix = relationship("RecsapMatrix")
    indemnity_matrix = relationship("IndemnityFactorMatrix")
    user = relationship("SystemUser")


class Typhoon(Base):
    __tablename__ = "tbl_typhoons"

    typhoon_id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    year = Column(Integer, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)


class InsuranceUsage(Base):
    """
    Source of truth for "was this policy line used (paid out) for this specific
    typhoon" -- one row per (insurance_records_id, typhoon_id), so a policy's
    usage history survives across multiple typhoons instead of being overwritten.
    tbl_insurance_records.is_used/used_for_typhoon_id/used_at is a denormalized
    mirror of only the latest row here, kept for quick "is this currently used"
    lookups -- see the docstring on those columns.

    Written by AssessmentService.calculate_for_bulletin at the end of computing
    payouts for a typhoon: is_used=True when final_indemnity_payment > 0 for that
    (insurance, typhoon) pair, flipped back to False if a later recompute for the
    same typhoon drops the payout back to zero.

    finalized_at is set by AssessmentService.finalize_exported_usage when the
    final PABS CSV is exported. A finalized, used row is a permanent lock:
    calculate_for_bulletin skips that policy for every typhoon from then on
    (new typhoons can't reuse it; the exported typhoon's results stay frozen).
    """

    __tablename__ = "tbl_insurance_usage"
    __table_args__ = (
        UniqueConstraint("insurance_records_id", "typhoon_id", name="uq_insurance_usage_insurance_typhoon"),
    )

    usage_id = Column(Integer, primary_key=True, index=True)
    insurance_records_id = Column(Integer, ForeignKey("tbl_insurance_records.insurance_records_id", ondelete="CASCADE"), nullable=False)
    typhoon_id = Column(Integer, ForeignKey("tbl_typhoons.typhoon_id", ondelete="CASCADE"), nullable=False)
    assessment_id = Column(Integer, ForeignKey("tbl_risk_assessment.assessment_id", ondelete="SET NULL"))
    is_used = Column(Boolean, nullable=False, default=True)
    marked_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    finalized_at = Column(DateTime)

    insurance_record = relationship("InsuranceRecord", foreign_keys=[insurance_records_id])
    typhoon = relationship("Typhoon", foreign_keys=[typhoon_id])
    assessment = relationship("RiskAssessment", foreign_keys=[assessment_id])


class TropicalCycloneBulletin(Base):
    __tablename__ = "tbl_tropical_cyclone_bulletins"

    tcb_id = Column(Integer, primary_key=True, index=True)
    typhoon_id = Column(Integer, ForeignKey("tbl_typhoons.typhoon_id", ondelete="CASCADE"))
    title = Column(String(255), nullable=False)
    bulletin_count = Column(Integer, nullable=False)
    category = Column(String(100), nullable=False)
    max_sustained_winds = Column(Integer)
    gustiness = Column(Integer)
    issued_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    center_geom = Column(Geometry(geometry_type="POINT", srid=4326))
    # PAGASA's own TCWS table as parsed, stored as-is with no AdminBoundary
    # validation (see backend/migrations/2026-09-30_tcb_raw_tcws.sql) -- so
    # the TCB viewer can show the real signal number and area text even for
    # areas that don't resolve to a boundary. tcws_areas shape:
    # {"<signal_level>": {"<island_group>": cell_text}}. Both NULL for
    # bulletins saved before this column existed, or with no TCWS table.
    max_signal_level = Column(Integer, nullable=True)
    tcws_areas = Column(JSONB, nullable=True)
    # True for a typhoon's last bulletin (PAGASA's trailing "F" on the
    # bulletin number, or an LPA bulletin) -- see backend/migrations/
    # 2026-10-09_tcb_is_final.sql. Drives the Monitoring "ready for
    # assessment" notice.
    is_final = Column(Boolean, nullable=False, default=False)
    # Typhoon track overlay (see backend/migrations/2026-10-12_tcb_track_radius.sql).
    # wind_radius_km: strong-wind extent (>= 39 km/h); storm_force_radius_km:
    # storm-force extent (>= 89 km/h), NULL when the bulletin doesn't state
    # it. forecast_track: [{"label", "lat", "lon", "location"}, ...] from the
    # Track and Intensity Outlook table. All NULL for bulletins saved before
    # these columns existed.
    wind_radius_km = Column(Integer, nullable=True)
    storm_force_radius_km = Column(Integer, nullable=True)
    forecast_track = Column(JSONB, nullable=True)
    # Traceability + corrected-bulletin detection (see backend/migrations/
    # 2026-10-22_exposure_signal_hours.sql). raw_text: the PDF's extracted
    # text. tcws_hash: sha256 of the parsed TCWS table -- a re-scrape with a
    # different hash is a corrected bulletin. issued_at_parsed: False when
    # "Issued at ..." couldn't be read and issued_at is the ingestion time;
    # such bulletins are left out of exposure timelines.
    raw_text = Column(Text, nullable=True)
    tcws_hash = Column(String(64), nullable=True)
    issued_at_parsed = Column(Boolean, nullable=False, default=True)

    typhoon = relationship("Typhoon")


class TcbSignal(Base):
    __tablename__ = "tbl_tcb_signals"

    signal_id = Column(Integer, primary_key=True, index=True)
    tcb_id = Column(Integer, ForeignKey("tbl_tropical_cyclone_bulletins.tcb_id", ondelete="CASCADE"))
    signal_level = Column(Integer, nullable=False)
    island_group = Column(Integer, nullable=False)
    area_name = Column(String(100), nullable=False)
    # The AdminBoundary province this signal was matched against (see
    # backend/migrations/2026-08-20_tcb_signal_province.sql). Nullable --
    # rows saved before the nationwide PSGC expansion (2026-08-20) never had
    # this populated. Exists so exposure_calculator.py can key boundary
    # lookups on (province, municipality) instead of municipality alone,
    # which collides once AdminBoundary covers the whole country (e.g.
    # multiple "Santa Cruz" across different provinces).
    province = Column(String(100), nullable=True)
    # The PAGASA clause this LGU was resolved from (2026-10-22), e.g.
    # "Batanes" or "the northern portion of Cagayan (Santa Ana, Gonzaga)".
    source_clause = Column(Text, nullable=True)

    bulletin = relationship("TropicalCycloneBulletin")


class TcbUnresolvedClause(Base):
    """
    A TCWS clause that resolved to no municipality (2026-10-22): an unknown
    name ("no_boundary_match"), or partial provincial coverage stated without
    a town list ("partial_coverage_no_list"), which is deliberately never
    expanded to the whole province. Shown as a warning beside the exposure
    tables so a specialist can see what was not assigned.
    """

    __tablename__ = "tbl_tcb_unresolved_clauses"

    unresolved_id = Column(Integer, primary_key=True, index=True)
    tcb_id = Column(Integer, ForeignKey("tbl_tropical_cyclone_bulletins.tcb_id", ondelete="CASCADE"), nullable=False)
    signal_level = Column(Integer, nullable=False)
    island_group = Column(Integer, nullable=False)
    clause = Column(Text, nullable=False)
    reason = Column(String(40), nullable=False)


class AreaExposureSummary(Base):
    __tablename__ = "tbl_area_exposure_summary"

    summary_id = Column(Integer, primary_key=True, index=True)
    typhoon_id = Column(Integer, ForeignKey("tbl_typhoons.typhoon_id", ondelete="CASCADE"))
    boundary_id = Column(Integer, ForeignKey("tbl_admin_boundaries.boundary_id", ondelete="SET NULL"))
    province = Column(String(100), nullable=False)
    municipality = Column(String(100), nullable=False)
    max_signal_level = Column(Integer, nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    is_eligible_6hr = Column(Boolean, default=False)
    # Hours accumulated under each TCWS level, and their sum (2026-10-22 --
    # see ExposureCalculatorService for how intervals are built).
    # payout_hours = the hours under max_signal_level, which AssessmentService
    # buckets into the PCIC matrix's 6/12/24h brackets.
    total_exposure_hours = Column(Numeric(7, 2), nullable=False)
    computed_at = Column(DateTime(timezone=True), server_default=func.now())
    island_group = Column(Integer, nullable=True)
    signal_1_hours = Column(Numeric(7, 2), nullable=False, default=0)
    signal_2_hours = Column(Numeric(7, 2), nullable=False, default=0)
    signal_3_hours = Column(Numeric(7, 2), nullable=False, default=0)
    signal_4_hours = Column(Numeric(7, 2), nullable=False, default=0)
    signal_5_hours = Column(Numeric(7, 2), nullable=False, default=0)
    payout_hours = Column(Numeric(7, 2), nullable=True)
    has_open_interval = Column(Boolean, nullable=False, default=False)
    has_long_gap = Column(Boolean, nullable=False, default=False)

    typhoon = relationship("Typhoon")


class ExposureInterval(Base):
    """One continuous stretch a municipality spent under one signal level
    during a typhoon (2026-10-22). Rebuilt on every exposure recompute; the
    audit trail behind tbl_area_exposure_summary's per-signal hours."""

    __tablename__ = "tbl_exposure_intervals"

    interval_id = Column(Integer, primary_key=True, index=True)
    typhoon_id = Column(Integer, ForeignKey("tbl_typhoons.typhoon_id", ondelete="CASCADE"), nullable=False)
    province = Column(String(100), nullable=False)
    municipality = Column(String(100), nullable=False)
    signal_level = Column(Integer, nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    start_tcb_id = Column(Integer, ForeignKey("tbl_tropical_cyclone_bulletins.tcb_id", ondelete="SET NULL"))
    end_tcb_id = Column(Integer, ForeignKey("tbl_tropical_cyclone_bulletins.tcb_id", ondelete="SET NULL"))


class SarObservation(Base):
    """
    One Sentinel-1 scene's polygon-mean VV/VH (dB) over one farm -- the
    cached input to the automatic planted check (2026-10-12). Stored so a
    re-run, or a later typhoon whose window overlaps, reads from here instead
    of Google Earth Engine. See migrations/2026-10-12_sar_planted_check.sql.
    """

    __tablename__ = "tbl_sar_observation"
    __table_args__ = (
        UniqueConstraint("farm_id", "scene_date", "relative_orbit", name="uq_sar_observation_farm_scene"),
    )

    observation_id = Column(Integer, primary_key=True, index=True)
    farm_id = Column(Integer, ForeignKey("tbl_farms.farm_id", ondelete="CASCADE"), nullable=False)
    scene_date = Column(Date, nullable=False)
    relative_orbit = Column(Integer, nullable=False)
    vv_db = Column(Numeric(6, 2), nullable=False)
    vh_db = Column(Numeric(6, 2), nullable=False)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SarFetchCoverage(Base):
    """
    The date range tbl_sar_observation fully covers for one farm, and the
    boundary it was measured on. A farm whose window falls inside
    [covered_start, covered_end] with an unchanged geom_hash needs no Earth
    Engine call. A scene with no valid pixels leaves no observation row,
    which is why coverage is tracked separately from the rows themselves.
    """

    __tablename__ = "tbl_sar_fetch_coverage"

    farm_id = Column(Integer, ForeignKey("tbl_farms.farm_id", ondelete="CASCADE"), primary_key=True)
    covered_start = Column(Date, nullable=False)
    covered_end = Column(Date, nullable=False)
    # md5 of the farm's location_geom when fetched -- a re-uploaded GPX
    # boundary invalidates the cached series.
    geom_hash = Column(String(32), nullable=False)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class SarPlantedCheck(Base):
    """
    Automatic planted-check result for one farm for one typhoon
    (2026-10-12, docs/SAR_ISPLANTED_METHOD.md §3): GREEN "planted" when all
    five conditions pass, YELLOW "field_verify" otherwise, with the first
    failed condition in reason_code. Like PlantedVerification, NOT read by
    AssessmentService or the PABS/PCIC export.
    """

    __tablename__ = "tbl_sar_planted_check"
    __table_args__ = (
        UniqueConstraint("farm_id", "typhoon_id", name="uq_sar_planted_check_farm_typhoon"),
    )

    check_id = Column(Integer, primary_key=True, index=True)
    farm_id = Column(Integer, ForeignKey("tbl_farms.farm_id", ondelete="CASCADE"), nullable=False)
    typhoon_id = Column(Integer, ForeignKey("tbl_typhoons.typhoon_id", ondelete="CASCADE"), nullable=False)
    status = Column(String(20), nullable=False)
    reason_code = Column(String(40), nullable=False)
    t0_date = Column(Date)
    tp_date = Column(Date)
    vh_rise_db = Column(Numeric(5, 2))
    ratio_drop_db = Column(Numeric(5, 2))
    relative_orbit = Column(Integer)
    scene_count = Column(Integer, nullable=False, default=0)
    window_start = Column(Date, nullable=False)
    window_end = Column(Date, nullable=False)
    checked_by = Column(Integer, ForeignKey("tbl_system_users.user_id", ondelete="SET NULL"))
    checked_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PlantedVerification(Base):
    """
    The GIS Specialist's planted / not-planted verdict for one farm for one
    typhoon -- the "Verify Farm Planted" use case (an <<include>> of Conduct
    Parametric Damage Assessment). Recorded after looking at the pre-event
    Sentinel-1 VV/VH layer (app/services/gee_sar_service.py) over the
    "Affected Only" polygons. See migrations/2026-10-12_planted_verification.sql.

    Per typhoon, not per farm, because planting is per season. Deliberately
    NOT read by AssessmentService or the PABS/PCIC export (per Fabio,
    2026-10-12: record the verdict, don't gate the payout).
    """

    __tablename__ = "tbl_planted_verification"
    __table_args__ = (
        UniqueConstraint("farm_id", "typhoon_id", name="uq_planted_verification_farm_typhoon"),
    )

    verification_id = Column(Integer, primary_key=True, index=True)
    farm_id = Column(Integer, ForeignKey("tbl_farms.farm_id", ondelete="CASCADE"), nullable=False)
    typhoon_id = Column(Integer, ForeignKey("tbl_typhoons.typhoon_id", ondelete="CASCADE"), nullable=False)
    is_planted = Column(Boolean, nullable=False)
    verified_by = Column(Integer, ForeignKey("tbl_system_users.user_id", ondelete="SET NULL"))
    verified_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    notes = Column(Text)

    verifier = relationship("SystemUser", foreign_keys=[verified_by])


class ParserSettings(Base):
    __tablename__ = "tbl_parser_settings"

    setting_id = Column(Integer, primary_key=True, index=True)
    # Minutes, not hours -- was polling_interval_hours (Integer, min 1) until
    # 2026-08-10, when Fabio asked for sub-hour granularity (down to 15 min).
    # Default 180 preserves the old default of "every 3 hours."
    # backend/migrations/2026-08-10_polling_interval_minutes.sql renames and
    # converts (x * 60) any existing value for already-provisioned DBs.
    polling_interval_minutes = Column(Integer, nullable=False, default=180)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class SystemSetting(Base):
    """Admin-editable key/value settings (2026-10-22) -- see
    migrations/2026-10-22_system_settings_backup_log.sql and
    app/core/system_settings.py for the keys and their defaults."""

    __tablename__ = "tbl_system_settings"

    setting_key = Column(String(50), primary_key=True)
    setting_value = Column(JSONB, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    updated_by = Column(Integer, ForeignKey("tbl_system_users.user_id", ondelete="SET NULL"), nullable=True)


class BackupLog(Base):
    """One row per pg_dump the app runs -- see app/services/backup_service.py."""

    __tablename__ = "tbl_backup_log"

    backup_id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(20), nullable=False)  # manual | scheduled | archive
    file_name = Column(String(255))
    size_bytes = Column(BigInteger)
    gdrive_file_id = Column(String(255))
    status = Column(String(20), nullable=False)  # success | failed
    error = Column(Text)
    gdrive_error = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    created_by = Column(Integer, ForeignKey("tbl_system_users.user_id", ondelete="SET NULL"), nullable=True)
    # Integrity + verification (2026-10-22, see backup_service.verify_backup).
    # row_counts: {table: rows} read from the dump's own snapshot.
    # encrypted: the Drive copy is AES-GCM encrypted (app/core/backup_crypto.py).
    sha256 = Column(String(64))
    row_counts = Column(JSONB)
    encrypted = Column(Boolean, nullable=False, default=False)
    gdrive_md5 = Column(String(32))
    verify_status = Column(String(20))  # pending | verified | failed
    verify_detail = Column(JSONB)
    verified_at = Column(DateTime(timezone=True))
