-- Migration: activity log remarks
-- (2026-10-22 -- every Activity Log entry now carries a full `remarks`
-- sentence of what was done: which file/record, what changed, how many rows
-- were accepted or rejected, and why a request was rejected. See
-- backend/app/core/activity_log.py.)
--
-- Also CLEARS the existing log, as requested: entries written before this
-- change have no remarks, so the table starts fresh in the new format.
-- This deletes every existing activity-log row and cannot be undone.
--
-- Run against any already-provisioned DB (local or remote):
--   psql -U agrisure_admin -d agrisure_db -f backend/migrations/2026-10-22_activity_log_remarks.sql
--
-- init_schema.sql has also been updated to create this column directly for
-- future fresh installs.

ALTER TABLE tbl_activity_log ADD COLUMN IF NOT EXISTS remarks TEXT;

TRUNCATE tbl_activity_log RESTART IDENTITY;
