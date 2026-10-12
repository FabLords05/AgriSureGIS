-- Migration: automatic SAR planted check + Sentinel-1 observation cache
-- (Cristian, 2026-10-12 -- "Verify Farm Planted" Phase 2, see
-- docs/SAR_ISPLANTED_METHOD.md §3. POST /api/sar/check classifies every
-- affected farm for a typhoon as GREEN "planted" or YELLOW "field_verify".)
--
-- tbl_sar_observation:     per-farm, per-scene polygon-mean VV/VH (dB) pulled
--                          from Google Earth Engine, kept so the same farm and
--                          dates are never queried twice.
-- tbl_sar_fetch_coverage:  the date range each farm's observations fully cover,
--                          and the boundary (md5 of location_geom) they were
--                          measured on. A re-uploaded GPX boundary refetches.
-- tbl_sar_planted_check:   the result per farm per typhoon. Like
--                          tbl_planted_verification, never read by the
--                          assessment or the PABS export.
--
-- NOT in docs/ERD.drawio.png yet -- the ERD needs these three tables added.
--
-- init_schema.sql has also been updated for fresh installs. Written to be safely
-- re-runnable.
--
-- Run against any already-provisioned DB:
--   psql -U agrisure_admin -d agrisure_db -f backend/migrations/2026-10-12_sar_planted_check.sql

CREATE TABLE IF NOT EXISTS tbl_sar_observation (
    observation_id SERIAL PRIMARY KEY,
    farm_id INT NOT NULL REFERENCES tbl_farms(farm_id) ON DELETE CASCADE,
    scene_date DATE NOT NULL,
    relative_orbit INT NOT NULL,
    vv_db NUMERIC(6,2) NOT NULL,
    vh_db NUMERIC(6,2) NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_sar_observation_farm_scene UNIQUE (farm_id, scene_date, relative_orbit)
);

CREATE TABLE IF NOT EXISTS tbl_sar_fetch_coverage (
    farm_id INT PRIMARY KEY REFERENCES tbl_farms(farm_id) ON DELETE CASCADE,
    covered_start DATE NOT NULL,
    covered_end DATE NOT NULL,
    geom_hash VARCHAR(32) NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tbl_sar_planted_check (
    check_id SERIAL PRIMARY KEY,
    farm_id INT NOT NULL REFERENCES tbl_farms(farm_id) ON DELETE CASCADE,
    typhoon_id INT NOT NULL REFERENCES tbl_typhoons(typhoon_id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL CHECK (status IN ('planted', 'field_verify')),
    reason_code VARCHAR(40) NOT NULL,
    t0_date DATE,
    tp_date DATE,
    vh_rise_db NUMERIC(5,2),
    ratio_drop_db NUMERIC(5,2),
    relative_orbit INT,
    scene_count INT NOT NULL DEFAULT 0,
    window_start DATE NOT NULL,
    window_end DATE NOT NULL,
    checked_by INT REFERENCES tbl_system_users(user_id) ON DELETE SET NULL,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_sar_planted_check_farm_typhoon UNIQUE (farm_id, typhoon_id)
);

CREATE INDEX IF NOT EXISTS idx_sar_planted_check_typhoon ON tbl_sar_planted_check (typhoon_id);
