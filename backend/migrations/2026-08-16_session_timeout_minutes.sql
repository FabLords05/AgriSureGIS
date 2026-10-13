-- Migration: per-account session timeout
-- (Fabio, 2026-08-16 -- session timeout was a decorative, non-functional
-- Calibration screen dropdown; now real, admin-editable per user account so
-- it follows a user across devices, enforced client-side in App.tsx).
--
-- Run against any already-provisioned DB (local or remote):
--   psql -U agrisure_admin -d agrisure_db -f backend/migrations/2026-08-16_session_timeout_minutes.sql
--
-- init_schema.sql has also been updated to create the column directly for
-- future fresh installs -- this file is for bringing an existing DB up to
-- date without losing its data.

ALTER TABLE tbl_system_users ADD COLUMN IF NOT EXISTS session_timeout_minutes INT NOT NULL DEFAULT 5;
