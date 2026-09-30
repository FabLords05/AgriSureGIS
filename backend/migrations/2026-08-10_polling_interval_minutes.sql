-- Migration: TCB polling interval moves from whole hours to minutes
-- (Fabio, 2026-08-10 -- wanted sub-hour granularity, down to 15 minutes,
-- for the PAGASA bulletin scraper's polling interval).
--
-- Run against any already-provisioned DB (local or remote):
--   psql -U agrisure_admin -d agrisure_db -f backend/migrations/2026-08-10_polling_interval_minutes.sql
--
-- init_schema.sql has also been updated to create the column with its new
-- name/semantics directly for future fresh installs -- this file is
-- specifically for bringing an existing DB (with data already in the old
-- polling_interval_hours column) up to date without losing that value.

ALTER TABLE tbl_parser_settings RENAME COLUMN polling_interval_hours TO polling_interval_minutes;

-- Converts whatever was persisted (e.g. "3" meaning 3 hours) into the same
-- real-world interval expressed in minutes ("180"), so existing settings
-- keep their actual meaning instead of silently becoming 4x more frequent.
UPDATE tbl_parser_settings SET polling_interval_minutes = polling_interval_minutes * 60;

ALTER TABLE tbl_parser_settings ALTER COLUMN polling_interval_minutes SET DEFAULT 180;
