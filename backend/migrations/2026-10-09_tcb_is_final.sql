-- Migration: tbl_tropical_cyclone_bulletins.is_final
-- (Cristian, 2026-10-09 -- the Monitoring & Extraction "TCBs Downloaded" card
-- now shows a "ready for assessment" notice once a typhoon's final bulletin
-- arrives. bulletin_parser.py already detected the final bulletin (PAGASA's
-- trailing "F" on the bulletin number, e.g. "NR. 14F", or a "Low Pressure
-- Area (formerly ...)" bulletin) but only used it in-memory to trigger
-- assessment -- it was never stored, and the saved title drops the "F", so
-- the frontend had no way to tell which bulletin was final.)
--
-- Run against any already-provisioned DB (local or remote):
--   psql -U agrisure_admin -d agrisure_db -f backend/migrations/2026-10-09_tcb_is_final.sql
--
-- init_schema.sql has also been updated to create the column directly for
-- future fresh installs. Existing LPA bulletins are backfilled below (always
-- final, same rule the parser applies); any other already-saved final
-- bulletin gets flagged the next time its PDF is scraped or re-uploaded (see
-- BulletinParserService.save_bulletin_to_db).

ALTER TABLE tbl_tropical_cyclone_bulletins
    ADD COLUMN IF NOT EXISTS is_final BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE tbl_tropical_cyclone_bulletins
SET is_final = TRUE
WHERE category = 'Low Pressure Area' AND is_final = FALSE;
