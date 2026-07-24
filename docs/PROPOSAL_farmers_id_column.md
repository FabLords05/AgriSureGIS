# Proposal: Add `farmers_id` (PABS-Native Farmer ID) to `tbl_farmers_profile`

**Status:** Proposal for Fabio's review — nothing in this document has been applied to the schema. Per `CLAUDE.md`, any database structure modification must be proposed to Fabio and approved before implementation.

## Problem
Real PABS CSV exports (`docs/Rice Risk Exposure Region X 04-15-2026.csv`, 23,917 rows) carry a `FarmersID` column: a stable, PABS-internal per-farmer identifier, distinct from `RSBSA No.` (the government RSBSA registry number). Empirically, across the full real export:
- `FarmersID` is populated on **100%** of rows (0 blank).
- `RSBSA No.` is blank on **28.7%** of rows (6,862 of 23,917) — common for non-RSBSA program types (`APCP`, `AGRISENSO PROGRAM`, `ACEF PROGRAM`, etc., all present in the same export).

`tbl_farmers_profile` has no field to store `FarmersID` today. This forces CSV ingestion (`backend/app/api/upload.py`'s `upload_csv()`) to key farmer-identity matching on `rsbsa_no` alone, which cannot deduplicate the ~28.7% of rows with a blank RSBSA number — without a fix, every farmer whose RSBSA No. is blank would collapse onto whichever single blank-RSBSA farmer profile was created first. This same `FarmersID` also shows up as the first numeric ID in GPX boundary-walk filenames (e.g. `TAB_ABAO , JONEL  J._120961_1148107_2024-08-06.gpx`), making it the natural key for automatically matching an uploaded GPX file to a farmer.

The manuscript's data dictionary (p.37, verified directly) specifies only `farmer_id`, `rsbsa_no` (UNIQUE, NULLABLE), `lastname`, `firstname`, `middlename`, `created_at`, `updated_at` for `tbl_farmers_profile` — no PABS-native ID field. This is a gap the manuscript didn't anticipate, not a contradiction of it.

## Proposed change
Add `tbl_farmers_profile.farmers_id` — `VARCHAR(20)`, `UNIQUE`, nullable — holding PABS's own per-farmer numeric ID, stored as text (not integer), consistent with how this codebase already stores other PABS-native identifiers that happen to look numeric (e.g. `tbl_farms.csv_farm_reference VARCHAR(50)` for the `FARMID` column) — this avoids any risk from a hypothetical future leading-zero ID.

- **Nullable:** Yes — legacy data (seeded via `backend/seed_database.py` from `backend/pabs_results.csv`, which has no `FarmersID` column) will never have this backfilled and must not be blocked.
- **Unique:** Yes — one real-world farmer maps to exactly one `farmers_id`, mirroring the existing `rsbsa_no UNIQUE` pattern.
- **Index:** No separate `CREATE INDEX` needed — `UNIQUE` already creates its own backing B-tree index.
- **Matching precedence:** Prefer `farmers_id` over `rsbsa_no` when both are available — `farmers_id` has 100% coverage in the real export vs. `rsbsa_no`'s 71.3%, making it the more reliable key. `rsbsa_no` remains the fallback for legacy-seeded rows that predate this column. See `backend/app/api/upload.py`'s get-or-create logic and the new `backend/app/services/gpx_farmer_matcher.py`.

### `init_schema.sql` diff
```sql
 CREATE TABLE tbl_farmers_profile (
     farmer_id SERIAL PRIMARY KEY,
+    farmers_id VARCHAR(20) UNIQUE,
     rsbsa_no VARCHAR(50) UNIQUE,
     last_name VARCHAR(100) NOT NULL,
     first_name VARCHAR(100) NOT NULL,
     middle_name VARCHAR(100),
     created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
     updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
 );
```

### `backend/app/models/models.py` diff
```python
 class FarmerProfile(Base):
     __tablename__ = "tbl_farmers_profile"

     farmer_id = Column(Integer, primary_key=True, index=True)
+    farmers_id = Column(String(20), unique=True)
-    rsbsa_no = Column(String(50), unique=True, nullable=False)
+    rsbsa_no = Column(String(50), unique=True)
     last_name = Column(String(50), nullable=False)
     first_name = Column(String(50), nullable=False)
     middle_name = Column(String(50))
     created_at = Column(DateTime, server_default=func.now())
```
(The `rsbsa_no` nullability fix corrects a pre-existing model/DDL drift: the live DDL above and the manuscript's own dictionary, p.37 ["UNIQUE, NULLABLE"], already treat `rsbsa_no` as nullable — only the SQLAlchemy model incorrectly said `nullable=False`. This is a Python-metadata-only correction; it does not change the live database, which is already nullable. Bundled here because the CSV-ingestion fix needs to insert genuine `NULL` `rsbsa_no` for the ~28.7% blank-RSBSA rows, and the model should stop contradicting reality.)

## What this unblocks
- Correct farmer deduplication in `upload_csv()` for the ~28.7% of real rows with blank `RSBSA No.`
- Filename-based farmer matching for GPX boundary uploads (`backend/app/services/gpx_farmer_matcher.py`).

## What this does NOT include
- No backfill of `farmers_id` for existing/legacy rows — no source data exists to backfill it from.
- No change to `rsbsa_no`'s role as the official registry number — `farmers_id` is additive, not a replacement.

## Files that need updating (already applied in code alongside this proposal, per Fabio's approval of the concept — see `.claude/FUNCTION_CHANGES.md`)
- `backend/init_schema.sql` — column added (not yet applied to any live database — that step is yours to run).
- `backend/app/models/models.py` — column + `rsbsa_no` nullability fix added.
- `backend/app/api/upload.py` — farmer get-or-create logic now prefers `farmers_id`.
- `backend/app/services/gpx_farmer_matcher.py` (new) — matches a GPX filename's first numeric ID against this column.

## Action needed from Fabio
The code changes above are already written and committed, but **the live database does not have this column until you apply it**. Any `farmers_id`-matching code path will raise `UndefinedColumn` against a live DB until then. Apply via your usual schema-update process (e.g. re-running `init_schema.sql`, or an `ALTER TABLE tbl_farmers_profile ADD COLUMN farmers_id VARCHAR(20) UNIQUE;` if you'd rather not re-run the full idempotent script against a populated database).
