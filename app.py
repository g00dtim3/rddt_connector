"""Point d'entrée Streamlit — MVP Reddit (voir docs/01-spec-fonctionnelle.md).

Règle de séparation des couches (docs/02-architecture.md) : cet écran
n'appelle jamais l'API Brandwatch ni PostgreSQL directement, uniquement les
Services (`services/`).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

import streamlit as st

from config import get_brandwatch_credentials
from connectors.brandwatch_connector import BrandwatchAPIError, BrandwatchConnector
from db.connection import test_connection as test_db_connection
from repositories.acquisition_configs_repository import AcquisitionConfigsRepository
from repositories.datasets_repository import DatasetsRepository
from services.acquisition_service import AcquisitionService
from services.brandwatch_service import BrandwatchService
from services.export_service import ExportService
from services.volume_service import VolumeService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

st.set_page_config(page_title="MVP Reddit — Brandwatch → PostgreSQL", layout="wide")


def _make_event_logger(placeholder) -> Callable[[str], None]:
    """Journal en direct (mode verbose) : accumule les événements et les affiche
    dans `placeholder` au fur et à mesure, même pendant une pause/retry qui
    bloque le reste du script (Streamlit est mono-thread par session)."""
    lines: list[str] = []

    def _log(message: str) -> None:
        lines.append(f"{datetime.now().strftime('%H:%M:%S')} — {message}")
        placeholder.code("\n".join(lines[-40:]))

    return _log

SCREENS = ["0. Connexions", "1. Sélection", "2. Volume", "3. Acquisition", "4. Export"]


@st.cache_resource
def get_brandwatch_service() -> BrandwatchService:
    creds = get_brandwatch_credentials()
    connector = BrandwatchConnector(
        username=creds.username, password=creds.password, client_id=creds.client_id, base_url=creds.base_url
    )
    return BrandwatchService(connector)


def main() -> None:
    st.title("MVP Reddit — Brandwatch → PostgreSQL")

    screen = st.sidebar.radio("Étape", SCREENS)

    brandwatch_service: BrandwatchService | None = None
    brandwatch_setup_error: str | None = None
    try:
        brandwatch_service = get_brandwatch_service()
    except RuntimeError as exc:
        brandwatch_setup_error = str(exc)

    if screen == "0. Connexions":
        render_connections(brandwatch_service, brandwatch_setup_error)
        return

    if brandwatch_service is None and screen in {"1. Sélection", "2. Volume", "3. Acquisition"}:
        st.error(brandwatch_setup_error)
        st.info("Va à l'écran « 0. Connexions » pour le détail.")
        return

    if screen == "1. Sélection":
        render_selection(brandwatch_service)
    elif screen == "2. Volume":
        render_volume(brandwatch_service)
    elif screen == "3. Acquisition":
        render_acquisition(brandwatch_service)
    elif screen == "4. Export":
        render_export()


def render_connections(brandwatch_service: BrandwatchService | None, brandwatch_setup_error: str | None) -> None:
    st.header("0. Connexions — vérifications au démarrage")
    st.caption(
        "Vérifie que l'app peut parler à Brandwatch et à la base de données avant "
        "d'utiliser les autres écrans."
    )

    if "db_check" not in st.session_state:
        _run_db_check()

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Brandwatch")
        st.caption(
            "Test manuel uniquement : chaque test consomme 1 appel du quota "
            "partagé de 30 requêtes / 10 minutes."
        )
        if brandwatch_setup_error:
            st.error(brandwatch_setup_error)
        else:
            if st.button("Tester la connexion Brandwatch"):
                log_sink = _make_event_logger(st.empty())
                brandwatch_service.set_event_sink(log_sink)
                try:
                    _run_brandwatch_check(brandwatch_service)
                finally:
                    brandwatch_service.set_event_sink(None)
            _render_check_result(st.session_state.get("brandwatch_check"))

    with col2:
        st.subheader("Base de données (Supabase)")
        if st.button("Retester la connexion à la base"):
            _run_db_check()
        _render_check_result(st.session_state.get("db_check"))

    if not brandwatch_setup_error:
        st.divider()
        st.subheader("Découverte des filtres Brandwatch")
        st.caption(
            "Pour confirmer la valeur exacte de pageType correspondant à Reddit "
            "(voir docs/05-brandwatch-api-notes.md). Chaque appel consomme aussi "
            "1 requête du quota."
        )
        col3, col4 = st.columns(2)
        with col3:
            if st.button("Appeler /filters"):
                try:
                    st.session_state["filters_result"] = brandwatch_service.list_filters()
                except (BrandwatchAPIError, RuntimeError) as exc:
                    st.session_state["filters_result"] = None
                    st.error(str(exc))
            if st.session_state.get("filters_result") is not None:
                st.json(st.session_state["filters_result"])
        with col4:
            if st.button("Appeler /metrics"):
                try:
                    st.session_state["metrics_result"] = brandwatch_service.list_metrics()
                except (BrandwatchAPIError, RuntimeError) as exc:
                    st.session_state["metrics_result"] = None
                    st.error(str(exc))
            if st.session_state.get("metrics_result") is not None:
                st.json(st.session_state["metrics_result"])
                st.caption(
                    "Cherche la clé pageType ci-dessus : la valeur correspondant à "
                    "Reddit va dans REDDIT_ONLY_FILTER_VALUE (services/brandwatch_service.py)."
                )


def _run_brandwatch_check(brandwatch_service: BrandwatchService) -> None:
    try:
        info = brandwatch_service.test_connection()
        st.session_state["brandwatch_check"] = {
            "ok": True,
            "message": f"Authentification réussie (scope : {info.get('scope')}).",
            "checked_at": datetime.now().strftime("%H:%M:%S"),
        }
    except (BrandwatchAPIError, RuntimeError) as exc:
        st.session_state["brandwatch_check"] = {
            "ok": False,
            "message": str(exc),
            "checked_at": datetime.now().strftime("%H:%M:%S"),
        }


def _run_db_check() -> None:
    try:
        info = test_db_connection()
        st.session_state["db_check"] = {
            "ok": True,
            "message": f"Connecté à {info['host']}:{info['port']}/{info['dbname']}.",
            "checked_at": datetime.now().strftime("%H:%M:%S"),
        }
    except Exception as exc:  # connexion DB : erreurs variées (réseau, credentials, driver)
        st.session_state["db_check"] = {
            "ok": False,
            "message": str(exc),
            "checked_at": datetime.now().strftime("%H:%M:%S"),
        }


def _render_check_result(result: dict | None) -> None:
    if result is None:
        st.info("Pas encore testé.")
        return
    display = st.success if result["ok"] else st.error
    display(f"{result['message']} (vérifié à {result['checked_at']})")


def render_selection(brandwatch_service: BrandwatchService) -> None:
    st.header("1. Sélection — Project, Query, dates")

    if st.button("Charger les Projects depuis Brandwatch"):
        try:
            st.session_state["projects"] = brandwatch_service.sync_projects()
        except BrandwatchAPIError as exc:
            st.error(f"Échec de l'appel Brandwatch : {exc}")

    projects = st.session_state.get("projects", brandwatch_service.list_cached_projects())
    if not projects:
        st.info("Aucun Project en cache. Clique sur « Charger les Projects » ci-dessus.")
        return

    project_labels = {p["id"]: p["name"] for p in projects}
    project_id = st.selectbox(
        "Project", options=list(project_labels), format_func=lambda pid: project_labels[pid]
    )

    if st.button("Charger les Queries de ce Project"):
        try:
            st.session_state["queries"] = brandwatch_service.sync_queries(project_id)
        except BrandwatchAPIError as exc:
            st.error(f"Échec de l'appel Brandwatch : {exc}")

    queries = st.session_state.get("queries", brandwatch_service.list_cached_queries(project_id))
    if not queries:
        st.info("Aucune Query en cache pour ce Project. Clique sur « Charger les Queries ».")
        return

    query_labels = {q["id"]: q["name"] for q in queries}
    query_id = st.selectbox("Query", options=list(query_labels), format_func=lambda qid: query_labels[qid])

    col1, col2 = st.columns(2)
    start_date = col1.date_input("Date de début")
    end_date = col2.date_input("Date de fin")

    st.caption(
        "Rappel : la comparaison de volume (étape 2) exclura automatiquement les "
        "dernières 48h — le contenu Reddit récent met du temps à arriver côté Brandwatch."
    )

    if st.button("Valider la sélection"):
        if start_date > end_date:
            st.error("La date de début doit précéder la date de fin.")
            return
        config_id = AcquisitionConfigsRepository().create(
            project_id=project_id, query_id=query_id, start_date=start_date, end_date=end_date
        )
        st.session_state["config_id"] = config_id
        st.session_state["config_project_id"] = project_id
        st.session_state["config_query_id"] = query_id
        st.session_state["config_start_date"] = str(start_date)
        st.session_state["config_end_date"] = str(end_date)
        st.success(f"Sélection enregistrée (config #{config_id}). Passe à l'étape 2. Volume.")


def render_volume(brandwatch_service: BrandwatchService) -> None:
    st.header("2. Volume — comparaison UI vs API")
    st.caption(
        "Ce contrôle est informatif : un MISMATCH n'empêche pas de passer à "
        "l'étape 3. Acquisition si tu juges que c'est pertinent quand même."
    )

    config_id = st.session_state.get("config_id")
    if not config_id:
        st.info("Complète d'abord l'étape 1. Sélection.")
        return

    volume_service = VolumeService()
    effective_end_date = volume_service.effective_comparison_end_date(st.session_state["config_end_date"])

    st.write(f"Config sélectionnée : #{config_id}")
    if effective_end_date != st.session_state["config_end_date"]:
        st.caption(
            f"La comparaison portera sur {st.session_state['config_start_date']} → "
            f"{effective_end_date} (fenêtre des 48 dernières heures exclue), pas sur "
            f"la date de fin complète de la sélection ({st.session_state['config_end_date']})."
        )

    ui_volume = st.number_input(
        f"Volume affiché dans Brandwatch Consumer Research pour cette même période "
        f"({st.session_state['config_start_date']} → {effective_end_date})",
        min_value=0,
        step=1,
    )
    diagnose = st.checkbox(
        "Comparer aussi sans le filtre pageType=reddit (diagnostic en cas d'écart)"
    )

    if st.button("Vérifier le volume API"):
        log_sink = _make_event_logger(st.empty())
        brandwatch_service.set_event_sink(log_sink)
        try:
            api_volume = brandwatch_service.count_mentions(
                st.session_state["config_project_id"],
                st.session_state["config_query_id"],
                st.session_state["config_start_date"],
                effective_end_date,
            )
            unfiltered_volume = None
            if diagnose:
                unfiltered_volume = brandwatch_service.count_mentions_unfiltered(
                    st.session_state["config_project_id"],
                    st.session_state["config_query_id"],
                    st.session_state["config_start_date"],
                    effective_end_date,
                )
        except NotImplementedError as exc:
            st.warning(str(exc))
            return
        except (BrandwatchAPIError, RuntimeError) as exc:
            st.error(str(exc))
            return
        finally:
            brandwatch_service.set_event_sink(None)

        st.write(f"Volume UI : **{int(ui_volume)}** — Volume API avec pageType=reddit : **{api_volume}**")
        if unfiltered_volume is not None:
            st.write(
                f"Volume API sans filtre (diagnostic) : **{unfiltered_volume}** "
                f"(écart avec le filtré : {unfiltered_volume - api_volume})"
            )
            if unfiltered_volume != api_volume:
                st.info(
                    "Le filtre pageType=reddit exclut des mentions de cette Query : "
                    "possible tagging incomplet depuis la bascule de flux Reddit du "
                    "28/08/2026 (voir docs/06-decisions-et-risques.md)."
                )

        result = volume_service.compare(config_id, int(ui_volume), api_volume)
        status_display = {"MATCH": st.success, "MISMATCH": st.error}[result["status"]]
        status_display(
            f"Statut : {result['status']} — écart {result['difference']} "
            f"({result['difference_pct']:.2f}%), fenêtre exclue : {result['excluded_recent_window']}"
        )


def render_acquisition(brandwatch_service: BrandwatchService) -> None:
    st.header("3. Acquisition — récupération et stockage")

    config_id = st.session_state.get("config_id")
    if not config_id:
        st.info("Complète d'abord l'étape 1. Sélection.")
        return

    if st.button("Lancer / reprendre l'acquisition"):
        dataset_id = st.session_state.get("dataset_id")
        if dataset_id is None:
            dataset_id = DatasetsRepository().create(
                start_date=st.session_state["config_start_date"],
                end_date=st.session_state["config_end_date"],
            )
            st.session_state["dataset_id"] = dataset_id

        acquisition_service = AcquisitionService(brandwatch_service)
        progress_placeholder = st.empty()
        st.caption("Mode verbose — détail des appels Brandwatch en direct :")
        log_sink = _make_event_logger(st.empty())
        brandwatch_service.set_event_sink(log_sink)
        try:
            for progress in acquisition_service.run(
                config_id=config_id,
                project_id=st.session_state["config_project_id"],
                query_id=st.session_state["config_query_id"],
                start_date=st.session_state["config_start_date"],
                end_date=st.session_state["config_end_date"],
                dataset_id=dataset_id,
            ):
                progress_placeholder.write(
                    f"Reçues : {progress['received']} — nouvelles : {progress['inserted']} — "
                    f"déjà en base : {progress['existing']}"
                )
        except (BrandwatchAPIError, RuntimeError) as exc:
            st.error(f"Acquisition interrompue : {exc}")
            return
        finally:
            brandwatch_service.set_event_sink(None)

        DatasetsRepository().update_status(dataset_id, "COMPLETE")
        st.success(f"Acquisition terminée. Dataset #{dataset_id} prêt pour l'export.")


def render_export() -> None:
    st.header("4. Export — CSV depuis PostgreSQL")
    st.caption("Cet écran ne déclenche jamais d'appel à l'API Brandwatch.")

    default_dataset_id = st.session_state.get("dataset_id", 0)
    dataset_id = st.number_input("ID du dataset à exporter", min_value=1, value=default_dataset_id or 1, step=1)
    requested_by = st.text_input("Demandé par (nom ou email, optionnel)")

    if st.button("Générer le CSV"):
        file_name, content = ExportService().generate_csv(int(dataset_id), requested_by=requested_by or None)
        st.download_button("Télécharger le CSV", data=content, file_name=file_name, mime="text/csv")


if __name__ == "__main__":
    main()
