from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.models import IndemnityFactorMatrix, RecsapMatrix

# tbl_recsap_matrix's crop_stage_no (1=Booting, 2=Flowering, 3=Maturity) uses a
# different, 3-stage taxonomy than tbl_indemnity_factor_matrix's crop_stage_group,
# which follows PCIC's own 5-stage taxonomy. Mapping confirmed with Fabio; not
# stated verbatim in the manuscript.
CROP_STAGE_TO_INDEMNITY_GROUP = {
    1: "Late Vegetative",  # Booting
    2: "Reproductive",  # Flowering
    3: "Maturity",  # Maturity
}


def _bucket_exposure_hours(exposure_hours: int) -> int | None:
    """Round raw exposure hours down to the matrix's discrete brackets (6/12/24)."""
    if exposure_hours >= 24:
        return 24
    if exposure_hours >= 12:
        return 12
    if exposure_hours >= 6:
        return 6
    return None


@dataclass
class ParametricRule:
    """Result of the two-step PCIC lookup, bundling both source rows' ids/values."""

    matrix_id: int
    indemnity_matrix_id: int
    estimated_yield_loss: Decimal
    indemnity_factor: Decimal


class ParametricAssessment:
    def __init__(self, db: Session):
        self.db = db

    def get_matrix_rule(
        self, crop_stage_no: int, wind_signal_tcws: int, exposure_hours: int
    ) -> ParametricRule | None:
        """Two-step PCIC lookup: (1) tbl_recsap_matrix for yield loss %, then
        (2) tbl_indemnity_factor_matrix for the indemnity factor, by yield-loss
        bracket and crop-stage group. Brackets are exclusive-lower/inclusive-upper
        (e.g. ">10 to 15" matches yield_loss_min < x <= yield_loss_max)."""
        bucketed_hours = _bucket_exposure_hours(exposure_hours)
        if bucketed_hours is None:
            return None

        yield_loss_rule = (
            self.db.query(RecsapMatrix)
            .filter(
                RecsapMatrix.crop_stage_no == crop_stage_no,
                RecsapMatrix.wind_signal_tcws == wind_signal_tcws,
                RecsapMatrix.exposure_hours == bucketed_hours,
                RecsapMatrix.is_active.is_(True),
            )
            .first()
        )
        if yield_loss_rule is None:
            return None

        stage_group = CROP_STAGE_TO_INDEMNITY_GROUP.get(crop_stage_no)
        if stage_group is None:
            return None

        indemnity_rule = (
            self.db.query(IndemnityFactorMatrix)
            .filter(
                IndemnityFactorMatrix.crop_stage_group == stage_group,
                IndemnityFactorMatrix.yield_loss_min < yield_loss_rule.estimated_yield_loss,
                IndemnityFactorMatrix.yield_loss_max >= yield_loss_rule.estimated_yield_loss,
                IndemnityFactorMatrix.is_active.is_(True),
            )
            .first()
        )
        if indemnity_rule is None:
            return None

        return ParametricRule(
            matrix_id=yield_loss_rule.matrix_id,
            indemnity_matrix_id=indemnity_rule.indemnity_id,
            estimated_yield_loss=yield_loss_rule.estimated_yield_loss,
            indemnity_factor=indemnity_rule.indemnity_factor,
        )

    def calculate_final_payout(
        self,
        amount_of_cover: float,
        crop_stage_no: int,
        wind_signal_tcws: int,
        exposure_hours: int,
    ) -> float:
        """Final Indemnity Payout Calculation: I = (AC / 1000) * IF.

        Per PCIC (the source of this formula), farm area is NOT a factor here --
        confirmed with Fabio 2026-07-23, correcting the earlier (AC/1000)*IF*Area
        version this engine originally shipped with.
        """
        rule = self.get_matrix_rule(crop_stage_no, wind_signal_tcws, exposure_hours)
        if rule is None:
            return 0.0

        payout = (amount_of_cover / 1000) * float(rule.indemnity_factor)
        return round(payout, 2)


# --- Interactive Terminal Execution for Manual Testing ---
if __name__ == "__main__":
    from app.core.database import SessionLocal

    session = SessionLocal()
    assessment = ParametricAssessment(session)

    print("\n" + "=" * 50)
    print("   AgriSureGIS Manual Parametric Testing Tool")
    print("=" * 50)

    try:
        ac = float(input("1. Amount of Cover per hectare (e.g., 25000): "))
        tcws = int(input("2. Peak TCWS Level (e.g., 2, 3, 4, 5): "))
        hours = int(input("3. Period of Exposure in hours (e.g., 6, 12, 24): "))
        crop_stage_no = int(input("4. Crop Stage No. (per tbl_recsap_matrix, e.g., 2 for Flowering): "))

        rule = assessment.get_matrix_rule(crop_stage_no, tcws, hours)
        payout = assessment.calculate_final_payout(ac, crop_stage_no, tcws, hours)

        print("\n" + "-" * 50)
        print("               ASSESSMENT RESULTS")
        print("-" * 50)
        if rule is None:
            print("No matching rule found (yield loss/indemnity bracket, invalid stage, or exposure below 6 hours).")
        else:
            print(f"Estimated Yield Loss:     {rule.estimated_yield_loss}%")
            print(f"Applied Indemnity Factor: {rule.indemnity_factor}")
        print(f"FINAL INDEMNITY PAYOUT:   ₱{payout:,.2f}")
        print("-" * 50 + "\n")

    except ValueError:
        print("\n[ERROR] Invalid input detected. Please ensure you are entering numbers for Cover, Area, TCWS, Hours, and Stage No.")
    finally:
        session.close()
