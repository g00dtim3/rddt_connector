from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text

from db.connection import get_connection


class DatasetsRepository:
    def create(
        self,
        start_date: date,
        end_date: date,
        acquisition_project_id: int | None = None,
        status: str = "LOCAL",
    ) -> int:
        with get_connection() as conn:
            with conn.begin():
                result = conn.execute(
                    text(
                        """
                        INSERT INTO datasets (acquisition_project_id, start_date, end_date, status)
                        VALUES (:acquisition_project_id, :start_date, :end_date, :status)
                        RETURNING id
                        """
                    ),
                    {
                        "acquisition_project_id": acquisition_project_id,
                        "start_date": start_date,
                        "end_date": end_date,
                        "status": status,
                    },
                )
                return result.scalar_one()

    def update_status(self, dataset_id: int, status: str) -> None:
        with get_connection() as conn:
            with conn.begin():
                conn.execute(
                    text("UPDATE datasets SET status = :status WHERE id = :id"),
                    {"id": dataset_id, "status": status},
                )

    def get(self, dataset_id: int) -> dict[str, Any] | None:
        with get_connection() as conn:
            row = conn.execute(text("SELECT * FROM datasets WHERE id = :id"), {"id": dataset_id}).mappings().first()
            return dict(row) if row else None


class DatasetMentionsRepository:
    def link_batch(self, dataset_id: int, mention_ids: list[int]) -> None:
        if not mention_ids:
            return
        with get_connection() as conn:
            with conn.begin():
                conn.execute(
                    text(
                        """
                        INSERT INTO dataset_mentions (dataset_id, mention_id)
                        VALUES (:dataset_id, :mention_id)
                        ON CONFLICT DO NOTHING
                        """
                    ),
                    [{"dataset_id": dataset_id, "mention_id": mention_id} for mention_id in mention_ids],
                )
