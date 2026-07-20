-- 1. Enable the Spatial Engine (Crucial for AgriSureGIS)
CREATE EXTENSION IF NOT EXISTS postgis;

-- 2. Clear out any old mistakes (Idempotent setup)
DROP TABLE IF EXISTS tbl_area_exposure_summary CASCADE;
DROP TABLE IF EXISTS tbl_tcb_signals CASCADE;
DROP TABLE IF EXISTS tbl_tropical_cyclone_bulletins CASCADE;
DROP TABLE IF EXISTS tbl_typhoons CASCADE;
DROP TABLE IF EXISTS tbl_risk_assessment CASCADE;
DROP TABLE IF EXISTS tbl_recsap_matrix CASCADE;
DROP TABLE IF EXISTS tbl_insurance_records CASCADE;
DROP TABLE IF EXISTS tbl_farms CASCADE;
DROP TABLE IF EXISTS tbl_admin_boundaries CASCADE;
DROP TABLE IF EXISTS tbl_farmers_profile CASCADE;
DROP TABLE IF EXISTS tbl_system_users CASCADE;

-- 3. Build the Core Lookup Tables First (Parents)
CREATE TABLE tbl_system_users (
    user_id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    firstname VARCHAR(100) NOT NULL,
    lastname VARCHAR(100) NOT NULL,
    role VARCHAR(50) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_login TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tbl_farmers_profile (
    farmer_id SERIAL PRIMARY KEY,
    rsbsa_no VARCHAR(50) UNIQUE,
    last_name VARCHAR(100) NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    middle_name VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tbl_admin_boundaries (
    boundary_id SERIAL PRIMARY KEY,
    psgc_code VARCHAR(10) UNIQUE NOT NULL,
    province VARCHAR(100) NOT NULL,
    municipality VARCHAR(100) NOT NULL,
    barangay VARCHAR(100) NOT NULL
);

CREATE TABLE tbl_recsap_matrix (
    matrix_id SERIAL PRIMARY KEY,
    crop_stage_no INT NOT NULL,
    wind_signal_tcws INT NOT NULL,
    exposure_hours INT NOT NULL,
    estimated_yield_loss NUMERIC(5,2) NOT NULL,
    indemnity_factor NUMERIC(5,4) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- 4. Build the Spatial Table (Child of Farmers & Boundaries)
CREATE TABLE tbl_farms (
    farm_id SERIAL PRIMARY KEY,
    farmer_id INT REFERENCES tbl_farmers_profile(farmer_id) ON DELETE CASCADE,
    boundary_id INT REFERENCES tbl_admin_boundaries(boundary_id) ON DELETE SET NULL,
    csv_farm_reference VARCHAR(50),
    georef_id VARCHAR(100),
    province VARCHAR(100),
    municipality VARCHAR(100),
    barangay VARCHAR(100),
    area_size NUMERIC(10,4) NOT NULL,
    location_geom GEOMETRY(MultiPolygon, 4326),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 5. Build the Transactional Tables (Children of Farms)
CREATE TABLE tbl_insurance_records (
    insurance_records_id SERIAL PRIMARY KEY,
    farmer_id INT REFERENCES tbl_farmers_profile(farmer_id) ON DELETE SET NULL,
    farm_id INT REFERENCES tbl_farms(farm_id) ON DELETE CASCADE,
    policy_no VARCHAR(50) UNIQUE NOT NULL,
    program_type VARCHAR(100),
    product_name VARCHAR(150),
    effectivity_date DATE,
    expiry_date DATE,
    amount_cover NUMERIC(15,2) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tbl_risk_assessment (
    assessment_id SERIAL PRIMARY KEY,
    insurance_records_id INT REFERENCES tbl_insurance_records(insurance_records_id) ON DELETE CASCADE,
    summary_id INT,
    matrix_id INT REFERENCES tbl_recsap_matrix(matrix_id) ON DELETE SET NULL,
    crop_stage_no INT,
    crop_stage VARCHAR(150),
    period_of_exposure INT,
    wind_velocity INT,
    indemnity_factor NUMERIC(5,4),
    estimated_damage NUMERIC(15,2) NOT NULL,
    final_indemnity_payment NUMERIC(15,2) NOT NULL,
    assessment_date TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id INT REFERENCES tbl_system_users(user_id)
);

CREATE TABLE tbl_typhoons (
    typhoon_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    year INT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE tbl_tropical_cyclone_bulletins (
    tcb_id SERIAL PRIMARY KEY,
    typhoon_id INT REFERENCES tbl_typhoons(typhoon_id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    bulletin_count INT NOT NULL,
    category VARCHAR(100) NOT NULL,
    max_sustained_winds INT,
    gustiness INT,
    issued_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    center_geom GEOMETRY(Point, 4326)
);

CREATE TABLE tbl_tcb_signals (
    signal_id SERIAL PRIMARY KEY,
    tcb_id INT REFERENCES tbl_tropical_cyclone_bulletins(tcb_id) ON DELETE CASCADE,
    signal_level INT NOT NULL,
    island_group INT NOT NULL,
    area_name VARCHAR(100) NOT NULL
);

CREATE TABLE tbl_area_exposure_summary (
    summary_id SERIAL PRIMARY KEY,
    typhoon_id INT REFERENCES tbl_typhoons(typhoon_id) ON DELETE CASCADE,
    boundary_id INT REFERENCES tbl_admin_boundaries(boundary_id) ON DELETE SET NULL,
    province VARCHAR(100) NOT NULL,
    municipality VARCHAR(100) NOT NULL,
    max_signal_level INT NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    is_eligible_6hr BOOLEAN DEFAULT FALSE,
    total_exposure_hours NUMERIC(5,2) NOT NULL,
    computed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 6. Optimize Spatial Queries
CREATE INDEX idx_farms_location_geom ON tbl_farms USING GIST(location_geom);
CREATE INDEX idx_tcb_center_geom ON tbl_tropical_cyclone_bulletins USING GIST(center_geom);