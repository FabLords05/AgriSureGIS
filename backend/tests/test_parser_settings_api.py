import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pydantic

from app.api.bulletins import (
    ParserSettingsUpdate,
    get_parser_settings,
    update_parser_settings,
)
from app.models.models import ParserSettings


def _fake_request(scheduler=None):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(scheduler=scheduler)))


class GetParserSettingsTests(unittest.TestCase):
    def test_creates_default_row_if_missing(self):
        mock_db = MagicMock()
        mock_db.query.return_value.first.return_value = None
        created = []
        mock_db.add.side_effect = created.append

        def refresh_side_effect(obj):
            obj.polling_interval_hours = 3
        mock_db.refresh.side_effect = refresh_side_effect

        result = get_parser_settings(db=mock_db)

        self.assertEqual(result, {"polling_interval_hours": 3})
        self.assertEqual(len(created), 1)
        self.assertIsInstance(created[0], ParserSettings)
        mock_db.commit.assert_called_once()

    def test_returns_existing_value(self):
        mock_db = MagicMock()
        mock_db.query.return_value.first.return_value = ParserSettings(polling_interval_hours=6)

        result = get_parser_settings(db=mock_db)

        self.assertEqual(result, {"polling_interval_hours": 6})
        mock_db.add.assert_not_called()


class UpdateParserSettingsTests(unittest.TestCase):
    @patch("app.api.bulletins.reschedule_bulletin_job")
    def test_persists_new_value_and_reschedules(self, mock_reschedule):
        existing = ParserSettings(polling_interval_hours=3)
        mock_db = MagicMock()
        mock_db.query.return_value.first.return_value = existing
        mock_scheduler = MagicMock()

        result = update_parser_settings(
            payload=ParserSettingsUpdate(polling_interval_hours=8),
            request=_fake_request(scheduler=mock_scheduler),
            db=mock_db,
        )

        self.assertEqual(existing.polling_interval_hours, 8)
        mock_db.commit.assert_called_once()
        mock_reschedule.assert_called_once_with(mock_scheduler, 8)
        self.assertEqual(result, {"polling_interval_hours": 8})

    def test_rejects_value_below_1(self):
        with self.assertRaises(pydantic.ValidationError):
            ParserSettingsUpdate(polling_interval_hours=0)

    def test_rejects_value_above_24(self):
        with self.assertRaises(pydantic.ValidationError):
            ParserSettingsUpdate(polling_interval_hours=25)


if __name__ == "__main__":
    unittest.main()
