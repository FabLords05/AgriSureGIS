import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

# Format: postgresql://user:password@host:port/dbname
# Falls back to the shared team default so existing setups keep working
# unchanged; override locally via backend/.env (gitignored, per ENV_GUIDE.md).
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://agrisure_admin:agrisure_password@localhost:5432/agrisure_db"
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