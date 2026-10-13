import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Loads backend/.env if present; no-op (and no error) if it doesn't exist yet.
load_dotenv()

# The connection string to your local PostgreSQL server.
# Format: postgresql://user:password@host:port/dbname
# Reads DATABASE_URL from backend/.env (see .claude/ENV_GUIDE.md); falls back
# to the previous hardcoded local-dev value so behavior is unchanged until a
# .env is actually created.
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://agrisure_admin:agrisure_password@localhost:5432/agrisure_db",
)

# The Engine is the actual connection to the database.
#
# Explicit pool sizing (SQLAlchemy's unstated defaults are pool_size=5,
# max_overflow=10 -- fine for one local dev process making one request at a
# time, not sized for multiple concurrent real users each potentially
# running their own farms-listing walk). pool_pre_ping issues a lightweight
# "is this connection still alive" check before handing a pooled connection
# to a request, so a connection that went stale while idle (network blip, a
# DB restart, a cloud DB's own idle-connection timeout) gets transparently
# replaced instead of surfacing as a request failure. pool_recycle proactively
# retires connections older than 30 minutes for the same reason, before they
# have a chance to go stale.
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=1800,
)

# The SessionLocal will be used to spawn temporary database sessions for each API request
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class that all our future database models will inherit from
Base = declarative_base()

# Dependency function to give our API endpoints a database session and close it when done
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()