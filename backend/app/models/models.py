from sqlalchemy import Column, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Boolean, UniqueConstraint, func
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
    action = Column(String(20), nullable=False)  # LOGIN, LOGOUT, POST, PUT, PATCH, DELETE
    endpoint = Column(String(255), nullable=False)
    status_code = Column(Integer, nullable=False)
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


class RiskAssessment(Base):
    __tablename__ = "tbl_risk_assessment"

    assessment_id = Column(Integer, primary_key=True, index=True)
    insurance_records_id = Column(Integer, ForeignKey("tbl_insurance_records.insurance_records_id", ondelete="CASCADE"))
    summary_id = Column(Integer)
    matrix_id = Column(Integer, ForeignKey("tbl_recsap_matrix.matrix_id", ondelete="SET NULL"))
    indemnity_matrix_id = Column(Integer, ForeignKey("tbl_indemnity_factor_matrix.indemnity_id", ondelete="SET NULL"))
    crop_stage_no = Column(Integer)
    crop_stage = Column(String(150))
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

    bulletin = relationship("TropicalCycloneBulletin")


class AreaExposureSummary(Base):
    __tablename__ = "tbl_area_exposure_summary"

    summary_id = Column(Integer, primary_key=True, index=True)
    typhoon_id = Column(Integer, ForeignKey("tbl_typhoons.typhoon_id", ondelete="CASCADE"))
    boundary_id = Column(Integer, ForeignKey("tbl_admin_boundaries.boundary_id", ondelete="SET NULL"))
    province = Column(String(100), nullable=False)
    municipality = Column(String(100), nullable=False)
    max_signal_level = Column(Integer, nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    is_eligible_6hr = Column(Boolean, default=False)
    total_exposure_hours = Column(Numeric(5, 2), nullable=False)
    computed_at = Column(DateTime, server_default=func.now())

    typhoon = relationship("Typhoon")


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