import pandas as pd
import psycopg2

# 1. Database Connection (Update with your credentials if different)
DB_CONFIG = {
    "dbname": "agrisure_db",
    "user": "agrisure_admin",
    "password": "agrisure_password",
    "host": "localhost",
    "port": "5432"
}

def run_setup():
    print("Connecting to database...")
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    print("Loading CSV Data...")
    # Load CSV and fill blank spaces with None for SQL compatibility
    df = pd.read_csv("pabs_results.csv").replace({float('nan'): None})

    # --- 1. SEED BOUNDARIES ---
    print("Ingesting Admin Boundaries...")
    boundaries = df[['Province', 'Municipality', 'Barangay']].drop_duplicates()
    for idx, (_, row) in enumerate(boundaries.iterrows()):
        # Check if boundary already exists
        cur.execute("""
            SELECT boundary_id FROM tbl_admin_boundaries 
            WHERE province = %s AND municipality = %s AND barangay = %s
        """, (row['Province'], row['Municipality'], row['Barangay']))
        res = cur.fetchone()
        if not res:
            # Generate a mock unique PSGC code for the boundaries found in the CSV
            psgc_code = f"PH10{idx:06d}"
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