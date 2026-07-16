class ParametricAssessment:
    def __init__(self):
        # Indemnity Factor Table mapped by Growth Stage and Yield Loss range
        # Format: { 'Broad Growth Stage': { (min_loss, max_loss): indemnity_factor } }
        self.indemnity_factors = {
            'EARLY VEGETATIVE': {(10, 15): 146.00, (15, 20): 198.00, (20, 25): 248.00, (25, 30): 294.00, (30, 35): 336.00},
            'LATE VEGETATIVE':  {(10, 15): 170.00, (15, 20): 231.00, (20, 25): 289.00, (25, 30): 343.00, (30, 35): 392.00},
            'REPRODUCTIVE':     {(10, 15): 194.00, (15, 20): 264.00, (20, 25): 330.00, (25, 30): 392.00, (30, 35): 448.00},
            'LATE REPRODUCTIVE':{(10, 15): 218.00, (15, 20): 297.00, (20, 25): 372.00, (25, 30): 441.00, (30, 35): 504.00},
            'MATURITY':         {(10, 15): 243.00, (15, 20): 330.00, (20, 25): 413.00, (25, 30): 490.00, (30, 35): 560.00}
        }

    def determine_yield_loss(self, tcws: int, exposure_hours: int, growth_stage: str) -> int:
        """Step 2: Determine the Yield Loss Percentage."""
        matrix = {
            2: {
                6:  {'BOOTING': 10, 'FLOWERING': 15, 'MATURITY': 9}, 
                12: {'BOOTING': 15, 'FLOWERING': 20, 'MATURITY': 10},
                24: {'BOOTING': 20, 'FLOWERING': 25, 'MATURITY': 15}
            },
            3: {
                6:  {'BOOTING': 15, 'FLOWERING': 20, 'MATURITY': 10},
                12: {'BOOTING': 20, 'FLOWERING': 25, 'MATURITY': 15},
                24: {'BOOTING': 25, 'FLOWERING': 30, 'MATURITY': 20}
            },
            4: { # Applies to TCWS 4 and 5 (> 184 KPH)
                6:  {'BOOTING': 20, 'FLOWERING': 25, 'MATURITY': 15},
                12: {'BOOTING': 30, 'FLOWERING': 25, 'MATURITY': 20},
                24: {'BOOTING': 30, 'FLOWERING': 35, 'MATURITY': 25}
            }
        }
        
        signal_bracket = 4 if tcws >= 4 else tcws
        
        if exposure_hours >= 24:
            hours = 24
        elif exposure_hours >= 12:
            hours = 12
        elif exposure_hours >= 6:
            hours = 6
        else:
            return 0 

        try:
            return matrix[signal_bracket][hours][growth_stage.upper()]
        except KeyError:
            return 0

    def get_indemnity_factor(self, yield_loss: int, broad_growth_stage: str) -> float:
        """Step 3: Identification of the Indemnity Factor."""
        if yield_loss < 10:
            return 0.0
            
        stage_factors = self.indemnity_factors.get(broad_growth_stage.upper())
        if not stage_factors:
            return 0.0

        for (min_loss, max_loss), factor in stage_factors.items():
            if min_loss < yield_loss <= max_loss:
                return factor
                
        if yield_loss == 10: 
            return stage_factors.get((10, 15))
            
        return 0.0

    def calculate_final_payout(self, amount_of_cover: float, area_hectares: float, tcws: int, exposure_hours: int, matrix_stage: str, broad_stage: str) -> float:
        """Step 4: Final Indemnity Payout Calculation."""
        yield_loss = self.determine_yield_loss(tcws, exposure_hours, matrix_stage)
        indemnity_factor = self.get_indemnity_factor(yield_loss, broad_stage)
        
        if indemnity_factor > 0:
            payout = (amount_of_cover / 1000) * indemnity_factor * area_hectares
            return round(payout, 2)
        
        return 0.0

# --- Interactive Terminal Execution for Manual Testing ---
if __name__ == "__main__":
    assessment = ParametricAssessment()
    
    print("\n" + "="*50)
    print("   AgriSureGIS Manual Parametric Testing Tool")
    print("="*50)
    
    try:
        # Prompting for numeric variables
        ac = float(input("1. Amount of Cover per hectare (e.g., 25000): "))
        area = float(input("2. Total Area in hectares (e.g., 2.87): "))
        tcws = int(input("3. Peak TCWS Level (e.g., 2, 3, 4, 5): "))
        hours = int(input("4. Period of Exposure in hours (e.g., 6, 12, 24): "))
        
        print("\n[Available Matrix Stages: BOOTING, FLOWERING, MATURITY]")
        matrix_stage = input("5. Enter the specific Crop Stage for Yield Loss: ").strip().upper()
        
        print("\n[Available Broad Stages: EARLY VEGETATIVE, LATE VEGETATIVE, REPRODUCTIVE, LATE REPRODUCTIVE, MATURITY]")
        broad_stage = input("6. Enter the Broad Growth Stage for Indemnity Factor: ").strip().upper()

        # Execute calculations
        payout = assessment.calculate_final_payout(ac, area, tcws, hours, matrix_stage, broad_stage)
        yield_loss = assessment.determine_yield_loss(tcws, hours, matrix_stage)
        indemnity_factor = assessment.get_indemnity_factor(yield_loss, broad_stage)
        
        # Display Results
        print("\n" + "-"*50)
        print("               ASSESSMENT RESULTS")
        print("-"*50)
        print(f"Computed Yield Loss:      {yield_loss}%")
        print(f"Applied Indemnity Factor: {indemnity_factor}")
        print(f"FINAL INDEMNITY PAYOUT:   ₱{payout:,.2f}")
        print("-"*50 + "\n")

    except ValueError:
        print("\n[ERROR] Invalid input detected. Please ensure you are entering numbers for Cover, Area, TCWS, and Hours.")