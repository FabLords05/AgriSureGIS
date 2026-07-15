-- 1. Enable the Spatial Engine (Crucial for AgriSureGIS)
CREATE EXTENSION IF NOT EXISTS postgis;

-- 2. Clear out any old mistakes (Idempotent setup)
DROP TABLE IF EXISTS tbl_risk_assessment CASCADE;
DROP TABLE IF EXISTS tbl_insurance_records CASCADE;
DROP TABLE IF EXISTS tbl_farms CASCADE;
DROP TABLE IF EXISTS tbl_admin_boundaries CASCADE;
DROP TABLE IF EXISTS tbl_farmers_profile CASCADE;

-- 3. Build the Core Lookup Tables First (Parents)
CREATE TABLE tbl_farmers_profile (
    farmer_id SERIAL PRIMARY KEY,
    rsbsa_no VARCHAR(50) UNIQUE NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    first_name VARCHAR(50) NOT NULL,
    middle_name VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tbl_admin_boundaries (
    boundary_id SERIAL PRIMARY KEY,
    province VARCHAR(100) NOT NULL,
    municipality VARCHAR(100) NOT NULL,
    barangay VARCHAR(100) NOT NULL,
    UNIQUE(province, municipality, barangay)
);

-- 4. Build the Spatial Table (Child of Farmers & Boundaries)
CREATE TABLE tbl_farms (
    farm_id SERIAL PRIMARY KEY,
    farmer_id INT REFERENCES tbl_farmers_profile(farmer_id) ON DELETE CASCADE,
    boundary_id INT REFERENCES tbl_admin_boundaries(boundary_id) ON DELETE SET NULL,
    csv_farm_reference VARCHAR(50), 
    georef_id VARCHAR(50),
    area_size NUMERIC(10,2) NOT NULL,
    location_geom GEOMETRY(Polygon, 4326), -- PostGIS WGS84 Spatial Column
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. Build the Transactional Tables (Children of Farms)
CREATE TABLE tbl_insurance_records (
    insurance_records_id SERIAL PRIMARY KEY,
    farm_id INT REFERENCES tbl_farms(farm_id) ON DELETE CASCADE,
    policy_no VARCHAR(50) UNIQUE NOT NULL,
    program_type VARCHAR(100),
    effectivity_date DATE,
    expiry_date DATE,
    amount_cover NUMERIC(12,2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tbl_risk_assessment (
    assessment_id SERIAL PRIMARY KEY,
    insurance_records_id INT REFERENCES tbl_insurance_records(insurance_records_id) ON DELETE CASCADE,
    crop_stage_no VARCHAR(20),
    crop_stage VARCHAR(100),
    estimated_damage NUMERIC(12,2),
    adjuster_calculation VARCHAR(255),
    assessment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 6. Optimize Spatial Queries
CREATE INDEX idx_farms_location_geom ON tbl_farms USING GIST(location_geom);