import unittest

import pandas as pd

from scripts.convert_psgc_publication import convert_rows, preserve_existing_names


def _psa_rows(rows):
    return pd.DataFrame(rows, columns=["10-digit PSGC", "Name", "Geographic Level"])


class ConvertPsgcPublicationTests(unittest.TestCase):
    def _convert(self, rows):
        return convert_rows(_psa_rows(rows), "Geographic Level", "10-digit PSGC", "Name")

    def test_regular_province_city_barangay_chain(self):
        out = self._convert([
            ("1000000000", "Region X", "Reg"),
            ("1001300000", "Bukidnon", "Prov"),
            ("1001301000", "Baungon", "Mun"),
            ("1001301001", "Balintad", "Bgy"),
        ])
        self.assertEqual(out.to_dict("records"), [
            {"psgc_code": "1001301001", "province": "Bukidnon", "municipality": "Baungon", "barangay": "Balintad"},
        ])

    def test_every_ncr_city_is_its_own_province(self):
        # Regression: the old `if current_province is None` check only caught
        # the first NCR city -- every later one inherited its name as province.
        out = self._convert([
            ("1300000000", "NCR", "Reg"),
            ("1380100000", "City of Caloocan", "City"),
            ("1380100001", "Barangay 1", "Bgy"),
            ("1380200000", "City of Las Piñas", "City"),
            ("1380200001", "Almanza Uno", "Bgy"),
        ])
        self.assertEqual(list(out["province"]), ["City of Caloocan", "City of Las Piñas"])

    def test_huc_after_a_regular_province_does_not_inherit_it(self):
        out = self._convert([
            ("1000000000", "Region X", "Reg"),
            ("1004300000", "Misamis Oriental", "Prov"),
            ("1004301000", "Alubijid", "Mun"),
            ("1004301001", "Baybay", "Bgy"),
            ("1030500000", "City of Cagayan De Oro", "City"),
            ("1030500001", "Agusan", "Bgy"),
        ])
        self.assertEqual(
            list(zip(out["province"], out["municipality"])),
            [("Misamis Oriental", "Alubijid"), ("City of Cagayan De Oro", "City of Cagayan De Oro")],
        )

    def test_submunicipality_barangays_stay_under_parent_city(self):
        out = self._convert([
            ("1300000000", "NCR", "Reg"),
            ("1380600000", "City of Manila", "City"),
            ("1380601000", "Tondo I/II", "SubMun"),
            ("1380601001", "Barangay 1", "Bgy"),
        ])
        self.assertEqual(out.iloc[0]["municipality"], "City of Manila")

    def test_numeric_code_regains_leading_zero(self):
        out = self._convert([
            ("100000000", "Region I", "Reg"),
            ("102800000", "Ilocos Norte", "Prov"),
            ("102801000", "Adams", "Mun"),
            ("102801001", "Adams", "Bgy"),
        ])
        self.assertEqual(out.iloc[0]["psgc_code"], "0102801001")
        self.assertEqual(out.iloc[0]["province"], "Ilocos Norte")

    def test_preserve_existing_names_keeps_current_spelling_and_rows(self):
        new_df = pd.DataFrame([
            {"psgc_code": "1660201001", "province": "City of Butuan", "municipality": "City of Butuan", "barangay": "Agao"},
            {"psgc_code": "0102801001", "province": "Ilocos Norte", "municipality": "Adams", "barangay": "Adams"},
        ])
        existing_df = pd.DataFrame([
            {"psgc_code": "1660201001", "province": "Agusan del Norte", "municipality": "City of Butuan", "barangay": "Agao"},
            {"psgc_code": "9999999999", "province": "Old", "municipality": "Old", "barangay": "Old"},
        ])

        out = preserve_existing_names(new_df, existing_df).set_index("psgc_code")

        self.assertEqual(out.loc["1660201001", "province"], "Agusan del Norte")
        self.assertEqual(out.loc["0102801001", "province"], "Ilocos Norte")
        self.assertIn("9999999999", out.index)  # kept, not dropped
