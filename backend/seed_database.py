import os

import pandas as pd
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# Falls back to the shared team default so existing setups keep working
# unchanged; override locally via backend/.env (gitignored, per ENV_GUIDE.md).
# Kept in sync with app/core/database.py's DATABASE_URL handling.
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://agrisure_admin:agrisure_password@localhost:5432/agrisure_db"
)

def run_setup():
    print("Connecting to database...")
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    print("Loading CSV Data...")
    # Load CSV and fill blank spaces with None for SQL compatibility
    df = pd.read_csv("pabs_results.csv").replace({float('nan'): None})

    # --- 1. SEED BOUNDARIES ---
    print("Ingesting Admin Boundaries...")
    # Real PSGC codes for Region X (Northern Mindanao), sourced from the PSA/NAMRIA-derived
    # 2023 PSGC dataset (via github.com/faeldon/philippines-json-maps). Covers every barangay
    # in Bukidnon (22 municipalities) and Misamis Oriental (25 municipalities) — the two
    # provinces pabs_results.csv currently has farms in.
    psgc_lookup = pd.read_csv("app/data/psgc_region10_boundaries.csv")
    psgc_lookup = psgc_lookup.set_index(['province', 'municipality', 'barangay'])['psgc_code']

    boundaries = df[['Province', 'Municipality', 'Barangay']].drop_duplicates()
    for _, row in boundaries.iterrows():
        # Check if boundary already exists
        cur.execute("""
            SELECT boundary_id FROM tbl_admin_boundaries
            WHERE province = %s AND municipality = %s AND barangay = %s
        """, (row['Province'], row['Municipality'], row['Barangay']))
        res = cur.fetchone()
        if not res:
            key = (row['Province'], row['Municipality'], row['Barangay'])
            if key not in psgc_lookup.index:
                raise ValueError(
                    f"No PSGC code on file for {key}. Add it to "
                    "app/data/psgc_region10_boundaries.csv before seeding."
                )
            psgc_code = str(psgc_lookup.loc[key])
            cur.execute("""
                INSERT INTO tbl_admin_boundaries (psgc_code, province, municipality, barangay)
                VALUES (%s, %s, %s, %s)
            """, (psgc_code, row['Province'], row['Municipality'], row['Barangay']))
    conn.commit()

    # --- 2. SEED FARMERS ---
    print("Ingesting Farmers...")
    farmers = df[['RSBSA No.', 'Surname', 'Firstname', 'Middlename']].drop_duplicates(subset=['RSBSA No.'])
    for _, row in farmers.iterrows():
        if row['RSBSA No.']: # Skip if empty
            cur.execute("""
                INSERT INTO tbl_farmers_profile (rsbsa_no, last_name, first_name, middle_name) 
                VALUES (%s, %s, %s, %s) ON CONFLICT (rsbsa_no) DO NOTHING
            """, (row['RSBSA No.'], row['Surname'], row['Firstname'], row['Middlename']))
    conn.commit()

    # --- 3. SEED FARMS & RELATIONS ---
    print("Ingesting Farms, Insurance, and Assessments...")
    for _, row in df.iterrows():
        # A. Get Farmer ID
        cur.execute("SELECT farmer_id FROM tbl_farmers_profile WHERE rsbsa_no = %s", (row['RSBSA No.'],))
        farmer_result = cur.fetchone()
        farmer_id = farmer_result[0] if farmer_result else None

        # B. Get Boundary ID
        cur.execute("""
            SELECT boundary_id FROM tbl_admin_boundaries 
            WHERE province = %s AND municipality = %s AND barangay = %s
        """, (row['Province'], row['Municipality'], row['Barangay']))
        boundary_result = cur.fetchone()
        boundary_id = boundary_result[0] if boundary_result else None

        # C. Insert Farm and get Farm ID
        area_val = str(row['Area']).replace(',', '') if row['Area'] else '0'
        cur.execute("""
            INSERT INTO tbl_farms (farmer_id, boundary_id, csv_farm_reference, georef_id, area_size)
            VALUES (%s, %s, %s, %s, %s) RETURNING farm_id
        """, (farmer_id, boundary_id, row['Farm ID'], row['Georef ID'], area_val))
        farm_id = cur.fetchone()[0]

        # D. Insert Insurance Record and get Insurance ID
        insured_cover = str(row['InsuredAmountofCover']).replace(',', '') if row['InsuredAmountofCover'] else '0'
        cur.execute("""
            INSERT INTO tbl_insurance_records (farmer_id, farm_id, policy_no, program_type, effectivity_date, expiry_date, amount_cover)
            VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (policy_no) DO NOTHING RETURNING insurance_records_id
        """, (farmer_id, farm_id, row['Policy No.'], row['Program Type'], row['Effectivity Date'], row['Expiry Date'], insured_cover))
        
        ins_result = cur.fetchone()
        if ins_result:
            insurance_id = ins_result[0]
            
            # E. Insert Risk Assessment
            est_damage = str(row['EstimatedDamage']).replace(',', '') if row['EstimatedDamage'] else '0'
            stage_no = int(row['Stage No.']) if row['Stage No.'] is not None else None
            
            cur.execute("""
                INSERT INTO tbl_risk_assessment (insurance_records_id, crop_stage_no, crop_stage, estimated_damage, final_indemnity_payment)
                VALUES (%s, %s, %s, %s, %s)
            """, (insurance_id, stage_no, row['Stage'], est_damage, est_damage))

    conn.commit()
    cur.close()
    conn.close()
    print("✅ Database successfully initialized and seeded from CSV!")

if __name__ == "__main__":
    run_setup()