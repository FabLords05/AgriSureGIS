-- Migration: tbl_tropical_cyclone_bulletins.max_signal_level + tcws_areas
-- (Fabio, 2026-09-30 -- the TCB viewer showed "No Signal Data" and an empty
-- "Areas Under Signal Warning" for every real bulletin. The signal number was
-- derived only from tbl_tcb_signals rows, and bulletin_parser.py only writes
-- a row when a TCWS area resolves to an AdminBoundary province+municipality
-- -- so any area outside the loaded boundaries (all of Luzon/Visayas, at the
-- time) was dropped entirely, taking the bulletin's signal number with it.
-- These columns keep PAGASA's own TCWS table exactly as parsed, with no
-- boundary validation, purely for display. tbl_tcb_signals and exposure
-- calculation are unchanged.)
--
-- Run against any already-provisioned DB (local or remote):
--   psql -U agrisure_admin -d agrisure_db -f backend/migrations/2026-09-30_tcb_raw_tcws.sql
--
-- init_schema.sql has also been updated to create the columns directly for
-- future fresh installs. Nullable: existing bulletins are left NULL and get
-- backfilled the next time their PDF is scraped or re-uploaded (see
-- BulletinParserService.save_bulletin_to_db).

ALTER TABLE tbl_tropical_cyclone_bulletins
    ADD COLUMN IF NOT EXISTS max_signal_level INT,
    ADD COLUMN IF NOT EXISTS tcws_areas JSONB;
