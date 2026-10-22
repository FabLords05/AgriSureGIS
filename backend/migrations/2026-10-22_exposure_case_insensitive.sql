-- Migration: one exposure summary per municipality regardless of letter case
-- (2026-10-22 -- the CSV import used to create missing barangays in the CSV's
-- ALL CAPS, e.g. 'CAGAYAN / PAMPLONA' next to the seeded 'Cagayan / Pamplona'.
-- The old exposure calculator then stored a second summary for the same town,
-- which uq_exposure_typhoon_area allowed because it is case-sensitive, and
-- later recomputes never touched it. Found in agrisure_db for Pamplona, Piat,
-- Quezon and Bayombong across 6 typhoons.)
--
-- Run AFTER recomputing exposure with the fixed calculator, which retires the
-- duplicate summaries:
--   python scripts/recompute_exposure.py --apply      (from backend/)
--   psql -U agrisure_admin -d agrisure_db -f backend/migrations/2026-10-22_exposure_case_insensitive.sql
--
-- init_schema.sql has also been updated for fresh installs.
--
-- Duplicates are NOT deleted here. If any remain, the migration stops and
-- names them, and nothing below is applied.

BEGIN;

DO $$
DECLARE dup_count INT;
BEGIN
    SELECT COUNT(*) INTO dup_count FROM (
        SELECT 1 FROM tbl_area_exposure_summary
        GROUP BY typhoon_id, lower(province), lower(municipality) HAVING COUNT(*) > 1
    ) d;
    IF dup_count > 0 THEN
        RAISE EXCEPTION 'tbl_area_exposure_summary has % municipality row(s) duplicated in a different letter case; run scripts/recompute_exposure.py --apply first. Find them with: SELECT typhoon_id, lower(province), lower(municipality), array_agg(summary_id) FROM tbl_area_exposure_summary GROUP BY 1, 2, 3 HAVING COUNT(*) > 1;', dup_count;
    END IF;
END $$;

-- Boundaries: give every barangay of a municipality the spelling its oldest
-- (seeded) barangay uses. Only rows whose municipality already exists under
-- another casing change; barangay names and PSGC codes are left as they are.
UPDATE tbl_admin_boundaries b
SET province = c.province, municipality = c.municipality
FROM (
    SELECT DISTINCT ON (upper(province), upper(municipality))
           upper(province) AS up_province, upper(municipality) AS up_municipality, province, municipality
    FROM tbl_admin_boundaries
    ORDER BY upper(province), upper(municipality), boundary_id
) c
WHERE upper(b.province) = c.up_province
  AND upper(b.municipality) = c.up_municipality
  AND (b.province <> c.province OR b.municipality <> c.municipality);

ALTER TABLE tbl_area_exposure_summary DROP CONSTRAINT IF EXISTS uq_exposure_typhoon_area;
CREATE UNIQUE INDEX IF NOT EXISTS uq_exposure_typhoon_area_ci
    ON tbl_area_exposure_summary (typhoon_id, lower(province), lower(municipality));

COMMIT;
