"""
One-command orchestrator for the full local-DB reseed sequence documented in
.claude/BACKEND_DATABASE_WORKFLOW.md's "Resetting the Local Database"
section -- runs every seed_*.py script in the right order as one script/one
process, instead of running each file by hand one at a time.

Does NOT run init_schema.sql itself -- that's psql/DB-provisioning (Fabio's
own terminal, per .claude/CLAUDE.md's Database Command Execution rule).
Run that first, by hand:

    cd backend
    psql -U agrisure_admin -d agrisure_db -h localhost -f init_schema.sql

...THEN run this:

    python seed_all.py

Order matters -- each later step depends on data the one(s) before it
create:
  1. seed_database                -- real PABS CSV farmers/insurance + PSGC admin boundaries
  2. seed_system_users             -- login accounts (nothing logs in without this)
  3. backfill_admin_boundary_geom  -- municipality polygons for GeoServer/map
  4. mock_data.seed_mock_typhoon   -- mock typhoon + bulletins, for exposure/assessment testing
  5. seed_active_insurance         -- synthetic active-insurance boost (1,000 records)
  6. seed_100k_farms               -- synthetic 100k-farm scale-test seed

Each step is independently wrapped: a failure partway through prints which
step failed and stops immediately (every later step assumes the ones before
it already succeeded), rather than plowing on into a step that would just
fail anyway for the same underlying reason.
"""
import sys

STEPS = [
    ("seed_database", "run_setup"),
    ("seed_system_users", "run"),
    ("backfill_admin_boundary_geom", "run_backfill"),
    ("mock_data.seed_mock_typhoon", "run_seed"),
    ("seed_active_insurance", "run"),
    ("seed_100k_farms", "run"),
]


def main():
    for module_name, func_name in STEPS:
        print(f"\n{'=' * 70}\n{module_name}.{func_name}()\n{'=' * 70}")
        try:
            module = __import__(module_name, fromlist=[func_name])
            getattr(module, func_name)()
        except Exception as exc:
            print(f"\n!!! {module_name}.{func_name}() failed: {exc!r}")
            print("Stopping here -- later steps assume this one succeeded.")
            sys.exit(1)

    print(f"\n{'=' * 70}\nAll seed steps completed.\n{'=' * 70}")


if __name__ == "__main__":
    main()
