import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.crop_stage_resolver import (
    CropStageResolver,
    coerce_stage_code,
    normalize_stage_label,
)


def _mapping(source_code=None, source_label=None, pcic_stage="XX", crop_stage_no=None, stage_group=None):
    return SimpleNamespace(
        source_code=source_code,
        source_label=source_label,
        pcic_stage=pcic_stage,
        crop_stage_no=crop_stage_no,
        stage_group=stage_group,
    )


# The subset of init_schema.sql's seed the assertions below actually lean on.
SEED = [
    _mapping(source_code=1, pcic_stage="MnTl", crop_stage_no=None, stage_group="Early Vegetative"),
    _mapping(source_code=3, pcic_stage="PI", crop_stage_no=None, stage_group="Reproductive"),
    _mapping(source_code=4, pcic_stage="BS", crop_stage_no=1, stage_group="Reproductive"),
    _mapping(source_code=6, pcic_stage="MS", crop_stage_no=2, stage_group="Late Reproductive"),
    _mapping(source_code=7, pcic_stage="SD", crop_stage_no=3, stage_group="Maturity"),
    _mapping(source_label="flowering", pcic_stage="FS", crop_stage_no=2, stage_group="Reproductive"),
    _mapping(source_label="milking stage", pcic_stage="MS", crop_stage_no=2, stage_group="Late Reproductive"),
    _mapping(source_label="dough stage", pcic_stage="SD/HD", crop_stage_no=3, stage_group="Maturity"),
    _mapping(source_label="panicle initiation/booting", pcic_stage="PI/BS", crop_stage_no=None, stage_group=None),
    _mapping(source_label="harvested", pcic_stage="Harvested", crop_stage_no=None, stage_group=None),
]


def _mock_db(rows=SEED):
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = rows
    return db


class NormalizationTests(unittest.TestCase):
    def test_label_is_lowercased_and_whitespace_collapsed(self):
        self.assertEqual(normalize_stage_label("  Dough   Stage "), "dough stage")

    def test_label_keeps_the_slash(self):
        # upload.py's _normalize_header() strips punctuation from column NAMES, but
        # doing that here would destroy the distinction between PCIC's merged
        # labels and the single stages they join.
        self.assertEqual(
            normalize_stage_label("Panicle Initiation/Booting"), "panicle initiation/booting"
        )

    def test_blank_label_is_none(self):
        self.assertIsNone(normalize_stage_label("   "))
        self.assertIsNone(normalize_stage_label(None))

    def test_stage_code_accepts_every_shape_pandas_infers(self):
        # The column lands as int64, float64 (when any row is blank) or object
        # depending on the file.
        for value in (4, 4.0, "4", " 4 "):
            self.assertEqual(coerce_stage_code(value), 4, msg=repr(value))

    def test_non_integral_stage_code_is_rejected(self):
        self.assertIsNone(coerce_stage_code(4.5))
        self.assertIsNone(coerce_stage_code("Booting"))
        self.assertIsNone(coerce_stage_code(""))
        self.assertIsNone(coerce_stage_code(None))


class CropStageResolverTests(unittest.TestCase):
    def setUp(self):
        self.resolver = CropStageResolver.load(_mock_db())

    def test_resolves_legacy_integer_code(self):
        resolved = self.resolver.resolve(stage_code=4)

        self.assertEqual(resolved.crop_stage_no, 1)
        self.assertEqual(resolved.stage_group, "Reproductive")
        self.assertEqual(resolved.pcic_stage, "BS")
        self.assertEqual(resolved.matched_by, "code")
        self.assertTrue(resolved.is_assessable)

    def test_resolves_new_text_label(self):
        resolved = self.resolver.resolve(stage_label="Dough Stage")

        self.assertEqual(resolved.crop_stage_no, 3)
        self.assertEqual(resolved.stage_group, "Maturity")
        self.assertEqual(resolved.matched_by, "label")

    def test_milking_and_flowering_share_a_stage_no_but_not_a_group(self):
        # The whole reason stage_group is resolved independently rather than derived
        # from crop_stage_no: PCIC pairs FS/MS for yield loss (Tables 9 and 10) while
        # Table 1 keeps them in different groups.
        flowering = self.resolver.resolve(stage_label="Flowering")
        milking = self.resolver.resolve(stage_label="Milking Stage")

        self.assertEqual(flowering.crop_stage_no, milking.crop_stage_no)
        self.assertEqual(flowering.stage_group, "Reproductive")
        self.assertEqual(milking.stage_group, "Late Reproductive")

    def test_legacy_code_wins_when_a_row_carries_both_signals(self):
        # The integer code distinguishes PI from BS; the merged label cannot.
        resolved = self.resolver.resolve(stage_code=4, stage_label="Panicle Initiation/Booting")

        self.assertEqual(resolved.crop_stage_no, 1)
        self.assertEqual(resolved.matched_by, "code")

    def test_held_pi_booting_label_resolves_to_nothing_assessable(self):
        resolved = self.resolver.resolve(stage_label="Panicle Initiation/Booting")

        self.assertIsNone(resolved.crop_stage_no)
        self.assertIsNone(resolved.stage_group)
        self.assertFalse(resolved.is_assessable)
        # It IS a known row, so it must not be reported as unmapped.
        self.assertEqual(resolved.matched_by, "label")

    def test_ineligible_stage_still_carries_its_group(self):
        # Tillering takes no wind damage (Table 11 Note 1) but is not "unknown".
        resolved = self.resolver.resolve(stage_code=1)

        self.assertIsNone(resolved.crop_stage_no)
        self.assertEqual(resolved.stage_group, "Early Vegetative")

    def test_unknown_value_resolves_to_nothing_and_warns_once_per_value(self):
        with self.assertLogs("app.services.crop_stage_resolver", level="WARNING") as captured:
            first = self.resolver.resolve(stage_label="Ratooning")
            self.resolver.resolve(stage_label="Ratooning")
            self.resolver.resolve(stage_label="Germination")

        self.assertIsNone(first.crop_stage_no)
        self.assertIsNone(first.matched_by)
        # Two distinct unknown values, three calls -- a 1,100-row file with one bad
        # stage must not emit 1,100 log lines.
        self.assertEqual(len(captured.output), 2)

    def test_blank_stage_is_silent(self):
        # A row with no stage column at all is normal for a partial export; it is
        # not an unmapped value and must not warn.
        resolver = CropStageResolver.load(_mock_db())
        with self.assertNoLogs("app.services.crop_stage_resolver", level="WARNING"):
            resolved = resolver.resolve(stage_code=None, stage_label=None)

        self.assertIsNone(resolved.crop_stage_no)
        self.assertIsNone(resolved.matched_by)

    def test_empty_mapping_table_warns_on_load(self):
        with self.assertLogs("app.services.crop_stage_resolver", level="WARNING"):
            resolver = CropStageResolver.load(_mock_db(rows=[]))

        self.assertIsNone(resolver.resolve(stage_label="Dough Stage").crop_stage_no)


if __name__ == "__main__":
    unittest.main()
