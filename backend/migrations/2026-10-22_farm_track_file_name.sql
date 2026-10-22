-- Migration: tbl_farms.track_file_name (2026-10-22 -- PCIC's "List of Farms
-- with GPX File" export names the exact GPX file walked for each farm in its
-- trackFileName column. It matches 1,434 of 1,456 rows of the Region II
-- sample, far more reliably than parsing IDs out of the file name, so the
-- CSV import now stores it and GpxFarmerMatcherService matches on it first.)
--
-- Run against any already-provisioned DB:
--   psql -U agrisure_admin -d agrisure_db -f backend/migrations/2026-10-22_farm_track_file_name.sql
--
-- Farms imported before this stay NULL until their CSV is uploaded again
-- (the import backfills blank track_file_name / georef_id on existing farms).

ALTER TABLE tbl_farms ADD COLUMN IF NOT EXISTS track_file_name VARCHAR(255);
CREATE INDEX IF NOT EXISTS idx_farms_track_file_name ON tbl_farms (lower(track_file_name));
CREATE INDEX IF NOT EXISTS idx_farms_georef_id ON tbl_farms (georef_id);
