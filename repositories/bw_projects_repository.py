from __future__ import annotations

from typing import Any

from sqlalchemy import text

from db.connection import get_connection


class BwProjectsRepository:
    def upsert_many(self, projects: list[dict[str, Any]]) -> None:
        if not projects:
            return
        with get_connection() as conn:
            with conn.begin():
                conn.execute(
                    text(
                        """
                        INSERT INTO bw_projects (id, name, synced_at)
                        VALUES (:id, :name, now())
                        ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, synced_at = now()
                        """
                    ),
                    [{"id": p["id"], "name": p["name"]} for p in projects],
                )

    def list_all(self) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(text("SELECT id, name, synced_at FROM bw_projects ORDER BY name")).mappings().all()
            return [dict(row) for row in rows]
