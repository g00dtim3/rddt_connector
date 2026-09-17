"""Orchestration du fetch + pagination + écriture par batch (voir docs/02-architecture.md §5).

Écrit en base après CHAQUE page reçue (jamais en attendant la fin complète
d'une acquisition), et reprend une acquisition interrompue via le
`checkpoint` sauvegardé dans `acquisition_runs`, plutôt que tout refaire.
"""

from __future__ import annotations

from typing import Any, Iterator

from repositories.acquisition_runs_repository import AcquisitionRunsRepository
from repositories.datasets_repository import DatasetMentionsRepository
from repositories.reddit_mentions_repository import RedditMentionsRepository
from services.brandwatch_service import BrandwatchService

SOURCE = "reddit"


def _map_mention(raw: dict[str, Any]) -> dict[str, Any]:
    """Traduit une mention brute Brandwatch vers les colonnes de reddit_mentions.

    Champs basés sur le format standard de l'API Mentions Brandwatch (id,
    date, fullText, author, url, language). À vérifier contre une vraie
    réponse lors de la Phase 0 (POC) : voir docs/05-brandwatch-api-notes.md.
    Le contenu lui-même n'est jamais transformé — `raw_payload` garde
    l'objet complet tel que reçu.
    """
    return {
        "source": SOURCE,
        "source_native_id": str(raw.get("id")),
        "published_at": raw.get("date"),
        "full_text": raw.get("fullText"),
        "author": raw.get("author"),
        "url": raw.get("url"),
        "language": raw.get("language"),
        "raw_payload": raw,
    }


class AcquisitionService:
    def __init__(
        self,
        brandwatch_service: BrandwatchService,
        mentions_repo: RedditMentionsRepository | None = None,
        dataset_mentions_repo: DatasetMentionsRepository | None = None,
        runs_repo: AcquisitionRunsRepository | None = None,
    ):
        self._brandwatch_service = brandwatch_service
        self._mentions_repo = mentions_repo or RedditMentionsRepository()
        self._dataset_mentions_repo = dataset_mentions_repo or DatasetMentionsRepository()
        self._runs_repo = runs_repo or AcquisitionRunsRepository()

    def run(
        self,
        config_id: int,
        project_id: int,
        query_id: int,
        start_date: str,
        end_date: str,
        dataset_id: int,
        expected_volume: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        resumable = self._runs_repo.get_resumable_run(config_id)
        resume_cursor = resumable["checkpoint"] if resumable else None
        run_id = resumable["id"] if resumable else self._runs_repo.create(config_id, expected_volume)
        received = resumable["received_volume"] if resumable else 0
        inserted_total = resumable["inserted_volume"] if resumable else 0
        existing_total = resumable["existing_volume"] if resumable else 0

        try:
            pages = self._brandwatch_service.fetch_mentions_pages(
                project_id, query_id, start_date, end_date, resume_cursor=resume_cursor
            )
            for page in pages:
                mapped = [_map_mention(raw) for raw in page.results]
                inserted, existing = self._mentions_repo.upsert_batch(mapped)

                native_ids = [m["source_native_id"] for m in mapped]
                ids_by_native_id = self._mentions_repo.get_ids_by_native_ids(SOURCE, native_ids)
                self._dataset_mentions_repo.link_batch(dataset_id, list(ids_by_native_id.values()))

                received += len(page.results)
                inserted_total += inserted
                existing_total += existing
                self._runs_repo.update_progress(run_id, received, inserted_total, existing_total, page.next_cursor)

                yield {
                    "run_id": run_id,
                    "received": received,
                    "inserted": inserted_total,
                    "existing": existing_total,
                    "expected": expected_volume or page.results_total,
                }
        except Exception as exc:
            self._runs_repo.mark_failed(run_id, error_code=type(exc).__name__, error_message=str(exc))
            raise

        self._runs_repo.mark_completed(run_id)
