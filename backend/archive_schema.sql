-- AgriSureGIS ARCHIVE database (2026-10-22) -- a separate PostgreSQL database
-- (agrisure_archive), not a schema inside agrisure_db.
--
-- Each typhoon season PCIC re-exports CSV/GPKG from PABS. Once every typhoon
-- assessed against the live data is at least 7 days past its last bulletin, a
-- user runs "Archive & Clear" (app/services/archive_service.py): every
-- uploaded record and polygon is copied here, then deleted from the live DB.
-- Archives are viewed, never restored.
--
-- READ-ONLY by design, enforced three ways:
--   1. agrisure_archive_reader  -- SELECT only. Every viewing endpoint uses it
--      (ARCHIVE_DATABASE_URL).
--   2. agrisure_archive_writer  -- SELECT + INSERT only, no UPDATE/DELETE. Used
--      only inside archive_and_clear (ARCHIVE_WRITER_DATABASE_URL).
--   3. A trigger on every table rejects UPDATE and DELETE outright, so even
--      the owner can't edit an archive by mistake (a superuser can still
--      DISABLE TRIGGER deliberately).
--
-- Original IDs are kept as plain columns, never foreign keys, so an archive
-- is a self-contained snapshot. Every row carries archive_id.
--
-- Provisioning (Fabio, as the postgres superuser -- one command at a time):
--   createdb -U postgres -O agrisure_admin agrisure_archive
--   psql -U postgres -d agrisure_archive -v reader_password=CHANGE_ME -v writer_password=CHANGE_ME -f backend/archive_schema.sql
-- Re-running this file DROPS every archive table. Only do that on an empty DB.

CREATE EXTENSION IF NOT EXISTS postgis;

-- Roles (idempotent). Passwords come from the psql -v variables above.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agrisure_archive_reader') THEN
        CREATE ROLE agrisure_archive_reader LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agrisure_archive_writer') THEN
        CREATE ROLE agrisure_archive_writer LOGIN;
    END IF;
END $$;
ALTER ROLE agrisure_archive_reader PASSWORD :'reader_password';
ALTER ROLE agrisure_archive_writer PASSWORD :'writer_password';

DROP TABLE IF EXISTS arc_sar_observation CASCADE;
DROP TABLE IF EXISTS arc_sar_planted_check CASCADE;
DROP TABLE IF EXISTS arc_planted_verification CASCADE;
DROP TABLE IF EXISTS arc_insurance_usage CASCADE;
DROP TABLE IF EXISTS arc_risk_assessment CASCADE;
DROP TABLE IF EXISTS arc_insurance_records CASCADE;
DROP TABLE IF EXISTS arc_farms CASCADE;
DROP TABLE IF EXISTS arc_farmers CASCADE;
DROP TABLE IF EXISTS arc_area_exposure_summary CASCADE;
DROP TABLE IF EXISTS arc_tcb_signals CASCADE;
DROP TABLE IF EXISTS arc_tropical_cyclone_bulletins CASCADE;
DROP TABLE IF EXISTS arc_typhoons CASCADE;
DROP TABLE IF EXISTS arc_admin_boundaries CASCADE;
DROP TABLE IF EXISTS tbl_archive_batch CASCADE;

CREATE TABLE tbl_archive_batch (
    archive_id SERIAL PRIMARY KEY,
    label VARCHAR(255) NOT NULL,
    -- [{"typhoon_id": 3, "name": "OPONG", "year": 2025, "last_bulletin_at": "..."}]
    typhoons JSONB NOT NULL,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archived_by_user_id INT,
    archived_by_name VARCHAR(255),
    -- {"arc_farms": 1180, "arc_insurance_records": 1204, ...}
    row_counts JSONB NOT NULL,
    record_count INT NOT NULL,
    dump_file_name VARCHAR(255),
    gdrive_file_id VARCHAR(255)
);

-- ── Uploaded PABS data (copied, then deleted from the live DB) ──────────────

CREATE TABLE arc_farmers (
    arc_row_id BIGSERIAL PRIMARY KEY,
    archive_id INT NOT NULL REFERENCES tbl_archive_batch(archive_id),
    farmer_id INT NOT NULL,
    farmers_id VARCHAR(20),
    rsbsa_no VARCHAR(50),
    last_name VARCHAR(100),
    first_name VARCHAR(100),
    middle_name VARCHAR(100),
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
);

CREATE TABLE arc_farms (
    arc_row_id BIGSERIAL PRIMARY KEY,
    archive_id INT NOT NULL REFERENCES tbl_archive_batch(archive_id),
    farm_id INT NOT NULL,
    farmer_id INT,
    boundary_id INT,
    csv_farm_reference VARCHAR(50),
    georef_id VARCHAR(100),
    province VARCHAR(100),
    municipality VARCHAR(100),
    barangay VARCHAR(100),
    area_size NUMERIC(10,4),
    location_geom GEOMETRY(MultiPolygon, 4326),
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
);

CREATE TABLE arc_insurance_records (
    arc_row_id BIGSERIAL PRIMARY KEY,
    archive_id INT NOT NULL REFERENCES tbl_archive_batch(archive_id),
    insurance_records_id INT NOT NULL,
    farmer_id INT,
    farm_id INT,
    policy_no VARCHAR(50),
    program_type VARCHAR(100),
    product_name VARCHAR(150),
    effectivity_date DATE,
    expiry_date DATE,
    amount_cover NUMERIC(15,2),
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    is_used BOOLEAN,
    used_for_typhoon_id INT,
    used_at TIMESTAMPTZ
);

CREATE TABLE arc_risk_assessment (
    arc_row_id BIGSERIAL PRIMARY KEY,
    archive_id INT NOT NULL REFERENCES tbl_archive_batch(archive_id),
    assessment_id INT NOT NULL,
    insurance_records_id INT,
    summary_id INT,
    matrix_id INT,
    indemnity_matrix_id INT,
    crop_stage_no INT,
    crop_stage VARCHAR(150),
    stage_group VARCHAR(30),
    period_of_exposure INT,
    wind_velocity INT,
    indemnity_factor NUMERIC(7,2),
    estimated_damage NUMERIC(15,2),
    final_indemnity_payment NUMERIC(15,2),
    assessment_date TIMESTAMPTZ,
    user_id INT
);

CREATE TABLE arc_insurance_usage (
    arc_row_id BIGSERIAL PRIMARY KEY,
    archive_id INT NOT NULL REFERENCES tbl_archive_batch(archive_id),
    usage_id INT NOT NULL,
    insurance_records_id INT,
    typhoon_id INT,
    assessment_id INT,
    is_used BOOLEAN,
    marked_at TIMESTAMPTZ,
    finalized_at TIMESTAMPTZ
);

CREATE TABLE arc_planted_verification (
    arc_row_id BIGSERIAL PRIMARY KEY,
    archive_id INT NOT NULL REFERENCES tbl_archive_batch(archive_id),
    verification_id INT NOT NULL,
    farm_id INT,
    typhoon_id INT,
    is_planted BOOLEAN,
    verified_by INT,
    verified_at TIMESTAMPTZ,
    notes TEXT
);

CREATE TABLE arc_sar_planted_check (
    arc_row_id BIGSERIAL PRIMARY KEY,
    archive_id INT NOT NULL REFERENCES tbl_archive_batch(archive_id),
    check_id INT NOT NULL,
    farm_id INT,
    typhoon_id INT,
    status VARCHAR(20),
    reason_code VARCHAR(40),
    t0_date DATE,
    tp_date DATE,
    vh_rise_db NUMERIC(5,2),
    ratio_drop_db NUMERIC(5,2),
    relative_orbit INT,
    scene_count INT,
    window_start DATE,
    window_end DATE,
    checked_by INT,
    checked_at TIMESTAMPTZ
);

CREATE TABLE arc_sar_observation (
    arc_row_id BIGSERIAL PRIMARY KEY,
    archive_id INT NOT NULL REFERENCES tbl_archive_batch(archive_id),
    observation_id INT NOT NULL,
    farm_id INT,
    scene_date DATE,
    relative_orbit INT,
    vv_db NUMERIC(6,2),
    vh_db NUMERIC(6,2),
    fetched_at TIMESTAMPTZ
);

-- ── Typhoon context (copied, kept live -- later typhoons still use it) ──────

CREATE TABLE arc_typhoons (
    arc_row_id BIGSERIAL PRIMARY KEY,
    archive_id INT NOT NULL REFERENCES tbl_archive_batch(archive_id),
    typhoon_id INT NOT NULL,
    name VARCHAR(100),
    year INT,
    is_active BOOLEAN
);

CREATE TABLE arc_tropical_cyclone_bulletins (
    arc_row_id BIGSERIAL PRIMARY KEY,
    archive_id INT NOT NULL REFERENCES tbl_archive_batch(archive_id),
    tcb_id INT NOT NULL,
    typhoon_id INT,
    title VARCHAR(255),
    bulletin_count INT,
    category VARCHAR(100),
    max_sustained_winds INT,
    gustiness INT,
    issued_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    center_geom GEOMETRY(Point, 4326),
    max_signal_level INT,
    tcws_areas JSONB,
    is_final BOOLEAN,
    wind_radius_km INT,
    storm_force_radius_km INT,
    forecast_track JSONB
);

CREATE TABLE arc_tcb_signals (
    arc_row_id BIGSERIAL PRIMARY KEY,
    archive_id INT NOT NULL REFERENCES tbl_archive_batch(archive_id),
    signal_id INT NOT NULL,
    tcb_id INT,
    signal_level INT,
    island_group INT,
    area_name VARCHAR(100),
    province VARCHAR(100)
);

CREATE TABLE arc_area_exposure_summary (
    arc_row_id BIGSERIAL PRIMARY KEY,
    archive_id INT NOT NULL REFERENCES tbl_archive_batch(archive_id),
    summary_id INT NOT NULL,
    typhoon_id INT,
    boundary_id INT,
    province VARCHAR(100),
    municipality VARCHAR(100),
    max_signal_level INT,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    is_eligible_6hr BOOLEAN,
    total_exposure_hours NUMERIC(5,2),
    computed_at TIMESTAMPTZ
);

-- Only the boundaries the archived farms and exposure summaries reference.
CREATE TABLE arc_admin_boundaries (
    arc_row_id BIGSERIAL PRIMARY KEY,
    archive_id INT NOT NULL REFERENCES tbl_archive_batch(archive_id),
    boundary_id INT NOT NULL,
    psgc_code VARCHAR(10),
    province VARCHAR(100),
    municipality VARCHAR(100),
    barangay VARCHAR(100),
    boundary_geom GEOMETRY(MultiPolygon, 4326)
);

-- ── Indexes for the archive viewer ──────────────────────────────────────────
CREATE INDEX idx_arc_farms_archive ON arc_farms (archive_id, farm_id);
CREATE INDEX idx_arc_farms_geom ON arc_farms USING GIST (location_geom);
CREATE INDEX idx_arc_farmers_archive ON arc_farmers (archive_id, farmer_id);
CREATE INDEX idx_arc_insurance_archive ON arc_insurance_records (archive_id, insurance_records_id);
CREATE INDEX idx_arc_assessment_archive ON arc_risk_assessment (archive_id, insurance_records_id);
CREATE INDEX idx_arc_summary_archive ON arc_area_exposure_summary (archive_id, summary_id);
CREATE INDEX idx_arc_bulletins_archive ON arc_tropical_cyclone_bulletins (archive_id, tcb_id);
CREATE INDEX idx_arc_signals_archive ON arc_tcb_signals (archive_id, tcb_id);
CREATE INDEX idx_arc_boundaries_archive ON arc_admin_boundaries (archive_id, boundary_id);

-- ── Read-only enforcement ───────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION fn_archive_reject_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'AgriSureGIS archive is read-only: % on % is not allowed.', TG_OP, TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE t TEXT;
BEGIN
    FOR t IN
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public' AND (tablename LIKE 'arc\_%' OR tablename = 'tbl_archive_batch')
    LOOP
        EXECUTE format(
            'CREATE TRIGGER trg_%s_read_only BEFORE UPDATE OR DELETE OR TRUNCATE ON %I '
            'FOR EACH STATEMENT EXECUTE FUNCTION fn_archive_reject_change()', t, t);
    END LOOP;
END $$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE agrisure_archive TO agrisure_archive_reader, agrisure_archive_writer;
GRANT USAGE ON SCHEMA public TO agrisure_archive_reader, agrisure_archive_writer;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO agrisure_archive_reader;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA public TO agrisure_archive_writer;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO agrisure_archive_writer;
