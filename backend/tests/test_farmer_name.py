import unittest
from types import SimpleNamespace

from app.core.farmer_name import format_given_first, format_surname_first


def _farmer(last_name=None, first_name=None, middle_name=None):
    return SimpleNamespace(last_name=last_name, first_name=first_name, middle_name=middle_name)


class FormatGivenFirstTests(unittest.TestCase):
    """'First Last' -- the form GET /farms/ returns as farmer_name for the Farm
    Records table and the map popup."""

    def test_both_parts(self):
        self.assertEqual(format_given_first(_farmer("ABANES", "ALFONSO")), "ALFONSO ABANES")

    def test_blank_strings_give_none_not_empty_string(self):
        # The whole point of this helper. tbl_farmers_profile.last_name/first_name
        # are NOT NULL, so CSV ingestion stored '' for a layout whose name columns
        # the parser didn't recognize yet. Returning '' here meant the frontend's
        # `farmer_name ?? "—"` never fired and the cell rendered visually empty --
        # which is exactly how 952 nameless farmers hid in plain sight (2026-10-09).
        self.assertIsNone(format_given_first(_farmer("", "")))

    def test_whitespace_only_gives_none(self):
        self.assertIsNone(format_given_first(_farmer("   ", "\t")))

    def test_nulls_give_none(self):
        self.assertIsNone(format_given_first(_farmer(None, None)))

    def test_no_farmer_gives_none(self):
        self.assertIsNone(format_given_first(None))

    def test_one_part_missing_leaves_no_stray_separator(self):
        self.assertEqual(format_given_first(_farmer("ABANES", "")), "ABANES")
        self.assertEqual(format_given_first(_farmer("", "ALFONSO")), "ALFONSO")

    def test_tolerates_a_row_without_middle_name(self):
        # search_farmers() selects only (farmer_id, first_name, last_name), so the
        # object passed in has no middle_name attribute at all.
        row = SimpleNamespace(farmer_id=1, first_name="ALFONSO", last_name="ABANES")
        self.assertEqual(format_given_first(row), "ALFONSO ABANES")


class FormatSurnameFirstTests(unittest.TestCase):
    """'Last, First' -- the form the insurance usage listing uses, and (with the
    middle initial) the payout CSV export."""

    def test_both_parts(self):
        self.assertEqual(format_surname_first(_farmer("ABANES", "ALFONSO")), "ABANES, ALFONSO")

    def test_blank_strings_give_none_not_a_bare_comma(self):
        # Previously produced ", " here and ", ." in the export.
        self.assertIsNone(format_surname_first(_farmer("", "")))
        self.assertIsNone(format_surname_first(_farmer("", ""), with_middle_initial=True))

    def test_no_farmer_gives_none(self):
        self.assertIsNone(format_surname_first(None))

    def test_one_part_missing_leaves_no_stray_separator(self):
        self.assertEqual(format_surname_first(_farmer("ABANES", "")), "ABANES")
        self.assertEqual(format_surname_first(_farmer("", "ALFONSO")), "ALFONSO")

    def test_export_shape_is_unchanged(self):
        # Reproduces the payout export's existing format exactly, trailing period
        # after the first name included -- that quirk predates this helper and the
        # column format is PCIC-facing, so it is deliberately preserved.
        self.assertEqual(
            format_surname_first(_farmer("ABANES", "ALFONSO", "FERNANDEZ"), with_middle_initial=True),
            "ABANES, ALFONSO. F.",
        )

    def test_export_shape_without_a_middle_name(self):
        self.assertEqual(
            format_surname_first(_farmer("ABANES", "ALFONSO"), with_middle_initial=True),
            "ABANES, ALFONSO.",
        )

    def test_export_shape_with_blank_middle_name(self):
        self.assertEqual(
            format_surname_first(_farmer("ABANES", "ALFONSO", "  "), with_middle_initial=True),
            "ABANES, ALFONSO.",
        )


if __name__ == "__main__":
    unittest.main()
