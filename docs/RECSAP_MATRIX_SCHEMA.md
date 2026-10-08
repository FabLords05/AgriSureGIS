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
Vegetative, Late Vegetative, Reproductive, Late Reproductive, Maturity).

**Superseded 2026-10-09.** The group is no longer derived from `crop_stage_no` at all.
The two are genuinely not a function of one another: Milking and Flowering both resolve
to `crop_stage_no` 2 (PCIC pairs `FS/MS` as a single unit in Tables 9 and 10) while
Table 1 keeps them in different groups. Both values are now resolved independently from
`tbl_crop_stage_mapping` and persisted on `tbl_risk_assessment.stage_group`; see the
step 0 section below. `indemnity_calc.CROP_STAGE_TO_INDEMNITY_GROUP` survives only as a
fallback for a row carrying no `stage_group`, and its Booting entry changed with the
rest:

| `tbl_recsap_matrix.crop_stage_no` | Stage 1 name | -> | fallback `crop_stage_group` |
|---|---|---|---|
| 1 | Booting | -> | Reproductive *(was Late Vegetative)* |
| 2 | Flowering | -> | Reproductive |
| 3 | Maturity | -> | Maturity |

## Step 0 — source crop stage -> (`crop_stage_no`, `stage_group`)

`tbl_crop_stage_mapping` (added 2026-10-09) translates whichever vocabulary a given
PCIC CSV export uses. Two exports, two vocabularies:

* the legacy export carries `Stage No.`, PCIC's own 0-9 agronomic code -- 0 = S/T, then
  the sequence printed as the Table 7a/7b column headers:
  `MnTl | MxTl | PI | BS | FS | MS | SD | HD | YR`;
* the newer PABS/GPX export carries `Stage of Crop` as free text only.

Before this table existed, `Stage No.` was written straight into `crop_stage_no`, which
`AssessmentService` reads as the Table 11 scale -- so code 1 (Maximum Tillering) was
assessed as Booting, while code 4 (the real Booting) fell outside `{1,2,3}` and was
dropped entirely.

The 5-group assignment is read off the legacy export's own parenthetical labels
("4 - Booting Stg. (REPRODUCTIVE)", "6 - Milking Stg. (LATE REPRODUCTIVE)",
"7 - Dough Stg. (MATURITY)"), which land on Table 1's five group names exactly, leaving
none unassigned:

| PCIC stage | `crop_stage_no` | `stage_group` |
|---|---|---|
| S/T, MnTl | — | Early Vegetative |
| MxTl | — | Late Vegetative |
| PI | — | Reproductive |
| BS | 1 | Reproductive |
| FS | 2 | Reproductive |
| MS | 2 | Late Reproductive |
| SD, HD, YR | 3 | Maturity |

`crop_stage_no` NULL means the row ingests but is never assessed. Three reasons occur:
Table 11's Note 1 ("MnTl,MxTl,PI stages - No immediate direct damage"), a harvested
crop, and the newer export's merged `Panicle Initiation/Booting` label.

That last one is **deliberately left unmapped**: it joins a no-damage stage (PI) to an
eligible one (BS), and no PCIC document supplies a days-after-transplanting threshold to
separate them. It is 176 of the 1,114 rows in the real file. Enabling it once PCIC
supplies that table is a single `UPDATE` setting `crop_stage_no = 1` and
`stage_group = 'Reproductive'` on that row -- no code change.

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
