-- Migration: per-typhoon insurance usage tracking.
--
-- Run this by hand against the already-provisioned, already-populated dev DB
-- (NOT via re-applying init_schema.sql, which starts with DROP TABLE and
-- would destroy existing data). init_schema.sql has also been updated with
-- the equivalent statements for future *fresh* installs -- this file is
-- specifically for bringing an existing DB up to date.
--
--   psql -U agrisure_admin -d agrisure_db -f backend/migrations/2026-08-14_insurance_typhoon_usage_tracking.sql
--
-- Context: at the end of AssessmentService.calculate_for_bulletin, each
-- assessed policy's insurance is now marked "used" for that specific typhoon
-- (final_indemnity_payment > 0), so a later assessment for a *different*
-- typhoon isn't confused by a prior typhoon's usage. See
-- .claude/FUNCTION_CHANGES.md for the full rationale.

BEGIN;

-- 1. Denormalized "latest usage" mirror on tbl_insurance_records -- convenience
-- snapshot only. Full per-typhoon history lives in tbl_insurance_usage (below),
-- since these three columns can only ever reflect one typhoon at a time.
ALTER TABLE tbl_insurance_records
    ADD COLUMN IF NOT EXISTS is_used BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS used_for_typhoon_id INT,
    ADD COLUMN IF NOT EXISTS used_at TIMESTAMPTZ;

ALTER TABLE tbl_insurance_records
    ADD CONSTRAINT fk_insurance_records_used_for_typhoon
    FOREIGN KEY (used_for_typhoon_id) REFERENCES tbl_typhoons(typhoon_id) ON DELETE SET NULL;

-- 2. Source of truth: one row per (insurance_records_id, typhoon_id).
CREATE TABLE IF NOT EXISTS tbl_insurance_usage (
    usage_id SERIAL PRIMARY KEY,
    insurance_records_id INT NOT NULL REFERENCES tbl_insurance_records(insurance_records_id) ON DELETE CASCADE,
    typhoon_id INT NOT NULL REFERENCES tbl_typhoons(typhoon_id) ON DELETE CASCADE,
    assessment_id INT REFERENCES tbl_risk_assessment(assessment_id) ON DELETE SET NULL,
    is_used BOOLEAN NOT NULL DEFAULT TRUE,
    marked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_insurance_usage_insurance_typhoon UNIQUE (insurance_records_id, typhoon_id)
);

COMMIT;
