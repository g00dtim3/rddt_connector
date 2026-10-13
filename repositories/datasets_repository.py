from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text

from db.connection import get_connection
from repositories._chunking import chunked


class DatasetsRepository:
    def create(
        self,
        start_date: date,
        end_date: date,
        acquisition_project_id: int | None = None,
        config_id: int | None = None,
        status: str = "LOCAL",
    ) -> int:
        with get_connection() as conn:
            with conn.begin():
                result = conn.execute(
                    text(
                        """
                        INSERT INTO datasets (acquisition_project_id, config_id, start_date, end_date, status)
                        VALUES (:acquisition_project_id, :config_id, :start_date, :end_date, :status)
                        RETURNING id
                        """
                    ),
                    {
                        "acquisition_project_id": acquisition_project_id,
                        "config_id": config_id,
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

    def update_end_date(self, dataset_id: int, end_date: date) -> None:
        with get_connection() as conn:
            with conn.begin():
                conn.execute(
                    text("UPDATE datasets SET end_date = :end_date WHERE id = :id"),
                    {"id": dataset_id, "end_date": end_date},
                )

    def get(self, dataset_id: int) -> dict[str, Any] | None:
        with get_connection() as conn:
            row = conn.execute(text("SELECT * FROM datasets WHERE id = :id"), {"id": dataset_id}).mappings().first()
            return dict(row) if row else None

    def list_with_stats(self) -> list[dict[str, Any]]:
        """Pour la Dataset Library : un dataset par ligne, avec l'étude, le
        Project/Query Brandwatch d'origine et le nombre de mentions liées."""
        with get_connection() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT
                        d.id AS dataset_id,
                        d.start_date, d.end_date, d.status, d.created_at,
                        d.config_id,
                        ap.id AS acquisition_project_id, ap.name AS acquisition_project_name,
                        bp.name AS bw_project_name, bq.name AS bw_query_name,
                        (SELECT count(*) FROM dataset_mentions dm WHERE dm.dataset_id = d.id) AS mention_count
                    FROM datasets d
                    LEFT JOIN acquisition_projects ap ON ap.id = d.acquisition_project_id
                    LEFT JOIN acquisition_configs ac ON ac.id = d.config_id
                    LEFT JOIN bw_projects bp ON bp.id = ac.project_id
                    LEFT JOIN bw_queries bq ON bq.id = ac.query_id
                    ORDER BY d.created_at DESC
                    """
                )
            ).mappings().all()
            return [dict(row) for row in rows]


class DatasetMentionsRepository:
    def link_batch(self, dataset_id: int, mention_ids: list[int]) -> None:
        if not mention_ids:
            return
        # Par blocs (voir RedditMentionsRepository.upsert_batch pour la raison :
        # un INSERT multi-lignes trop gros dépasse le délai maximum par requête
        # côté Supabase).
        with get_connection() as conn:
            with conn.begin():
                for chunk in chunked(mention_ids):
                    values_clause = ", ".join(f"(:dataset_id, :mention_id_{i})" for i in range(len(chunk)))
                    params: dict[str, Any] = {"dataset_id": dataset_id}
                    for i, mention_id in enumerate(chunk):
                        params[f"mention_id_{i}"] = mention_id

                    conn.execute(
                        text(
                            f"""
                            INSERT INTO dataset_mentions (dataset_id, mention_id)
                            VALUES {values_clause}
                            ON CONFLICT DO NOTHING
                            """
                        ),
                        params,
                    )
