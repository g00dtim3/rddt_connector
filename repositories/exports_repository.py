from __future__ import annotations

from sqlalchemy import text

from db.connection import get_connection


class ExportsRepository:
    def log_export(self, dataset_id: int, file_name: str, row_count: int, requested_by: str | None) -> int:
        with get_connection() as conn:
            with conn.begin():
                result = conn.execute(
                    text(
                        """
                        INSERT INTO exports (dataset_id, file_name, row_count, requested_by)
                        VALUES (:dataset_id, :file_name, :row_count, :requested_by)
                        RETURNING id
                        """
                    ),
                    {
                        "dataset_id": dataset_id,
                        "file_name": file_name,
                        "row_count": row_count,
                        "requested_by": requested_by,
                    },
                )
                return result.scalar_one()
