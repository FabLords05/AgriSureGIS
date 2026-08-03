import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

# Import our database connection and models
from app.api.upload import router as upload_router
from app.api.bulletins import router as bulletins_router
from app.api.assessments import router as assessments_router
from app.api.farms import router as farms_router
from app.api.insurance import router as insurance_router
from app.api.typhoons import router as typhoons_router
from app.core.database import SessionLocal, get_db
from app.core.scheduler import build_scheduler
from app.models import models

logger = logging.getLogger("agrisuregis.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    try:
        settings = db.query(models.ParserSettings).first()
        interval = settings.polling_interval_hours if settings else 3
    finally:
        db.close()

    scheduler = build_scheduler(interval)
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("PAGASA polling scheduler started, interval=%dh.", interval)

    yield

    scheduler.shutdown(wait=False)


# Initialize the FastAPI application
app = FastAPI(title="AgriSureGIS API", version="1.0", lifespan=lifespan)

app.include_router(upload_router)
app.include_router(bulletins_router, prefix="/api")
app.include_router(assessments_router, prefix="/api")
app.include_router(farms_router, prefix="/api")
app.include_router(insurance_router, prefix="/api")
app.include_router(typhoons_router, prefix="/api")

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

