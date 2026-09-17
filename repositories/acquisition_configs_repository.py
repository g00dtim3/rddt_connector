from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy import text

from db.connection import get_connection


class AcquisitionConfigsRepository:
    def create(
        self,
        project_id: int,
        query_id: int,
        start_date: date,
        end_date: date,
        timezone: str = "UTC",
        filters: list[dict[str, Any]] | None = None,
        acquisition_project_id: int | None = None,
        config_hash: str | None = None,
    ) -> int:
        with get_connection() as conn:
            with conn.begin():
                result = conn.execute(
                    text(
                        """
                        INSERT INTO acquisition_configs
                            (acquisition_project_id, project_id, query_id, start_date, end_date,
                             timezone, filters, config_hash)
                        VALUES
                            (:acquisition_project_id, :project_id, :query_id, :start_date, :end_date,
                             :timezone, :filters, :config_hash)
                        RETURNING id
                        """
                    ),
                    {
                        "acquisition_project_id": acquisition_project_id,
                        "project_id": project_id,
                        "query_id": query_id,
                        "start_date": start_date,
                        "end_date": end_date,
                        "timezone": timezone,
                        "filters": json.dumps(filters or []),
                        "config_hash": config_hash,
                    },
                )
                return result.scalar_one()

    def get(self, config_id: int) -> dict[str, Any] | None:
        with get_connection() as conn:
            row = conn.execute(
                text("SELECT * FROM acquisition_configs WHERE id = :id"), {"id": config_id}
            ).mappings().first()
            return dict(row) if row else None
