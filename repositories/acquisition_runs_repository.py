from __future__ import annotations

from typing import Any

from sqlalchemy import text

from db.connection import get_connection


class AcquisitionRunsRepository:
    def create(self, config_id: int, expected_volume: int | None = None) -> int:
        with get_connection() as conn:
            with conn.begin():
                result = conn.execute(
                    text(
                        """
                        INSERT INTO acquisition_runs (config_id, status, expected_volume, started_at)
                        VALUES (:config_id, 'RUNNING', :expected_volume, now())
                        RETURNING id
                        """
                    ),
                    {"config_id": config_id, "expected_volume": expected_volume},
                )
                return result.scalar_one()

    def update_progress(
        self,
        run_id: int,
        received_volume: int,
        inserted_volume: int,
        existing_volume: int,
        checkpoint: str | None,
    ) -> None:
        with get_connection() as conn:
            with conn.begin():
                conn.execute(
                    text(
                        """
                        UPDATE acquisition_runs
                        SET received_volume = :received_volume,
                            inserted_volume = :inserted_volume,
                            existing_volume = :existing_volume,
                            checkpoint = :checkpoint
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": run_id,
                        "received_volume": received_volume,
                        "inserted_volume": inserted_volume,
                        "existing_volume": existing_volume,
                        "checkpoint": checkpoint,
                    },
                )

    def mark_completed(self, run_id: int) -> None:
        with get_connection() as conn:
            with conn.begin():
                conn.execute(
                    text("UPDATE acquisition_runs SET status = 'COMPLETED', completed_at = now() WHERE id = :id"),
                    {"id": run_id},
                )

    def mark_failed(self, run_id: int, error_code: str, error_message: str) -> None:
        with get_connection() as conn:
            with conn.begin():
                conn.execute(
                    text(
                        """
                        UPDATE acquisition_runs
                        SET status = 'FAILED', error_code = :error_code, error_message = :error_message
                        WHERE id = :id
                        """
                    ),
                    {"id": run_id, "error_code": error_code, "error_message": error_message},
                )

    def get_resumable_run(self, config_id: int) -> dict[str, Any] | None:
        with get_connection() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT * FROM acquisition_runs
                    WHERE config_id = :config_id AND status IN ('RUNNING', 'FAILED') AND checkpoint IS NOT NULL
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ),
                {"config_id": config_id},
            ).mappings().first()
            return dict(row) if row else None
