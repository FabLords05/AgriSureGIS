-- Migration: per-signal exposure hours + TCB coverage traceability
-- (2026-10-22 -- the Exposure Summary / Areas Affected tables now show how
-- many hours each municipality spent under each TCWS level, and Total
-- Exposure = Signal 1 + ... + Signal 5 hours. Payouts read payout_hours,
-- the hours accumulated under the municipality's Max Signal. See
-- ExposureCalculatorService and .claude/MASTER_DEVELOPMENT_CONTEXT.md.)
--
-- Run against any already-provisioned DB (local or remote):
--   psql -U agrisure_admin -d agrisure_db -f backend/migrations/2026-10-22_exposure_signal_hours.sql
-- then recompute every typhoon's exposure under the new rules:
--   python scripts/recompute_exposure.py --apply      (from backend/)
--
-- init_schema.sql has also been updated for fresh installs.
--
-- Duplicates are NOT deleted here: application code already prevents them,
-- so any that exist need a human look. The migration stops and names them.

BEGIN;

DO $$
DECLARE dup_count INT;
BEGIN
    SELECT COUNT(*) INTO dup_count FROM (
        SELECT 1 FROM tbl_tropical_cyclone_bulletins
        GROUP BY typhoon_id, bulletin_count HAVING COUNT(*) > 1
    ) d;
    IF dup_count > 0 THEN
        RAISE EXCEPTION 'tbl_tropical_cyclone_bulletins has % duplicated (typhoon_id, bulletin_count) pair(s); resolve them before re-running. Find them with: SELECT typhoon_id, bulletin_count, array_agg(tcb_id) FROM tbl_tropical_cyclone_bulletins GROUP BY 1, 2 HAVING COUNT(*) > 1;', dup_count;
    END IF;

    SELECT COUNT(*) INTO dup_count FROM (
        SELECT 1 FROM tbl_area_exposure_summary
        GROUP BY typhoon_id, province, municipality HAVING COUNT(*) > 1
    ) d;
    IF dup_count > 0 THEN
        RAISE EXCEPTION 'tbl_area_exposure_summary has % duplicated (typhoon_id, province, municipality) row(s); resolve them before re-running. Find them with: SELECT typhoon_id, province, municipality, array_agg(summary_id) FROM tbl_area_exposure_summary GROUP BY 1, 2, 3 HAVING COUNT(*) > 1;', dup_count;
    END IF;
END $$;

-- ── Bulletins ───────────────────────────────────────────────────────────────
-- raw_text:         the PDF's full extracted text, kept for verification
-- tcws_hash:        sha256 of the parsed TCWS table; a re-scrape with a
--                   different hash is a corrected bulletin (signals replaced)
-- issued_at_parsed: FALSE when "Issued at ..." could not be read and
--                   issued_at holds the ingestion time instead; such
--                   bulletins are left out of exposure timelines
ALTER TABLE tbl_tropical_cyclone_bulletins
    ADD COLUMN IF NOT EXISTS raw_text TEXT,
    ADD COLUMN IF NOT EXISTS tcws_hash CHAR(64),
    ADD COLUMN IF NOT EXISTS issued_at_parsed BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE tbl_tropical_cyclone_bulletins
    DROP CONSTRAINT IF EXISTS uq_tcb_typhoon_bulletin_count;
ALTER TABLE tbl_tropical_cyclone_bulletins
    ADD CONSTRAINT uq_tcb_typhoon_bulletin_count UNIQUE (typhoon_id, bulletin_count);

-- ── Signals ─────────────────────────────────────────────────────────────────
-- source_clause: the PAGASA clause this LGU was resolved from, e.g.
-- "Batanes" (whole province) or "the northern portion of Cagayan (Santa Ana)".
ALTER TABLE tbl_tcb_signals
    ADD COLUMN IF NOT EXISTS source_clause TEXT;

-- Clauses that resolved to no municipality: unknown names, and partial
-- provincial coverage stated without a town list ("the northern portion of
-- Isabela"), which is never expanded to the whole province.
CREATE TABLE IF NOT EXISTS tbl_tcb_unresolved_clauses (
    unresolved_id SERIAL PRIMARY KEY,
    tcb_id INT NOT NULL REFERENCES tbl_tropical_cyclone_bulletins(tcb_id) ON DELETE CASCADE,
    signal_level INT NOT NULL,
    island_group INT NOT NULL,
    clause TEXT NOT NULL,
    reason VARCHAR(40) NOT NULL
        CHECK (reason IN ('no_boundary_match', 'partial_coverage_no_list'))
);
CREATE INDEX IF NOT EXISTS idx_tcb_unresolved_tcb ON tbl_tcb_unresolved_clauses(tcb_id);

-- ── Exposure summary ────────────────────────────────────────────────────────
ALTER TABLE tbl_area_exposure_summary
    ALTER COLUMN total_exposure_hours TYPE NUMERIC(7,2),
    ADD COLUMN IF NOT EXISTS island_group INT,
    ADD COLUMN IF NOT EXISTS signal_1_hours NUMERIC(7,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS signal_2_hours NUMERIC(7,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS signal_3_hours NUMERIC(7,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS signal_4_hours NUMERIC(7,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS signal_5_hours NUMERIC(7,2) NOT NULL DEFAULT 0,
    -- Hours under max_signal_level; what AssessmentService buckets into 6/12/24
    ADD COLUMN IF NOT EXISTS payout_hours NUMERIC(7,2),
    -- The latest bulletin still lists the area: its interval is not counted yet
    ADD COLUMN IF NOT EXISTS has_open_interval BOOLEAN NOT NULL DEFAULT FALSE,
    -- Counted across a gap of more than 12h between consecutive bulletins
    ADD COLUMN IF NOT EXISTS has_long_gap BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE tbl_area_exposure_summary
    DROP CONSTRAINT IF EXISTS ck_exposure_hours_non_negative,
    DROP CONSTRAINT IF EXISTS ck_exposure_total_is_sum,
    DROP CONSTRAINT IF EXISTS uq_exposure_typhoon_area;
ALTER TABLE tbl_area_exposure_summary
    ADD CONSTRAINT ck_exposure_hours_non_negative CHECK (
        signal_1_hours >= 0 AND signal_2_hours >= 0 AND signal_3_hours >= 0
        AND signal_4_hours >= 0 AND signal_5_hours >= 0 AND total_exposure_hours >= 0
        AND (payout_hours IS NULL OR payout_hours >= 0)
    ) NOT VALID,
    -- NOT VALID: rows computed under the old first-to-last-bulletin rule are
    -- exempt until scripts/recompute_exposure.py rewrites them.
    ADD CONSTRAINT ck_exposure_total_is_sum CHECK (
        total_exposure_hours = signal_1_hours + signal_2_hours + signal_3_hours
                               + signal_4_hours + signal_5_hours
    ) NOT VALID,
    ADD CONSTRAINT uq_exposure_typhoon_area UNIQUE (typhoon_id, province, municipality);

-- One row per continuous stretch a municipality spent under one signal level,
-- rebuilt on every recompute -- the audit trail behind the summary's hours.
CREATE TABLE IF NOT EXISTS tbl_exposure_intervals (
    interval_id SERIAL PRIMARY KEY,
    typhoon_id INT NOT NULL REFERENCES tbl_typhoons(typhoon_id) ON DELETE CASCADE,
    province VARCHAR(100) NOT NULL,
    municipality VARCHAR(100) NOT NULL,
    signal_level INT NOT NULL CHECK (signal_level BETWEEN 1 AND 5),
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    start_tcb_id INT REFERENCES tbl_tropical_cyclone_bulletins(tcb_id) ON DELETE SET NULL,
    end_tcb_id INT REFERENCES tbl_tropical_cyclone_bulletins(tcb_id) ON DELETE SET NULL,
    CONSTRAINT ck_exposure_interval_order CHECK (end_time > start_time)
);
CREATE INDEX IF NOT EXISTS idx_exposure_intervals_area
    ON tbl_exposure_intervals(typhoon_id, province, municipality);

COMMIT;
