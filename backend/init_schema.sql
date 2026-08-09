-- 1. Enable the Spatial Engine (Crucial for AgriSureGIS)
CREATE EXTENSION IF NOT EXISTS postgis;

-- 2. Clear out any old mistakes (Idempotent setup)
DROP TABLE IF EXISTS tbl_area_exposure_summary CASCADE;
DROP TABLE IF EXISTS tbl_tcb_signals CASCADE;
DROP TABLE IF EXISTS tbl_tropical_cyclone_bulletins CASCADE;
DROP TABLE IF EXISTS tbl_typhoons CASCADE;
DROP TABLE IF EXISTS tbl_risk_assessment CASCADE;
DROP TABLE IF EXISTS tbl_recsap_matrix CASCADE;
DROP TABLE IF EXISTS tbl_indemnity_factor_matrix CASCADE;
DROP TABLE IF EXISTS tbl_insurance_records CASCADE;
DROP TABLE IF EXISTS tbl_farms CASCADE;
DROP TABLE IF EXISTS tbl_admin_boundaries CASCADE;
DROP TABLE IF EXISTS tbl_farmers_profile CASCADE;
DROP TABLE IF EXISTS tbl_system_users CASCADE;
DROP TABLE IF EXISTS tbl_parser_settings CASCADE;

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
    -- PABS-native per-farmer ID (see docs/PROPOSAL_farmers_id_column.md). 100% populated
    -- in real PABS exports vs. rsbsa_no's ~71%, so it's the preferred farmer-matching key
    -- for CSV ingestion and GPX filename-based matching; rsbsa_no is the legacy fallback.
    farmers_id VARCHAR(20) UNIQUE,
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
    barangay VARCHAR(100) NOT NULL,
    -- Municipality-level outline, backfilled from frontend/public/data/region10-boundaries.geojson
    -- (matched on psgc_municipality) so GeoServer can publish region boundaries as a live WFS
    -- layer instead of the static bundled GeoJSON. Not used in any exposure calculation --
    -- ExposureCalculatorService still matches on province/municipality/barangay text.
    boundary_geom GEOMETRY(MultiPolygon, 4326)
);

-- Step 1 of the parametric lookup: (crop stage, wind signal, exposure hours) -> yield loss %.
-- Source: PCIC "Table 11" damage matrix (Typhoon-Induced Strong Winds - Rice).
CREATE TABLE tbl_recsap_matrix (
    matrix_id SERIAL PRIMARY KEY,
    crop_stage_no INT NOT NULL,
    wind_signal_tcws INT NOT NULL,
    exposure_hours INT NOT NULL,
    estimated_yield_loss NUMERIC(5,2) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- Step 2 of the parametric lookup: (crop stage group, yield loss % bracket) -> indemnity factor.
-- Source: PCIC Rice Indemnity Factor Table. crop_stage_group uses PCIC's own 5-stage
-- taxonomy, which differs from tbl_recsap_matrix.crop_stage_no's 3-stage taxonomy
-- (Booting/Flowering/Maturity); the mapping is Booting->Late Vegetative,
-- Flowering->Reproductive, Maturity->Maturity (confirmed with Fabio, not stated
-- verbatim in the manuscript). Brackets are exclusive-lower/inclusive-upper, e.g.
-- ">10 to 15" means yield_loss_min=10, yield_loss_max=15, matched as
-- (estimated_yield_loss > yield_loss_min AND estimated_yield_loss <= yield_loss_max).
CREATE TABLE tbl_indemnity_factor_matrix (
    indemnity_id SERIAL PRIMARY KEY,
    crop_stage_group VARCHAR(30) NOT NULL,
    yield_loss_min NUMERIC(5,2) NOT NULL,
    yield_loss_max NUMERIC(5,2) NOT NULL,
    indemnity_factor NUMERIC(7,2) NOT NULL,
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
-- policy_no is NOT globally unique: real PABS exports have one Policy No. (a
-- batch/program policy) covering many different farmers/farms. The real
-- per-row unique identity is (policy_no, farm_id) -- confirmed with Fabio
-- 2026-07-30, after docs/Rice Risk Exposure Region X 04-15-2026.csv showed a
-- single Policy No. spanning 10-14 distinct farmers.
CREATE TABLE tbl_insurance_records (
    insurance_records_id SERIAL PRIMARY KEY,
    farmer_id INT REFERENCES tbl_farmers_profile(farmer_id) ON DELETE SET NULL,
    farm_id INT REFERENCES tbl_farms(farm_id) ON DELETE CASCADE,
    policy_no VARCHAR(50) NOT NULL,
    program_type VARCHAR(100),
    product_name VARCHAR(150),
    effectivity_date DATE,
    expiry_date DATE,
    amount_cover NUMERIC(15,2) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_insurance_records_policy_no_farm_id UNIQUE (policy_no, farm_id)
);

CREATE TABLE tbl_risk_assessment (
    assessment_id SERIAL PRIMARY KEY,
    insurance_records_id INT REFERENCES tbl_insurance_records(insurance_records_id) ON DELETE CASCADE,
    summary_id INT,
    matrix_id INT REFERENCES tbl_recsap_matrix(matrix_id) ON DELETE SET NULL,
    indemnity_matrix_id INT REFERENCES tbl_indemnity_factor_matrix(indemnity_id) ON DELETE SET NULL,
    crop_stage_no INT,
    crop_stage VARCHAR(150),
    period_of_exposure INT,
    wind_velocity INT,
    indemnity_factor NUMERIC(7,2),
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

-- 5b. Automated TCB polling settings (single-row config table backing the
-- Calibration screen's "TCB Polling Interval" field and the in-process
-- APScheduler job that drives automated PAGASA bulletin ingestion).
CREATE TABLE tbl_parser_settings (
    setting_id SERIAL PRIMARY KEY,
    polling_interval_hours INT NOT NULL DEFAULT 3,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO tbl_parser_settings (polling_interval_hours) VALUES (3);

-- 6. Optimize Spatial Queries
CREATE INDEX idx_farms_location_geom ON tbl_farms USING GIST(location_geom);
CREATE INDEX idx_tcb_center_geom ON tbl_tropical_cyclone_bulletins USING GIST(center_geom);
CREATE INDEX idx_admin_boundaries_boundary_geom ON tbl_admin_boundaries USING GIST(boundary_geom);

-- 6b. Optimize CSV ingestion lookups (backend/app/api/upload.py, upload_csv()).
-- Without these, tbl_farms.csv_farm_reference and the boundary triplet below
-- were scanned sequentially on every never-before-seen value -- on a large CSV
-- (e.g. the real ~23,917-row PABS export) that turned a mostly-new-farms import
-- into an effectively O(n^2) table scan as tbl_farms grew mid-upload, which is
-- what actually made ingestion "hang" rather than just being generically slow.
CREATE INDEX idx_farms_csv_farm_reference ON tbl_farms (csv_farm_reference);
CREATE INDEX idx_admin_boundaries_province_municipality_barangay
    ON tbl_admin_boundaries (province, municipality, barangay);

-- 6c. Covers backend/app/api/farms.py's active_only=True filter (WHERE
-- effectivity_date <= today AND expiry_date >= today, projecting DISTINCT
-- farm_id). Column order puts the two range filters first so Postgres can
-- use the index for the WHERE clause, with farm_id included last to make
-- it a covering index (index-only scan, no heap lookup) for that exact
-- query. See models.py's InsuranceRecord.__table_args__ for the ORM-side
-- mirror of this index.
CREATE INDEX ix_insurance_records_active_lookup
    ON tbl_insurance_records (effectivity_date, expiry_date, farm_id);

-- 6d. Precomputes "most recent InsuranceRecord per farm" for
-- backend/app/api/farms.py's list_farms() -- see app/core/farms_view.py.
-- Empty until tbl_insurance_records has data and gets refreshed (the app
-- refreshes it itself after every CSV/GPX upload; seed_active_insurance.py
-- does too). See backend/migrations/2026-08-09_farms_perf.sql for the
-- standalone version of these same two statements, for applying this to an
-- already-provisioned DB without re-running this whole file.
CREATE MATERIALIZED VIEW mv_farm_latest_insurance AS
SELECT DISTINCT ON (farm_id)
    farm_id,
    insurance_records_id,
    policy_no,
    effectivity_date,
    expiry_date
FROM tbl_insurance_records
ORDER BY farm_id, effectivity_date DESC NULLS LAST;

CREATE UNIQUE INDEX ix_mv_farm_latest_insurance_farm_id
    ON mv_farm_latest_insurance (farm_id);

-- 7. Real PCIC seed data for the two-step parametric lookup (replaces the old
-- made-up placeholder block). Source: PCIC "Table 11" damage matrix and Rice
-- Indemnity Factor Table, transcribed from the manuscript figures.
-- crop_stage_no: 1=Booting, 2=Flowering, 3=Maturity (2 and 3 confirmed against
-- backend/pabs_results.csv; 1=Booting inferred from MASTER_DEVELOPMENT_CONTEXT.md's
-- stage ordering, not independently confirmed).
--
-- Step 1: yield loss %. The source table's "TCWS No.04 (118-184 KPH) AND > 184 KPH"
-- header groups signal 4 and signal 5 under one set of values, so both are seeded
-- identically here. The "Maturity, signal 2, 6h" cell reads "<10" in the source
-- (no exact figure) and is intentionally omitted rather than guessing a number --
-- it falls under the indemnity table's own >10% floor either way, so the payout
-- engine already returns $0 for it via the no-matching-rule path.
INSERT INTO tbl_recsap_matrix (crop_stage_no, wind_signal_tcws, exposure_hours, estimated_yield_loss) VALUES
(1, 2, 6, 10.00),  -- Booting, signal 2, 6h
(1, 2, 12, 15.00), -- Booting, signal 2, 12h
(1, 2, 24, 20.00), -- Booting, signal 2, 24h
(2, 2, 6, 15.00),  -- Flowering, signal 2, 6h
(2, 2, 12, 20.00), -- Flowering, signal 2, 12h
(2, 2, 24, 25.00), -- Flowering, signal 2, 24h
(3, 2, 12, 10.00), -- Maturity, signal 2, 12h
(3, 2, 24, 15.00), -- Maturity, signal 2, 24h
(1, 3, 6, 15.00),  -- Booting, signal 3, 6h
(1, 3, 12, 20.00), -- Booting, signal 3, 12h
(1, 3, 24, 25.00), -- Booting, signal 3, 24h
(2, 3, 6, 20.00),  -- Flowering, signal 3, 6h
(2, 3, 12, 25.00), -- Flowering, signal 3, 12h
(2, 3, 24, 30.00), -- Flowering, signal 3, 24h
(3, 3, 6, 10.00),  -- Maturity, signal 3, 6h
(3, 3, 12, 15.00), -- Maturity, signal 3, 12h
(3, 3, 24, 20.00), -- Maturity, signal 3, 24h
(1, 4, 6, 20.00),  -- Booting, signal 4, 6h
(1, 4, 12, 25.00), -- Booting, signal 4, 12h
(1, 4, 24, 30.00), -- Booting, signal 4, 24h
(2, 4, 6, 25.00),  -- Flowering, signal 4, 6h
(2, 4, 12, 30.00), -- Flowering, signal 4, 12h
(2, 4, 24, 35.00), -- Flowering, signal 4, 24h
(3, 4, 6, 15.00),  -- Maturity, signal 4, 6h
(3, 4, 12, 20.00), -- Maturity, signal 4, 12h
(3, 4, 24, 25.00), -- Maturity, signal 4, 24h
(1, 5, 6, 20.00),  -- Booting, signal 5 (>184kph), 6h
(1, 5, 12, 25.00), -- Booting, signal 5 (>184kph), 12h
(1, 5, 24, 30.00), -- Booting, signal 5 (>184kph), 24h
(2, 5, 6, 25.00),  -- Flowering, signal 5 (>184kph), 6h
(2, 5, 12, 30.00), -- Flowering, signal 5 (>184kph), 12h
(2, 5, 24, 35.00), -- Flowering, signal 5 (>184kph), 24h
(3, 5, 6, 15.00),  -- Maturity, signal 5 (>184kph), 6h
(3, 5, 12, 20.00), -- Maturity, signal 5 (>184kph), 12h
(3, 5, 24, 25.00); -- Maturity, signal 5 (>184kph), 24h

-- Step 2: indemnity factor by yield loss % bracket and PCIC's 5-stage taxonomy.
-- All 5 stage-groups from the source table are seeded for fidelity, though only 3
-- (Late Vegetative <- Booting, Reproductive <- Flowering, Maturity <- Maturity) are
-- reachable via crop_stage_no's mapping today -- Early Vegetative and Late
-- Reproductive sit unqueried until crop-stage tracking covers those stages.
INSERT INTO tbl_indemnity_factor_matrix (crop_stage_group, yield_loss_min, yield_loss_max, indemnity_factor) VALUES
('Early Vegetative', 10.00, 15.00, 146.00),
('Early Vegetative', 15.00, 20.00, 198.00),
('Early Vegetative', 20.00, 25.00, 248.00),
('Early Vegetative', 25.00, 30.00, 294.00),
('Early Vegetative', 30.00, 35.00, 336.00),
('Late Vegetative', 10.00, 15.00, 170.00),
('Late Vegetative', 15.00, 20.00, 231.00),
('Late Vegetative', 20.00, 25.00, 289.00),
('Late Vegetative', 25.00, 30.00, 343.00),
('Late Vegetative', 30.00, 35.00, 392.00),
('Reproductive', 10.00, 15.00, 194.00),
('Reproductive', 15.00, 20.00, 264.00),
('Reproductive', 20.00, 25.00, 330.00),
('Reproductive', 25.00, 30.00, 392.00),
('Reproductive', 30.00, 35.00, 448.00),
('Late Reproductive', 10.00, 15.00, 218.00),
('Late Reproductive', 15.00, 20.00, 297.00),
('Late Reproductive', 20.00, 25.00, 372.00),
('Late Reproductive', 25.00, 30.00, 441.00),
('Late Reproductive', 30.00, 35.00, 504.00),
('Maturity', 10.00, 15.00, 243.00),
('Maturity', 15.00, 20.00, 330.00),
('Maturity', 20.00, 25.00, 413.00),
('Maturity', 25.00, 30.00, 490.00),
('Maturity', 30.00, 35.00, 560.00);