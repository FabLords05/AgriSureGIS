import unittest
from datetime import date
from decimal import Decimal

import pandas as pd

from app.api.upload import prepare_row_payload


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

        self.assertEqual(payload["boundary"], {"province": "Bohol", "municipality": "Tagbilaran", "barangay": "Poblacion"})
        self.assertEqual(payload["farmer"], {"rsbsa_no": "RSBSA-001", "last_name": "Dela Cruz", "first_name": "Juan", "middle_name": "Santos"})
        self.assertEqual(payload["farm"], {"csv_farm_reference": "FARM-100", "georef_id": "GEO-100", "area_size": Decimal("1200.50")})
        self.assertEqual(payload["insurance"], {"policy_no": "POL-001", "amount_cover": Decimal("500000.00"), "effectivity_date": date(2024, 1, 1), "expiry_date": date(2024, 12, 31), "program_type": "Rice"})
        self.assertEqual(payload["assessment"], {"crop_stage_no": "1", "crop_stage": "Vegetative", "estimated_damage": Decimal("20.50"), "adjuster_calculation": "Early"})


if __name__ == "__main__":
    unittest.main()
