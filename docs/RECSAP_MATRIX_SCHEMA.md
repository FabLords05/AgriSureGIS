# ReCSAP Matrix Schema (Parametric Lookup Tables)

Text record of the schema change made on 2026-07-21 (see `.claude/FUNCTION_CHANGES.md`,
"Real PCIC Table 11 Data: Recsap Matrix Split Into Two Lookups"). `docs/ERD.drawio.png`
is a static image exported from a `.drawio` source that isn't checked into this repo,
so it can't be regenerated here — this file is the interim text record until whoever
owns the `.drawio` source updates the visual diagram to match.

## Why two tables

The real PCIC data (manuscript "Table 11" damage matrix + Rice Indemnity Factor Table)
is two lookups chained together, not one flat table:

1. `(crop growth stage, wind signal, exposure hours)` -> estimated yield loss %
2. `(crop stage group, yield loss % bracket)` -> indemnity factor (₱, used directly in
   the payout formula `I = (AC / 1000) × IF × Area`)

The two source tables also use different growth-stage taxonomies. Step 1 uses 3 stages
(Booting, Flowering, Maturity). Step 2 uses PCIC's own 5-stage taxonomy (Early
Vegetative, Late Vegetative, Reproductive, Late Reproductive, Maturity). The mapping
between them (confirmed with Fabio, not stated verbatim in the manuscript):

| `tbl_recsap_matrix.crop_stage_no` | Stage 1 name | -> | `tbl_indemnity_factor_matrix.crop_stage_group` |
|---|---|---|---|
| 1 | Booting | -> | Late Vegetative |
| 2 | Flowering | -> | Reproductive |
| 3 | Maturity | -> | Maturity |

## `tbl_recsap_matrix` (step 1: yield loss %)

| Column | Type | Notes |
|---|---|---|
| `matrix_id` | `SERIAL PRIMARY KEY` | |
| `crop_stage_no` | `INT NOT NULL` | 1=Booting, 2=Flowering, 3=Maturity |
| `wind_signal_tcws` | `INT NOT NULL` | PAGASA TCWS level, 2-5 |
| `exposure_hours` | `INT NOT NULL` | Bucketed to 6/12/24 by `indemnity_calc._bucket_exposure_hours()` |
| `estimated_yield_loss` | `NUMERIC(5,2) NOT NULL` | Percent |
| `is_active` | `BOOLEAN NOT NULL DEFAULT TRUE` | |

Previously also held `indemnity_factor NUMERIC(5,4)` directly on this table — removed;
that precision couldn't hold real values like 392.00 or 560.00 anyway (max was 9.9999).

## `tbl_indemnity_factor_matrix` (step 2: indemnity factor) — new table

| Column | Type | Notes |
|---|---|---|
| `indemnity_id` | `SERIAL PRIMARY KEY` | |
| `crop_stage_group` | `VARCHAR(30) NOT NULL` | PCIC's 5-stage taxonomy (see mapping above) |
| `yield_loss_min` | `NUMERIC(5,2) NOT NULL` | Bracket lower bound, exclusive |
| `yield_loss_max` | `NUMERIC(5,2) NOT NULL` | Bracket upper bound, inclusive |
| `indemnity_factor` | `NUMERIC(7,2) NOT NULL` | ₱-scale multiplier, not 0-1 |
| `is_active` | `BOOLEAN NOT NULL DEFAULT TRUE` | |

Matched as `estimated_yield_loss > yield_loss_min AND estimated_yield_loss <= yield_loss_max`,
i.e. the source table's ">10 to 15" style bracket labels.

All 5 stage groups are seeded (25 rows total: 5 brackets × 5 groups) for fidelity to
the source table, though only the 3 reachable via the mapping above (Late Vegetative,
Reproductive, Maturity) are ever queried by the current app — Early Vegetative and
Late Reproductive sit unused until crop-stage tracking covers those stages.

## `tbl_risk_assessment` (consumer, changed columns only)

| Column | Type | Notes |
|---|---|---|
| `matrix_id` | `INT REFERENCES tbl_recsap_matrix(matrix_id) ON DELETE SET NULL` | Unchanged |
| `indemnity_matrix_id` | `INT REFERENCES tbl_indemnity_factor_matrix(indemnity_id) ON DELETE SET NULL` | New |
| `indemnity_factor` | `NUMERIC(7,2)` | Widened from `NUMERIC(5,4)` to match |

## Full source data (as seeded in `backend/init_schema.sql`)

### Step 1 — yield loss % by stage / wind signal / exposure hours

Signal 4 (118-184 KPH) and signal 5 (>184 KPH) share identical values in the source
table, so both are seeded identically.

| Wind Signal | Stage | 6h | 12h | 24h |
|---|---|---|---|---|
| 2 (62-88 KPH) | Booting | 10 | 15 | 20 |
| 2 (62-88 KPH) | Flowering | 15 | 20 | 25 |
| 2 (62-88 KPH) | Maturity | *<10 (omitted)* | 10 | 15 |
| 3 (89-117 KPH) | Booting | 15 | 20 | 25 |
| 3 (89-117 KPH) | Flowering | 20 | 25 | 30 |
| 3 (89-117 KPH) | Maturity | 10 | 15 | 20 |
| 4 (118-184 KPH) | Booting | 20 | 25 | 30 |
| 4 (118-184 KPH) | Flowering | 25 | 30 | 35 |
| 4 (118-184 KPH) | Maturity | 15 | 20 | 25 |
| 5 (>184 KPH) | Booting | 20 | 25 | 30 |
| 5 (>184 KPH) | Flowering | 25 | 30 | 35 |
| 5 (>184 KPH) | Maturity | 15 | 20 | 25 |

### Step 2 — indemnity factor (₱) by yield loss % bracket / stage group

| Yield Loss % | Early Vegetative | Late Vegetative | Reproductive | Late Reproductive | Maturity |
|---|---|---|---|---|---|
| >10 to 15 | 146 | 170 | 194 | 218 | 243 |
| >15 to 20 | 198 | 231 | 264 | 297 | 330 |
| >20 to 25 | 248 | 289 | 330 | 372 | 413 |
| >25 to 30 | 294 | 343 | 392 | 441 | 490 |
| >30 to 35 | 336 | 392 | 448 | 504 | 560 |
