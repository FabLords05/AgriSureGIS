import io
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
from sqlalchemy.sql.elements import False_, True_

from app.api import upload as upload_module
from app.models import models

# These tests drive _run_csv_ingestion() directly rather than the /csv endpoint.
# upload_csv() now only validates + parses the file and hands the row loop to a
# background thread with its own SessionLocal, so there is no longer a `db` to
# inject at the endpoint -- see _run_ingestion() below.

# Test fixtures use "Bukidnon/Malaybalay/Casisang" as a stand-in boundary --
# _load_psgc_lookup() reads a real on-disk reference file (whose exact contents
# and naming quirks, e.g. "City of Malaybalay" vs "Malaybalay", shouldn't leak
# into these tests), so it's patched per-test instead. Keyed uppercase to match
# what _boundary_key() (upload.py's case-normalizing helper) actually produces.
_FAKE_PSGC_LOOKUP = {("BUKIDNON", "MALAYBALAY", "CASISANG"): "1001312012"}

_PK_FIELDS = {
    models.AdminBoundary: "boundary_id",
    models.FarmerProfile: "farmer_id",
    models.Farm: "farm_id",
    models.InsuranceRecord: "insurance_records_id",
}


def _dataframe(csv_text: str, encoding: str = "utf-8"):
    """Mirrors upload_csv()'s own decode chain (UTF-8 first, then cp1252 for the
    Windows-exported files PABS actually produces) so an encoding regression is
    still caught here even though the endpoint itself is no longer called."""
    raw_bytes = csv_text.encode(encoding)
    for candidate in ("utf-8-sig", "cp1252"):
        try:
            return pd.read_csv(io.BytesIO(raw_bytes), encoding=candidate)
        except UnicodeDecodeError:
            continue
    raise AssertionError("fixture CSV could not be decoded")


def _run_ingestion(csv_text: str, mock_db, encoding: str = "utf-8", filename: str = "export.csv"):
    """Runs one full ingestion against the in-memory fake DB and returns the result
    dict _run_csv_ingestion() hands to upload_jobs.mark_done() -- the same payload
    GET /csv/status/{job_id} eventually serves to the frontend.

    Fails the calling test with the mark_error() message if the run errored out
    instead -- _run_csv_ingestion() swallows its own exceptions, so without this
    a crash surfaces only as an opaque None result.
    """
    outcome = {}

    def mark_done(job_id, result):
        outcome["result"] = result

    def mark_error(job_id, message):
        outcome["error"] = message

    jobs = MagicMock()
    jobs.mark_done.side_effect = mark_done
    jobs.mark_error.side_effect = mark_error

    with (
        patch.object(upload_module, "SessionLocal", return_value=mock_db),
        patch.object(upload_module, "upload_jobs", jobs),
        # Both touch real infrastructure (Redis, a materialized view) and are
        # no-ops in production unless configured; stubbed so the suite needs neither.
        patch.object(upload_module, "invalidate_farms_cache"),
        patch.object(upload_module, "refresh_farm_latest_insurance_view"),
    ):
        upload_module._run_csv_ingestion("job-test", filename, _dataframe(csv_text, encoding))

    if "error" in outcome:
        raise AssertionError(f"CSV ingestion errored: {outcome['error']}")
    return outcome["result"]


def _stage_mapping(source_code=None, source_label=None, pcic_stage="XX", crop_stage_no=None, stage_group=None):
    return SimpleNamespace(
        source_code=source_code,
        source_label=source_label,
        pcic_stage=pcic_stage,
        crop_stage_no=crop_stage_no,
        stage_group=stage_group,
        is_active=True,
    )


def _row_matches(row, filters: list) -> bool:
    for key, value, transform, is_in in filters:
        actual = getattr(row, key, None)
        if actual is not None:
            actual = transform(actual)
        if is_in:
            if actual not in value:
                return False
        elif actual != value:
            return False
    return True


class _FakeTable:
    """A tiny in-memory stand-in for one DB table, matched by exact-value equality
    (or membership, for .in_(...)) on whatever columns a given .filter(...) call
    compared against -- close enough to real get-or-create/prefetch behavior to
    catch the blank-value collapse bug, without needing a live database."""

    def __init__(self):
        self.rows: list = []

    def add(self, instance):
        self.rows.append(instance)

    def first(self, filters: list):
        for row in self.rows:
            if _row_matches(row, filters):
                return row
        return None

    def all(self, filters: list):
        return [row for row in self.rows if _row_matches(row, filters)]


def _extract_filter(criterion):
    # criterion is a SQLAlchemy BinaryExpression for "Model.column == value",
    # "func.upper(Model.column) == value", or "Model.column.in_([...])" (used by
    # _prefetch_caches()). .left is either the Column itself (has .name) or a
    # Function wrapping it (whose .clauses holds the wrapped column); .right is
    # the bound literal/list (has .value). upload_csv() only ever wraps columns
    # in func.upper(), so that's the only transform simulated here.
    # "Model.column.is_(True)" (CropStageResolver.load()) is the exception: its
    # .right is a True_/False_ constant with no .value, compared here by equality.
    left = criterion.left
    right = criterion.right
    if isinstance(right, (True_, False_)):
        value = isinstance(right, True_)
    else:
        value = right.value
    is_in = getattr(criterion.operator, "__name__", "") == "in_op"
    if getattr(left, "name", None) == "upper" and hasattr(left, "clauses"):
        inner = list(left.clauses)[0]
        return inner.name, value, str.upper, is_in
    return left.name, value, (lambda v: v), is_in


class _FakeQuery:
    def __init__(self, table: _FakeTable):
        self._table = table
        self._filters: list = []

    def filter(self, *criteria):
        self._filters.extend(_extract_filter(c) for c in criteria)
        return self

    def first(self):
        return self._table.first(self._filters)

    def all(self):
        return self._table.all(self._filters)


def _build_mock_db():
    tables = {model: _FakeTable() for model in _PK_FIELDS}
    # tbl_crop_stage_mapping is a read-only lookup CropStageResolver.load() pulls
    # once per upload (via _prefetch_caches). Seeded with the subset of
    # init_schema.sql's rows these fixtures use: 1 = MnTl (ineligible),
    # 5 = FS (Flowering), 6 = MS (Milking -- same crop_stage_no as Flowering but a
    # different group), plus the newer export's text labels.
    tables[models.CropStageMapping] = _FakeTable()
    for mapping in (
        _stage_mapping(source_code=1, pcic_stage="MnTl", crop_stage_no=None, stage_group="Early Vegetative"),
        _stage_mapping(source_code=2, pcic_stage="MxTl", crop_stage_no=None, stage_group="Late Vegetative"),
        _stage_mapping(source_code=4, pcic_stage="BS", crop_stage_no=1, stage_group="Reproductive"),
        _stage_mapping(source_code=5, pcic_stage="FS", crop_stage_no=2, stage_group="Reproductive"),
        _stage_mapping(source_code=6, pcic_stage="MS", crop_stage_no=2, stage_group="Late Reproductive"),
        _stage_mapping(source_code=7, pcic_stage="SD", crop_stage_no=3, stage_group="Maturity"),
        _stage_mapping(source_label="flowering", pcic_stage="FS", crop_stage_no=2, stage_group="Reproductive"),
        _stage_mapping(source_label="milking stage", pcic_stage="MS", crop_stage_no=2, stage_group="Late Reproductive"),
        _stage_mapping(source_label="dough stage", pcic_stage="SD/HD", crop_stage_no=3, stage_group="Maturity"),
        _stage_mapping(source_label="panicle initiation/booting", pcic_stage="PI/BS", crop_stage_no=None, stage_group=None),
    ):
        tables[models.CropStageMapping].add(mapping)
    counters = {model: 0 for model in _PK_FIELDS}
    added_instances: list = []
    query_call_counts: dict = {}

    mock_db = MagicMock()

    def query_side_effect(model):
        query_call_counts[model] = query_call_counts.get(model, 0) + 1
        return _FakeQuery(tables[model])

    mock_db.query.side_effect = query_side_effect

    def add_side_effect(instance):
        model = type(instance)
        added_instances.append(instance)
        # Models outside _PK_FIELDS (e.g. RiskAssessment) are only ever inserted,
        # never queried back by the ingest -- nothing to track a fake PK for.
        # CropStageMapping is the mirror image: queried, never inserted.
        if model in tables:
            tables[model].add(instance)
            counters[model] += 1
            setattr(instance, _PK_FIELDS[model], counters[model])

    mock_db.add.side_effect = add_side_effect
    mock_db.tables = tables
    mock_db.added_instances = added_instances
    mock_db.query_call_counts = query_call_counts
    return mock_db


_HEADER = (
    "Province,Municipality,Barangay,Policy No.,Program Type,Product Name,Surname,Firstname,Middlename,"
    "AreaInsured,AmountofCover,Stage No.,FarmersID,RSBSA No.,FARMID,Stage,EstimatedDamage,RiskExposureAmount"
)


def _row(
    policy_no,
    surname,
    firstname,
    farmers_id="",
    rsbsa_no="",
    farmid="",
    stage_no=1,
    stage="Booting",
    estimated_damage="500",
    risk_exposure_amount="",
    amount_cover="10000",
    area="1.0",
):
    return (
        f"Bukidnon,Malaybalay,Casisang,{policy_no},RSBSA,,{surname},{firstname},,"
        f"{area},{amount_cover},{stage_no},{farmers_id},{rsbsa_no},{farmid},{stage},"
        f"{estimated_damage},{risk_exposure_amount}"
    )


def _csv(*rows: str) -> str:
    return _HEADER + "\n" + "\n".join(rows) + "\n"


class UploadCsvIngestionTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("app.api.upload._load_psgc_lookup", return_value=_FAKE_PSGC_LOOKUP)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_blank_rsbsa_no_does_not_collapse_distinct_farmers(self):
        csv_text = _csv(
            _row("POL-1", "Cruz", "Ana", farmers_id="111", farmid="5001"),
            _row("POL-2", "Reyes", "Ben", farmers_id="222", farmid="5002"),
        )
        mock_db = _build_mock_db()

        result = _run_ingestion(csv_text, mock_db)

        self.assertEqual(result["rows_inserted"], 2)
        farmers = mock_db.tables[models.FarmerProfile].rows
        self.assertEqual(len(farmers), 2)
        self.assertEqual({f.farmers_id for f in farmers}, {"111", "222"})

    def test_same_farmers_id_reuses_existing_farmer(self):
        csv_text = _csv(
            _row("POL-1", "Cruz", "Ana", farmers_id="111", farmid="5001"),
            _row("POL-2", "Cruz", "Ana", farmers_id="111", farmid="5002", area="0.5", amount_cover="5000"),
        )
        mock_db = _build_mock_db()

        _run_ingestion(csv_text, mock_db)

        farmers = mock_db.tables[models.FarmerProfile].rows
        self.assertEqual(len(farmers), 1)
        farms = mock_db.tables[models.Farm].rows
        self.assertEqual(len(farms), 2)
        self.assertTrue(all(f.farmer_id == farmers[0].farmer_id for f in farms))

    def test_repeated_boundary_across_many_rows_is_only_queried_once(self):
        # Regression test for a real performance problem: a real 23,917-row CSV
        # spans far fewer distinct boundaries (the same barangay repeats across
        # ~10-20 rows on average), and the original per-row implementation
        # re-queried the database for the same boundary on every single row.
        # Expected count is 3, not 1: _prefetch_caches() does one whole-table
        # `.all()` query up front (query #1), and this boundary doesn't exist yet
        # in the fake DB, so the first row still falls back to one name lookup
        # (query #2) and one psgc_code lookup (query #3) before creating + caching
        # it -- rows 2 and 3 then hit that cache and issue no further queries, so
        # the count still doesn't scale with the number of repeated rows.
        csv_text = _csv(
            _row("POL-1", "Cruz", "Ana", farmers_id="111", farmid="5001"),
            _row("POL-2", "Reyes", "Ben", farmers_id="222", farmid="5002"),
            _row("POL-3", "Santos", "Cid", farmers_id="333", farmid="5003"),
        )
        mock_db = _build_mock_db()

        _run_ingestion(csv_text, mock_db)

        self.assertEqual(mock_db.query_call_counts.get(models.AdminBoundary, 0), 3)

    def test_name_variant_reuses_existing_boundary_by_psgc_code(self):
        # Regression test for the 2026-10-09 PCIC10 export: 'POBLACION (ALEGRIA)'
        # missed the name lookup, _resolve_psgc_code() stripped the parenthetical
        # to reach 'POBLACION' (1606701001) -- a boundary already preloaded under
        # that spelling -- and the ingest tried to insert it a second time, failing
        # all 45 such rows on tbl_admin_boundaries_psgc_code_key.
        mock_db = _build_mock_db()
        existing = models.AdminBoundary(
            psgc_code="1001312012", province="BUKIDNON", municipality="MALAYBALAY", barangay="CASISANG"
        )
        mock_db.add(existing)
        csv_text = _csv(
            _row("POL-1", "Cruz", "Ana", farmers_id="111", farmid="5001").replace(
                ",Casisang,", ",Casisang (Pob.),", 1
            ),
            _row("POL-2", "Reyes", "Ben", farmers_id="222", farmid="5002").replace(
                ",Casisang,", ",Casisang (Pob.),", 1
            ),
        )

        result = _run_ingestion(csv_text, mock_db)

        self.assertEqual(result["rows_failed"], 0)
        self.assertEqual(result["rows_inserted"], 2)
        self.assertEqual(mock_db.tables[models.AdminBoundary].rows, [existing])
        farms = mock_db.tables[models.Farm].rows
        self.assertEqual({farm.boundary_id for farm in farms}, {existing.boundary_id})

    def test_same_rsbsa_no_across_rows_is_only_queried_once(self):
        # Expected count is 2, not 1: _prefetch_caches() issues one batched
        # `rsbsa_no.in_([...])` query up front (query #1; the farmers_id branch is
        # skipped entirely since no row here sets one), and since this farmer
        # doesn't exist yet in the fake DB, row 1 still falls back to one real
        # lookup (query #2) before creating + caching it -- row 2 then hits that
        # cache and issues no further query, so the count still doesn't scale
        # with the number of repeated rows.
        csv_text = _csv(
            _row("POL-1", "Cruz", "Ana", rsbsa_no="RSBSA-1"),
            _row("POL-2", "Cruz", "Ana", rsbsa_no="RSBSA-1", area="0.5", amount_cover="5000"),
        )
        mock_db = _build_mock_db()

        _run_ingestion(csv_text, mock_db)

        farmers = mock_db.tables[models.FarmerProfile].rows
        self.assertEqual(len(farmers), 1)
        self.assertEqual(mock_db.query_call_counts.get(models.FarmerProfile, 0), 2)

    def test_blank_farmid_does_not_collapse_distinct_farms(self):
        csv_text = _csv(
            _row("POL-1", "Cruz", "Ana", farmers_id="111"),
            _row("POL-2", "Reyes", "Ben", farmers_id="222"),
        )
        mock_db = _build_mock_db()

        _run_ingestion(csv_text, mock_db)

        farms = mock_db.tables[models.Farm].rows
        self.assertEqual(len(farms), 2)

    def test_insurance_record_farmer_id_and_product_name_are_set(self):
        csv_text = _HEADER + "\n" + (
            "Bukidnon,Malaybalay,Casisang,POL-1,RSBSA,S/T Stg (EARLY VEGETATIVE),Cruz,Ana,,"
            "1.0,10000,1,111,,5001,Booting,500,\n"
        )
        mock_db = _build_mock_db()

        _run_ingestion(csv_text, mock_db)

        insurance = mock_db.tables[models.InsuranceRecord].rows[0]
        farmer = mock_db.tables[models.FarmerProfile].rows[0]
        self.assertEqual(insurance.farmer_id, farmer.farmer_id)
        self.assertEqual(insurance.product_name, "S/T Stg (EARLY VEGETATIVE)")

    def test_crop_stage_seed_uses_estimated_damage_as_final_indemnity_payment_placeholder(self):
        # Stage No. 5 is PCIC's Flowering Stage (FS), which tbl_crop_stage_mapping
        # translates to the Table 11 crop_stage_no 2. The legacy export's own code
        # is NOT that scale -- see test_legacy_stage_code_is_translated_not_copied.
        csv_text = _csv(
            _row("POL-1", "Cruz", "Ana", farmers_id="111", farmid="5001", stage_no=5,
                 stage="5 - Flowering Stg. (REPRODUCTIVE)", estimated_damage="777.50")
        )
        mock_db = _build_mock_db()

        _run_ingestion(csv_text, mock_db)

        seeds = [i for i in mock_db.added_instances if isinstance(i, models.RiskAssessment)]
        self.assertEqual(len(seeds), 1)
        seed = seeds[0]
        self.assertEqual(seed.crop_stage_no, 2)
        self.assertEqual(seed.stage_group, "Reproductive")
        self.assertEqual(seed.estimated_damage, Decimal("777.50"))
        self.assertEqual(seed.final_indemnity_payment, Decimal("777.50"))
        # Intentionally unset -- this is a seed row, not a real computed assessment.
        # AssessmentService/export_assessments_csv both rely on matrix_id staying NULL here.
        self.assertIsNone(seed.matrix_id)
        self.assertIsNone(seed.wind_velocity)

    def test_risk_exposure_amount_mismatch_logs_a_warning(self):
        csv_text = _csv(
            _row("POL-1", "Cruz", "Ana", farmers_id="111", farmid="5001", estimated_damage="500", risk_exposure_amount="999")
        )
        mock_db = _build_mock_db()

        with self.assertLogs("app.api.upload", level="WARNING") as captured:
            _run_ingestion(csv_text, mock_db)
        self.assertTrue(any("differs from EstimatedDamage" in message for message in captured.output))

    def test_missing_psgc_code_is_reported_as_a_row_failure_not_a_raised_exception(self):
        # Regression test for a real failure hit against a live DB: a province not
        # covered by the PSGC lookup file used to reach the DB with no psgc_code at
        # all, surfacing as a cryptic psycopg2 NotNullViolation instead of an
        # actionable, per-row-isolated message.
        csv_text = _HEADER + "\n" + (
            "Agusan del Norte,Unknown Town,Unknown Barangay,POL-1,RSBSA,,Cruz,Ana,,"
            "1.0,10000,1,111,,5001,Booting,500,\n"
        )
        mock_db = _build_mock_db()

        result = _run_ingestion(csv_text, mock_db)

        self.assertEqual(result["rows_failed"], 1)
        self.assertEqual(result["rows_inserted"], 0)
        self.assertIn("No PSGC code on file for", result["failures"][0]["error"])
        self.assertEqual(result["failures"][0]["policy_no"], "POL-1")

    def test_one_bad_row_does_not_abort_the_rest_of_the_batch(self):
        csv_text = _csv(
            _row("POL-1", "Cruz", "Ana", farmers_id="111", farmid="5001"),
        ) + (
            "Agusan del Norte,Unknown Town,Unknown Barangay,POL-BAD,RSBSA,,Reyes,Ben,,"
            "1.0,10000,1,222,,5002,Booting,500,\n"
        )
        mock_db = _build_mock_db()

        result = _run_ingestion(csv_text, mock_db)

        self.assertEqual(result["rows_processed"], 2)
        self.assertEqual(result["rows_inserted"], 1)
        self.assertEqual(result["rows_failed"], 1)
        self.assertEqual(result["failures"][0]["row"], 2)
        # The good row's data must still be there -- one bad row shouldn't roll
        # back everything else already processed in the same upload.
        self.assertEqual(len(mock_db.tables[models.FarmerProfile].rows), 1)
        self.assertEqual(mock_db.tables[models.FarmerProfile].rows[0].farmers_id, "111")
        self.assertEqual(len(mock_db.tables[models.InsuranceRecord].rows), 1)

    def test_latin1_encoded_csv_with_accented_surname_is_ingested(self):
        csv_text = _csv(_row("POL-1", "SEÑERES", "Ana", farmers_id="111", farmid="5001"))
        mock_db = _build_mock_db()

        result = _run_ingestion(csv_text, mock_db, encoding="cp1252")

        self.assertEqual(result["rows_inserted"], 1)
        farmer = mock_db.tables[models.FarmerProfile].rows[0]
        self.assertEqual(farmer.last_name, "SEÑERES")

    def test_mixed_case_source_values_are_normalized_to_upper_on_ingest(self):
        # Real PABS exports mix ALL CAPS and Title Case for the same fields, even
        # within one export -- upload_csv() should normalize farmer names and
        # boundary fields to ALL CAPS on ingest regardless of source casing.
        csv_text = _HEADER + "\n" + (
            "bukidnon,Malaybalay,CasiSang,POL-1,RSBSA,,Abao,jonel,,"
            "1.0,10000,1,111,,5001,Booting,500,\n"
        )
        mock_db = _build_mock_db()

        result = _run_ingestion(csv_text, mock_db)

        self.assertEqual(result["rows_inserted"], 1)
        farmer = mock_db.tables[models.FarmerProfile].rows[0]
        self.assertEqual(farmer.last_name, "ABAO")
        self.assertEqual(farmer.first_name, "JONEL")
        boundary = mock_db.tables[models.AdminBoundary].rows[0]
        self.assertEqual(boundary.province, "BUKIDNON")
        self.assertEqual(boundary.municipality, "MALAYBALAY")
        self.assertEqual(boundary.barangay, "CASISANG")

    def test_purely_numeric_policy_no_ingests_successfully_end_to_end(self):
        # Regression test for a real failure hit against a live DB: a purely
        # numeric "Policy No." (e.g. 1192155, as in the real PABS export) made
        # pandas infer the whole column as int64, and Postgres rejected the
        # resulting `policy_no = 1192155` comparison against the VARCHAR column.
        # _row()'s other tests all use non-numeric policy numbers like "POL-1",
        # which never exercised pandas' numeric type inference at all.
        csv_text = _csv(_row("1192155", "Cruz", "Ana", farmers_id="111", farmid="5001"))
        mock_db = _build_mock_db()

        result = _run_ingestion(csv_text, mock_db)

        self.assertEqual(result["rows_inserted"], 1)
        self.assertEqual(result["rows_failed"], 0)
        insurance = mock_db.tables[models.InsuranceRecord].rows[0]
        self.assertEqual(insurance.policy_no, "1192155")

    def test_large_file_all_rows_accounted_for_with_no_duplicates(self):
        # Regression test for the prefetch/caching rewrite (_prefetch_caches()):
        # ingests a file large enough to exercise the batched WHERE...IN(...)
        # prefetch queries in chunks (_PREFETCH_CHUNK_SIZE=1000), spanning many
        # distinct farmers/farms plus a handful of exact-duplicate rows, and
        # checks the row accounting and the dedup/reuse behavior still hold at
        # this size -- not just for the 1-3 row cases above.
        n = 1500
        rows = [
            _row(f"POL-{i}", "Cruz", "Ana", farmers_id=str(i), farmid=str(10_000 + i))
            for i in range(n)
        ]
        # 50 exact re-uploads of already-defined (policy_no, farm) pairs -- must
        # be detected as duplicates (skipped), not re-inserted.
        duplicate_rows = [
            _row(f"POL-{i}", "Cruz", "Ana", farmers_id=str(i), farmid=str(10_000 + i))
            for i in range(50)
        ]
        csv_text = _csv(*(rows + duplicate_rows))
        mock_db = _build_mock_db()

        result = _run_ingestion(csv_text, mock_db)

        self.assertEqual(result["rows_processed"], n + 50)
        self.assertEqual(result["rows_inserted"], n)
        self.assertEqual(result["rows_skipped"], 50)
        self.assertEqual(result["rows_failed"], 0)
        # No row was silently dropped or double-counted.
        self.assertEqual(
            result["rows_inserted"] + result["rows_skipped"] + result["rows_failed"],
            result["rows_processed"],
        )
        # Every farmer/farm is distinct and none were collapsed or duplicated.
        self.assertEqual(len(mock_db.tables[models.FarmerProfile].rows), n)
        self.assertEqual(len(mock_db.tables[models.Farm].rows), n)
        self.assertEqual(len(mock_db.tables[models.InsuranceRecord].rows), n)
        self.assertEqual(
            {f.farmers_id for f in mock_db.tables[models.FarmerProfile].rows},
            {str(i) for i in range(n)},
        )


class CropStageTranslationTests(unittest.TestCase):
    """The ingest must translate whichever crop-stage vocabulary a CSV layout uses
    into the Table 11 crop_stage_no, never copy it through. Before 2026-10-09 the
    legacy export's PCIC agronomic code was written straight into crop_stage_no,
    which AssessmentService reads as the 1=Booting/2=Flowering/3=Maturity scale --
    so code 1 (Maximum Tillering) was assessed as Booting while code 4 (the real
    Booting) fell outside {1,2,3} and was dropped."""

    def setUp(self):
        patcher = patch("app.api.upload._load_psgc_lookup", return_value=_FAKE_PSGC_LOOKUP)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _seed_for(self, **row_kwargs):
        csv_text = _csv(_row("POL-1", "Cruz", "Ana", farmers_id="111", farmid="5001", **row_kwargs))
        mock_db = _build_mock_db()
        _run_ingestion(csv_text, mock_db)
        seeds = [i for i in mock_db.added_instances if isinstance(i, models.RiskAssessment)]
        self.assertEqual(len(seeds), 1)
        return seeds[0]

    def test_legacy_stage_code_is_translated_not_copied(self):
        # Code 4 is Booting -- previously dropped because 4 is not in {1,2,3}.
        seed = self._seed_for(stage_no=4, stage="4 - Booting Stg. (REPRODUCTIVE)")

        self.assertEqual(seed.crop_stage_no, 1)
        self.assertEqual(seed.stage_group, "Reproductive")

    def test_legacy_tillering_code_is_not_mistaken_for_booting(self):
        # Code 1 is Maximum/Minimum Tillering, which takes no wind damage at all
        # (Table 11 Note 1) -- it must NOT land on crop_stage_no 1 (Booting).
        seed = self._seed_for(stage_no=1, stage="1 - Mn. Tl. Stg. (EARLY VEGETATIVE)")

        self.assertIsNone(seed.crop_stage_no)
        self.assertEqual(seed.stage_group, "Early Vegetative")

    def test_milking_and_flowering_share_a_stage_no_but_not_a_group(self):
        flowering = self._seed_for(stage_no=5, stage="5 - Flowering Stg. (REPRODUCTIVE)")
        milking = self._seed_for(stage_no=6, stage="6 - Milking Stg. (LATE REPRODUCTIVE)")

        self.assertEqual(flowering.crop_stage_no, milking.crop_stage_no)
        self.assertEqual(flowering.stage_group, "Reproductive")
        self.assertEqual(milking.stage_group, "Late Reproductive")

    def test_unresolvable_stage_still_ingests_the_row(self):
        # "Panicle Initiation/Booting" is deliberately unmapped (it merges a
        # no-damage stage with an eligible one and PCIC has not supplied a
        # days-after-transplanting threshold). The row must still land.
        header = (
            "PROVINCE,MUNICIPALITY,BARANGAY,CIC NO,FARMERSID,FARMER NAME,FARMID,"
            "AREA,AMOUNT OF COVER,Stage of Crop,EFFECTIVITY DATE,EXPIRY DATE"
        )
        csv_text = header + "\n" + (
            "Bukidnon,Malaybalay,Casisang,1742153,29136,\"ABANES, ALFONSO F.\",365827,"
            "1,\"20,000.00\",Panicle Initiation/Booting,08/15/2025,02/28/2026"
        ) + "\n"
        mock_db = _build_mock_db()

        result = _run_ingestion(csv_text, mock_db)

        self.assertEqual(result["rows_inserted"], 1)
        self.assertEqual(result["rows_failed"], 0)
        seed = [i for i in mock_db.added_instances if isinstance(i, models.RiskAssessment)][0]
        self.assertIsNone(seed.crop_stage_no)
        self.assertIsNone(seed.stage_group)

    def test_new_layout_text_label_resolves(self):
        header = (
            "PROVINCE,MUNICIPALITY,BARANGAY,CIC NO,FARMERSID,FARMER NAME,FARMID,"
            "AREA,AMOUNT OF COVER,Stage of Crop,EFFECTIVITY DATE,EXPIRY DATE"
        )
        csv_text = header + "\n" + (
            "Bukidnon,Malaybalay,Casisang,1742153,29136,\"ABANES, ALFONSO F.\",365827,"
            "1,\"20,000.00\",Dough Stage,08/15/2025,02/28/2026"
        ) + "\n"
        mock_db = _build_mock_db()

        result = _run_ingestion(csv_text, mock_db)

        self.assertEqual(result["rows_inserted"], 1)
        seed = [i for i in mock_db.added_instances if isinstance(i, models.RiskAssessment)][0]
        self.assertEqual(seed.crop_stage_no, 3)
        self.assertEqual(seed.stage_group, "Maturity")
        # And the combined name field was split on the way through.
        farmer = [i for i in mock_db.added_instances if isinstance(i, models.FarmerProfile)][0]
        self.assertEqual(farmer.last_name, "ABANES")
        self.assertEqual(farmer.first_name, "ALFONSO")


class ExistingRowBackfillTests(unittest.TestCase):
    """Re-ingesting a file must REPAIR rows this same ingest created earlier under a
    CSV layout whose columns the parser didn't recognize yet -- not preserve the
    damage forever.

    This is the root cause of blank farmer names in Spatial Analysis (2026-10-09).
    The newer PABS export was uploaded once before `FARMER NAME`/`AREA` aliases
    existed; because tbl_farmers_profile.last_name/first_name are NOT NULL, the
    `or ""` fallback stored empty strings rather than failing, and AreaInsured's
    absence stored area_size = 0. _ingest_row() then resolved those rows purely as
    lookups and discarded the payload, so re-uploading the corrected file matched
    them by farmers_id and changed nothing at all.

    The rule is blank-only (Fabio's call, 2026-10-09): fill a gap, never overwrite
    a value that's really there -- the newer export derives the farmer from one
    combined 'FARMER NAME' field, so letting it win outright would let a split
    value clobber the legacy export's three discrete columns.
    """

    # The newer PABS/GPX layout -- combined FARMER NAME, CIC NO, AREA.
    _NEW_HEADER = (
        "PROVINCE,MUNICIPALITY,BARANGAY,CIC NO,FARMERSID,FARMER NAME,FARMID,"
        "AREA,AMOUNT OF COVER,Stage of Crop,EFFECTIVITY DATE,EXPIRY DATE"
    )

    def setUp(self):
        patcher = patch("app.api.upload._load_psgc_lookup", return_value=_FAKE_PSGC_LOOKUP)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _new_layout_csv(self, *, farmers_id="29136", farmid="365827", area="1.5"):
        return self._NEW_HEADER + "\n" + (
            f"Bukidnon,Malaybalay,Casisang,1742153,{farmers_id},\"ABANES, ALFONSO F.\",{farmid},"
            f"{area},\"20,000.00\",Dough Stage,08/15/2025,02/28/2026"
        ) + "\n"

    def test_blank_names_on_existing_farmer_are_backfilled(self):
        mock_db = _build_mock_db()
        # Exactly what the pre-alias ingest left behind: identified, but nameless.
        existing = models.FarmerProfile(farmers_id="29136", last_name="", first_name="", middle_name=None)
        mock_db.add(existing)

        result = _run_ingestion(self._new_layout_csv(), mock_db)

        self.assertEqual(result["rows_failed"], 0)
        # Repaired in place -- no second profile created for the same farmers_id.
        self.assertEqual(len(mock_db.tables[models.FarmerProfile].rows), 1)
        self.assertEqual(existing.last_name, "ABANES")
        self.assertEqual(existing.first_name, "ALFONSO")
        self.assertEqual(existing.middle_name, "F")

    def test_whitespace_only_names_are_treated_as_blank(self):
        mock_db = _build_mock_db()
        existing = models.FarmerProfile(farmers_id="29136", last_name="   ", first_name="\t", middle_name="  ")
        mock_db.add(existing)

        _run_ingestion(self._new_layout_csv(), mock_db)

        self.assertEqual(existing.last_name, "ABANES")
        self.assertEqual(existing.first_name, "ALFONSO")
        self.assertEqual(existing.middle_name, "F")

    def test_real_names_on_existing_farmer_are_not_overwritten(self):
        # The conservative half of the rule: a farmer already carrying a real name
        # (e.g. from the legacy export's three discrete columns) keeps it, even
        # though this CSV disagrees.
        mock_db = _build_mock_db()
        existing = models.FarmerProfile(
            farmers_id="29136", last_name="ABANES-LEGACY", first_name="ALFONSO JOSE", middle_name="FERNANDEZ"
        )
        mock_db.add(existing)

        _run_ingestion(self._new_layout_csv(), mock_db)

        self.assertEqual(existing.last_name, "ABANES-LEGACY")
        self.assertEqual(existing.first_name, "ALFONSO JOSE")
        self.assertEqual(existing.middle_name, "FERNANDEZ")

    def test_partially_blank_existing_farmer_only_fills_the_gap(self):
        mock_db = _build_mock_db()
        existing = models.FarmerProfile(farmers_id="29136", last_name="ABANES-LEGACY", first_name="", middle_name=None)
        mock_db.add(existing)

        _run_ingestion(self._new_layout_csv(), mock_db)

        self.assertEqual(existing.last_name, "ABANES-LEGACY")  # kept
        self.assertEqual(existing.first_name, "ALFONSO")       # filled
        self.assertEqual(existing.middle_name, "F")            # filled

    def test_zero_area_size_on_existing_farm_is_backfilled(self):
        # area_size is NOT NULL and the create path coerces an unreadable
        # AreaInsured/AREA column to 0, so 0 is this column's "never actually read"
        # marker -- a real farm is never 0 ha.
        mock_db = _build_mock_db()
        farmer = models.FarmerProfile(farmers_id="29136", last_name="ABANES", first_name="ALFONSO")
        mock_db.add(farmer)
        existing_farm = models.Farm(
            farmer_id=farmer.farmer_id, boundary_id=1, csv_farm_reference="365827",
            georef_id=None, area_size=Decimal("0"), location_geom=None,
        )
        mock_db.add(existing_farm)

        result = _run_ingestion(self._new_layout_csv(area="1.5"), mock_db)

        self.assertEqual(result["rows_failed"], 0)
        self.assertEqual(len(mock_db.tables[models.Farm].rows), 1)
        self.assertEqual(existing_farm.area_size, Decimal("1.5"))

    def test_real_area_size_on_existing_farm_is_not_overwritten(self):
        mock_db = _build_mock_db()
        farmer = models.FarmerProfile(farmers_id="29136", last_name="ABANES", first_name="ALFONSO")
        mock_db.add(farmer)
        existing_farm = models.Farm(
            farmer_id=farmer.farmer_id, boundary_id=1, csv_farm_reference="365827",
            georef_id=None, area_size=Decimal("2.25"), location_geom=None,
        )
        mock_db.add(existing_farm)

        _run_ingestion(self._new_layout_csv(area="1.5"), mock_db)

        self.assertEqual(existing_farm.area_size, Decimal("2.25"))


if __name__ == "__main__":
    unittest.main()
