-- Migration: activity log
-- (Fabio, 2026-08-16 -- new admin-only Activity Log tab: records login,
-- logout, and every mutating (POST/PUT/PATCH/DELETE) backend call, alongside
-- the same-day session-token auth work in app/core/security.py).
--
-- Run against any already-provisioned DB (local or remote):
--   psql -U agrisure_admin -d agrisure_db -f backend/migrations/2026-08-16_activity_log.sql
--
-- init_schema.sql has also been updated to create this table directly for
-- future fresh installs.

CREATE TABLE IF NOT EXISTS tbl_activity_log (
    log_id BIGSERIAL PRIMARY KEY,
    user_id INT REFERENCES tbl_system_users(user_id) ON DELETE SET NULL,
    action VARCHAR(20) NOT NULL,
    endpoint VARCHAR(255) NOT NULL,
    status_code INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_activity_log_created_at ON tbl_activity_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_log_user_id ON tbl_activity_log (user_id);
