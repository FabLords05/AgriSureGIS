-- Migration (ARCHIVE database): per-signal exposure hours on archived typhoons
-- (2026-10-22 -- companion to 2026-10-22_exposure_signal_hours.sql on the
-- live DB. archive_service.py now copies these columns, so Archive & Clear
-- fails until this is applied to the archive database.)
--
-- Run against the archive database (agrisure_archive), as postgres (same as provisioning):
--   psql -U postgres -d agrisure_archive -f backend/migrations/2026-10-22_archive_exposure_signal_hours.sql
--
-- archive_schema.sql has also been updated for fresh installs. Rows archived
-- before this migration keep 0 / NULL in the new columns.

ALTER TABLE arc_area_exposure_summary
    ALTER COLUMN total_exposure_hours TYPE NUMERIC(7,2),
    ADD COLUMN IF NOT EXISTS island_group INT,
    ADD COLUMN IF NOT EXISTS signal_1_hours NUMERIC(7,2) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS signal_2_hours NUMERIC(7,2) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS signal_3_hours NUMERIC(7,2) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS signal_4_hours NUMERIC(7,2) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS signal_5_hours NUMERIC(7,2) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS payout_hours NUMERIC(7,2),
    ADD COLUMN IF NOT EXISTS has_open_interval BOOLEAN,
    ADD COLUMN IF NOT EXISTS has_long_gap BOOLEAN;
