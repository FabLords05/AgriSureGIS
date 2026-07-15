import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

# 1. Database Connection (Update with your credentials if different)
DB_CONFIG = {
    "dbname": "agrisure_db",
    "user": "agrisure_admin",
    "password": "agrisure_password", # Replace with your actual password
    "host": "localhost",
    "port": "5432"
}

# 2. The Normalized DDL Schema
# (Applied fixes: snake_case columns, removed redundant farmer_id in insurance, fixed spelling)
SCHEMA_SQL = """
DROP TABLE IF EXISTS tbl_risk_assessment CASCADE;
DROP TABLE IF EXISTS tbl_insurance_records CASCADE;
DROP TABLE IF EXISTS tbl_farms CASCADE;
DROP TABLE IF EXISTS tbl_admin_boundaries CASCADE;
DROP TABLE IF EXISTS tbl_farmers_profile CASCADE;

CREATE TABLE tbl_farmers_profile (
    farmer_id SERIAL PRIMARY KEY,
    rsbsa_no VARCHAR(50) UNIQUE NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    first_name VARCHAR(50) NOT NULL,
    middle_name VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tbl_admin_boundaries (
    boundary_id SERIAL PRIMARY KEY,
    province VARCHAR(100) NOT NULL,
    municipality VARCHAR(100) NOT NULL,
    barangay VARCHAR(100) NOT NULL,
    UNIQUE(province, municipality, barangay)
);

CREATE TABLE tbl_farms (
    farm_id SERIAL PRIMARY KEY,
    farmer_id INT REFERENCES tbl_farmers_profile(farmer_id) ON DELETE CASCADE,
    boundary_id INT REFERENCES tbl_admin_boundaries(boundary_id) ON DELETE SET NULL,
    csv_farm_reference VARCHAR(50), -- To map the raw 'Farm ID' from CSV
    georef_id VARCHAR(50),
    area_size NUMERIC(10,2) NOT NULL,
    location_geom GEOMETRY(Polygon, 4326), -- Nullable initially until real polygons are drawn
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tbl_insurance_records (
    insurance_records_id SERIAL PRIMARY KEY,
    farm_id INT REFERENCES tbl_farms(farm_id) ON DELETE CASCADE,
    policy_no VARCHAR(50) UNIQUE NOT NULL,
    program_type VARCHAR(100),
    effectivity_date DATE,
    expiry_date DATE,
    amount_cover NUMERIC(12,2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tbl_risk_assessment (
    assessment_id SERIAL PRIMARY KEY,
    insurance_records_id INT REFERENCES tbl_insurance_records(insurance_records_id) ON DELETE CASCADE,
    crop_stage_no VARCHAR(20),
    crop_stage VARCHAR(100),
    estimated_damage NUMERIC(12,2),
    adjuster_calculation VARCHAR(255),
    assessment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

# def run_setup():
#     print("Connecting to database...")
#     conn = psycopg2.connect(**DB_CONFIG)
#     cur = conn.cursor()

#     print("Building normalized schema...")
#     cur.execute(SCHEMA_SQL)
#     conn.commit()

#     print("Loading CSV Data...")
#     # Load CSV and fill blank spaces with None for SQL compatibility
#     df = pd.read_csv("pabs_results.csv").replace({float('nan'): None})

#     # --- 1. SEED BOUNDARIES ---
#     print("Ingesting Admin Boundaries...")
#     boundaries = df[['Province', 'Municipality', 'Barangay']].drop_duplicates()
#     for _, row in boundaries.iterrows():
#         cur.execute("""
#             INSERT INTO tbl_admin_boundaries (province, municipality, barangay) 
#             VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
#         """, (row['Province'], row['Municipality'], row['Barangay']))
#     conn.commit()

#     # --- 2. SEED FARMERS ---
#     print("Ingesting Farmers...")
#     farmers = df[['RSBSA No.', 'Surname', 'Firstname', 'Middlename']].drop_duplicates(subset=['RSBSA No.'])
#     for _, row in farmers.iterrows():
#         if row['RSBSA No.']: # Skip if empty
#             cur.execute("""
#                 INSERT INTO tbl_farmers_profile (rsbsa_no, last_name, first_name, middle_name) 
#                 VALUES (%s, %s, %s, %s) ON CONFLICT (rsbsa_no) DO NOTHING
#             """, (row['RSBSA No.'], row['Surname'], row['Firstname'], row['Middlename']))
#     conn.commit()

#     # --- 3. SEED FARMS & RELATIONS ---
#     print("Ingesting Farms, Insurance, and Assessments...")
#     for _, row in df.iterrows():
#         # A. Get Farmer ID
#         cur.execute("SELECT farmer_id FROM tbl_farmers_profile WHERE rsbsa_no = %s", (row['RSBSA No.'],))
#         farmer_result = cur.fetchone()
#         farmer_id = farmer_result[0] if farmer_result else None

#         # B. Get Boundary ID
#         cur.execute("""
#             SELECT boundary_id FROM tbl_admin_boundaries 
#             WHERE province = %s AND municipality = %s AND barangay = %s
#         """, (row['Province'], row['Municipality'], row['Barangay']))
#         boundary_result = cur.fetchone()
#         boundary_id = boundary_result[0] if boundary_result else None

#         # C. Insert Farm and get Farm ID
#         cur.execute("""
#             INSERT INTO tbl_farms (farmer_id, boundary_id, csv_farm_reference, georef_id, area_size)
#             VALUES (%s, %s, %s, %s, %s) RETURNING farm_id
#         """, (farmer_id, boundary_id, row['Farm ID'], row['Georef ID'], str(row['Area']).replace(',', '') if row['Area'] else 0))
#         farm_id = cur.fetchone()[0]

#         # D. Insert Insurance Record and get Insurance ID
#         cur.execute("""
#             INSERT INTO tbl_insurance_records (farm_id, policy_no, program_type, effectivity_date, expiry_date, amount_cover)
#             VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (policy_no) DO NOTHING RETURNING insurance_records_id
#         """, (farm_id, row['Policy No.'], row['Program Type'], row['Effectivity Date'], row['Expiry Date'], str(row['InsuredAmountofCover']).replace(',', '') if row['InsuredAmountofCover'] else 0))
        
#         ins_result = cur.fetchone()
#         if ins_result:
#             insurance_id = ins_result[0]
            
#             # E. Insert Risk Assessment
#             cur.execute("""
#                 INSERT INTO tbl_risk_assessment (insurance_records_id, crop_stage_no, crop_stage, estimated_damage, adjuster_calculation)
#                 VALUES (%s, %s, %s, %s, %s)
#             """, (insurance_id, row['Stage No.'], row['Stage'], str(row['EstimatedDamage']).replace(',', '') if row['EstimatedDamage'] else 0, row["Adjuster's Stage of Crop Calculation"]))

#     conn.commit()
#     cur.close()
#     conn.close()
#     print("✅ Database successfully initialized and seeded from CSV!")

# if __name__ == "__main__":
#     run_setup()