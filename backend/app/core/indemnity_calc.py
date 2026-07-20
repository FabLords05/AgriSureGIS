from sqlalchemy.orm import Session

from app.models.models import RecsapMatrix


def _bucket_exposure_hours(exposure_hours: int) -> int | None:
    """Round raw exposure hours down to the matrix's discrete brackets (6/12/24)."""
    if exposure_hours >= 24:
        return 24
    if exposure_hours >= 12:
        return 12
    if exposure_hours >= 6:
        return 6
    return None


class ParametricAssessment:
    def __init__(self, db: Session):
        self.db = db

    def get_matrix_rule(self, crop_stage_no: int, wind_signal_tcws: int, exposure_hours: int) -> RecsapMatrix | None:
        """Look up the yield loss % and indemnity factor for this parametric rule in tbl_recsap_matrix."""
        bucketed_hours = _bucket_exposure_hours(exposure_hours)
        if bucketed_hours is None:
            return None

        return (
            self.db.query(RecsapMatrix)
            .filter(
                RecsapMatrix.crop_stage_no == crop_stage_no,
                RecsapMatrix.wind_signal_tcws == wind_signal_tcws,
                RecsapMatrix.exposure_hours == bucketed_hours,
                RecsapMatrix.is_active.is_(True),
            )
            .first()
        )

    def calculate_final_payout(
        self,
        amount_of_cover: float,
        area_hectares: float,
        crop_stage_no: int,
        wind_signal_tcws: int,
        exposure_hours: int,
    ) -> float:
        """Final Indemnity Payout Calculation: I = (AC / 1000) * IF * Area."""
        rule = self.get_matrix_rule(crop_stage_no, wind_signal_tcws, exposure_hours)
        if rule is None:
            return 0.0

        payout = (amount_of_cover / 1000) * float(rule.indemnity_factor) * area_hectares
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
        area = float(input("2. Total Area in hectares (e.g., 2.87): "))
        tcws = int(input("3. Peak TCWS Level (e.g., 2, 3, 4, 5): "))
        hours = int(input("4. Period of Exposure in hours (e.g., 6, 12, 24): "))
        crop_stage_no = int(input("5. Crop Stage No. (per tbl_recsap_matrix, e.g., 2 for Flowering): "))

        rule = assessment.get_matrix_rule(crop_stage_no, tcws, hours)
        payout = assessment.calculate_final_payout(ac, area, crop_stage_no, tcws, hours)

        print("\n" + "-" * 50)
        print("               ASSESSMENT RESULTS")
        print("-" * 50)
        if rule is None:
            print("No matching rule found in tbl_recsap_matrix (or exposure below 6 hours).")
        else:
            print(f"Estimated Yield Loss:     {rule.estimated_yield_loss}%")
            print(f"Applied Indemnity Factor: {rule.indemnity_factor}")
        print(f"FINAL INDEMNITY PAYOUT:   ₱{payout:,.2f}")
        print("-" * 50 + "\n")

    except ValueError:
        print("\n[ERROR] Invalid input detected. Please ensure you are entering numbers for Cover, Area, TCWS, Hours, and Stage No.")
    finally:
        session.close()
