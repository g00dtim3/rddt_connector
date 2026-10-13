"""Orchestration des appels Brandwatch (Projects, Queries, Mentions).

L'UI Streamlit ne doit jamais importer `connectors.brandwatch_connector`
directement : elle passe toujours par ce Service (voir docs/02-architecture.md).
"""

from __future__ import annotations

from typing import Any, Callable, Iterator

from connectors.brandwatch_connector import BrandwatchConnector, MentionsPage
from repositories.bw_projects_repository import BwProjectsRepository
from repositories.bw_queries_repository import BwQueriesRepository

# Paramètre de filtrage "page type" confirmé dans la doc Brandwatch "Available
# Filters" (ex. d'usage officiel : pageType=twitter). Voir docs/05-brandwatch-
# api-notes.md.
REDDIT_ONLY_FILTER_PARAM = "pageType"

# Valeur confirmée le 13/10/2026 via un vrai appel GET /metrics (bouton
# « Appeler /metrics » de l'écran Connexions) : {"id": "reddit", "name":
# "Reddit", "type": "STANDARD", "group": "PRE_CONFIGURED", "canonical": true}.
REDDIT_ONLY_FILTER_VALUE = "reddit"


class BrandwatchService:
    def __init__(
        self,
        connector: BrandwatchConnector,
        projects_repo: BwProjectsRepository | None = None,
        queries_repo: BwQueriesRepository | None = None,
    ):
        self._connector = connector
        self._projects_repo = projects_repo or BwProjectsRepository()
        self._queries_repo = queries_repo or BwQueriesRepository()

    def sync_projects(self) -> list[dict[str, Any]]:
        projects = self._connector.list_projects()
        self._projects_repo.upsert_many(projects)
        return self._projects_repo.list_all()

    def list_cached_projects(self) -> list[dict[str, Any]]:
        return self._projects_repo.list_all()

    def sync_queries(self, project_id: int) -> list[dict[str, Any]]:
        queries = self._connector.list_queries(project_id)
        self._queries_repo.upsert_many(project_id, queries)
        return self._queries_repo.list_by_project(project_id)

    def list_cached_queries(self, project_id: int) -> list[dict[str, Any]]:
        return self._queries_repo.list_by_project(project_id)

    def test_connection(self) -> dict[str, Any]:
        return self._connector.test_connection()

    def set_event_sink(self, callback: Callable[[str], None] | None) -> None:
        """Mode verbose : branche (ou débranche avec None) un callback appelé à
        chaque étape d'un appel Brandwatch, pour affichage en direct dans l'UI."""
        self._connector.set_event_sink(callback)

    def list_filters(self) -> dict[str, Any]:
        return self._connector.list_filters()

    def list_metrics(self) -> dict[str, Any]:
        return self._connector.list_metrics()

    def _reddit_only_filter(self) -> dict[str, Any]:
        if REDDIT_ONLY_FILTER_VALUE is None:
            raise RuntimeError(
                "Le filtre 'Reddit uniquement' n'est pas encore configurable : la "
                "valeur exacte de pageType pour Reddit n'a pas été confirmée. "
                "Utilise le bouton « Appeler /metrics » (écran Connexions) pour "
                "lire les valeurs réelles de pageType, puis renseigne "
                "REDDIT_ONLY_FILTER_VALUE dans services/brandwatch_service.py."
            )
        return {REDDIT_ONLY_FILTER_PARAM: REDDIT_ONLY_FILTER_VALUE}

    def count_mentions(self, project_id: int, query_id: int, start_date: str, end_date: str) -> int:
        return self._connector.count_mentions(
            project_id, query_id, start_date, end_date, extra_params=self._reddit_only_filter()
        )

    def count_mentions_unfiltered(self, project_id: int, query_id: int, start_date: str, end_date: str) -> int:
        """Comptage SANS le filtre pageType=reddit — sert uniquement de diagnostic :
        la Query Brandwatch est en principe déjà construite pour ne contenir que du
        Reddit (voir CLAUDE.md), donc un écart entre les deux comptages peut révéler
        un souci de tagging pageType plutôt qu'un vrai problème de volume."""
        return self._connector.count_mentions(project_id, query_id, start_date, end_date)

    def fetch_mentions_pages(
        self,
        project_id: int,
        query_id: int,
        start_date: str,
        end_date: str,
        resume_cursor: str | None = None,
    ) -> Iterator[MentionsPage]:
        return self._connector.iter_mentions(
            project_id,
            query_id,
            start_date,
            end_date,
            extra_params=self._reddit_only_filter(),
            resume_cursor=resume_cursor,
        )
