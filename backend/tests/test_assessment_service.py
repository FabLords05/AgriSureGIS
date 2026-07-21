import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.models.models import IndemnityFactorMatrix, InsuranceRecord, RecsapMatrix, RiskAssessment, TropicalCycloneBulletin
from app.services.assessment_service import AssessmentService


class AssessmentServiceTests(unittest.TestCase):
    def _bulletin(self):
        return MagicMock(
            spec=TropicalCycloneBulletin,
            tcb_id=12,
            typhoon_id=1,
            issued_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        )

    def _summary(self, boundary_id=5, max_signal_level=3, total_exposure_hours=12.0):
        return MagicMock(
            summary_id=99,
            boundary_id=boundary_id,
            max_signal_level=max_signal_level,
            total_exposure_hours=total_exposure_hours,
        )

    def _insurance_record(self, insurance_records_id=7, area_size="2.5", amount_cover="50000.00"):
        farm = MagicMock(area_size=Decimal(area_size))
        return MagicMock(
            spec=InsuranceRecord,
            insurance_records_id=insurance_records_id,
            farm=farm,
            amount_cover=Decimal(amount_cover),
            effectivity_date=date(2026, 1, 1),
            expiry_date=date(2026, 12, 31),
        )

    def _build_mock_db(
        self,
        bulletin,
        insurance_records,
        prior_assessment,
        yield_loss_rule,
        indemnity_rule=None,
        existing_assessment=None,
    ):
        mock_db = MagicMock()

        bulletin_query = MagicMock()
        bulletin_query.filter.return_value.first.return_value = bulletin

        insurance_query = MagicMock()
        insurance_query.join.return_value.filter.return_value.all.return_value = insurance_records

        # get_matrix_rule() does two chained lookups: RecsapMatrix (yield loss %)
        # then, only if that matched, IndemnityFactorMatrix (indemnity factor).
        yield_loss_query = MagicMock()
        yield_loss_query.filter.return_value.first.return_value = yield_loss_rule

        indemnity_query = MagicMock()
        indemnity_query.filter.return_value.first.return_value = indemnity_rule

        risk_assessment_returns = []
        for _ in insurance_records:
            prior_query = MagicMock()
            prior_query.filter.return_value.order_by.return_value.first.return_value = prior_assessment
            existing_query = MagicMock()
            existing_query.filter.return_value.first.return_value = existing_assessment
            risk_assessment_returns.extend([prior_query, existing_query])
        risk_assessment_calls = iter(risk_assessment_returns)

        def query_side_effect(model):
            if model is TropicalCycloneBulletin:
                return bulletin_query
            if model is InsuranceRecord:
                return insurance_query
            if model is RecsapMatrix:
                return yield_loss_query
            if model is IndemnityFactorMatrix:
                return indemnity_query
            if model is RiskAssessment:
                return next(risk_assessment_calls)
            raise AssertionError(f"Unexpected model queried in test: {model}")

        mock_db.query.side_effect = query_side_effect
        return mock_db

    @patch("app.services.assessment_service.ExposureCalculatorService.compute_for_typhoon")
    def test_calculate_for_bulletin_creates_assessment_for_eligible_policy(self, mock_compute):
        bulletin = self._bulletin()
        summary = self._summary()
        mock_compute.return_value = [summary]

        insurance = self._insurance_record()
        prior = MagicMock(spec=RiskAssessment, crop_stage_no=2, crop_stage="Flowering")
        # Flowering -> Reproductive stage group; 25.00% falls in the >20 to 25 bracket.
        yield_loss_rule = MagicMock(spec=RecsapMatrix, matrix_id=3, estimated_yield_loss=Decimal("25.00"))
        indemnity_rule = MagicMock(spec=IndemnityFactorMatrix, indemnity_id=8, indemnity_factor=Decimal("330.00"))

        mock_db = self._build_mock_db(bulletin, [insurance], prior, yield_loss_rule, indemnity_rule)

        results = AssessmentService.calculate_for_bulletin(1, 12, mock_db)

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result.insurance_records_id, 7)
        self.assertEqual(result.summary_id, 99)
        self.assertEqual(result.matrix_id, 3)
        self.assertEqual(result.indemnity_matrix_id, 8)
        self.assertEqual(result.crop_stage_no, 2)
        self.assertEqual(result.crop_stage, "Flowering")
        self.assertEqual(result.period_of_exposure, 12)
        self.assertEqual(result.wind_velocity, 3)
        # I = (AC / 1000) * IF * Area = (50000 / 1000) * 330.00 * 2.5 = 41250.0
        self.assertEqual(result.final_indemnity_payment, 41250.0)
        self.assertEqual(result.estimated_damage, 12500.0)  # 50000 * 25 / 100
        mock_db.commit.assert_called_once()

    @patch("app.services.assessment_service.ExposureCalculatorService.compute_for_typhoon")
    def test_calculate_for_bulletin_skips_ineligible_crop_stage(self, mock_compute):
        bulletin = self._bulletin()
        summary = self._summary()
        mock_compute.return_value = [summary]

        insurance = self._insurance_record()
        prior = MagicMock(spec=RiskAssessment, crop_stage_no=5, crop_stage="Ripening")

        mock_db = self._build_mock_db(bulletin, [insurance], prior, yield_loss_rule=None)

        results = AssessmentService.calculate_for_bulletin(1, 12, mock_db)

        self.assertEqual(results, [])
        mock_db.commit.assert_called_once()

    @patch("app.services.assessment_service.ExposureCalculatorService.compute_for_typhoon")
    def test_calculate_for_bulletin_skips_summary_below_signal_threshold(self, mock_compute):
        bulletin = self._bulletin()
        summary = self._summary(max_signal_level=1)
        mock_compute.return_value = [summary]

        mock_db = self._build_mock_db(bulletin, [], prior_assessment=None, yield_loss_rule=None)

        results = AssessmentService.calculate_for_bulletin(1, 12, mock_db)

        self.assertEqual(results, [])

    def test_calculate_for_bulletin_raises_if_bulletin_not_found(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with self.assertRaises(ValueError):
            AssessmentService.calculate_for_bulletin(1, 999, mock_db)


if __name__ == "__main__":
    unittest.main()
