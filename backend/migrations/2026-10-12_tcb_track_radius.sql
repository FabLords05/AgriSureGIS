-- Migration: tbl_tropical_cyclone_bulletins wind radius + forecast track
-- (Cristian, 2026-10-12 -- the Spatial Analysis map's new "Typhoon track
-- overlay" draws every bulletin center of a typhoon, the wind circulation
-- radius around each one, and the latest bulletin's forecast path.
-- center_geom was already stored; the wind extent and the Track and
-- Intensity Outlook table were read from the PDF but never saved.)
--
-- Run against any already-provisioned DB (local or remote):
--   psql -U agrisure_admin -d agrisure_db -f backend/migrations/2026-10-12_tcb_track_radius.sql
--
-- init_schema.sql has also been updated to create the columns directly for
-- future fresh installs. All three stay NULL for bulletins saved before
-- this migration until their PDF is scraped or re-uploaded again (see
-- BulletinParserService.save_bulletin_to_db) -- the observed track still
-- draws for them from center_geom, just without radius circles.
--
-- wind_radius_km:        "Strong to gale-force winds extend outwards up to N km"
--                        (area with at least strong winds, >= 39 km/h)
-- storm_force_radius_km: "Storm-force winds extend outwards up to N km"
--                        (area with at least storm-force winds, >= 89 km/h);
--                        NULL when the bulletin doesn't state it
-- forecast_track:        [{"label", "lat", "lon", "location"}, ...] in table order

ALTER TABLE tbl_tropical_cyclone_bulletins
    ADD COLUMN IF NOT EXISTS wind_radius_km INT,
    ADD COLUMN IF NOT EXISTS storm_force_radius_km INT,
    ADD COLUMN IF NOT EXISTS forecast_track JSONB;
