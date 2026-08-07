"""Benchmark for POST /api/upload/csv against a running backend.

Generates a synthetic CSV of realistic shape (same headers `upload_csv()`
expects, rows spread across real Region X barangays from
`app/data/psgc_region10_boundaries.csv` so nothing gets rejected for a missing
PSGC code) and times how long the endpoint takes to ingest it end to end.

Intended use: run once against the code/DB state *before* the CSV ingestion
performance fix (backend/app/api/upload.py + the new indexes in
init_schema.sql / CREATE INDEX commands), note the time, then run again
*after* applying the fix, to get real before/after numbers instead of
estimates -- see .claude/FUNCTION_CHANGES.md's 2026-08-07 CSV ingestion entry.

Usage (run yourself -- this is not executed automatically, see CLAUDE.md's
Python Environment Execution rule):

    python backend/scripts/benchmark_csv_ingestion.py --rows 24000
    python backend/scripts/benchmark_csv_ingestion.py --rows 24000 --url http://localhost:8000

Requires the backend server to already be running and reachable at --url, and
a real (or already-seeded) DB behind it -- this hits the real endpoint, it
does not mock anything out.
"""

import argparse
import csv
import io
import random
import time
from pathlib import Path

import httpx

_PSGC_LOOKUP_PATH = Path(__file__).resolve().parent.parent / "app" / "data" / "psgc_region10_boundaries.csv"

_HEADER = [
    "Province", "Municipality", "Barangay", "Policy No.", "Program Type", "Product Name",
    "Surname", "Firstname", "Middlename", "AreaInsured", "AmountofCover", "Stage No.",
    "FarmersID", "RSBSA No.", "FARMID", "Stage", "EstimatedDamage", "RiskExposureAmount",
]

_STAGES = [(1, "Booting"), (2, "Flowering"), (3, "Maturity")]


def _load_boundaries(sample_size: int) -> list[tuple[str, str, str]]:
    with open(_PSGC_LOOKUP_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        boundaries = [(row["province"], row["municipality"], row["barangay"]) for row in reader]
    if sample_size < len(boundaries):
        boundaries = random.sample(boundaries, sample_size)
    return boundaries


def _generate_csv(num_rows: int, num_boundaries: int, run_id: str) -> bytes:
    boundaries = _load_boundaries(num_boundaries)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_HEADER)
    for i in range(num_rows):
        province, municipality, barangay = boundaries[i % len(boundaries)]
        stage_no, stage = _STAGES[i % len(_STAGES)]
        # run_id keeps FarmersID/FARMID/Policy No. unique across separate
        # benchmark runs against the same DB, so a "before" run and an "after"
        # run don't collide as duplicates of each other. Kept short --
        # tbl_farmers_profile.farmers_id is VARCHAR(20), and "F" + 6-digit
        # run_id + up to 6 digits of i must fit inside that.
        writer.writerow([
            province, municipality, barangay,
            f"POL{run_id}{i}", "RSBSA", "",
            "Delacruz", f"Farmer{i}", "",
            "1.5", "10000", stage_no,
            f"F{run_id}{i}", "", f"FARM{run_id}{i}",
            stage, "500.00", "",
        ])
    return buf.getvalue().encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rows", type=int, default=24000, help="Number of CSV rows to generate (default: 24000, matching the real PABS export size referenced in upload.py's comments).")
    parser.add_argument("--boundaries", type=int, default=50, help="Number of distinct barangays to spread rows across (default: 50, ~480 rows/barangay at 24000 rows).")
    parser.add_argument("--url", default="http://localhost:8000", help="Backend base URL (default: http://localhost:8000).")
    parser.add_argument("--timeout", type=float, default=1800.0, help="Request timeout in seconds (default: 1800 = 30 min, generous on purpose for a 'before the fix' baseline run).")
    args = parser.parse_args()

    run_id = str(int(time.time()))[-6:]  # short on purpose -- see _generate_csv()'s VARCHAR(20) note
    print(f"Generating {args.rows} rows across {args.boundaries} boundaries (run id {run_id})...")
    csv_bytes = _generate_csv(args.rows, args.boundaries, run_id)
    print(f"Generated CSV: {len(csv_bytes) / 1024:.1f} KB")

    files = {"file": (f"benchmark_{run_id}.csv", csv_bytes, "text/csv")}
    print(f"POST {args.url}/api/upload/csv ...")
    start = time.monotonic()
    with httpx.Client(timeout=args.timeout) as client:
        response = client.post(f"{args.url}/api/upload/csv", files=files)
    elapsed = time.monotonic() - start

    print(f"\nHTTP {response.status_code} in {elapsed:.1f}s ({args.rows / elapsed:.1f} rows/sec)")
    if response.status_code != 200:
        print(response.text)
        return

    result = response.json()
    print(f"  rows_processed: {result['rows_processed']}")
    print(f"  rows_inserted:  {result['rows_inserted']}")
    print(f"  rows_skipped:   {result['rows_skipped']}")
    print(f"  rows_failed:    {result['rows_failed']}")
    if result["rows_failed"]:
        print(f"  sample failures: {result['failures'][:5]}")


if __name__ == "__main__":
    main()
