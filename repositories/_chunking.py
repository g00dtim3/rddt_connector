"""Découpage en blocs pour les écritures multi-lignes (voir RedditMentionsRepository
et DatasetMentionsRepository) : une requête unique pour toute une page Brandwatch
(jusqu'à 5000 lignes) peut dépasser le délai maximum par requête côté Supabase
(psycopg2.errors.QueryCanceled). Des blocs de taille modérée restent rapides tout
en gardant le bénéfice d'un seul aller-retour réseau par bloc plutôt que par ligne.
"""

from __future__ import annotations

from typing import Iterator, Sequence, TypeVar

T = TypeVar("T")

CHUNK_SIZE = 250


def chunked(items: Sequence[T], size: int = CHUNK_SIZE) -> Iterator[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]
