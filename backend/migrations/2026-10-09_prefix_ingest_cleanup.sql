-- Migration: remove the shadow insurance records left by the pre-"FARMER NAME" ingest
-- (Fabio, 2026-10-09 -- farmer names rendered as blank cells in Spatial Analysis ->
-- Farm Records for every farm from "PCIC10 GPX 11-05-2025 WITH EXISTING IC AFFECTED
-- BY TY.csv". Root cause chain:
--
--   1. That CSV was uploaded once BEFORE commit 9547564. At the time,
--      prepare_row_payload() had no "FARMER NAME" / "CIC NO" / "AREA" aliases, and
--      tbl_farmers_profile.last_name/first_name are NOT NULL -- so the `or ""`
--      fallback stored EMPTY STRINGS instead of failing. Nothing errored. The same
--      missing aliases also stored policy_no = '', area_size = 0, amount_cover = 0.
--   2. _ingest_row() resolved an existing farmer/farm purely as a lookup and
--      discarded the parsed values, so re-uploading the corrected file matched those
--      broken rows by farmers_id and changed nothing. (Fixed in app/api/upload.py by
--      _backfill_blank_fields() -- re-upload now repairs blanks in place.)
--   3. The duplicate guard is (policy_no, farm_id). The pre-fix rows hold
--      policy_no = '' while the re-upload supplied the real 'CIC NO', so the guard
--      did not match and a SECOND tbl_insurance_records row was inserted per farm,
--      each with its own tbl_risk_assessment seed.
--
-- This file cleans up (3). (1) and (2) are repaired by re-uploading the CSV once the
-- code fix is deployed -- which is why the farms and farmers are deliberately NOT
-- deleted here.)
--
-- Run against any DB that received the pre-fix upload:
--   psql -U agrisure_admin -d agrisure_db -f backend/migrations/2026-10-09_prefix_ingest_cleanup.sql
--
-- Safe to re-run: the second pass simply reports 0 rows and deletes nothing.
--
-- WHY `policy_no = ''` IS A SAFE FINGERPRINT: nothing else in the system writes a
-- blank policy number. seed_database.py inserts the real values from the legacy
-- export, seed_active_insurance.py prefixes its synthetic rows with 'POL-SEED-',
-- and app/api/upload.py only ever produces '' when the source CSV had no
-- recognizable policy-number column at all -- i.e. exactly the pre-fix run.

\echo ''
\echo '=== DIAGNOSTIC (read-only) -- confirm these counts before the delete below ==='
\echo ''

-- Expected on Fabio's DB: ~1,100 (one per farm in the pre-fix upload).
SELECT 'insurance records with blank policy_no (TO BE DELETED)' AS check_name,
       COUNT(*) AS row_count
  FROM tbl_insurance_records
 WHERE policy_no = '';

-- Cascades away with the delete below (tbl_risk_assessment.insurance_records_id is
-- ON DELETE CASCADE, see init_schema.sql) -- listed so the number is not a surprise.
SELECT 'crop-stage seeds hanging off those records (CASCADE)' AS check_name,
       COUNT(*) AS row_count
  FROM tbl_risk_assessment ra
  JOIN tbl_insurance_records ir USING (insurance_records_id)
 WHERE ir.policy_no = '';

-- Sanity check: these are the GOOD records from the post-fix upload. This number
-- must NOT change. If it is 0, the corrected CSV was never re-uploaded and you
-- should re-upload it rather than run the delete.
SELECT 'insurance records with a real policy_no (KEPT)' AS check_name,
       COUNT(*) AS row_count
  FROM tbl_insurance_records
 WHERE policy_no <> '';

-- Repaired by re-uploading the CSV after the code fix, NOT by this migration.
SELECT 'farmers with no name on file (fixed by re-upload)' AS check_name,
       COUNT(*) AS row_count
  FROM tbl_farmers_profile
 WHERE COALESCE(TRIM(last_name), '') = ''
   AND COALESCE(TRIM(first_name), '') = '';

SELECT 'farms with area_size = 0 (fixed by re-upload)' AS check_name,
       COUNT(*) AS row_count
  FROM tbl_farms
 WHERE area_size IS NULL OR area_size = 0;

\echo ''
\echo '=== DELETE ==='
\echo ''

BEGIN;

-- One statement is enough: both child tables reference
-- tbl_insurance_records(insurance_records_id) ON DELETE CASCADE, so the
-- tbl_risk_assessment crop-stage seeds and any tbl_insurance_usage rows go with
-- these automatically (init_schema.sql:189 and :229).
DELETE FROM tbl_insurance_records
 WHERE policy_no = '';

COMMIT;

\echo ''
\echo '=== VERIFY -- blank-policy count must now be 0 ==='
\echo ''

SELECT 'insurance records with blank policy_no (expect 0)' AS check_name,
       COUNT(*) AS row_count
  FROM tbl_insurance_records
 WHERE policy_no = '';

-- Orphan check: no crop-stage seed should be left without its parent record.
SELECT 'orphaned crop-stage seeds (expect 0)' AS check_name,
       COUNT(*) AS row_count
  FROM tbl_risk_assessment ra
 WHERE ra.insurance_records_id IS NOT NULL
   AND NOT EXISTS (
           SELECT 1 FROM tbl_insurance_records ir
            WHERE ir.insurance_records_id = ra.insurance_records_id
       );

\echo ''
\echo 'Next step: re-upload the CSV through the UI. That is what repairs the blank'
\echo 'farmer names and the area_size = 0 farms (via _backfill_blank_fields in'
\echo 'app/api/upload.py). Re-running this migration afterwards should report 0.'
\echo ''
