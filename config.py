"""Lecture des secrets (identifiants Brandwatch, connexion Supabase).

Aucun credential ne doit être écrit en dur ici : tout vient soit des
secrets Streamlit (`.streamlit/secrets.toml`, jamais commité), soit de
variables d'environnement — utile pour les scripts (ex. migrations) lancés
hors du serveur Streamlit.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _get_secret(section: str, key: str, env_var: str, default: str | None = None) -> str | None:
    try:
        import streamlit as st

        if section in st.secrets and key in st.secrets[section]:
            return st.secrets[section][key]
    except Exception:
        pass
    return os.environ.get(env_var, default)


@dataclass(frozen=True)
class BrandwatchCredentials:
    username: str
    password: str
    client_id: str
    base_url: str


@dataclass(frozen=True)
class SupabaseCredentials:
    host: str
    port: int
    dbname: str
    user: str
    password: str


def get_brandwatch_credentials() -> BrandwatchCredentials:
    username = _get_secret("brandwatch", "username", "BW_USERNAME")
    password = _get_secret("brandwatch", "password", "BW_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            "Identifiants Brandwatch manquants : renseigne "
            "[brandwatch].username / .password dans .streamlit/secrets.toml "
            "(voir .streamlit/secrets.toml.example) ou les variables "
            "d'environnement BW_USERNAME / BW_PASSWORD."
        )
    return BrandwatchCredentials(
        username=username,
        password=password,
        client_id=_get_secret("brandwatch", "client_id", "BW_CLIENT_ID", "brandwatch-api-client"),
        base_url=_get_secret("brandwatch", "base_url", "BW_BASE_URL", "https://api.brandwatch.com"),
    )


def get_supabase_credentials() -> SupabaseCredentials:
    host = _get_secret("supabase", "host", "SUPABASE_HOST")
    user = _get_secret("supabase", "user", "SUPABASE_USER")
    password = _get_secret("supabase", "password", "SUPABASE_PASSWORD")
    if not host or not user or not password:
        raise RuntimeError(
            "Identifiants Supabase manquants : renseigne [supabase] dans "
            ".streamlit/secrets.toml (voir .streamlit/secrets.toml.example) "
            "ou les variables d'environnement SUPABASE_HOST / SUPABASE_USER / "
            "SUPABASE_PASSWORD."
        )
    return SupabaseCredentials(
        host=host,
        port=int(_get_secret("supabase", "port", "SUPABASE_PORT", "5432")),
        dbname=_get_secret("supabase", "dbname", "SUPABASE_DBNAME", "postgres"),
        user=user,
        password=password,
    )
