# Proposal: Add `tbl_parser_settings` for a Live-Configurable TCB Polling Interval

**Status:** Proposal for Fabio's review — nothing in this document has been applied to the schema. Per `.claude/GITHUB_WORKFLOW.md` ("Any database structure modifications must be proposed to Fabio specifically"), this schema change needs approval before `init_schema.sql`'s new table is applied to a live database.

## Problem
TCB (Tropical Cyclone Bulletin) ingestion is being automated: instead of a GIS specialist manually clicking "Parse Latest Bulletin," a background job will periodically scrape/parse/save new PAGASA bulletins on its own (see `.claude/FUNCTION_CHANGES.md` for the full change once implemented). The frontend's Calibration & Settings screen already has a "TCB Polling Interval (hours)" input (`frontend/src/app/components/CalibrationModule.tsx:74,409-415`, range 1-24h) — today it's pure local `useState`, not backed by anything real.

For the specialist's chosen interval to actually control the running background job (and survive a backend restart), it needs to be persisted somewhere. No existing table is a fit — this is an application/operational setting, not a domain entity from the ERD (farmers, farms, policies, bulletins, etc.).

## Proposed change
Add a new single-row table, `tbl_parser_settings`, holding just the polling interval:

- **Single-row:** the application enforces "exactly one row" by always querying `.first()` and creating a default row (`polling_interval_hours = 3`) if none exists — no `CHECK`/trigger needed to enforce this at the DB level, since nothing else ever inserts into this table.
- **`polling_interval_hours` (`INT`, default `3`):** matches the frontend's current default state (`CalibrationModule.tsx:74`, `useState(3)`) and its `min={1} max={24}` bounds (enforced at the API layer via Pydantic, not a DB `CHECK` constraint, consistent with how this codebase validates elsewhere).
- **`updated_at`:** for visibility into when the interval was last changed, same pattern as `tbl_system_users.created_at` (`server_default=func.now()`).

### `init_schema.sql` diff
```sql
+CREATE TABLE tbl_parser_settings (
+    setting_id SERIAL PRIMARY KEY,
+    polling_interval_hours INT NOT NULL DEFAULT 3,
+    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
+);
+
+INSERT INTO tbl_parser_settings (polling_interval_hours) VALUES (3);
```
(Also add `DROP TABLE IF EXISTS tbl_parser_settings CASCADE;` alongside this script's other drops, since the script is fully idempotent/destructive-and-recreate today.)

### `backend/app/models/models.py` diff
```python
+class ParserSettings(Base):
+    __tablename__ = "tbl_parser_settings"
+
+    setting_id = Column(Integer, primary_key=True, index=True)
+    polling_interval_hours = Column(Integer, nullable=False, default=3)
+    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
```

## What this unblocks
- A real `GET/PUT /api/bulletins/settings` endpoint pair so the Calibration screen's polling-interval field reads/writes an actual persisted value instead of being a disconnected mock.
- Live rescheduling of the in-process APScheduler job that drives automated PAGASA scraping, without restarting the backend.

## What this does NOT include
- No email/SMTP settings, no notification-preference settings — this table holds only the polling interval. Broader "settings" (session timeout, GEE API key, auto-backup, etc., all still mock in `CalibrationModule.tsx`) are out of scope here.
- No historical log of interval changes — `updated_at` reflects only the most recent change, not an audit trail.

## Files that need updating (already applied in code alongside this proposal, per the approach agreed with Fabio — see `.claude/FUNCTION_CHANGES.md`)
- `backend/init_schema.sql` — table + seed row added (not yet applied to any live database — that step is yours to run).
- `backend/app/models/models.py` — `ParserSettings` model added.
- `backend/app/api/bulletins.py` — `GET/PUT /api/bulletins/settings` added, backed by this table.
- `backend/app/core/scheduler.py` (new) — reads the initial interval from this table at startup.

## Action needed from Fabio
The code changes are already written and committed, but **the live database does not have this table until you apply it**. The new settings endpoints (and the scheduler's startup read) will raise `UndefinedTable` against a live DB until then. Apply via your usual schema-update process — re-running `init_schema.sql` is simplest since this is a brand-new table with no data to preserve elsewhere in it, but if you'd rather not re-run the full idempotent script against a populated database, the equivalent is:
```sql
CREATE TABLE tbl_parser_settings (
    setting_id SERIAL PRIMARY KEY,
    polling_interval_hours INT NOT NULL DEFAULT 3,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO tbl_parser_settings (polling_interval_hours) VALUES (3);
```
