from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Boolean, func
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


class AdminBoundary(Base):
    __tablename__ = "tbl_admin_boundaries"

    boundary_id = Column(Integer, primary_key=True, index=True)
    psgc_code = Column(String(10), unique=True, nullable=False)
    province = Column(String(100), nullable=False)
    municipality = Column(String(100), nullable=False)
    barangay = Column(String(100), nullable=False)


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

    insurance_records_id = Column(Integer, primary_key=True, index=True)
    farmer_id = Column(Integer, ForeignKey("tbl_farmers_profile.farmer_id", ondelete="SET NULL"))
    farm_id = Column(Integer, ForeignKey("tbl_farms.farm_id", ondelete="CASCADE"))
    policy_no = Column(String(50), unique=True, nullable=False)
    program_type = Column(String(100))
    product_name = Column(String(150))
    effectivity_date = Column(Date)
    expiry_date = Column(Date)
    amount_cover = Column(Numeric(12, 2), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    farmer = relationship("FarmerProfile")
    farm = relationship("Farm")


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


class TropicalCycloneBulletin(Base):
    __tablename__ = "tbl_tropical_cyclone_bulletins"

    tcb_id = Column(Integer, primary_key=True, index=True)
    typhoon_id = Column(Integer, ForeignKey("tbl_typhoons.typhoon_id", ondelete="CASCADE"))
    title = Column(String(255), nullable=False)
    bulletin_count = Column(Integer, nullable=False)
    category = Column(String(100), nullable=False)
    max_sustained_winds = Column(Integer)
    gustiness = Column(Integer)
    issued_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    center_geom = Column(Geometry(geometry_type="POINT", srid=4326))

    typhoon = relationship("Typhoon")


class TcbSignal(Base):
    __tablename__ = "tbl_tcb_signals"

    signal_id = Column(Integer, primary_key=True, index=True)
    tcb_id = Column(Integer, ForeignKey("tbl_tropical_cyclone_bulletins.tcb_id", ondelete="CASCADE"))
    signal_level = Column(Integer, nullable=False)
    island_group = Column(Integer, nullable=False)
    area_name = Column(String(100), nullable=False)

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
    boundary = relationship("AdminBoundary")