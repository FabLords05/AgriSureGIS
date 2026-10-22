import io
import unittest
from datetime import date
from decimal import Decimal

import pandas as pd

from app.api.upload import _normalize_header, _repair_enye, prepare_row_payload


class CsvUploadPreparationTests(unittest.TestCase):
    def test_region_ii_list_of_farms_export_maps_address_dates_and_track_file(self):
        # PCIC's "Region II List of Farms with GPX File" layout (2026-10-22):
        # "... Address" location columns, "Date Effectivity"/"Date Expiry" and
        # trackFileName. Before these aliases the whole file was rejected.
        df = pd.DataFrame([{
            "Georef ID": "",
            "Farmers ID": "189763",
            "Farmer Name": "GUIYAB, MERCIE LIBAN",
            "Barangay Address": "SANTA",
            "Municipality Address": "TUMAUINI",
            "Province Address": "ISABELA",
            "Policy No.": "2267454",
            "Area": "0.8514",
            "Date Effectivity": "09/10/2026",
            "Date Expiry": "01/08/2027",
            "Amount of Cover": "21,285.00",
            "FarmID": "1609622",
            "trackFileName": "TAB_GUIYAB, MERCIE M._189763_1609622_2024-04-04.gpx",
        }])

        payload = prepare_row_payload(df.iloc[0])

        self.assertEqual(payload["boundary"], {"province": "ISABELA", "municipality": "TUMAUINI", "barangay": "SANTA"})
        self.assertEqual(payload["insurance"]["effectivity_date"], date(2026, 9, 10))
        self.assertEqual(payload["insurance"]["expiry_date"], date(2027, 1, 8))
        self.assertEqual(payload["insurance"]["amount_cover"], Decimal("21285.00"))
        self.assertEqual(payload["farm"]["csv_farm_reference"], "1609622")
        self.assertEqual(payload["farm"]["track_file_name"], "TAB_GUIYAB, MERCIE M._189763_1609622_2024-04-04.gpx")

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
        self.assertEqual(
            payload["farm"],
            {"csv_farm_reference": "FARM-100", "georef_id": "GEO-100", "area_size": Decimal("1200.50"), "track_file_name": None},
        )
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


_REGION_III_HEADER = (
    "Georef ID,Farmers ID,Farmer Name,Barangay Address,Municipality Address,Province Address,Mobile No.,"
    "Policy No.,IR ID,Policy Date Issued,Area,Commodity,Amount Cover,varietyName,VarietyID,StgeCode,"
    "Stage of Crop,Type of Planting,Date of Sowing,Date of Transplant,Date of Harvest,Date Effectivity,"
    "Date Expiry,Insurance Status,GPX From:,Tenurial Status,Farm Name,FarmID,trackFileName,imageFileName,Track date\n"
)
_REGION_III_ROWS = (
    ',87932,"DIMALANTA, EDUARDO MENDOZA",CARMENCITA,FLORIDABLANCA,PAMPANGA,(0918) 534-9848,2124465,,'
    "7/10/2026,0.7406,Rice/Palay,,RICE120DAYS,416,,Mn. Tl. Stg. (EARLY VEGETATIVE),Transplant,7/25/2026,"
    "8/20/2026,11/22/2026,7/10/2026,12/18/2026,ACTIVE INSURANCE,PPI,Owner,FARM 694946 - GPX,694946,"
    '"TAB_DIMALANTA, EDUARDO M._87932_694946_2025-05-17.gpx",87932_694946_2025-06-08.jpg,\n'
    ',199787,"BARIAS, ATILANO JR. TAYAG",SAN NICOLAS (POB.),CONCEPCION,TARLAC,(0916) 754-6759,2119786,,'
    "6/16/2026,0.9445,Rice/Palay,\"21,000.00\",RICE120DAYS,416,,Mn. Tl. Stg. (EARLY VEGETATIVE),Direct Seeding,"
    "7/30/2026,7/30/2026,11/27/2026,6/16/2026,11/27/2026,ACTIVE INSURANCE,PPI,Owner,FARM 969118 - GPX,969118,"
    '"TAB_BARIAS, ATILANO JR. T._199787_969118_2026-02-14.gpx",0_969118_2026-04-07.jpg,\n'
    ',64167,"BULAUN, MAGDALENA SIMBULAN",SANTO NIÑO,MAGALANG,PAMPANGA,(0965) 428-4105,2121781,,6/26/2026,'
    "0.7501,Rice/Palay,,RICE120DAYS,416,,Mn. Tl. Stg. (EARLY VEGETATIVE),Direct Seeding,7/30/2026,7/30/2026,"
    "11/27/2026,6/26/2026,11/27/2026,ACTIVE INSURANCE,PPI,Owner,FARM 671586 - GPX,671586,"
    '"TAB_BULAUN, MAGDALENA S._64167_671586_2025-05-14",64167_671586_2025-06-07.jpg,\n'
)


class RegionIIIOfficialLayoutTests(unittest.TestCase):
    """docs/Region III List of Farms with GPX File_Corrected Format.csv -- the
    official ingestion layout (2026-10-22). Read as upload_csv() reads it: the
    real file is cp1252, so 'SANTO NIÑO' is a single 0xD1 byte."""

    def setUp(self):
        raw = (_REGION_III_HEADER + _REGION_III_ROWS).encode("cp1252")
        self.df = pd.read_csv(io.BytesIO(raw), encoding="cp1252")

    def _payload(self, index):
        return prepare_row_payload(self.df.iloc[index])

    def test_core_fields_map(self):
        payload = self._payload(0)

        self.assertEqual(payload["boundary"], {
            "province": "PAMPANGA", "municipality": "FLORIDABLANCA", "barangay": "CARMENCITA",
        })
        self.assertEqual(payload["farmer"]["farmers_id"], "87932")
        self.assertEqual(payload["farm"]["csv_farm_reference"], "694946")
        self.assertEqual(payload["farm"]["area_size"], Decimal("0.7406"))
        self.assertIsNone(payload["farm"]["georef_id"])
        self.assertEqual(
            payload["farm"]["track_file_name"], "TAB_DIMALANTA, EDUARDO M._87932_694946_2025-05-17.gpx"
        )
        self.assertEqual(payload["insurance"]["policy_no"], "2124465")
        self.assertEqual(payload["insurance"]["product_name"], "RICE120DAYS")
        self.assertEqual(payload["insurance"]["effectivity_date"], date(2026, 7, 10))
        self.assertEqual(payload["insurance"]["expiry_date"], date(2026, 12, 18))
        self.assertFalse(payload["repaired_enye"])

    def test_amount_cover_header_is_read(self):
        # Blank -> None (the Admin Panel rate applies in _ingest_row); filled -> used.
        self.assertIsNone(self._payload(0)["insurance"]["amount_cover"])
        self.assertEqual(self._payload(1)["insurance"]["amount_cover"], Decimal("21000.00"))

    def test_full_middle_name_is_split_off(self):
        farmer = self._payload(0)["farmer"]
        self.assertEqual((farmer["last_name"], farmer["first_name"], farmer["middle_name"]),
                         ("DIMALANTA", "EDUARDO", "MENDOZA"))

        farmer = self._payload(1)["farmer"]
        self.assertEqual((farmer["last_name"], farmer["first_name"], farmer["middle_name"]),
                         ("BARIAS", "ATILANO JR.", "TAYAG"))

    def test_stage_comes_from_the_label_and_stgecode_is_not_read(self):
        seed = self._payload(0)["crop_stage_seed"]
        self.assertIsNone(seed["stage_code"])
        self.assertEqual(seed["stage_label"], "Mn. Tl. Stg. (EARLY VEGETATIVE)")

    def test_cp1252_enye_survives(self):
        self.assertEqual(self._payload(2)["boundary"]["barangay"], "SANTO NIÑO")

    def test_parenthetical_barangay_is_kept_for_the_psgc_fallback(self):
        self.assertEqual(self._payload(1)["boundary"]["barangay"], "SAN NICOLAS (POB.)")


class RepairEnyeTests(unittest.TestCase):
    """A Ñ lost to a lossy re-save arrives as '�' (U+FFFD)."""

    def test_uppercase_context_gets_capital_enye(self):
        self.assertEqual(_repair_enye("SANTO NI�O"), "SANTO NIÑO")

    def test_first_letter_of_a_word_gets_capital_enye(self):
        self.assertEqual(_repair_enye("�ANO"), "ÑANO")
        self.assertEqual(_repair_enye("Dela �eve"), "Dela Ñeve")

    def test_lowercase_context_gets_small_enye(self):
        self.assertEqual(_repair_enye("Santo Ni�o"), "Santo Niño")
        self.assertEqual(_repair_enye("Pe�a"), "Peña")

    def test_text_without_the_marker_is_untouched(self):
        self.assertEqual(_repair_enye("SAN ISIDRO"), "SAN ISIDRO")

    def test_payload_is_repaired_and_flagged(self):
        raw = (_REGION_III_HEADER + _REGION_III_ROWS.splitlines()[2].replace("Ñ", "�") + "\n")
        raw = raw.replace("BULAUN", "PE�A")
        df = pd.read_csv(io.StringIO(raw))

        payload = prepare_row_payload(df.iloc[0])

        self.assertEqual(payload["boundary"]["barangay"], "SANTO NIÑO")
        self.assertEqual(payload["farmer"]["last_name"], "PEÑA")
        self.assertTrue(payload["repaired_enye"])


class NormalizeHeaderTests(unittest.TestCase):
    def test_legacy_and_new_farm_id_headers_collide(self):
        self.assertEqual(_normalize_header("Farm ID"), _normalize_header("FARMID"))

    def test_strips_punctuation_and_casing(self):
        self.assertEqual(_normalize_header("RSBSA No."), "rsbsano")
        self.assertEqual(_normalize_header("  Policy No.  "), "policyno")


if __name__ == "__main__":
    unittest.main()
