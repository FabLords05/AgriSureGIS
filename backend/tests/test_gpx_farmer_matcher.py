import unittest
from unittest.mock import MagicMock

from app.models.models import Farm, FarmerProfile
from app.services.gpx_farmer_matcher import GpxFarmerMatcherService

REAL_SAMPLE_FILENAME = "TAB_ABAO , JONEL  J._120961_1148107_2024-08-06.gpx"


class ParseGpxFilenameTests(unittest.TestCase):
    def test_parses_real_sample_filename(self):
        parsed = GpxFarmerMatcherService.parse_filename(REAL_SAMPLE_FILENAME)

        self.assertEqual(parsed.last_name, "ABAO")
        self.assertEqual(parsed.first_name, "JONEL")
        self.assertEqual(parsed.middle_initial, "J")
        self.assertEqual(parsed.id1, "120961")
        self.assertEqual(parsed.id2, "1148107")
        self.assertEqual(parsed.walk_date, "2024-08-06")

    def test_recovers_ids_even_without_tab_prefix(self):
        parsed = GpxFarmerMatcherService.parse_filename("ABAO , JONEL  J._120961_1148107_2024-08-06.gpx")

        self.assertEqual(parsed.id1, "120961")
        self.assertEqual(parsed.id2, "1148107")

    def test_recovers_ids_when_name_portion_has_no_comma(self):
        parsed = GpxFarmerMatcherService.parse_filename("UNSTRUCTURED_NAME_120961_1148107_2024-08-06.gpx")

        self.assertEqual(parsed.id1, "120961")
        self.assertEqual(parsed.id2, "1148107")
        self.assertEqual(parsed.walk_date, "2024-08-06")
        self.assertIsNone(parsed.last_name)

    def test_missing_ids_still_recovers_name(self):
        parsed = GpxFarmerMatcherService.parse_filename("TAB_ABAO , JONEL  J..gpx")

        self.assertEqual(parsed.last_name, "ABAO")
        self.assertEqual(parsed.first_name, "JONEL")
        self.assertEqual(parsed.middle_initial, "J")
        self.assertIsNone(parsed.id1)
        self.assertIsNone(parsed.id2)


def _mock_db(farmer_query, farm_query):
    mock_db = MagicMock()

    def side_effect(model):
        if model is FarmerProfile:
            return farmer_query
        if model is Farm:
            return farm_query
        raise AssertionError(f"Unexpected model queried in test: {model}")

    mock_db.query.side_effect = side_effect
    return mock_db


class GpxFarmerMatcherServiceMatchTests(unittest.TestCase):
    def test_matches_via_farmers_id_first(self):
        farmer = MagicMock(spec=FarmerProfile, farmer_id=1, farmers_id="120961")
        farm = MagicMock(spec=Farm, farm_id=10, farmer_id=1, csv_farm_reference="1148107")

        farmer_query = MagicMock()
        farmer_query.filter.return_value.first.return_value = farmer
        farm_query = MagicMock()
        farm_query.filter.return_value.all.return_value = [farm]  # _pick_farm's farmer_id lookup

        result = GpxFarmerMatcherService.match(REAL_SAMPLE_FILENAME, _mock_db(farmer_query, farm_query))

        self.assertEqual(result.matched_by, "farmers_id")
        self.assertIs(result.farm, farm)
        self.assertIs(result.farmer, farmer)

    def test_falls_back_to_farm_reference_when_farmers_id_has_no_match(self):
        matched_farmer = MagicMock(spec=FarmerProfile, farmer_id=2)
        matched_farm = MagicMock(spec=Farm, farm_id=20, csv_farm_reference="1148107", farmer=matched_farmer)

        farmer_query = MagicMock()
        farmer_query.filter.return_value.first.return_value = None  # id1 lookup: nobody
        farm_query = MagicMock()
        farm_query.filter.return_value.first.return_value = matched_farm  # id2 lookup: hit

        result = GpxFarmerMatcherService.match(REAL_SAMPLE_FILENAME, _mock_db(farmer_query, farm_query))

        self.assertEqual(result.matched_by, "farm_reference")
        self.assertIs(result.farm, matched_farm)
        self.assertIs(result.farmer, matched_farmer)

    def test_falls_back_to_normalized_name_when_single_candidate(self):
        candidate = MagicMock(spec=FarmerProfile, farmer_id=3, middle_name="Beberreno")
        matched_farm = MagicMock(spec=Farm, farm_id=30, csv_farm_reference="0000000")

        farmer_query = MagicMock()
        farmer_query.filter.return_value.first.return_value = None       # id1 lookup: nobody
        farmer_query.filter.return_value.all.return_value = [candidate]  # name lookup: exactly one
        farm_query = MagicMock()
        farm_query.filter.return_value.first.return_value = None          # id2 lookup: nobody
        farm_query.filter.return_value.all.return_value = [matched_farm]  # _pick_farm's farmer_id lookup

        result = GpxFarmerMatcherService.match(REAL_SAMPLE_FILENAME, _mock_db(farmer_query, farm_query))

        # Real-world proof point: filename middle initial "J" disagrees with this
        # farmer's actual middle name "Beberreno" -- match must succeed anyway,
        # since middle name/initial is only ever a tiebreaker, never a requirement.
        self.assertEqual(result.matched_by, "name")
        self.assertIs(result.farmer, candidate)
        self.assertIs(result.farm, matched_farm)

    def test_middle_initial_resolves_ambiguous_name_candidates(self):
        wrong_candidate = MagicMock(spec=FarmerProfile, farmer_id=4, middle_name="Reyes")
        right_candidate = MagicMock(spec=FarmerProfile, farmer_id=5, middle_name="Juntilla")
        matched_farm = MagicMock(spec=Farm, farm_id=50, csv_farm_reference="0000000")

        farmer_query = MagicMock()
        farmer_query.filter.return_value.first.return_value = None
        farmer_query.filter.return_value.all.return_value = [wrong_candidate, right_candidate]
        farm_query = MagicMock()
        farm_query.filter.return_value.first.return_value = None
        farm_query.filter.return_value.all.return_value = [matched_farm]

        result = GpxFarmerMatcherService.match(REAL_SAMPLE_FILENAME, _mock_db(farmer_query, farm_query))

        self.assertEqual(result.matched_by, "name+middle_initial")
        self.assertIs(result.farmer, right_candidate)

    def test_returns_ambiguous_candidates_when_unresolvable(self):
        candidate_a = MagicMock(spec=FarmerProfile, farmer_id=6, middle_name="Reyes")
        candidate_b = MagicMock(spec=FarmerProfile, farmer_id=7, middle_name="Ramos")

        farmer_query = MagicMock()
        farmer_query.filter.return_value.first.return_value = None
        farmer_query.filter.return_value.all.return_value = [candidate_a, candidate_b]
        farm_query = MagicMock()
        farm_query.filter.return_value.first.return_value = None

        result = GpxFarmerMatcherService.match(REAL_SAMPLE_FILENAME, _mock_db(farmer_query, farm_query))

        self.assertIsNone(result.farm)
        self.assertIsNone(result.farmer)
        self.assertEqual(result.candidates, [candidate_a, candidate_b])

    def test_returns_empty_result_when_nothing_matches(self):
        # Mirrors the real, confirmed case: docs/TAB_ABAO , JONEL  J._120961_1148107_2024-08-06.gpx
        # does not correspond to any row in the new PABS CSV/XLSX exports.
        farmer_query = MagicMock()
        farmer_query.filter.return_value.first.return_value = None
        farmer_query.filter.return_value.all.return_value = []
        farm_query = MagicMock()
        farm_query.filter.return_value.first.return_value = None

        result = GpxFarmerMatcherService.match(REAL_SAMPLE_FILENAME, _mock_db(farmer_query, farm_query))

        self.assertIsNone(result.farm)
        self.assertIsNone(result.farmer)
        self.assertEqual(result.candidates, [])


if __name__ == "__main__":
    unittest.main()
