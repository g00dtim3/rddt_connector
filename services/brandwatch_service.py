"""Orchestration des appels Brandwatch (Projects, Queries, Mentions).

L'UI Streamlit ne doit jamais importer `connectors.brandwatch_connector`
directement : elle passe toujours par ce Service (voir docs/02-architecture.md).
"""

from __future__ import annotations

from typing import Any, Iterator

from connectors.brandwatch_connector import BrandwatchConnector, MentionsPage
from repositories.bw_projects_repository import BwProjectsRepository
from repositories.bw_queries_repository import BwQueriesRepository

# Nom exact du paramètre de filtrage "Reddit uniquement" côté API Brandwatch :
# non confirmé (voir docs/05-brandwatch-api-notes.md, "À confirmer"). Ne pas
# deviner : renseigner cette constante une fois vérifié, pas avant.
REDDIT_ONLY_FILTER_PARAM: str | None = None


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

    def _reddit_only_filter(self) -> dict[str, Any]:
        if REDDIT_ONLY_FILTER_PARAM is None:
            raise RuntimeError(
                "Le filtre 'Reddit uniquement' n'est pas encore configurable : le "
                "nom exact du paramètre Brandwatch n'a pas été confirmé (voir "
                "docs/05-brandwatch-api-notes.md, section 'À confirmer'). Renseigne "
                "REDDIT_ONLY_FILTER_PARAM dans services/brandwatch_service.py une "
                "fois vérifié."
            )
        return {REDDIT_ONLY_FILTER_PARAM: "reddit"}

    def count_mentions(self, project_id: int, query_id: int, start_date: str, end_date: str) -> int:
        return self._connector.count_mentions(
            project_id, query_id, start_date, end_date, extra_params=self._reddit_only_filter()
        )

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
