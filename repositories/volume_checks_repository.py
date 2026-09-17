from __future__ import annotations

from sqlalchemy import text

from db.connection import get_connection


class VolumeChecksRepository:
    def insert(
        self,
        config_id: int,
        ui_volume: int,
        api_volume: int,
        difference: int,
        difference_pct: float,
        status: str,
        excluded_recent_window: str | None,
    ) -> int:
        with get_connection() as conn:
            with conn.begin():
                result = conn.execute(
                    text(
                        """
                        INSERT INTO volume_checks
                            (config_id, ui_volume, api_volume, difference, difference_pct, status, excluded_recent_window)
                        VALUES
                            (:config_id, :ui_volume, :api_volume, :difference, :difference_pct, :status, :excluded_recent_window)
                        RETURNING id
                        """
                    ),
                    {
                        "config_id": config_id,
                        "ui_volume": ui_volume,
                        "api_volume": api_volume,
                        "difference": difference,
                        "difference_pct": difference_pct,
                        "status": status,
                        "excluded_recent_window": excluded_recent_window,
                    },
                )
                return result.scalar_one()
