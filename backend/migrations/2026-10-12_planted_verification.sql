-- Migration: tbl_planted_verification
-- (2026-10-12 -- "Verify Farm Planted" use case, Phase 1. The GIS Specialist
-- looks at the pre-event Sentinel-1 VV/VH layer over the "Affected Only"
-- polygons and records Planted / Not planted per farm per typhoon. Per Fabio:
-- the verdict is recorded and shown, but NOT read by the assessment or the
-- PABS export -- it never gates a payout.)
--
-- NOT in docs/ERD.drawio.png yet -- the ERD needs this table added.
--
-- init_schema.sql has also been updated for fresh installs. Written to be safely
-- re-runnable.
--
-- Run against any already-provisioned DB:
--   psql -U agrisure_admin -d agrisure_db -f backend/migrations/2026-10-12_planted_verification.sql

CREATE TABLE IF NOT EXISTS tbl_planted_verification (
    verification_id SERIAL PRIMARY KEY,
    farm_id INT NOT NULL REFERENCES tbl_farms(farm_id) ON DELETE CASCADE,
    typhoon_id INT NOT NULL REFERENCES tbl_typhoons(typhoon_id) ON DELETE CASCADE,
    is_planted BOOLEAN NOT NULL,
    verified_by INT REFERENCES tbl_system_users(user_id) ON DELETE SET NULL,
    verified_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    CONSTRAINT uq_planted_verification_farm_typhoon UNIQUE (farm_id, typhoon_id)
);
