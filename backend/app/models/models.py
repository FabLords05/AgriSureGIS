from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry

from app.core.database import Base


class AdminBoundary(Base):
    __tablename__ = "tbl_admin_boundaries"

    boundary_id = Column(Integer, primary_key=True, index=True)
    province = Column(String(100), nullable=False)
    municipality = Column(String(100), nullable=False)
    barangay = Column(String(100), nullable=False)


class FarmerProfile(Base):
    __tablename__ = "tbl_farmers_profile"

    farmer_id = Column(Integer, primary_key=True, index=True)
    rsbsa_no = Column(String(50), unique=True, nullable=False)
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
    location_geom = Column(Geometry(geometry_type="POLYGON", srid=4326))
    created_at = Column(DateTime, server_default=func.now())

    farmer = relationship("FarmerProfile")
    boundary = relationship("AdminBoundary")


class InsuranceRecord(Base):
    __tablename__ = "tbl_insurance_records"

    insurance_records_id = Column(Integer, primary_key=True, index=True)
    farm_id = Column(Integer, ForeignKey("tbl_farms.farm_id", ondelete="CASCADE"))
    policy_no = Column(String(50), unique=True, nullable=False)
    program_type = Column(String(100))
    effectivity_date = Column(Date)
    expiry_date = Column(Date)
    amount_cover = Column(Numeric(12, 2), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    farm = relationship("Farm")


class RiskAssessment(Base):
    __tablename__ = "tbl_risk_assessment"

    assessment_id = Column(Integer, primary_key=True, index=True)
    insurance_records_id = Column(Integer, ForeignKey("tbl_insurance_records.insurance_records_id", ondelete="CASCADE"))
    crop_stage_no = Column(String(20))
    crop_stage = Column(String(100))
    estimated_damage = Column(Numeric(12, 2))
    adjuster_calculation = Column(String(255))
    assessment_date = Column(DateTime, server_default=func.now())

    insurance_record = relationship("InsuranceRecord")