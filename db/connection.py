"""Connexion PostgreSQL (Supabase) — point d'entrée unique utilisé par les Repositories.

Aucune requête SQL brute ne doit être écrite ailleurs que dans repositories/.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection

from config import get_supabase_credentials

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        creds = get_supabase_credentials()
        url = (
            f"postgresql+psycopg2://{creds.user}:{creds.password}"
            f"@{creds.host}:{creds.port}/{creds.dbname}"
        )
        _engine = create_engine(url, pool_pre_ping=True)
    return _engine


@contextmanager
def get_connection() -> Iterator[Connection]:
    with get_engine().connect() as conn:
        yield conn


def test_connection() -> dict[str, Any]:
    """Vérifie que la base Supabase est joignable (SELECT 1)."""
    creds = get_supabase_credentials()
    with get_connection() as conn:
        conn.execute(text("SELECT 1"))
    return {"host": creds.host, "port": creds.port, "dbname": creds.dbname}
