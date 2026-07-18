from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

# Import our database connection and models
from app.api.upload import router as upload_router
from app.api.bulletins import router as bulletins_router
from app.core.database import get_db
from app.models import models

# Initialize the FastAPI application
app = FastAPI(title="AgriSureGIS API", version="1.0")

app.include_router(upload_router)
app.include_router(bulletins_router, prefix="/api")

@app.get("/")
def root():
    return {"message": "Welcome to the AgriSureGIS Backend!"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"], # This is Vite's default React port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- THE TEST ENDPOINT ---
@app.get("/api/test-db")
def test_database_connection(db: Session = Depends(get_db)):
    """
    This endpoint attempts to connect to the database using SQLAlchemy
    and count the number of farms in tbl_farms.
    """
    try:
        # We use our Python ORM Model (models.Farm) instead of raw SQL!
        farm_count = db.query(models.Farm).count()
        
        return {
            "status": "success",
            "message": "Successfully connected to PostGIS via SQLAlchemy!",
            "total_farms_found": farm_count
        }
    except Exception as e:
        # If the database is off or the password is wrong, this catches the error safely
        raise HTTPException(status_code=500, detail=f"Database connection failed: {str(e)}")

@app.get("/api/assessments")
def get_all_assessments(db: Session = Depends(get_db)):
    """
    Provides the frontend developer with a complete list of risk assessments,
    joining the damage calculations with the specific farm and policy.
    """
    # This acts like a massive SQL JOIN across three tables
    results = db.query(
        models.RiskAssessment.assessment_id,
        models.RiskAssessment.crop_stage,
        models.RiskAssessment.estimated_damage,
        models.InsuranceRecord.policy_no,
        models.InsuranceRecord.amount_cover,
        models.Farm.georef_id,
    ).join(models.RiskAssessment.insurance_record).join(models.InsuranceRecord.farm).all()

    # Format the data cleanly for the frontend developer to consume
    payload = []
    for r in results:
        payload.append({
            "assessment_id": r.assessment_id,
            "policy_no": r.policy_no,
            "georef_id": r.georef_id,
            "crop_stage": r.crop_stage,
            "estimated_damage_percentage": float(r.estimated_damage) if r.estimated_damage else 0,
            "financial_cover": float(r.amount_cover)
        })

    return {"status": "success", "data": payload}