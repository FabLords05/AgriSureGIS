-- 1. Enable the Spatial Engine (Crucial for AgriSureGIS)
CREATE EXTENSION IF NOT EXISTS postgis;

-- 2. Clear out any old mistakes (Idempotent setup)
DROP TABLE IF EXISTS tbl_area_exposure_summary CASCADE;
DROP TABLE IF EXISTS tbl_tcb_signals CASCADE;
DROP TABLE IF EXISTS tbl_tropical_cyclone_bulletins CASCADE;
DROP TABLE IF EXISTS tbl_insurance_usage CASCADE;
DROP TABLE IF EXISTS tbl_typhoons CASCADE;
DROP TABLE IF EXISTS tbl_risk_assessment CASCADE;
DROP TABLE IF EXISTS tbl_crop_stage_mapping CASCADE;
DROP TABLE IF EXISTS tbl_recsap_matrix CASCADE;
DROP TABLE IF EXISTS tbl_indemnity_factor_matrix CASCADE;
DROP TABLE IF EXISTS tbl_insurance_records CASCADE;
DROP TABLE IF EXISTS tbl_farms CASCADE;
DROP TABLE IF EXISTS tbl_admin_boundaries CASCADE;
DROP TABLE IF EXISTS tbl_farmers_profile CASCADE;
DROP TABLE IF EXISTS tbl_system_users CASCADE;
DROP TABLE IF EXISTS tbl_parser_settings CASCADE;
DROP TABLE IF EXISTS tbl_activity_log CASCADE;

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
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Per-account idle-logout policy (2026-08-16 -- see
    -- backend/migrations/2026-08-16_session_timeout_minutes.sql), admin-set
    -- per user from User Management, enforced client-side in App.tsx.
    -- 0 = disabled. Not tied to any server-side token expiry (see
    -- app/core/security.py's module docstring for why).
    session_timeout_minutes INT NOT NULL DEFAULT 5
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
-- Source: PCIC Rice Indemnity Factor Table (RECSAP-From-IRR.pptx, Table 1).
-- crop_stage_group uses PCIC's own 5-stage taxonomy, which differs from
-- tbl_recsap_matrix.crop_stage_no's 3-stage taxonomy (Booting/Flowering/Maturity).
-- The group is NO LONGER derived from crop_stage_no -- it is resolved independently
-- via tbl_crop_stage_mapping below and persisted on tbl_risk_assessment.stage_group.
-- (Fabio, 2026-10-09: Milking and Flowering share crop_stage_no 2 but sit in
-- different groups -- Late Reproductive vs Reproductive -- so one cannot be derived
-- from the other. The older Booting->Late Vegetative mapping recorded here was
-- superseded at the same time; see tbl_crop_stage_mapping's comment.)
-- Brackets are exclusive-lower/inclusive-upper, e.g.
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

-- Translation layer between the crop-stage vocabularies the two real PCIC CSV exports
-- use and the two lookup tables above. Needed because neither export speaks the
-- 3-stage Table 11 taxonomy directly:
--   * the legacy export (docs/Rice Risk Exposure Region X 04-15-2026.csv) carries
--     "Stage No.", PCIC's own 0-9 agronomic code (0=S/T, then the Table 7a/7b
--     sequence MnTl|MxTl|PI|BS|FS|MS|SD|HD|YR);
--   * the newer PABS/GPX export carries "Stage of Crop" as free text only.
-- Before this table existed, "Stage No." was written straight into
-- tbl_risk_assessment.crop_stage_no, which AssessmentService reads as the Table 11
-- scale -- so code 1 (Maximum Tillering) was assessed as Booting while code 4
-- (the real Booting) fell outside {1,2,3} and was dropped entirely.
--
-- crop_stage_no NULL means "ingest the row but never assess it". Three reasons occur:
-- Table 11 Note 1 ("MnTl,MxTl,PI stages - No immediate direct damage"), a harvested
-- crop, and the deliberately-unresolved PI/BS pairing (see its row's note).
-- stage_group is resolved independently of crop_stage_no -- see the comment above.
CREATE TABLE tbl_crop_stage_mapping (
    mapping_id SERIAL PRIMARY KEY,
    -- Exactly one of these two is populated per row: source_code keys the legacy
    -- export's integer "Stage No.", source_label keys the newer export's lowercased
    -- "Stage of Crop" text.
    source_code INT,
    source_label VARCHAR(80),
    pcic_stage VARCHAR(20) NOT NULL,
    crop_stage_no INT,
    stage_group VARCHAR(30),
    notes TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT ck_crop_stage_mapping_one_key CHECK (
        (source_code IS NOT NULL AND source_label IS NULL)
        OR (source_code IS NULL AND source_label IS NOT NULL)
    )
);

-- Partial, so a retired (is_active = FALSE) row can be superseded by a new one
-- carrying the same key instead of having to be deleted.
CREATE UNIQUE INDEX ux_crop_stage_mapping_source_code
    ON tbl_crop_stage_mapping (source_code) WHERE is_active AND source_code IS NOT NULL;
CREATE UNIQUE INDEX ux_crop_stage_mapping_source_label
    ON tbl_crop_stage_mapping (source_label) WHERE is_active AND source_label IS NOT NULL;

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
    -- Denormalized mirror of this record's most recent row in tbl_insurance_usage
    -- (below) -- convenience snapshot only, not the source of truth for usage
    -- history across multiple typhoons. See tbl_insurance_usage's comment and
    -- models.py's InsuranceRecord docstring.
    is_used BOOLEAN NOT NULL DEFAULT FALSE,
    used_for_typhoon_id INT,
    used_at TIMESTAMPTZ,
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
    -- PCIC 5-stage group, resolved independently of crop_stage_no via
    -- tbl_crop_stage_mapping (Fabio, 2026-10-09). Carries the step-2 indemnity
    -- lookup; NULL falls back to indemnity_calc.CROP_STAGE_TO_INDEMNITY_GROUP.
    stage_group VARCHAR(30),
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

-- tbl_insurance_records.used_for_typhoon_id can't be declared REFERENCES inline
-- above -- tbl_typhoons doesn't exist yet at that point in the script.
ALTER TABLE tbl_insurance_records
    ADD CONSTRAINT fk_insurance_records_used_for_typhoon
    FOREIGN KEY (used_for_typhoon_id) REFERENCES tbl_typhoons(typhoon_id) ON DELETE SET NULL;

-- Source of truth for "was this policy line used (paid out) for this specific
-- typhoon" -- one row per (insurance_records_id, typhoon_id), so usage history
-- survives across multiple typhoons instead of the single-row mirror on
-- tbl_insurance_records getting overwritten by whichever typhoon assessed it
-- last. Written by AssessmentService.calculate_for_bulletin at the end of
-- computing payouts for a typhoon.
CREATE TABLE tbl_insurance_usage (
    usage_id SERIAL PRIMARY KEY,
    insurance_records_id INT NOT NULL REFERENCES tbl_insurance_records(insurance_records_id) ON DELETE CASCADE,
    typhoon_id INT NOT NULL REFERENCES tbl_typhoons(typhoon_id) ON DELETE CASCADE,
    assessment_id INT REFERENCES tbl_risk_assessment(assessment_id) ON DELETE SET NULL,
    is_used BOOLEAN NOT NULL DEFAULT TRUE,
    marked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_insurance_usage_insurance_typhoon UNIQUE (insurance_records_id, typhoon_id)
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
    center_geom GEOMETRY(Point, 4326),
    -- Raw PAGASA TCWS as parsed, unvalidated (see migrations/2026-09-30_tcb_raw_tcws.sql)
    max_signal_level INT,
    tcws_areas JSONB,
    -- PAGASA's final-bulletin marker (trailing "F" on the number, or an LPA
    -- bulletin) -- see migrations/2026-10-09_tcb_is_final.sql
    is_final BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE tbl_tcb_signals (
    signal_id SERIAL PRIMARY KEY,
    tcb_id INT REFERENCES tbl_tropical_cyclone_bulletins(tcb_id) ON DELETE CASCADE,
    signal_level INT NOT NULL,
    island_group INT NOT NULL,
    area_name VARCHAR(100) NOT NULL,
    -- The AdminBoundary province this signal was matched against (see
    -- backend/migrations/2026-08-20_tcb_signal_province.sql). Nullable --
    -- lets exposure_calculator.py key boundary lookups on (province,
    -- municipality) instead of municipality alone, which collides once
    -- AdminBoundary covers the whole country (nationwide PSGC expansion).
    province VARCHAR(100)
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
    -- Minutes, not hours (as of 2026-08-10 -- see
    -- backend/migrations/2026-08-10_polling_interval_minutes.sql). 180 = 3 hours.
    polling_interval_minutes INT NOT NULL DEFAULT 180,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO tbl_parser_settings (polling_interval_minutes) VALUES (180);

-- 5c. Activity log (2026-08-16) -- backs the admin-only Activity Log tab.
-- user_id nullable: a failed/anonymous login attempt has no authenticated
-- user yet, but is still worth recording.
CREATE TABLE tbl_activity_log (
    log_id BIGSERIAL PRIMARY KEY,
    user_id INT REFERENCES tbl_system_users(user_id) ON DELETE SET NULL,
    action VARCHAR(20) NOT NULL, -- LOGIN, LOGOUT, POST, PUT, PATCH, DELETE
    endpoint VARCHAR(255) NOT NULL,
    status_code INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_activity_log_created_at ON tbl_activity_log (created_at DESC);
CREATE INDEX idx_activity_log_user_id ON tbl_activity_log (user_id);

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

-- Step 0: source crop-stage vocabulary -> (crop_stage_no, stage_group).
-- Stage names follow PCIC's own abbreviations as printed in the Table 7a/7b column
-- headers (RECSAP-From-IRR.pptx): MnTl|MxTl|PI|BS|FS|MS|SD|HD|YR, with S/T
-- (seedling/transplanting) preceding them in the legacy export's numbering.
--
-- Group assignment (Fabio, 2026-10-09) is read off the legacy export's own
-- parenthetical labels -- e.g. "4 - Booting Stg. (REPRODUCTIVE)", "6 - Milking Stg.
-- (LATE REPRODUCTIVE)", "7 - Dough Stg. (MATURITY)" -- which land on Table 1's five
-- group names exactly, leaving none unassigned. This supersedes the earlier
-- Booting->Late Vegetative mapping, which this file itself had flagged as
-- "inferred ... not independently confirmed"; Late Vegetative is MxTl.
-- Flowering->Reproductive is confirmed verbatim by the manuscript's worked example
-- (p. 53: Flowering -> Reproductive -> IF 392.00).
INSERT INTO tbl_crop_stage_mapping (source_code, source_label, pcic_stage, crop_stage_no, stage_group, notes) VALUES
-- Legacy export, "Stage No." (PCIC agronomic code).
(0, NULL, 'S/T',  NULL, 'Early Vegetative',  'Table 11 Note 1: no immediate direct wind damage.'),
(1, NULL, 'MnTl', NULL, 'Early Vegetative',  'Table 11 Note 1: no immediate direct wind damage.'),
(2, NULL, 'MxTl', NULL, 'Late Vegetative',   'Table 11 Note 1: no immediate direct wind damage.'),
(3, NULL, 'PI',   NULL, 'Reproductive',      'Table 11 Note 1: no immediate direct wind damage.'),
(4, NULL, 'BS',   1,    'Reproductive',      'Table 11 BOOTING row.'),
(5, NULL, 'FS',   2,    'Reproductive',      'Table 11 FLOWERING row.'),
(6, NULL, 'MS',   2,    'Late Reproductive', 'Table 11 FLOWERING row -- PCIC pairs FS/MS as one unit in Tables 9 and 10 -- but the Table 1 group is Late Reproductive.'),
(7, NULL, 'SD',   3,    'Maturity',          'Table 11 MATURITY row.'),
(8, NULL, 'HD',   3,    'Maturity',          'Table 11 MATURITY row.'),
(9, NULL, 'YR',   3,    'Maturity',          'Table 11 MATURITY row.'),
-- Newer PABS/GPX export, "Stage of Crop" (free text, stored lowercased).
(NULL, 'vegetative/tillering',       'MnTl/MxTl', NULL, 'Early Vegetative',  'Table 11 Note 1: no immediate direct wind damage.'),
(NULL, 'panicle initiation/booting', 'PI/BS',     NULL, NULL,                'ON HOLD (Fabio, 2026-10-09): merges PI (no wind damage per Table 11 Note 1) with BS (eligible, crop_stage_no 1), and no PCIC document gives a days-after-transplanting threshold to separate them. Rows ingest but are never assessed. To enable: set crop_stage_no=1, stage_group=''Reproductive'' once PCIC supplies the days-per-stage table.'),
(NULL, 'flowering',                  'FS',        2,    'Reproductive',      'Table 11 FLOWERING row.'),
(NULL, 'milking stage',              'MS',        2,    'Late Reproductive', 'Table 11 FLOWERING row via PCIC''s FS/MS pairing; the Table 1 group is Late Reproductive.'),
(NULL, 'dough stage',                'SD/HD',     3,    'Maturity',          'Table 11 MATURITY row.'),
(NULL, 'yellow ripening',            'YR',        3,    'Maturity',          'Table 11 MATURITY row.'),
(NULL, 'harvested',                  'Harvested', NULL, NULL,                'No standing crop at typhoon occurrence -- nothing to assess.');
