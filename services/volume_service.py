"""Comparaison du volume Brandwatch UI vs API (voir docs/01-spec-fonctionnelle.md, §5).

Important : le contenu Reddit peut mettre jusqu'à ~30h à arriver côté
Brandwatch. Toute comparaison doit exclure une fenêtre de sécurité des
dernières 48h, sinon des écarts apparaissent à tort sur les périodes
récentes (voir docs/06-decisions-et-risques.md).
"""

from __future__ import annotations

from typing import Any

from repositories.volume_checks_repository import VolumeChecksRepository

RECENT_WINDOW_LABEL = "48h"
WARNING_THRESHOLD_PCT = 1.0


class VolumeService:
    def __init__(self, volume_checks_repo: VolumeChecksRepository | None = None):
        self._repo = volume_checks_repo or VolumeChecksRepository()

    def compare(self, config_id: int, ui_volume: int, api_volume: int) -> dict[str, Any]:
        difference = api_volume - ui_volume
        difference_pct = (difference / ui_volume * 100) if ui_volume else 0.0
        status = "MATCH" if abs(difference_pct) <= WARNING_THRESHOLD_PCT else "MISMATCH"

        check_id = self._repo.insert(
            config_id=config_id,
            ui_volume=ui_volume,
            api_volume=api_volume,
            difference=difference,
            difference_pct=difference_pct,
            status=status,
            excluded_recent_window=RECENT_WINDOW_LABEL,
        )

        return {
            "id": check_id,
            "ui_volume": ui_volume,
            "api_volume": api_volume,
            "difference": difference,
            "difference_pct": difference_pct,
            "status": status,
            "excluded_recent_window": RECENT_WINDOW_LABEL,
        }
