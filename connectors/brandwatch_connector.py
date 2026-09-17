"""Connecteur HTTP vers l'API Brandwatch Consumer Research.

Seul module autorisé à parler HTTP à Brandwatch (voir docs/02-architecture.md,
séparation des couches : UI -> Service -> Connector -> API). Ne contient aucune
logique métier (pas de dédup, pas de décision MATCH/WARNING/MISMATCH) : ça
reste dans services/.

Deux points sont volontairement laissés en `NotImplementedError` /
paramètre optionnel plutôt que devinés, conformément à CLAUDE.md et à la
section "À confirmer" de docs/05-brandwatch-api-notes.md :
- le nom exact de l'endpoint de comptage (`count_mentions`) ;
- le nom exact du paramètre "Reddit uniquement" (laissé au niveau du Service
  appelant, via `extra_params`, plutôt que codé en dur ici).
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Iterator

import requests

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

    def wait_if_needed(self) -> None:
        now = time.monotonic()
        while self._timestamps and now - self._timestamps[0] >= self._window_seconds:
            self._timestamps.popleft()
        if len(self._timestamps) >= self._max_requests:
            sleep_for = self._window_seconds - (now - self._timestamps[0])
            if sleep_for > 0:
                time.sleep(sleep_for)

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

    # -- Authentification --------------------------------------------------

    def _authenticate(self) -> str:
        response = self._request(
            "POST",
            "/oauth/token",
            params={
                "username": self._username,
                "grant_type": "api-password",
                "client_id": self._client_id,
            },
            data={"password": self._password},
            authenticated=False,
        )
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise BrandwatchAPIError("Réponse d'authentification Brandwatch sans access_token.")
        return token

    def _token(self) -> str:
        if self._access_token is None:
            self._access_token = self._authenticate()
        return self._access_token

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
            self._rate_limiter.wait_if_needed()
            try:
                response = requests.request(method, url, params=params, data=data, headers=headers, timeout=30)
                self._rate_limiter.record_call()
            except requests.RequestException as exc:
                last_error = exc
                if attempt == MAX_RETRIES:
                    raise BrandwatchAPIError(f"Échec réseau après {MAX_RETRIES} tentatives : {exc}") from exc
                time.sleep(backoff)
                backoff *= 2
                continue

            if response.status_code < 400:
                return response

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                time.sleep(backoff)
                backoff *= 2
                continue

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

    # -- Comptage (non confirmé, voir docs/05) ---------------------------------

    def count_mentions(
        self,
        project_id: int,
        query_id: int,
        start_date: str,
        end_date: str,
        extra_params: dict[str, Any] | None = None,
    ) -> int:
        raise NotImplementedError(
            "Endpoint de comptage Brandwatch non confirmé (voir docs/05-brandwatch-"
            "api-notes.md, section 'À confirmer'). À implémenter une fois le nom "
            "exact de l'endpoint et de ses paramètres vérifié dans la doc "
            "'Available Filters' / par un appel réel."
        )

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
        while True:
            page_params = dict(params)
            if cursor:
                page_params["cursor"] = cursor

            response = self._request("GET", f"/projects/{project_id}/data/mentions", params=page_params)
            payload = response.json()

            results = payload.get("results", [])
            cursor = payload.get("nextCursor") or None

            yield MentionsPage(
                results=results,
                results_total=payload.get("resultsTotal"),
                next_cursor=cursor,
            )

            if not results or not cursor:
                break
