import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

# Import our database connection and models
from app.api.activity_log import router as activity_log_router
from app.api.upload import router as upload_router
from app.api.bulletins import router as bulletins_router
from app.api.assessments import router as assessments_router
from app.api.farms import router as farms_router
from app.api.insurance import router as insurance_router
from app.api.typhoons import router as typhoons_router
from app.api.users import router as users_router
from app.core.activity_log import record_activity
from app.core.database import SessionLocal, get_db
from app.core.scheduler import FIXED_POLL_INTERVAL_MINUTES, build_scheduler
from app.models import models

logger = logging.getLogger("agrisuregis.main")

# POST /api/users/login and /api/users/logout self-log a distinct LOGIN/LOGOUT
# action from inside their own route bodies (see app/api/users.py) --
# excluded here to avoid double-logging them as a generic "POST".
_SELF_LOGGED_PATHS = {"/api/users/login", "/api/users/logout"}
_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fixed interval, not read from tbl_parser_settings anymore -- see
    # FIXED_POLL_INTERVAL_MINUTES's comment in scheduler.py.
    scheduler = build_scheduler(FIXED_POLL_INTERVAL_MINUTES)
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("PAGASA polling scheduler started, interval=%dmin.", FIXED_POLL_INTERVAL_MINUTES)

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
app.include_router(users_router, prefix="/api")
app.include_router(activity_log_router, prefix="/api")

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


@app.middleware("http")
async def activity_log_middleware(request: Request, call_next):
    """
    Generic half of the Activity Log feature (2026-08-16) -- records every
    mutating (POST/PUT/PATCH/DELETE) request as it finishes, resolving the
    acting user from `request.state.user` (stamped by
    app/core/security.py's get_current_user, which every protected router
    now depends on). LOGIN/LOGOUT are excluded here since they self-log a
    more specific action label from inside app/api/users.py -- see
    _SELF_LOGGED_PATHS above.

    Opens its own short-lived DB session rather than reusing the route's --
    middleware runs outside any single route's `Depends(get_db)` scope, and
    by the time control reaches here that session may already be closed.
    """
    response = await call_next(request)

    if request.method in _MUTATING_METHODS and request.url.path not in _SELF_LOGGED_PATHS:
        user = getattr(request.state, "user", None)
        db = SessionLocal()
        try:
            record_activity(db, user.user_id if user else None, request.method, request.url.path, response.status_code)
        finally:
            db.close()

    return response

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

