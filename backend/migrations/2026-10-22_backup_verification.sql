-- Migration: backup integrity + verification columns on tbl_backup_log
-- (2026-10-22 -- backups are now checksummed, row-counted from the dump's
-- own snapshot, optionally encrypted for Google Drive, and can be
-- test-restored into a separate verification database; see
-- app/services/backup_service.py).
--
-- Run against any already-provisioned DB:
--   psql -U agrisure_admin -d agrisure_db -f backend/migrations/2026-10-22_backup_verification.sql
--
-- Backups taken before this have no sha256 / row_counts, so they can still be
-- test-restored but their row counts can't be compared (reported as such).

ALTER TABLE tbl_backup_log
    ADD COLUMN IF NOT EXISTS sha256 CHAR(64),
    ADD COLUMN IF NOT EXISTS row_counts JSONB,
    ADD COLUMN IF NOT EXISTS encrypted BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS gdrive_md5 VARCHAR(32),
    ADD COLUMN IF NOT EXISTS verify_status VARCHAR(20),
    ADD COLUMN IF NOT EXISTS verify_detail JSONB,
    ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;

ALTER TABLE tbl_backup_log DROP CONSTRAINT IF EXISTS tbl_backup_log_verify_status_check;
ALTER TABLE tbl_backup_log
    ADD CONSTRAINT tbl_backup_log_verify_status_check
    CHECK (verify_status IN ('pending', 'verified', 'failed'));
