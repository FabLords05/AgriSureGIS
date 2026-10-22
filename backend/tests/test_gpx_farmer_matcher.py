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


class ParseRealPcicFilenameTests(unittest.TestCase):
    """Name shapes seen in PCIC's Region II GPX folder (2026-10-22)."""

    def test_any_uploader_prefix_is_stripped_from_the_name(self):
        for prefix in ("GE_", "R02_", "FAM02_", "AGRILEVER02_", "TAB_"):
            parsed = GpxFarmerMatcherService.parse_filename(f"{prefix}ABAD, NENA A._479740_1867860_2025-10-10.gpx")
            self.assertEqual((parsed.last_name, parsed.first_name), ("ABAD", "NENA"), prefix)
            self.assertEqual((parsed.id1, parsed.id2), ("479740", "1867860"), prefix)

    def test_spaces_around_separators_still_yield_ids(self):
        for filename in (
            "GE_DELA CRUZ, JUAN P._ 123_456_2024-08-17.gpx",
            "GE_DELA CRUZ, JUAN P._123_1783621 2024-08-21.gpx",
            "GE_DELA CRUZ, JUAN P._123_456_2025-10-07 .gpx",
            "GE_DELA CRUZ, JUAN P._14571 _474510_2025-10-07.gpx",
        ):
            parsed = GpxFarmerMatcherService.parse_filename(filename)
            self.assertIsNotNone(parsed.id1, filename)
            self.assertIsNotNone(parsed.id2, filename)

    def test_month_first_date_is_normalised(self):
        parsed = GpxFarmerMatcherService.parse_filename("R02_DOE, JANE D._123_456_07-16-2025.gpx")
        self.assertEqual(parsed.walk_date, "2025-07-16")


class MatchFileTests(unittest.TestCase):
    def test_track_file_name_from_the_csv_wins(self):
        farm = MagicMock(spec=Farm, farm_id=7)
        farm_query = MagicMock()
        farm_query.filter.return_value.all.return_value = [farm]

        result = GpxFarmerMatcherService.match_file(REAL_SAMPLE_FILENAME, _mock_db(MagicMock(), farm_query))

        self.assertEqual(result.matched_by, "track_file_name")
        self.assertIs(result.farm, farm)

    def test_georef_named_file_matches_georef_id(self):
        farm = MagicMock(spec=Farm, farm_id=8)
        farm_query = MagicMock()
        farm_query.filter.return_value.all.side_effect = [[], [farm]]  # no track-file hit, then georef

        result = GpxFarmerMatcherService.match_file("R02-15-26-012-000079.gpx", _mock_db(MagicMock(), farm_query))

        self.assertEqual(result.matched_by, "georef_id")
        self.assertIs(result.farm, farm)


class ParseFarmerNameTests(unittest.TestCase):
    """parse_farmer_name() is shared by the GPX filename parser, GeoPackage
    ingestion and (since 2026-10-09) CSV ingestion of the newer PABS export's
    combined "FARMER NAME" column -- all three must agree on the split, or a
    farmer created from the CSV won't match the .gpkg feature carrying its
    boundary."""

    def test_splits_last_first_and_middle_initial(self):
        self.assertEqual(
            GpxFarmerMatcherService.parse_farmer_name("ABARICO, REPARADA C."),
            ("ABARICO", "REPARADA", "C"),
        )

    def test_compound_first_name_is_kept_whole(self):
        # 131 of the real export's 1,114 rows carry three or more tokens after the
        # comma; taking only the first dropped "MARIE" here before 2026-10-09.
        self.assertEqual(
            GpxFarmerMatcherService.parse_farmer_name("ACERO, ANNA MARIE S."),
            ("ACERO", "ANNA MARIE", "S"),
        )

    def test_suffix_stays_with_the_first_name(self):
        self.assertEqual(
            GpxFarmerMatcherService.parse_farmer_name("APAL, ROY SR. C."),
            ("APAL", "ROY SR.", "C"),
        )

    def test_trailing_word_that_is_not_an_initial_is_part_of_the_first_name(self):
        self.assertEqual(
            GpxFarmerMatcherService.parse_farmer_name("SMITH, JOHN PAUL"),
            ("SMITH", "JOHN PAUL", None),
        )

    def test_single_first_name_has_no_middle_initial(self):
        self.assertEqual(
            GpxFarmerMatcherService.parse_farmer_name("SMITH, JOHN"),
            ("SMITH", "JOHN", None),
        )

    def test_name_without_a_comma_yields_nothing(self):
        self.assertEqual(GpxFarmerMatcherService.parse_farmer_name("UNSTRUCTURED NAME"), (None, None, None))


class ParseFullMiddleNameTests(unittest.TestCase):
    """full_middle_name=True: the official Region III CSV writes the whole middle
    name, so a trailing word is the middle name -- which also lines its first
    name up with the GPX filename's ('TAB_DIMALANTA, EDUARDO M._...')."""

    def _parse(self, name):
        return GpxFarmerMatcherService.parse_farmer_name(name, full_middle_name=True)

    def test_last_word_is_the_middle_name(self):
        self.assertEqual(self._parse("DIMALANTA, EDUARDO MENDOZA"), ("DIMALANTA", "EDUARDO", "MENDOZA"))

    def test_extension_stays_with_the_first_name(self):
        self.assertEqual(self._parse("BARIAS, ATILANO JR. TAYAG"), ("BARIAS", "ATILANO JR.", "TAYAG"))

    def test_trailing_extension_is_not_a_middle_name(self):
        self.assertEqual(self._parse("CRUZ, JUAN JR."), ("CRUZ", "JUAN JR.", None))

    def test_trailing_initial_still_reads_as_before(self):
        self.assertEqual(self._parse("ACERO, ANNA MARIE S."), ("ACERO", "ANNA MARIE", "S"))

    def test_single_first_name_has_no_middle_name(self):
        self.assertEqual(self._parse("SMITH, JOHN"), ("SMITH", "JOHN", None))

    def test_default_is_unchanged_for_gpx_and_gpkg(self):
        self.assertEqual(
            GpxFarmerMatcherService.parse_farmer_name("DIMALANTA, EDUARDO MENDOZA"),
            ("DIMALANTA", "EDUARDO MENDOZA", None),
        )



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
        matched_farm = MagicMock(spec=Farm, farm_id=30, csv_farm_reference="1148107")

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
        matched_farm = MagicMock(spec=Farm, farm_id=50, csv_farm_reference="1148107")

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

    def test_farm_id_in_filename_must_agree_with_the_farmers_farm(self):
        # 2026-10-22: the farmer (by FarmersID) has one farm, but it is not the
        # FarmID the file names -- that used to put the boundary on it anyway.
        farmer = MagicMock(spec=FarmerProfile, farmer_id=1, farmers_id="120961", middle_name=None)
        other_farm = MagicMock(spec=Farm, farm_id=10, farmer_id=1, csv_farm_reference="9999999")

        farmer_query = MagicMock()
        farmer_query.filter.return_value.first.return_value = farmer
        farmer_query.filter.return_value.all.return_value = []
        farm_query = MagicMock()
        farm_query.filter.return_value.all.return_value = [other_farm]
        farm_query.filter.return_value.first.return_value = None

        result = GpxFarmerMatcherService.match(REAL_SAMPLE_FILENAME, _mock_db(farmer_query, farm_query))

        self.assertIsNone(result.farm)

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
