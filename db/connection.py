"""Connexion PostgreSQL (Supabase) — point d'entrée unique utilisé par les Repositories.

Aucune requête SQL brute ne doit être écrite ailleurs que dans repositories/.

Schéma de travail (lot 2, regroupement dans la base principale) :
les requêtes des Repositories ne précisent jamais de schéma (`FROM reddit_mentions`).
Le schéma est donc fixé une fois, à l'ouverture de chaque connexion, par
`SET search_path`, à partir du secret `[supabase].schema` ("public" par défaut,
"reddit" dans la base principale). Cette méthode fonctionne avec le « Session pooler »
de Supabase (port 5432), qui garde la même session pendant toute la connexion.
Elle ne fonctionnerait PAS avec le « Transaction pooler » (port 6543) : refusé plus bas.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import URL, Connection

from config import get_supabase_credentials

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        creds = get_supabase_credentials()
        if creds.port == 6543:
            raise RuntimeError(
                "Le port 6543 (Transaction pooler) ne conserve pas le schéma de travail. "
                "Utilisez la chaîne « Session pooler » (port 5432) dans [supabase]."
            )
        # URL.create échappe les caractères spéciaux du mot de passe (@, #, /, :…),
        # qui cassaient l'adresse construite à la main.
        url = URL.create(
            "postgresql+psycopg2",
            username=creds.user,
            password=creds.password,
            host=creds.host,
            port=creds.port,
            database=creds.dbname,
        )
        engine = create_engine(url, pool_pre_ping=True)
        schema = creds.schema  # déjà validé dans config.py (lettres, chiffres, _)

        @event.listens_for(engine, "connect")
        def _fixer_schema(dbapi_connection, _record) -> None:
            # Recette SQLAlchemy : passer en autocommit le temps du SET, pour qu'il
            # s'applique à toute la session et pas seulement à une transaction.
            ancien = dbapi_connection.autocommit
            dbapi_connection.autocommit = True
            with dbapi_connection.cursor() as cur:
                cur.execute(f'SET search_path TO "{schema}"')
            dbapi_connection.autocommit = ancien

        _engine = engine
    return _engine


@contextmanager
def get_connection() -> Iterator[Connection]:
    with get_engine().connect() as conn:
        yield conn


def test_connection() -> dict[str, Any]:
    """Vérifie que la base Supabase est joignable et que le schéma de travail contient les tables."""
    creds = get_supabase_credentials()
    with get_connection() as conn:
        conn.execute(text("SELECT 1"))
        schema_actif = conn.execute(text("SELECT current_schema()")).scalar()
        if schema_actif != creds.schema:
            raise RuntimeError(
                f"Schéma « {creds.schema} » introuvable dans cette base (schéma actif : {schema_actif})."
            )
        conn.execute(text("SELECT 1 FROM reddit_mentions LIMIT 1"))
    return {"host": creds.host, "port": creds.port, "dbname": creds.dbname, "schema": creds.schema}
