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
                        """
                        INSERT INTO reddit_mentions
                            (source, source_native_id, published_at, full_text, author, url, language, raw_payload)
                        VALUES
                            (:source, :source_native_id, :published_at, :full_text, :author, :url, :language, :raw_payload)
                        ON CONFLICT (source, source_native_id) DO UPDATE SET last_seen_at = now()
                        """
                    ),
                    [
                        {
                            "source": m["source"],
                            "source_native_id": m["source_native_id"],
                            "published_at": m.get("published_at"),
                            "full_text": m.get("full_text"),
                            "author": m.get("author"),
                            "url": m.get("url"),
                            "language": m.get("language"),
                            "raw_payload": json.dumps(m["raw_payload"]),
                        }
                        for m in mentions
                    ],
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
