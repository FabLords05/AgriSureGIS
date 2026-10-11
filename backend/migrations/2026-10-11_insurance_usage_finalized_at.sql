-- Migration: tbl_insurance_usage.finalized_at
-- (2026-10-11 -- once a specialist exports the final PABS CSV, every policy on it
-- with a payout is locked as used: AssessmentService.calculate_for_bulletin skips
-- it for any new typhoon, and recalculating the exported typhoon leaves its
-- exported results frozen. NULL = only the provisional calculate-time mark;
-- non-NULL = locked by an export, at that time.)
--
-- init_schema.sql has also been updated for fresh installs. Written to be safely
-- re-runnable.
--
-- Run against any already-provisioned DB:
--   psql -U agrisure_admin -d agrisure_db -f backend/migrations/2026-10-11_insurance_usage_finalized_at.sql

ALTER TABLE tbl_insurance_usage ADD COLUMN IF NOT EXISTS finalized_at TIMESTAMPTZ;
