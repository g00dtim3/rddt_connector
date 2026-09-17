"""Génération d'export CSV — toujours depuis PostgreSQL, jamais depuis l'API.

Ce module n'importe volontairement pas `connectors.brandwatch_connector` :
un export ne doit jamais déclencher d'appel réseau vers Brandwatch.
"""

from __future__ import annotations

import csv
import io

from repositories.exports_repository import ExportsRepository
from repositories.reddit_mentions_repository import RedditMentionsRepository

MENTION_COLUMNS = ["id", "source", "source_native_id", "published_at", "full_text", "author", "url", "language"]


class ExportService:
    def __init__(
        self,
        mentions_repo: RedditMentionsRepository | None = None,
        exports_repo: ExportsRepository | None = None,
    ):
        self._mentions_repo = mentions_repo or RedditMentionsRepository()
        self._exports_repo = exports_repo or ExportsRepository()

    def generate_csv(self, dataset_id: int, requested_by: str | None = None) -> tuple[str, bytes]:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=MENTION_COLUMNS)
        writer.writeheader()

        row_count = 0
        for row in self._mentions_repo.iter_for_dataset(dataset_id):
            writer.writerow(row)
            row_count += 1

        content = buffer.getvalue().encode("utf-8")
        file_name = f"dataset_{dataset_id}.csv"
        self._exports_repo.log_export(dataset_id, file_name, row_count, requested_by)
        return file_name, content
