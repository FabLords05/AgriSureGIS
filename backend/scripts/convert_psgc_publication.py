"""Converts the official PSA PSGC Publication Excel file into the flat CSV
format the app already uses (backend/app/data/psgc_nationwide_boundaries.csv,
columns: psgc_code,province,municipality,barangay -- one row per barangay).

Part of the 2026-08-20 nationwide PSGC expansion (see .claude/FUNCTION_CHANGES.md)
-- Fabio wants to test whether typhoon-signal exposure calculation works with
real nationwide data, not just the previous Region X + Caraga subset. The
official PSA/FOI sites block automated fetching, so Fabio downloads the file
himself from https://psa.gov.ph/classification/psgc and this script converts
it locally.

Usage (run yourself -- this is not executed automatically, see CLAUDE.md's
Python Environment Execution rule):

    python backend/scripts/convert_psgc_publication.py --inspect app/data/psgc_publication_raw.xlsx
    python backend/scripts/convert_psgc_publication.py app/data/psgc_publication_raw.xlsx

--inspect only prints each sheet's shape/columns/geographic-level values and
exits -- run this FIRST against the real file, since PSA's exact layout
(single sheet vs. per-region sheets, exact column names, exact Geographic
Level label strings) isn't assumed blind here; it's read from whatever the
real file actually contains. Once the layout is confirmed, the full
conversion writes the flat CSV.

Known open decision (resolve once real columns are visible, per the plan in
/home/fabio/.claude/plans/why-it-does-not-prancy-pony.md): Highly Urbanized
Cities and NCR cities have no parent province in PSA's own hierarchy. This
script's convention: the `province` column for those rows is set to the
city's own name (e.g. a barangay in Davao City gets province="Davao City",
municipality="Davao City") -- keeps the (province, municipality, barangay)
key non-null and self-consistent with how upload.py's matching logic already
treats every other row, without inventing a new sentinel value the rest of
the codebase would need to special-case.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

_OUTPUT_PATH = Path(__file__).resolve().parent.parent / "app" / "data" / "psgc_nationwide_boundaries.csv"

# PSA's own level labels have varied slightly release to release -- matched
# case-insensitively, and this list is deliberately checked/extended against
# whatever --inspect actually prints for the real file before the full
# conversion runs, not assumed complete here.
_REGION_LEVELS = {"reg", "region"}
_PROVINCE_LEVELS = {"prov", "province", "distinct"}  # "Distinct" appears in some releases for HUCs' own pseudo-province row
_CITY_MUN_LEVELS = {"city", "mun", "municipality", "submun", "sub-municipality"}
_BARANGAY_LEVELS = {"bgy", "barangay"}


def inspect(path: Path) -> None:
    sheets = pd.read_excel(path, sheet_name=None)
    print(f"{len(sheets)} sheet(s) found in {path}:\n")
    for name, df in sheets.items():
        print(f"--- Sheet: {name!r} ---")
        print(f"  shape: {df.shape}")
        print(f"  columns: {df.columns.tolist()}")
        level_col = _find_level_column(df)
        if level_col:
            print(f"  geographic-level column: {level_col!r}, values:")
            print(f"    {df[level_col].value_counts().to_dict()}")
        else:
            print("  (no obvious geographic-level column found)")
        print()


def _find_level_column(df: pd.DataFrame) -> str | None:
    for col in df.columns:
        if "level" in str(col).lower() or "geo" in str(col).lower():
            return col
    return None


def _find_code_column(df: pd.DataFrame) -> str | None:
    for col in df.columns:
        if "code" in str(col).lower() and "corr" not in str(col).lower():
            return col
    return None


def _find_name_column(df: pd.DataFrame) -> str | None:
    for col in df.columns:
        lc = str(col).lower()
        if lc in ("name", "location", "province", "municipality", "city/municipality"):
            return col
    return None


def _classify_level(raw_level: str) -> str | None:
    lc = str(raw_level).strip().lower()
    if lc in _BARANGAY_LEVELS:
        return "barangay"
    if lc in _CITY_MUN_LEVELS:
        return "city_mun"
    if lc in _PROVINCE_LEVELS:
        return "province"
    if lc in _REGION_LEVELS:
        return "region"
    return None


def convert(path: Path) -> pd.DataFrame:
    sheets = pd.read_excel(path, sheet_name=None)
    # Assume the largest sheet (by row count) is the actual data table --
    # PSA publications sometimes carry a small "Notes"/cover sheet alongside
    # the real one. Adjust here once --inspect shows the real file's shape.
    name, df = max(sheets.items(), key=lambda kv: len(kv[1]))
    print(f"Using sheet {name!r} ({len(df)} rows) as the source table.")

    level_col = _find_level_column(df)
    code_col = _find_code_column(df)
    name_col = _find_name_column(df)
    if not (level_col and code_col and name_col):
        raise SystemExit(
            f"Could not confidently identify level/code/name columns in sheet {name!r} "
            f"(found level={level_col!r}, code={code_col!r}, name={name_col!r}). "
            "Run with --inspect first and adjust _find_*_column() to match the real headers."
        )

    df = df.sort_values(code_col).reset_index(drop=True)

    rows: list[dict] = []
    current_region: str | None = None
    current_province: str | None = None
    current_municipality: str | None = None
    dropped = 0

    for _, row in df.iterrows():
        level = _classify_level(row[level_col])
        raw_name = str(row[name_col]).strip()
        code = str(row[code_col]).strip()

        if level == "region":
            current_region = raw_name
            current_province = None
            current_municipality = None
        elif level == "province":
            current_province = raw_name
            current_municipality = None
        elif level == "city_mun":
            current_municipality = raw_name
            # HUC/NCR cities have no real parent province -- see this
            # script's module docstring for the chosen convention.
            if current_province is None:
                current_province = raw_name
        elif level == "barangay":
            if current_province is None or current_municipality is None:
                dropped += 1
                continue
            rows.append({
                "psgc_code": code,
                "province": current_province,
                "municipality": current_municipality,
                "barangay": raw_name,
            })
        # else: unrecognized level label -- skipped, not counted as dropped
        # (dropped tracks barangay rows specifically missing lineage).

    if dropped:
        print(f"WARNING: {dropped} barangay row(s) dropped for missing province/municipality lineage.")

    return pd.DataFrame(rows, columns=["psgc_code", "province", "municipality", "barangay"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Path to the raw PSA PSGC Publication Excel file")
    parser.add_argument("--inspect", action="store_true", help="Print sheet/column structure and exit, no conversion")
    args = parser.parse_args()

    if not args.path.exists():
        print(f"File not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    if args.inspect:
        inspect(args.path)
        return

    out_df = convert(args.path)
    out_df.to_csv(_OUTPUT_PATH, index=False)

    print(f"\nWrote {len(out_df)} rows to {_OUTPUT_PATH}")
    print(f"Distinct provinces: {out_df['province'].nunique()}")
    print(f"Distinct municipalities: {out_df['municipality'].nunique()}")
    print("\nReview the output before committing it -- spot-check a few provinces you know, "
          "and confirm the HUC/province convention (see module docstring) looks right.")


if __name__ == "__main__":
    main()
