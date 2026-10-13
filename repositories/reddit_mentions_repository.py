"""Accès à reddit_mentions — la table centrale (voir docs/03-modele-donnees.md).

Règle de préservation : aucune transformation du contenu ici. `raw_payload`
est stocké tel quel ; les colonnes structurées ne couvrent que les champs
encore fiables côté Brandwatch (voir docs/06-decisions-et-risques.md).
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from db.connection import get_connection


class RedditMentionsRepository:
    def upsert_batch(self, mentions: list[dict[str, Any]]) -> tuple[int, int]:
        """Insère les mentions, dédupliquées sur (source, source_native_id).

        Retourne (nombre_inséré, nombre_déjà_existant).
        """
        if not mentions:
            return 0, 0

        source = mentions[0]["source"]
        native_ids = [m["source_native_id"] for m in mentions]

        # Un seul aller-retour réseau pour toute la page (jusqu'à pageSize
        # mentions), plutôt que l'executemany par défaut de psycopg2/SQLAlchemy
        # qui envoie une requête par ligne — beaucoup trop lent avec une base
        # distante dès que la page contient des centaines/milliers de mentions.
        values_clause = ", ".join(
            f"(:source_{i}, :native_id_{i}, :published_at_{i}, :full_text_{i}, "
            f":author_{i}, :url_{i}, :language_{i}, :raw_payload_{i})"
            for i in range(len(mentions))
        )
        params: dict[str, Any] = {}
        for i, m in enumerate(mentions):
            params[f"source_{i}"] = m["source"]
            params[f"native_id_{i}"] = m["source_native_id"]
            params[f"published_at_{i}"] = m.get("published_at")
            params[f"full_text_{i}"] = m.get("full_text")
            params[f"author_{i}"] = m.get("author")
            params[f"url_{i}"] = m.get("url")
            params[f"language_{i}"] = m.get("language")
            params[f"raw_payload_{i}"] = json.dumps(m["raw_payload"])

        with get_connection() as conn:
            with conn.begin():
                existing_rows = conn.execute(
                    text(
                        "SELECT source_native_id FROM reddit_mentions "
                        "WHERE source = :source AND source_native_id = ANY(:native_ids)"
                    ),
                    {"source": source, "native_ids": native_ids},
                ).all()
                existing_ids = {row[0] for row in existing_rows}

                conn.execute(
                    text(
                        f"""
                        INSERT INTO reddit_mentions
                            (source, source_native_id, published_at, full_text, author, url, language, raw_payload)
                        VALUES {values_clause}
                        ON CONFLICT (source, source_native_id) DO UPDATE SET last_seen_at = now()
                        """
                    ),
                    params,
                )

        inserted = len(native_ids) - len(existing_ids)
        return inserted, len(existing_ids)

    def get_ids_by_native_ids(self, source: str, native_ids: list[str]) -> dict[str, int]:
        if not native_ids:
            return {}
        with get_connection() as conn:
            rows = conn.execute(
                text(
                    "SELECT source_native_id, id FROM reddit_mentions "
                    "WHERE source = :source AND source_native_id = ANY(:native_ids)"
                ),
                {"source": source, "native_ids": native_ids},
            ).all()
            return {row[0]: row[1] for row in rows}

    def iter_for_dataset(self, dataset_id: int):
        """Générateur de lignes (dict) pour un export CSV — jamais d'appel API."""
        with get_connection() as conn:
            result = conn.execute(
                text(
                    """
                    SELECT m.id, m.source, m.source_native_id, m.published_at, m.full_text,
                           m.author, m.url, m.language
                    FROM reddit_mentions m
                    JOIN dataset_mentions dm ON dm.mention_id = m.id
                    WHERE dm.dataset_id = :dataset_id
                    ORDER BY m.published_at
                    """
                ),
                {"dataset_id": dataset_id},
            )
            for row in result.mappings():
                yield dict(row)
