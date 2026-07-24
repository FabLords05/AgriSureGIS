import io
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.api import upload as upload_module
from app.models import models

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

    def first(self, filters: dict):
        for row in self.rows:
            if all(getattr(row, key, None) == value for key, value in filters.items()):
                return row
        return None


class _FakeQuery:
    def __init__(self, table: _FakeTable):
        self._table = table
        self._filters: dict = {}

    def filter(self, *criteria):
        for criterion in criteria:
            # criterion is a SQLAlchemy BinaryExpression for "Model.column == value";
            # .left is the Column (has .name) and .right is the bound literal (has .value).
            self._filters[criterion.left.name] = criterion.right.value
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
        tables[model].add(instance)
        counters[model] += 1
        setattr(instance, _PK_FIELDS[model], counters[model])
        added_instances.append(instance)

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

    def test_latin1_encoded_csv_with_accented_surname_is_ingested(self):
        csv_text = _csv(_row("POL-1", "SEÑERES", "Ana", farmers_id="111", farmid="5001"))
        mock_db = _build_mock_db()

        result = upload_module.upload_csv(file=_fake_upload_file(csv_text, encoding="cp1252"), db=mock_db)

        self.assertEqual(result["rows_inserted"], 1)
        farmer = mock_db.tables[models.FarmerProfile].rows[0]
        self.assertEqual(farmer.last_name, "SEÑERES")


if __name__ == "__main__":
    unittest.main()
