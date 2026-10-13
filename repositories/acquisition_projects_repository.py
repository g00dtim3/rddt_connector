from __future__ import annotations

from typing import Any

from sqlalchemy import text

from db.connection import get_connection


class AcquisitionProjectsRepository:
    """Une "étude" métier (ex. "Observatoire Peau") qui regroupe des datasets
    dans la Dataset Library — voir docs/01-spec-fonctionnelle.md §3."""

    def create(self, name: str) -> int:
        with get_connection() as conn:
            with conn.begin():
                result = conn.execute(
                    text("INSERT INTO acquisition_projects (name) VALUES (:name) RETURNING id"),
                    {"name": name},
                )
                return result.scalar_one()

    def list_all(self) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                text("SELECT id, name, created_at FROM acquisition_projects ORDER BY name")
            ).mappings().all()
            return [dict(row) for row in rows]

    def get(self, acquisition_project_id: int) -> dict[str, Any] | None:
        with get_connection() as conn:
            row = conn.execute(
                text("SELECT * FROM acquisition_projects WHERE id = :id"), {"id": acquisition_project_id}
            ).mappings().first()
            return dict(row) if row else None
