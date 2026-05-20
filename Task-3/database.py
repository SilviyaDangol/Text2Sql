# ─────────────────────────────────────────────
# project/database.py
#
# Database connection management and query execution.
# Uses SQLAlchemy for connection pooling + psycopg2 as the driver.
# ─────────────────────────────────────────────
from __future__ import annotations
import sys as _sys
import os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import os
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import QueuePool

load_dotenv()


def _build_url() -> str:
    """Build a PostgreSQL connection URL from env variables.

    Prefers DATABASE_URL if set; otherwise assembles it from individual vars.
    """
    url = os.getenv("DATABASE_URL")
    if url:
        return url

    user = os.getenv("POSTGRES_USER", "classicmodels")
    password = os.getenv("POSTGRES_PASSWORD", "classicmodels")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "classicmodels")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"


# Module-level engine (singleton)
_engine = None


def get_engine():
    """Return a module-level SQLAlchemy engine (created once)."""
    global _engine
    if _engine is None:
        url = _build_url()
        _engine = create_engine(
            url,
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,   # Detect stale connections
            echo=False,
        )
    return _engine


def execute_query(sql: str) -> list[dict[str, Any]]:
    """Execute a SELECT query and return rows as a list of dicts.

    Parameters
    ----------
    sql : str
        A validated SELECT statement.

    Returns
    -------
    list[dict]
        Each element represents one row with column names as keys.

    Raises
    ------
    SQLAlchemyError
        Propagated so the caller (executor.py) can handle retry logic.
    RuntimeError
        If the engine cannot be reached.
    """
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        columns = list(result.keys())
        rows = [dict(zip(columns, row)) for row in result.fetchall()]
    return rows


def test_connection() -> bool:
    """Return True if the database is reachable, False otherwise."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False