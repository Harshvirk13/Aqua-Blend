"""
config.py — central place every script/notebook imports credentials from.

Usage:
    from config import SUPABASE_URL, SUPABASE_ANON_KEY, DATABASE_URL, get_engine

Never hardcode a key anywhere else in the codebase. If a new secret is
needed, add it to .env.example (placeholder) and .env (real value), then
read it here.
"""

import os
from dotenv import load_dotenv

# Load variables from .env into the process environment.
# Does nothing (silently) if .env is missing, so this is safe in CI too.
load_dotenv()


def _require(name: str) -> str:
    """Fetch an env var or fail fast with a clear error instead of a
    confusing crash later in the pipeline."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


# --- Supabase ---
SUPABASE_URL = _require("SUPABASE_URL")
SUPABASE_ANON_KEY = _require("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # optional, admin-only tasks

# --- Direct Postgres URL (used by SQLAlchemy/pandas) ---
DATABASE_URL = _require("DATABASE_URL")

# --- Misc ---
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


def get_supabase_client():
    """Return a ready-to-use Supabase client (lazy import so scripts that
    only need the Postgres connection don't need the supabase package)."""
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def get_engine():
    """Return a SQLAlchemy engine connected to the Supabase Postgres DB."""
    from sqlalchemy import create_engine
    return create_engine(DATABASE_URL)


if __name__ == "__main__":
    # Quick sanity check: run `python config.py` to confirm your .env loads.
    print(f"Environment: {ENVIRONMENT}")
    print(f"Supabase URL: {SUPABASE_URL}")
    print("DATABASE_URL loaded:", "yes" if DATABASE_URL else "no")
