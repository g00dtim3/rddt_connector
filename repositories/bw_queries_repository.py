from __future__ import annotations

from typing import Any

from sqlalchemy import text

from db.connection import get_connection


class BwQueriesRepository:
    def upsert_many(self, project_id: int, queries: list[dict[str, Any]]) -> None:
        if not queries:
            return
        with get_connection() as conn:
            with conn.begin():
                conn.execute(
                    text(
                        """
                        INSERT INTO bw_queries (id, project_id, name, synced_at)
                        VALUES (:id, :project_id, :name, now())
                        ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, synced_at = now()
                        """
                    ),
                    [{"id": q["id"], "project_id": project_id, "name": q["name"]} for q in queries],
                )

    def list_by_project(self, project_id: int) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = (
                conn.execute(
                    text("SELECT id, project_id, name, synced_at FROM bw_queries WHERE project_id = :project_id ORDER BY name"),
                    {"project_id": project_id},
                )
                .mappings()
                .all()
            )
            return [dict(row) for row in rows]
