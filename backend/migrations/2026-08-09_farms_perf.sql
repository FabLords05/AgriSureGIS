-- Migration: farms listing performance (items 3 and 5 of the 2026-08-09
-- optimization pass -- see .claude/FUNCTION_CHANGES.md for the full
-- rationale/discussion).
--
-- Run this by hand against the already-provisioned, already-populated dev
-- DB (NOT via re-applying init_schema.sql, which starts with DROP TABLE
-- and would destroy the existing ~49,588 rows). init_schema.sql has also
-- been updated with the same statements for future *fresh* installs --
-- this file is specifically for bringing an existing DB up to date.
--
--   psql -U agrisure_admin -d agrisure_db -f backend/migrations/2026-08-09_farms_perf.sql
--
-- Both the app (backend/app/api/farms.py) and this migration are written
-- so that running this is optional but recommended: the app checks for
-- both objects at runtime and falls back to its pre-migration behavior if
-- they're not there yet (see app/core/farms_view.py's docstring). Nothing
-- breaks if this is skipped or delayed -- it just runs slower without it.

-- 1. Index backing GET /api/farms/'s active_only=True filter (item 3).
-- CONCURRENTLY avoids taking a lock that would block other queries/writes
-- against tbl_insurance_records while the index builds -- slower to build,
-- but safe to run against a live table instead of needing a maintenance
-- window. (CONCURRENTLY can't run inside a transaction block, which is why
-- this is its own top-level statement, not wrapped in BEGIN/COMMIT.)
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_insurance_records_active_lookup
    ON tbl_insurance_records (effectivity_date, expiry_date, farm_id);

-- 2. Materialized view precomputing "most recent InsuranceRecord per farm"
-- (item 5) -- see app/core/farms_view.py for how the app reads/refreshes
-- this. DISTINCT ON + the same NULLS LAST ordering as farms.py's Python
-- fallback (see that file's docstring for why NULLS LAST matters as soon
-- as a farm has more than one InsuranceRecord).
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_farm_latest_insurance AS
SELECT DISTINCT ON (farm_id)
    farm_id,
    insurance_records_id,
    policy_no,
    effectivity_date,
    expiry_date
FROM tbl_insurance_records
ORDER BY farm_id, effectivity_date DESC NULLS LAST;

-- Required for REFRESH MATERIALIZED VIEW CONCURRENTLY (used by
-- app/core/farms_view.py's refresh_farm_latest_insurance_view(), called
-- after every CSV/GPX upload) -- without a unique index, only a full
-- table-locking REFRESH is possible.
CREATE UNIQUE INDEX IF NOT EXISTS ix_mv_farm_latest_insurance_farm_id
    ON mv_farm_latest_insurance (farm_id);

-- One-time initial population is already done by the CREATE MATERIALIZED
-- VIEW above (it runs the SELECT immediately) -- this manual refresh is
-- only needed if you run this migration, then separately seed/import more
-- data (e.g. backend/seed_active_insurance.py, which also calls
-- refresh_farm_latest_insurance_view() itself after inserting) before the
-- app's next write-triggered refresh. Safe to re-run any time.
-- REFRESH MATERIALIZED VIEW CONCURRENTLY mv_farm_latest_insurance;
