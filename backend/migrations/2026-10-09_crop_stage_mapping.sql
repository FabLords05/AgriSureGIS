-- Migration: tbl_crop_stage_mapping + tbl_risk_assessment.stage_group
-- (Fabio, 2026-10-09 -- the client's newer PABS/GPX export
-- ("PCIC10 GPX 11-05-2025 WITH EXISTING IC AFFECTED BY TY.csv", 42 columns) could
-- not be ingested: it carries the crop stage as free text ("Dough Stage") where the
-- legacy export carries an integer "Stage No.". Investigating that surfaced a live
-- bug in the legacy path too -- "Stage No." is PCIC's own 0-9 agronomic code, but it
-- was being written straight into tbl_risk_assessment.crop_stage_no, which
-- AssessmentService reads as the Table 11 scale (1=Booting, 2=Flowering,
-- 3=Maturity). On the legacy file that meant 41 of 100 rows passed the eligibility
-- gate while every one of them was mis-staged, and the genuinely eligible rows
-- (code 4 = Booting, code 7 = Dough) were dropped. This table is the translation
-- layer for both vocabularies.)
--
-- NOTE: Fabio is resetting his own development database rather than migrating it,
-- so this file exists for the OTHER already-provisioned instances (e.g. Cristian's
-- Tailscale-hosted backend) that are not being wiped. It is written to be safely
-- re-runnable.
--
-- Run against any already-provisioned DB:
--   psql -U agrisure_admin -d agrisure_db -f backend/migrations/2026-10-09_crop_stage_mapping.sql
--
-- init_schema.sql has also been updated to create and seed this directly for fresh
-- installs. Existing tbl_risk_assessment rows keep whatever crop_stage_no they were
-- given before and get a NULL stage_group; re-ingesting their CSV restates them
-- correctly. stage_group NULL falls back to indemnity_calc's
-- CROP_STAGE_TO_INDEMNITY_GROUP, so nothing breaks in the meantime.

CREATE TABLE IF NOT EXISTS tbl_crop_stage_mapping (
    mapping_id SERIAL PRIMARY KEY,
    -- Exactly one of these two is populated per row: source_code keys the legacy
    -- export's integer "Stage No.", source_label keys the newer export's lowercased
    -- "Stage of Crop" text.
    source_code INT,
    source_label VARCHAR(80),
    pcic_stage VARCHAR(20) NOT NULL,
    crop_stage_no INT,
    stage_group VARCHAR(30),
    notes TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT ck_crop_stage_mapping_one_key CHECK (
        (source_code IS NOT NULL AND source_label IS NULL)
        OR (source_code IS NULL AND source_label IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_crop_stage_mapping_source_code
    ON tbl_crop_stage_mapping (source_code) WHERE is_active AND source_code IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_crop_stage_mapping_source_label
    ON tbl_crop_stage_mapping (source_label) WHERE is_active AND source_label IS NOT NULL;

ALTER TABLE tbl_risk_assessment
    ADD COLUMN IF NOT EXISTS stage_group VARCHAR(30);

-- Seed. ON CONFLICT DO NOTHING against the two partial unique indexes makes a
-- re-run a no-op rather than a duplicate-key error. See init_schema.sql's seed
-- comment for where the group assignment comes from (RECSAP-From-IRR.pptx Tables 1
-- and 7a/7b, plus the legacy export's own parenthetical labels).
INSERT INTO tbl_crop_stage_mapping (source_code, source_label, pcic_stage, crop_stage_no, stage_group, notes) VALUES
-- Legacy export, "Stage No." (PCIC agronomic code).
(0, NULL, 'S/T',  NULL, 'Early Vegetative',  'Table 11 Note 1: no immediate direct wind damage.'),
(1, NULL, 'MnTl', NULL, 'Early Vegetative',  'Table 11 Note 1: no immediate direct wind damage.'),
(2, NULL, 'MxTl', NULL, 'Late Vegetative',   'Table 11 Note 1: no immediate direct wind damage.'),
(3, NULL, 'PI',   NULL, 'Reproductive',      'Table 11 Note 1: no immediate direct wind damage.'),
(4, NULL, 'BS',   1,    'Reproductive',      'Table 11 BOOTING row.'),
(5, NULL, 'FS',   2,    'Reproductive',      'Table 11 FLOWERING row.'),
(6, NULL, 'MS',   2,    'Late Reproductive', 'Table 11 FLOWERING row -- PCIC pairs FS/MS as one unit in Tables 9 and 10 -- but the Table 1 group is Late Reproductive.'),
(7, NULL, 'SD',   3,    'Maturity',          'Table 11 MATURITY row.'),
(8, NULL, 'HD',   3,    'Maturity',          'Table 11 MATURITY row.'),
(9, NULL, 'YR',   3,    'Maturity',          'Table 11 MATURITY row.'),
-- Newer PABS/GPX export, "Stage of Crop" (free text, stored lowercased).
(NULL, 'vegetative/tillering',       'MnTl/MxTl', NULL, 'Early Vegetative',  'Table 11 Note 1: no immediate direct wind damage.'),
(NULL, 'panicle initiation/booting', 'PI/BS',     NULL, NULL,                'ON HOLD (Fabio, 2026-10-09): merges PI (no wind damage per Table 11 Note 1) with BS (eligible, crop_stage_no 1), and no PCIC document gives a days-after-transplanting threshold to separate them. Rows ingest but are never assessed. To enable: set crop_stage_no=1, stage_group=''Reproductive'' once PCIC supplies the days-per-stage table.'),
(NULL, 'flowering',                  'FS',        2,    'Reproductive',      'Table 11 FLOWERING row.'),
(NULL, 'milking stage',              'MS',        2,    'Late Reproductive', 'Table 11 FLOWERING row via PCIC''s FS/MS pairing; the Table 1 group is Late Reproductive.'),
(NULL, 'dough stage',                'SD/HD',     3,    'Maturity',          'Table 11 MATURITY row.'),
(NULL, 'yellow ripening',            'YR',        3,    'Maturity',          'Table 11 MATURITY row.'),
(NULL, 'harvested',                  'Harvested', NULL, NULL,                'No standing crop at typhoon occurrence -- nothing to assess.')
ON CONFLICT DO NOTHING;
