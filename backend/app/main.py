import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

# Import our database connection and models
from app.api.activity_log import router as activity_log_router
from app.api.archives import router as archives_router
from app.api.upload import router as upload_router
from app.api.bulletins import router as bulletins_router
from app.api.assessments import router as assessments_router
from app.api.farms import router as farms_router
from app.api.insurance import router as insurance_router
from app.api.sar import router as sar_router
from app.api.typhoons import router as typhoons_router
from app.api.settings import router as settings_router
from app.api.system import router as system_router
from app.api.users import router as users_router
from app.core.activity_log import (
    compose_request_remarks,
    end_request_remarks,
    note_activity_error,
    record_activity,
    start_request_remarks,
)
from app.core.database import SessionLocal, get_db
from app.core.scheduler import FIXED_POLL_INTERVAL_MINUTES, build_scheduler
from app.models import models

logger = logging.getLogger("agrisuregis.main")

# Without a handler, Python only prints WARNING and up, so every INFO line
# from our own loggers ("agrisuregis.*" and the `__name__` ones under "app.*")
# was silently dropped -- e.g. why a TCB alert was skipped. Scoped to those two
# namespaces, not the root logger, so httpx/apscheduler INFO noise stays off.
_log_handler = logging.StreamHandler()
_log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
for _name in ("agrisuregis", "app"):
    _app_logger = logging.getLogger(_name)
    if not _app_logger.handlers:
        _app_logger.addHandler(_log_handler)
    _app_logger.setLevel(logging.INFO)
    _app_logger.propagate = False

# POST /api/users/login and /api/users/logout self-log a distinct LOGIN/LOGOUT
# action from inside their own route bodies (see app/api/users.py) --
# excluded here to avoid double-logging them as a generic "POST".
_SELF_LOGGED_PATHS = {"/api/users/login", "/api/users/logout"}
_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# Read-only routes still worth an audit entry: the two CSV downloads that hand
# insured farmers' data out of the system (2026-10-22). Every other GET (page
# loads, polling) stays unlogged -- it would bury the real actions.
_LOGGED_GET_PATHS = {"/api/assessments/export", "/api/sar/field-verify/export"}
# Same idea for the 2026-10-22 Database Backup & Archive downloads, whose
# paths carry an id: archive CSVs and raw pg_dump files.
_LOGGED_GET_PATTERN = re.compile(r"^/api/(archives/\d+/export|backups/\d+/download)$")


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
app.include_router(sar_router, prefix="/api")
app.include_router(typhoons_router, prefix="/api")
app.include_router(system_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(activity_log_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(archives_router, prefix="/api")

@app.get("/")
def root():
    return {"message": "Welcome to the AgriSureGIS Backend!"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"], # This is Vite's default React port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # CSV exports name themselves after their typhoon via Content-Disposition
    # (see app/api/assessments.py's _export_filename). It isn't a CORS-safelisted
    # response header, so without this the browser hides it from the frontend's
    # download helper and every file saves under the fallback name (2026-10-12).
    expose_headers=["Content-Disposition"],
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

    Since 2026-10-22 it also opens the per-request remarks holder the route
    fills via note_activity() (and the exception handlers below fill with
    the error), and writes the composed sentence alongside the entry. An
    unhandled exception is logged as a 500 before it is re-raised, so a
    crashed action is never missing from the log.
    """
    logged = (
        (request.method in _MUTATING_METHODS and request.url.path not in _SELF_LOGGED_PATHS)
        or (request.method == "GET" and (request.url.path in _LOGGED_GET_PATHS
                                         or _LOGGED_GET_PATTERN.match(request.url.path)))
    )
    if not logged:
        return await call_next(request)

    holder, token = start_request_remarks()
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception as exc:
        status_code = 500
        if not holder["error"]:
            note_activity_error(f"Unexpected server error: {exc}")
        _log_request_activity(request, holder, status_code)
        raise
    finally:
        end_request_remarks(token)

    _log_request_activity(request, holder, status_code)
    return response


def _log_request_activity(request: Request, holder: dict, status_code: int) -> None:
    user = getattr(request.state, "user", None)
    db = SessionLocal()
    try:
        record_activity(
            db,
            user.user_id if user else None,
            request.method,
            request.url.path,
            status_code,
            compose_request_remarks(holder, status_code),
        )
    finally:
        db.close()


@app.exception_handler(StarletteHTTPException)
async def _http_exception_with_activity_remarks(request: Request, exc: StarletteHTTPException):
    # Hands the message the user saw to the Activity Log (e.g. why a CSV was
    # rejected), then answers exactly as FastAPI's default handler does.
    note_activity_error(exc.detail)
    return await http_exception_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def _validation_error_with_activity_remarks(request: Request, exc: RequestValidationError):
    note_activity_error(exc.errors())
    return await request_validation_exception_handler(request, exc)

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

