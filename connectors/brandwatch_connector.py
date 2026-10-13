"""Connecteur HTTP vers l'API Brandwatch Consumer Research.

Seul module autorisé à parler HTTP à Brandwatch (voir docs/02-architecture.md,
séparation des couches : UI -> Service -> Connector -> API). Ne contient aucune
logique métier (pas de dédup, pas de décision MATCH/WARNING/MISMATCH) : ça
reste dans services/.

Le filtre "Reddit uniquement" (paramètre `pageType`) est géré par le Service
appelant, via `extra_params`, plutôt que codé en dur ici — voir
services/brandwatch_service.py.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Iterator

import requests

logger = logging.getLogger(__name__)

RATE_LIMIT_MAX_REQUESTS = 30
RATE_LIMIT_WINDOW_SECONDS = 600
MAX_PAGE_SIZE = 5000

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 2


class BrandwatchAPIError(RuntimeError):
    """Erreur non retryable (auth invalide, permission, requête/filtre invalide)."""


class _RateLimiter:
    """Ralentit les appels avant d'atteindre 30 requêtes / 10 minutes.

    Suivi local (source de vérité, car le quota est partagé par compte, pas
    par session) complété par les en-têtes `x-rate-limit-used` renvoyés par
    l'API quand disponibles.
    """

    def __init__(self, max_requests: int = RATE_LIMIT_MAX_REQUESTS, window_seconds: int = RATE_LIMIT_WINDOW_SECONDS):
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._timestamps: deque[float] = deque()

    def wait_if_needed(self) -> float:
        """Patiente si besoin et retourne le nombre de secondes attendues (0.0 sinon)."""
        now = time.monotonic()
        while self._timestamps and now - self._timestamps[0] >= self._window_seconds:
            self._timestamps.popleft()
        if len(self._timestamps) >= self._max_requests:
            sleep_for = self._window_seconds - (now - self._timestamps[0])
            if sleep_for > 0:
                time.sleep(sleep_for)
                return sleep_for
        return 0.0

    def record_call(self) -> None:
        self._timestamps.append(time.monotonic())


@dataclass
class MentionsPage:
    results: list[dict[str, Any]]
    results_total: int | None
    next_cursor: str | None


class BrandwatchConnector:
    def __init__(self, username: str, password: str, client_id: str, base_url: str):
        self._username = username
        self._password = password
        self._client_id = client_id
        self._base_url = base_url.rstrip("/")
        self._rate_limiter = _RateLimiter()
        self._access_token: str | None = None
        self._on_event: Callable[[str], None] | None = None

    def set_event_sink(self, callback: Callable[[str], None] | None) -> None:
        """Branche (ou débranche avec None) un callback appelé à chaque étape d'un
        appel HTTP (tentative, pause rate limit, retry, résultat) — mode verbose
        pour l'UI, en plus du logging standard."""
        self._on_event = callback

    def _emit(self, message: str) -> None:
        logger.info(message)
        if self._on_event:
            self._on_event(message)

    # -- Authentification --------------------------------------------------

    def _authenticate(self) -> dict[str, Any]:
        # Convention standard OAuth2 : les paramètres du token endpoint
        # partent dans le corps de la requête (application/x-www-form-
        # urlencoded), pas en query string. Deux essais précédents avec les
        # paramètres en query string ont échoué avec la même erreur 500
        # générique de Brandwatch, ce qui suggère que le problème n'est pas
        # là où ces paramètres sont envoyés (voir docs/06-decisions-et-
        # risques.md, "Risque : accès API non confirmé").
        response = self._request(
            "POST",
            "/oauth/token",
            data={
                "username": self._username,
                "password": self._password,
                "grant_type": "api-password",
                "client_id": self._client_id,
            },
            authenticated=False,
        )
        return response.json()

    def _token(self) -> str:
        if self._access_token is None:
            payload = self._authenticate()
            token = payload.get("access_token")
            if not token:
                raise BrandwatchAPIError("Réponse d'authentification Brandwatch sans access_token.")
            self._access_token = token
        return self._access_token

    def test_connection(self) -> dict[str, Any]:
        """Vérifie que l'authentification Brandwatch fonctionne (1 appel API).

        À utiliser pour un contrôle explicite (écran Connexions), pas en
        automatique à chaque démarrage : ça consomme une requête du quota
        partagé de 30/10min.
        """
        payload = self._authenticate()
        token = payload.get("access_token")
        if not token:
            raise BrandwatchAPIError("Réponse d'authentification Brandwatch sans access_token.")
        self._access_token = token
        return {
            "token_type": payload.get("token_type"),
            "scope": payload.get("scope"),
            "expires_in": payload.get("expires_in"),
        }

    # -- HTTP bas niveau (rate limit + retry) --------------------------------

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> requests.Response:
        url = f"{self._base_url}{path}"
        headers = {"Authorization": f"Bearer {self._token()}"} if authenticated else {}

        backoff = INITIAL_BACKOFF_SECONDS
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            sleep_for = self._rate_limiter.wait_if_needed()
            if sleep_for > 0:
                self._emit(f"Quota Brandwatch : pause de {sleep_for:.1f}s avant {method} {path}")

            self._emit(f"{method} {path} (tentative {attempt}/{MAX_RETRIES})")
            request_start = time.monotonic()
            try:
                response = requests.request(method, url, params=params, data=data, headers=headers, timeout=30)
                self._rate_limiter.record_call()
            except requests.RequestException as exc:
                elapsed = time.monotonic() - request_start
                last_error = exc
                if attempt == MAX_RETRIES:
                    self._emit(f"Échec réseau définitif sur {method} {path} après {elapsed:.1f}s : {exc}")
                    raise BrandwatchAPIError(f"Échec réseau après {MAX_RETRIES} tentatives : {exc}") from exc
                self._emit(f"Erreur réseau sur {method} {path} ({exc}), nouvel essai dans {backoff}s")
                time.sleep(backoff)
                backoff *= 2
                continue

            elapsed = time.monotonic() - request_start

            if response.status_code < 400:
                self._emit(f"{method} {path} -> {response.status_code} en {elapsed:.1f}s")
                return response

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                self._emit(
                    f"{method} {path} -> {response.status_code} en {elapsed:.1f}s, nouvel essai dans {backoff}s"
                )
                time.sleep(backoff)
                backoff *= 2
                continue

            self._emit(f"{method} {path} -> {response.status_code} (échec définitif)")
            raise BrandwatchAPIError(
                f"Brandwatch a répondu {response.status_code} sur {method} {path} : {response.text[:500]}"
            )

        raise BrandwatchAPIError(f"Échec après {MAX_RETRIES} tentatives : {last_error}")

    # -- Projects / Queries ---------------------------------------------------

    def list_projects(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/projects/summary")
        payload = response.json()
        return payload if isinstance(payload, list) else payload.get("results", payload)

    def list_queries(self, project_id: int) -> list[dict[str, Any]]:
        response = self._request("GET", f"/projects/{project_id}/queries/summary")
        payload = response.json()
        return payload if isinstance(payload, list) else payload.get("results", payload)

    # -- Découverte des filtres (pour confirmer le filtre Reddit, voir docs/05) --

    def list_filters(self) -> dict[str, Any]:
        """GET /filters — liste les champs filtrables (ex. pageType, gender, sentiment)."""
        return self._request("GET", "/filters").json()

    def list_metrics(self) -> dict[str, Any]:
        """GET /metrics — liste les filtres à valeurs limitées et leurs valeurs acceptées
        (ex. les valeurs possibles de pageType, dont celle pour Reddit)."""
        return self._request("GET", "/metrics").json()

    # -- Comptage ---------------------------------------------------------------

    def count_mentions(
        self,
        project_id: int,
        query_id: int,
        start_date: str,
        end_date: str,
        extra_params: dict[str, Any] | None = None,
    ) -> int:
        """GET /projects/{projectId}/data/mentions/count — nombre de mentions sans
        les récupérer entièrement. Endpoint trouvé dans la doc publique Brandwatch
        ("Total Mentions") ; à vérifier contre un vrai appel lors du premier test
        (voir docs/05-brandwatch-api-notes.md)."""
        params = {
            "queryId": query_id,
            "startDate": start_date,
            "endDate": end_date,
            **(extra_params or {}),
        }
        response = self._request("GET", f"/projects/{project_id}/data/mentions/count", params=params)
        payload = response.json()
        return payload["mentionsCount"]

    # -- Mentions (pagination par cursor au-delà de 10 000 résultats) ----------

    def iter_mentions(
        self,
        project_id: int,
        query_id: int,
        start_date: str,
        end_date: str,
        page_size: int = MAX_PAGE_SIZE,
        extra_params: dict[str, Any] | None = None,
        resume_cursor: str | None = None,
    ) -> Iterator[MentionsPage]:
        if page_size > MAX_PAGE_SIZE:
            raise ValueError(f"pageSize maximum autorisé par Brandwatch : {MAX_PAGE_SIZE}")

        params = {
            "queryId": query_id,
            "startDate": start_date,
            "endDate": end_date,
            "pageSize": page_size,
            "orderBy": "date",
            "orderDirection": "asc",
            **(extra_params or {}),
        }

        cursor = resume_cursor
        received_so_far = 0
        while True:
            page_params = dict(params)
            if cursor:
                page_params["cursor"] = cursor

            response = self._request("GET", f"/projects/{project_id}/data/mentions", params=page_params)
            payload = response.json()

            results = payload.get("results", [])
            results_total = payload.get("resultsTotal")
            next_cursor = payload.get("nextCursor") or None
            received_so_far += len(results)

            yield MentionsPage(
                results=results,
                results_total=results_total,
                next_cursor=next_cursor,
            )

            # Trois conditions d'arrêt indépendantes : le total annoncé par
            # Brandwatch est atteint, il n'y a plus de curseur, ou le curseur ne
            # progresse plus (vu en conditions réelles : Brandwatch peut renvoyer
            # le même nextCursor en boucle au lieu de le vider une fois la fin
            # atteinte — sans ce filet, ça boucle indéfiniment sur la même page).
            reached_total = results_total is not None and received_so_far >= results_total
            no_progress = next_cursor is not None and next_cursor == cursor
            if not results or not next_cursor or reached_total or no_progress:
                if no_progress:
                    self._emit(f"Curseur inchangé après {received_so_far} mentions reçues, arrêt de la pagination")
                break
            cursor = next_cursor
