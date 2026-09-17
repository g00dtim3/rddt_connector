"""Point d'entrée Streamlit — MVP Reddit (voir docs/01-spec-fonctionnelle.md).

Règle de séparation des couches (docs/02-architecture.md) : cet écran
n'appelle jamais l'API Brandwatch ni PostgreSQL directement, uniquement les
Services (`services/`).
"""

from __future__ import annotations

import streamlit as st

from config import get_brandwatch_credentials
from connectors.brandwatch_connector import BrandwatchAPIError, BrandwatchConnector
from repositories.acquisition_configs_repository import AcquisitionConfigsRepository
from repositories.datasets_repository import DatasetsRepository
from services.acquisition_service import AcquisitionService
from services.brandwatch_service import BrandwatchService
from services.export_service import ExportService
from services.volume_service import VolumeService

st.set_page_config(page_title="MVP Reddit — Brandwatch → PostgreSQL", layout="wide")


@st.cache_resource
def get_brandwatch_service() -> BrandwatchService:
    creds = get_brandwatch_credentials()
    connector = BrandwatchConnector(
        username=creds.username, password=creds.password, client_id=creds.client_id, base_url=creds.base_url
    )
    return BrandwatchService(connector)


def main() -> None:
    st.title("MVP Reddit — Brandwatch → PostgreSQL")

    screen = st.sidebar.radio("Étape", ["1. Sélection", "2. Volume", "3. Acquisition", "4. Export"])

    try:
        brandwatch_service = get_brandwatch_service()
    except RuntimeError as exc:
        st.error(str(exc))
        return

    if screen == "1. Sélection":
        render_selection(brandwatch_service)
    elif screen == "2. Volume":
        render_volume(brandwatch_service)
    elif screen == "3. Acquisition":
        render_acquisition(brandwatch_service)
    elif screen == "4. Export":
        render_export()


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

    config_id = st.session_state.get("config_id")
    if not config_id:
        st.info("Complète d'abord l'étape 1. Sélection.")
        return

    st.write(f"Config sélectionnée : #{config_id}")
    ui_volume = st.number_input("Volume affiché dans Brandwatch Consumer Research (saisie manuelle)", min_value=0, step=1)

    if st.button("Vérifier le volume API"):
        try:
            api_volume = brandwatch_service.count_mentions(
                st.session_state["config_project_id"],
                st.session_state["config_query_id"],
                st.session_state["config_start_date"],
                st.session_state["config_end_date"],
            )
        except NotImplementedError as exc:
            st.warning(str(exc))
            return
        except (BrandwatchAPIError, RuntimeError) as exc:
            st.error(str(exc))
            return

        result = VolumeService().compare(config_id, int(ui_volume), api_volume)
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
