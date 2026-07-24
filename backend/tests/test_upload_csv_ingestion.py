import io
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.api import upload as upload_module
from app.models import models

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


def _fake_upload_file(csv_text: str, encoding: str = "utf-8", filename: str = "export.csv"):
    return SimpleNamespace(
        filename=filename,
        content_type="text/csv",
        file=io.BytesIO(csv_text.encode(encoding)),
    )


class _FakeTable:
    """A tiny in-memory stand-in for one DB table, matched by exact-value equality
    on whatever columns a given .filter(...) call compared against -- close enough
    to real get-or-create behavior to catch the blank-value collapse bug, without
    needing a live database."""

    def __init__(self):
        self.rows: list = []

    def add(self, instance):
        self.rows.append(instance)

    def first(self, filters: list):
        for row in self.rows:
            matched = True
            for key, value, transform in filters:
                actual = getattr(row, key, None)
                if actual is not None:
                    actual = transform(actual)
                if actual != value:
                    matched = False
                    break
            if matched:
                return row
        return None


def _extract_filter(criterion):
    # criterion is a SQLAlchemy BinaryExpression for "Model.column == value" or
    # "func.upper(Model.column) == value". .left is either the Column itself (has
    # .name) or a Function wrapping it (whose .clauses holds the wrapped column);
    # .right is the bound literal (has .value). upload_csv() only ever wraps
    # columns in func.upper(), so that's the only transform simulated here.
    left = criterion.left
    value = criterion.right.value
    if getattr(left, "name", None) == "upper" and hasattr(left, "clauses"):
        inner = list(left.clauses)[0]
        return inner.name, value, str.upper
    return left.name, value, (lambda v: v)


class _FakeQuery:
    def __init__(self, table: _FakeTable):
        self._table = table
        self._filters: list = []

    def filter(self, *criteria):
        self._filters.extend(_extract_filter(c) for c in criteria)
        return self

    def first(self):
        return self._table.first(self._filters)


def _build_mock_db():
    tables = {model: _FakeTable() for model in _PK_FIELDS}
    counters = {model: 0 for model in _PK_FIELDS}
    added_instances: list = []

    mock_db = MagicMock()
    mock_db.query.side_effect = lambda model: _FakeQuery(tables[model])

    def add_side_effect(instance):
        model = type(instance)
        added_instances.append(instance)
        # Models outside _PK_FIELDS (e.g. RiskAssessment) are only ever inserted,
        # never queried back by upload_csv() -- nothing to track a fake PK for.
        if model in tables:
            tables[model].add(instance)
            counters[model] += 1
            setattr(instance, _PK_FIELDS[model], counters[model])

    mock_db.add.side_effect = add_side_effect
    mock_db.tables = tables
    mock_db.added_instances = added_instances
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

        result = upload_module.upload_csv(file=_fake_upload_file(csv_text), db=mock_db)

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

        upload_module.upload_csv(file=_fake_upload_file(csv_text), db=mock_db)

        farmers = mock_db.tables[models.FarmerProfile].rows
        self.assertEqual(len(farmers), 1)
        farms = mock_db.tables[models.Farm].rows
        self.assertEqual(len(farms), 2)
        self.assertTrue(all(f.farmer_id == farmers[0].farmer_id for f in farms))

    def test_blank_farmid_does_not_collapse_distinct_farms(self):
        csv_text = _csv(
            _row("POL-1", "Cruz", "Ana", farmers_id="111"),
            _row("POL-2", "Reyes", "Ben", farmers_id="222"),
        )
        mock_db = _build_mock_db()

        upload_module.upload_csv(file=_fake_upload_file(csv_text), db=mock_db)

        farms = mock_db.tables[models.Farm].rows
        self.assertEqual(len(farms), 2)

    def test_insurance_record_farmer_id_and_product_name_are_set(self):
        csv_text = _HEADER + "\n" + (
            "Bukidnon,Malaybalay,Casisang,POL-1,RSBSA,S/T Stg (EARLY VEGETATIVE),Cruz,Ana,,"
            "1.0,10000,1,111,,5001,Booting,500,\n"
        )
        mock_db = _build_mock_db()

        upload_module.upload_csv(file=_fake_upload_file(csv_text), db=mock_db)

        insurance = mock_db.tables[models.InsuranceRecord].rows[0]
        farmer = mock_db.tables[models.FarmerProfile].rows[0]
        self.assertEqual(insurance.farmer_id, farmer.farmer_id)
        self.assertEqual(insurance.product_name, "S/T Stg (EARLY VEGETATIVE)")

    def test_crop_stage_seed_uses_estimated_damage_as_final_indemnity_payment_placeholder(self):
        csv_text = _csv(
            _row("POL-1", "Cruz", "Ana", farmers_id="111", farmid="5001", stage_no=2, stage="Flowering", estimated_damage="777.50")
        )
        mock_db = _build_mock_db()

        upload_module.upload_csv(file=_fake_upload_file(csv_text), db=mock_db)

        seeds = [i for i in mock_db.added_instances if isinstance(i, models.RiskAssessment)]
        self.assertEqual(len(seeds), 1)
        seed = seeds[0]
        self.assertEqual(seed.crop_stage_no, 2)
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
            upload_module.upload_csv(file=_fake_upload_file(csv_text), db=mock_db)
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

        result = upload_module.upload_csv(file=_fake_upload_file(csv_text), db=mock_db)

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

        result = upload_module.upload_csv(file=_fake_upload_file(csv_text), db=mock_db)

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

        result = upload_module.upload_csv(file=_fake_upload_file(csv_text, encoding="cp1252"), db=mock_db)

        self.assertEqual(result["rows_inserted"], 1)
        farmer = mock_db.tables[models.FarmerProfile].rows[0]
        self.assertEqual(farmer.last_name, "SEÑERES")


if __name__ == "__main__":
    unittest.main()
