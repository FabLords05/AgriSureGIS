import io
import unittest
from datetime import date
from decimal import Decimal

import pandas as pd

from app.api.upload import _normalize_header, prepare_row_payload


class CsvUploadPreparationTests(unittest.TestCase):
    def test_prepare_row_payload_normalizes_missing_values_and_numeric_fields(self):
        df = pd.DataFrame([
            {
                "No.": 1,
                "Program Type": "Rice",
                "Province": "Bohol",
                "Municipality": "Tagbilaran",
                "Barangay": "Poblacion",
                "Policy No.": "POL-001",
                "Effectivity Date": "2024-01-01",
                "Expiry Date": "2024-12-31",
                "Surname": "Dela Cruz",
                "Firstname": "Juan",
                "Middlename": "Santos",
                "AreaInsured": "1,200.50",
                "AmountofCover": "500,000.00",
                "Stage No.": "1",
                "FarmersID": None,
                "RSBSA No.": "RSBSA-001",
                "Farm ID": "FARM-100",
                "Georef ID": "GEO-100",
                "RiskExposureAmount": "10,000.00",
                "Stage": "Vegetative",
                "EstimatedDamage": "20.50",
                "Days from Planting to Typhoon Occurance": "35",
                "Adjuster's Stage of Crop Calculation": "Early",
            }
        ])

        payload = prepare_row_payload(df.iloc[0])

        # Boundary and farmer-name fields are uppercased on ingest (_boundary_key()
        # / _normalize_text_upper() in upload.py) -- see
        # test_upload_csv_ingestion.py's dedicated casing test for the full
        # rationale; IDs (rsbsa_no) are untouched since they're not free-text.
        self.assertEqual(payload["boundary"], {"province": "BOHOL", "municipality": "TAGBILARAN", "barangay": "POBLACION"})
        self.assertEqual(
            payload["farmer"],
            {"farmers_id": None, "rsbsa_no": "RSBSA-001", "last_name": "DELA CRUZ", "first_name": "JUAN", "middle_name": "SANTOS"},
        )
        self.assertEqual(payload["farm"], {"csv_farm_reference": "FARM-100", "georef_id": "GEO-100", "area_size": Decimal("1200.50")})
        self.assertEqual(
            payload["insurance"],
            {
                "policy_no": "POL-001",
                "amount_cover": Decimal("500000.00"),
                "effectivity_date": date(2024, 1, 1),
                "expiry_date": date(2024, 12, 31),
                "program_type": "Rice",
                "product_name": None,
            },
        )
        # Stage values are carried RAW here and translated in _ingest_row() via
        # CropStageResolver (2026-10-09) -- "Stage No." is PCIC's 0-9 agronomic code,
        # not the Table 11 1/2/3 scale, so prepare_row_payload must NOT emit a
        # crop_stage_no of its own.
        self.assertEqual(
            payload["crop_stage_seed"],
            {
                "stage_code": "1",
                "stage_label": None,
                "crop_stage": "Vegetative",
                "estimated_damage": Decimal("20.50"),
                "risk_exposure_amount": Decimal("10000.00"),
            },
        )
        self.assertNotIn("crop_stage_no", payload["crop_stage_seed"])
        # adjuster_calculation no longer exists as a field anywhere -- it mapped to a
        # RiskAssessment kwarg that was never a real column and crashed every upload.
        self.assertNotIn("adjuster_calculation", payload["crop_stage_seed"])

    def test_prepare_row_payload_handles_real_pabs_export_header_names(self):
        # Exact header spelling from docs/Rice Risk Exposure Region X 04-15-2026.csv:
        # "FARMID" (no space, unlike legacy "Farm ID"), plus columns the legacy
        # format doesn't have at all (Product Name, FarmersID, RiskExposureAmount,
        # DistinctCount).
        df = pd.DataFrame([
            {
                "Program Type": "RSBSA",
                "Product Name": "S/T Stg (EARLY VEGETATIVE)",
                "Province": "Bukidnon",
                "Municipality": "Pangantucan",
                "Barangay": "Malipayon",
                "Policy No.": "1761604",
                "Effectivity Date": "04/30/2026",
                "Expiry Date": "08/28/2026",
                "Surname": "Segura",
                "Firstname": "Ivy",
                "Middlename": "Nobleza",
                "AreaInsured": "0.35",
                "AmountofCover": "8750",
                "Stage No.": 0,
                "FarmersID": 391636,
                "RSBSA No.": "10-13-16-012-000357",
                "FARMID": 1355930,
                "Georef ID": None,
                "RiskExposureAmount": "5250",
                "Stage": "0 - S/T Stg (EARLY VEGETATIVE)",
                "EstimatedDamage": "5250",
                "DistinctCount": "3.91636E+12",
            }
        ])

        payload = prepare_row_payload(df.iloc[0])

        # FARMID (no space) must resolve to the same field the legacy "Farm ID"
        # header maps to -- this is the exact bug that collapsed every farm in a
        # real 23,917-row import onto a single DB row.
        self.assertEqual(payload["farm"]["csv_farm_reference"], "1355930")
        self.assertEqual(payload["farmer"]["farmers_id"], "391636")
        self.assertEqual(payload["insurance"]["product_name"], "S/T Stg (EARLY VEGETATIVE)")
        self.assertEqual(payload["crop_stage_seed"]["risk_exposure_amount"], Decimal("5250"))
        # DistinctCount is a spreadsheet artifact (empirically FarmersID * 1e7) --
        # confirm it's simply never read anywhere.
        self.assertNotIn("distinct_count", str(payload).lower())

    def test_prepare_row_payload_blank_rsbsa_and_farmid_normalize_to_none_not_empty_string(self):
        # Root cause of the collapse bug: matching farmer/farm get-or-create lookups
        # on "" (falsy-but-not-None) treats "no RSBSA/FARMID on this row" as a real,
        # matchable identity shared by every other blank row.
        df = pd.DataFrame([
            {
                "Province": "Agusan del Norte", "Municipality": "Butuan", "Barangay": "Lemon",
                "Policy No.": "POL-1", "Surname": "Cruz", "Firstname": "Ana", "Middlename": "",
                "AreaInsured": "1.0", "AmountofCover": "1000", "Stage No.": 1,
                "FarmersID": "", "RSBSA No.": "", "FARMID": "", "Georef ID": "",
                "Stage": "Booting", "EstimatedDamage": "0",
            }
        ])

        payload = prepare_row_payload(df.iloc[0])

        self.assertIsNone(payload["farmer"]["rsbsa_no"])
        self.assertIsNone(payload["farmer"]["farmers_id"])
        self.assertIsNone(payload["farm"]["csv_farm_reference"])

    def test_purely_numeric_policy_no_is_coerced_to_string(self):
        # Regression test for a real failure hit against a live DB: "Policy No."
        # in the real PABS export is purely numeric (e.g. 1192155), so pandas
        # infers the whole column as int64 -- Postgres then rejected
        # `policy_no = 1192155` against the VARCHAR column with "operator does
        # not exist: character varying = integer". Built from a real CSV string
        # (not a hand-built DataFrame) so pandas' own type inference is actually
        # exercised, matching how upload_csv() reads a real file.
        csv_text = (
            "Province,Municipality,Barangay,Policy No.,Surname,Firstname,Middlename,"
            "AreaInsured,AmountofCover,Stage No.,FarmersID,RSBSA No.,FARMID,Stage,EstimatedDamage\n"
            "Agusan del Norte,Buenavista,Poblacion,1192155,Cruz,Ana,,1.0,10000,1,229159,"
            "16-02-12-002-000035,1033691,Booting,500\n"
        )
        df = pd.read_csv(io.StringIO(csv_text))

        payload = prepare_row_payload(df.iloc[0])

        self.assertEqual(payload["insurance"]["policy_no"], "1192155")
        self.assertIsInstance(payload["insurance"]["policy_no"], str)
        self.assertEqual(payload["farmer"]["farmers_id"], "229159")
        self.assertEqual(payload["farm"]["csv_farm_reference"], "1033691")


class NewPabsGpxLayoutTests(unittest.TestCase):
    """The client's newer export
    ("PCIC10 GPX 11-05-2025 WITH EXISTING IC AFFECTED BY TY.csv", 42 columns).
    Only 9 of its headers collide with the legacy layout after normalization, so
    everything else resolves through prepare_row_payload()'s alias list."""

    @staticmethod
    def _row(**overrides):
        row = {
            "REGION": "X",
            "FARMERSID": 29136,
            "FARMER NAME": "ABANES, ALFONSO F.",
            "CIC NO": 1742153,
            "EFFECTIVITY DATE": "08/15/2025",
            "EXPIRY DATE": "02/28/2026",
            "PROGRAM TYPE": "RSBSA",
            "VARIETY NAME": "NSIC RC160 (TUBIGAN 14) TPR",
            "FARMID": 365827,
            "AREA": "1",
            "PROVINCE": "Surigao del Norte",
            "MUNICIPALITY": "MAINIT",
            "BARANGAY": "MAGPAYANG",
            "AMOUNT OF COVER": "20,000.00",
            "PHASE": "105",
            "Stage of Crop": "Dough Stage",
            "PERIOD OF EXPOSURE, HRS": "SN3_12",
        }
        row.update(overrides)
        return row

    def test_new_header_spellings_resolve_to_the_same_payload_fields(self):
        payload = prepare_row_payload(pd.DataFrame([self._row()]).iloc[0])

        self.assertEqual(payload["boundary"], {
            "province": "SURIGAO DEL NORTE", "municipality": "MAINIT", "barangay": "MAGPAYANG",
        })
        # "CIC NO" is this layout's name for the policy number, "AREA" for
        # AreaInsured, "AMOUNT OF COVER" for AmountofCover.
        self.assertEqual(payload["insurance"]["policy_no"], "1742153")
        self.assertEqual(payload["insurance"]["amount_cover"], Decimal("20000.00"))
        self.assertEqual(payload["farm"]["area_size"], Decimal("1"))
        self.assertEqual(payload["farm"]["csv_farm_reference"], "365827")
        self.assertEqual(payload["farmer"]["farmers_id"], "29136")

    def test_combined_farmer_name_is_split_into_three_fields(self):
        payload = prepare_row_payload(pd.DataFrame([self._row()]).iloc[0])

        self.assertEqual(payload["farmer"]["last_name"], "ABANES")
        self.assertEqual(payload["farmer"]["first_name"], "ALFONSO")
        self.assertEqual(payload["farmer"]["middle_name"], "F")

    def test_compound_first_name_survives_the_split(self):
        # 131 of the real file's 1,114 rows carry three or more tokens after the
        # comma; taking only the first would drop "MARIE" here.
        payload = prepare_row_payload(
            pd.DataFrame([self._row(**{"FARMER NAME": "ACERO, ANNA MARIE S."})]).iloc[0]
        )

        self.assertEqual(payload["farmer"]["last_name"], "ACERO")
        self.assertEqual(payload["farmer"]["first_name"], "ANNA MARIE")
        self.assertEqual(payload["farmer"]["middle_name"], "S")

    def test_legacy_name_columns_win_over_combined_field_when_both_present(self):
        payload = prepare_row_payload(
            pd.DataFrame([self._row(**{"Surname": "Cruz", "Firstname": "Ana"})]).iloc[0]
        )

        self.assertEqual(payload["farmer"]["last_name"], "CRUZ")
        self.assertEqual(payload["farmer"]["first_name"], "ANA")

    def test_stage_of_crop_is_carried_as_the_label_not_a_code(self):
        payload = prepare_row_payload(pd.DataFrame([self._row()]).iloc[0])

        self.assertEqual(payload["crop_stage_seed"]["stage_label"], "Dough Stage")
        self.assertIsNone(payload["crop_stage_seed"]["stage_code"])
        # Falls back to "Stage of Crop" for the human-readable column, since this
        # layout has no "Stage" column.
        self.assertEqual(payload["crop_stage_seed"]["crop_stage"], "Dough Stage")

    def test_thousands_separated_cover_and_dash_nulls_parse(self):
        # The newer export quotes money with separators and writes "-" for null.
        payload = prepare_row_payload(
            pd.DataFrame([self._row(**{"AMOUNT OF COVER": "56,485.20", "AREA": "-"})]).iloc[0]
        )

        self.assertEqual(payload["insurance"]["amount_cover"], Decimal("56485.20"))
        self.assertIsNone(payload["farm"]["area_size"])


class NormalizeHeaderTests(unittest.TestCase):
    def test_legacy_and_new_farm_id_headers_collide(self):
        self.assertEqual(_normalize_header("Farm ID"), _normalize_header("FARMID"))

    def test_strips_punctuation_and_casing(self):
        self.assertEqual(_normalize_header("RSBSA No."), "rsbsano")
        self.assertEqual(_normalize_header("  Policy No.  "), "policyno")


if __name__ == "__main__":
    unittest.main()
