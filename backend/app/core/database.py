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

# The Engine is the actual connection to the database
engine = create_engine(SQLALCHEMY_DATABASE_URL)

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