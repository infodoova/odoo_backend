"""
Thin database helpers for the agent module.

Re-uses the DATABASE_URL that the rest of doova_one_view already depends on,
but provides simple `run_query` / `run_command` wrappers so the agent tools
can run raw SQL without importing Django ORM.
"""

import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set.  "
        "The AI agent requires a PostgreSQL connection string in the environment."
    )

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def run_query(query: str, params: dict | None = None) -> list[dict]:
    """Execute a read-only query and return rows as dicts."""
    with engine.connect() as conn:
        result = conn.execute(text(query), params or {})
        return [dict(row._mapping) for row in result]


def run_command(query: str, params: dict | None = None):
    """Execute a write query inside a transaction."""
    with engine.begin() as conn:
        conn.execute(text(query), params or {})
