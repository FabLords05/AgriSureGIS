# AgriSureGIS — Typhoon Simulation

Everything needed to put a typhoon into the system and exercise the full
pipeline — bulletin ingestion → wind-signal matching → exposure → assessment →
notification — without waiting for a live PAGASA storm.

All data here is **real**: Typhoon OPONG's 23 actual PAGASA bulletins. The old
fictional storms (MARISOL, ALBRITCH) and their invented farmer CSV/GPX data
were deleted on 2026-10-13 — recover them from git history if ever needed.

## Contents

| Path | What it is |
|---|---|
| `tcb_opong/` | OPONG's 23 real PAGASA bulletin PDFs (`TCB#1_opong.pdf` … `TCB#23_opong.pdf`, NR. 23F final). Public PAGASA documents, committed on purpose. |
| `prepare_presentation.py` | One-shot presentation setup: clears OPONG's results and the activity log, re-runs the Tino CSV + GPKG ingestion, seeds OPONG with every record active. Keeps farms and SAR data (Recipe 0). |
| `seed_opong_assessment_test.py` | Replays those 23 bulletins through the app's own parser, date-shifted so OPONG is the newest TCB, and activates 100 existing insurance records to assess against it. |
| `reparse_opong_bulletins.py` | Re-parses OPONG's already-saved bulletins after a TCWS parser fix. Dry run by default. |
| `backfill_tcb_track_radius.py` | Backfills the track-overlay columns (`wind_radius_km`, `storm_force_radius_km`, `forecast_track`) for bulletins saved before those columns existed. |
| `simulate_new_bulletin_alert.py` | Simulates "a new TCB just arrived" and drives the email alert to active users. Dry run by default. |

## What is deliberately *not* here

The PCIC insurance-records CSV stays inside the gitignored
`USTP CAPSTONE-*/INSURANCE RECORDS/` export — it holds **real farmer PII**.
`seed_opong_assessment_test.py` reads it in place; only the bulletins were
moved into version control. Never copy that CSV into the repo.

## Before any of this

Every command runs **from `backend/`** (not from this folder) with the venv
active, because these scripts import the `app` package:

```
cd backend
```

PostgreSQL must be running and the schema applied. Per
[`.claude/CLAUDE.md`](../../.claude/CLAUDE.md), `sudo`/`psql`/venv commands are
Fabio's to run — the DB must already be provisioned before anything below.

## Recipe 0 — Presentation-ready in one command

```
python simulation/prepare_presentation.py                 # or, from the repo root: simulate.bat ready
python simulation/prepare_presentation.py --skip-ingest   # same, without the CSV/GPKG ingestion
```

Deletes no farm data and no SAR data. Clears OPONG's computed assessment
results, its insurance usage (export locks included) and the activity log,
re-runs the full Tino CSV + GeoPackage ingestion through the upload code
(rows already in are skipped, so it only adds what's missing), then re-seeds
OPONG with every record active (Recipe 1 with `--all`). Only Compute Exposure
Summary and Compute Assessments are left to click. Asks you to type `YES`
first.

## Recipe 1 — Put a real typhoon in the system (OPONG)

```
python simulation/seed_opong_assessment_test.py
```

Parses all 23 bulletins, shifts every `issued_at` forward by one shared
whole-day offset so NR. 23F lands today (relative timing, and therefore every
exposure duration, is unchanged), applies the TEST-ONLY Signal 2 override for
Surigao del Norte, and activates the 100 insurance records most likely to pay
out. Safe to re-run.

To activate **every** ingested insurance record instead of the top 100 (same
coverage window, same backup, so `--restore` undoes it too) — run it after all
uploads, since records ingested later keep their CSV dates:

```
python simulation/seed_opong_assessment_test.py --all
```

Then, in the app itself — this is the part being tested, so the scripts leave
it alone:

1. **Monitoring** → Compute Exposure Summary
2. **Assessment & Reporting** → Compute Assessments

To run the demo again from the top:

```
python simulation/seed_opong_assessment_test.py --reset     # clear computed results
python simulation/seed_opong_assessment_test.py --restore   # put the 100 records' dates back
```

## Recipe 2 — Simulate a new TCB arriving (email alert)

Needs `SMTP_HOST` / `SMTP_USER` / `SMTP_PASSWORD` in `backend/.env` — without
them the alert is a deliberate no-op. See
[`.claude/ENV_GUIDE.md`](../../.claude/ENV_GUIDE.md) → "Activating Email Alerts".

```
python simulation/simulate_new_bulletin_alert.py                 # dry run: prints the email, sends nothing
python simulation/simulate_new_bulletin_alert.py --send          # really deliver
```

The dry run still exercises the config read, the `Typhoon.is_active` gate, the
real recipient query and the message body — only the SMTP socket is faked. It
opens with a preflight report: whether SMTP is configured, every recipient
address and role, the newest bulletin, and an OK/MISSING check on all three
ingestion paths that are supposed to trigger the alert.

Why a script rather than just waiting: off-season the real path *cannot* email.
`POST /api/bulletins/parse` returns 404 before reaching the alert step when
PAGASA has nothing posted, and the 15-minute scheduler's own status sync sets
`is_active = False` on every typhoon immediately before the alert's
`is_active` gate is checked. This script holds the typhoon active for the call
and reverts it afterward.

Other modes (each writes real bulletin rows, hence the extra flag):

```
python simulation/simulate_new_bulletin_alert.py --mode upload \
    --pdf "simulation/tcb_opong/TCB#23_opong.pdf" \
    --activate-typhoon OPONG --confirm-db-write
python simulation/simulate_new_bulletin_alert.py --mode parse --confirm-db-write
python simulation/simulate_new_bulletin_alert.py --mode scheduler --confirm-db-write
```

`parse` and `scheduler` hit the live PAGASA site and re-sync `is_active`, so
off-season they will correctly find nothing to alert about.

## Recipe 3 — Re-parse or backfill an already-loaded typhoon

After a TCWS parser fix, OPONG's stored signals are stale (signals are only
seeded on a bulletin's first insert):

```
python simulation/reparse_opong_bulletins.py            # dry run — prints stored vs. re-parsed
python simulation/reparse_opong_bulletins.py --apply
```

`--apply` refuses to run while OPONG has assessment results or insurance-usage
rows; clear them with `seed_opong_assessment_test.py --reset` first. It also
removes that script's TEST-ONLY Surigao del Norte Signal 2 override, so re-run
the seeder afterwards if the assessment demo still needs it.

Track overlay for a typhoon whose bulletins predate those columns:

```
python simulation/backfill_tcb_track_radius.py --typhoon OPONG
```

`--dir` defaults to `tcb_opong/`; paths you pass are relative to `backend/`.

## Notes

- `python -m pytest` and `python <script>` are Fabio's to run (venv rule).
- Scripts default to dry runs or are idempotent; the ones that write real
  bulletin rows require an explicit `--apply` / `--confirm-db-write`.
- `opong_test_original_dates.json` is written here by the OPONG seeder and read
  back by `--restore`. Don't delete it while records are activated.
