-- Admin settings + backup history (2026-10-22).
--
-- tbl_system_settings: key/value store for admin-editable settings that used
-- to be client-side only. coverage_rate_per_ha is the RSBSA default Amount of
-- Cover per hectare, applied at upload ONLY when a record carries no (or a
-- zero) AmountofCover -- see app/api/upload.py. auto_backup_enabled drives the
-- nightly 23:00 PHT pg_dump job in app/core/scheduler.py.
--
-- tbl_backup_log: one row per pg_dump the app runs (manual, scheduled, or the
-- safety dump taken right before an Archive & Clear). Feeds the Database
-- Backup tab's Last backup / size / count figures.
--
-- Apply to an already-provisioned DB with:
--   psql -U agrisure_admin -d agrisure_db -f backend/migrations/2026-10-22_system_settings_backup_log.sql

CREATE TABLE IF NOT EXISTS tbl_system_settings (
    setting_key VARCHAR(50) PRIMARY KEY,
    setting_value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by INT REFERENCES tbl_system_users(user_id) ON DELETE SET NULL
);

INSERT INTO tbl_system_settings (setting_key, setting_value) VALUES
    ('coverage_rate_per_ha', '25000'),
    ('auto_backup_enabled', 'true')
ON CONFLICT (setting_key) DO NOTHING;

CREATE TABLE IF NOT EXISTS tbl_backup_log (
    backup_id SERIAL PRIMARY KEY,
    kind VARCHAR(20) NOT NULL CHECK (kind IN ('manual', 'scheduled', 'archive')),
    file_name VARCHAR(255),
    size_bytes BIGINT,
    gdrive_file_id VARCHAR(255),
    -- 'success' = dump written; gdrive_error set separately when only the
    -- Drive upload failed (the local dump still exists).
    status VARCHAR(20) NOT NULL CHECK (status IN ('success', 'failed')),
    error TEXT,
    gdrive_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by INT REFERENCES tbl_system_users(user_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_backup_log_created_at ON tbl_backup_log (created_at DESC);
