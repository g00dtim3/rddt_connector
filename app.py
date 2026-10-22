"""Point d'entrée Streamlit — MVP Reddit (voir docs/01-spec-fonctionnelle.md).

Règle de séparation des couches (docs/02-architecture.md) : cet écran
n'appelle jamais l'API Brandwatch ni PostgreSQL directement, uniquement les
Services (`services/`).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Callable

import pandas as pd
import streamlit as st

from auth import exiger_mot_de_passe
from charte import appliquer_charte, badge_statut, bandeau, encadre_cle, etapes, libelle_statut, section, vide
from config import get_brandwatch_credentials
from connectors.brandwatch_connector import BrandwatchAPIError, BrandwatchConnector
from db.connection import test_connection as test_db_connection
from repositories.acquisition_configs_repository import AcquisitionConfigsRepository
from repositories.acquisition_projects_repository import AcquisitionProjectsRepository
from repositories.datasets_repository import DatasetsRepository
from services.acquisition_service import AcquisitionService
from services.brandwatch_service import BrandwatchService
from services.export_service import ExportService
from services.volume_service import VolumeService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

st.set_page_config(page_title="Collecte Reddit", page_icon=":material/forum:", layout="wide")
exiger_mot_de_passe()  # rien ne s'exécute après tant que le mot de passe n'est pas saisi
appliquer_charte()

APPLI = "Consumer Voice · Collecte Reddit"


def _make_event_logger(placeholder) -> Callable[[str], None]:
    """Journal en direct (mode verbose) : accumule les événements et les affiche
    dans `placeholder` au fur et à mesure, même pendant une pause/retry qui
    bloque le reste du script (Streamlit est mono-thread par session)."""
    lines: list[str] = []

    def _log(message: str) -> None:
        lines.append(f"{datetime.now().strftime('%H:%M:%S')} — {message}")
        placeholder.code("\n".join(lines[-40:]))

    return _log


def _nombre(valeur: int) -> str:
    """Nombre au format français : 189 824."""
    return f"{valeur:,}".replace(",", "\u00a0")


def _date(valeur: date | str | None) -> str:
    """Date au format JJ/MM/AAAA (accepte une date ou une chaîne AAAA-MM-JJ)."""
    if valeur is None:
        return "—"
    if isinstance(valeur, str):
        valeur = date.fromisoformat(valeur[:10])
    return valeur.strftime("%d/%m/%Y")


def _render_counters(placeholder, progress: dict[str, int]) -> None:
    """Compteurs d'une acquisition en cours (reçues, nouvelles, déjà en base)."""
    with placeholder.container():
        col1, col2, col3 = st.columns(3)
        col1.metric("Mentions reçues", _nombre(progress["received"]), border=True)
        col2.metric("Nouvelles en base", _nombre(progress["inserted"]), border=True)
        col3.metric("Déjà en base", _nombre(progress["existing"]), border=True)


# Écran → (sous-titre du bandeau, icône Material de la navigation)
SCREENS = {
    "Connexions": ("Vérifier l'accès à Brandwatch et à la base de données avant de commencer.", "power"),
    "Sélection et volume": ("Choisir le Project, la Query et la période, puis contrôler le volume.", "tune"),
    "Acquisition": ("Récupérer les mentions Reddit et les enregistrer en base.", "cloud_download"),
    "Export": ("Télécharger un dataset en CSV, depuis la base de données.", "download"),
    "Bibliothèque de datasets": ("Tous les datasets acquis, regroupés par étude.", "folder_open"),
}
PARCOURS = ["Sélection et volume", "Acquisition", "Export"]


@st.cache_resource
def get_brandwatch_service() -> BrandwatchService:
    creds = get_brandwatch_credentials()
    connector = BrandwatchConnector(
        username=creds.username, password=creds.password, client_id=creds.client_id, base_url=creds.base_url
    )
    return BrandwatchService(connector)


def main() -> None:
    screen = st.sidebar.radio(
        "Écran", list(SCREENS), format_func=lambda nom: f":material/{SCREENS[nom][1]}: {nom}"
    )

    bandeau(APPLI, screen, sous_titre=SCREENS[screen][0])
    if screen in PARCOURS:
        etapes(PARCOURS, courante=PARCOURS.index(screen))

    brandwatch_service: BrandwatchService | None = None
    brandwatch_setup_error: str | None = None
    try:
        brandwatch_service = get_brandwatch_service()
    except RuntimeError as exc:
        brandwatch_setup_error = str(exc)

    if screen == "Connexions":
        render_connections(brandwatch_service, brandwatch_setup_error)
        return

    if brandwatch_service is None and screen in {"Sélection et volume", "Acquisition"}:
        st.error(brandwatch_setup_error, icon=":material/error:")
        st.info("Le détail est sur l'écran « Connexions ».", icon=":material/info:")
        return

    if screen == "Sélection et volume":
        render_selection_and_volume(brandwatch_service)
    elif screen == "Acquisition":
        render_acquisition(brandwatch_service)
    elif screen == "Export":
        render_export()
    elif screen == "Bibliothèque de datasets":
        render_dataset_library(brandwatch_service, brandwatch_setup_error)


def render_connections(brandwatch_service: BrandwatchService | None, brandwatch_setup_error: str | None) -> None:
    if "db_check" not in st.session_state:
        _run_db_check()

    col1, col2 = st.columns(2)

    with col1, section(
        "Brandwatch",
        "Test manuel uniquement : chaque test consomme 1 appel du quota partagé de 30 requêtes / 10 minutes.",
    ):
        if brandwatch_setup_error:
            st.error(brandwatch_setup_error, icon=":material/error:")
        else:
            if st.button("Tester la connexion Brandwatch", type="primary", icon=":material/power:"):
                log_sink = _make_event_logger(st.empty())
                brandwatch_service.set_event_sink(log_sink)
                try:
                    _run_brandwatch_check(brandwatch_service)
                finally:
                    brandwatch_service.set_event_sink(None)
            _render_check_result(st.session_state.get("brandwatch_check"))

    with col2, section("Base de données", "Base Supabase où sont stockées les mentions et les datasets."):
        if st.button("Tester la connexion à la base", icon=":material/database:"):
            _run_db_check()
        _render_check_result(st.session_state.get("db_check"))

    if not brandwatch_setup_error:
        with section(
            "Découverte des filtres Brandwatch",
            "Pour confirmer la valeur exacte de pageType correspondant à Reddit "
            "(voir docs/05-brandwatch-api-notes.md). Chaque appel consomme aussi 1 requête du quota.",
        ):
            col3, col4 = st.columns(2)
            with col3:
                if st.button("Afficher les filtres (/filters)"):
                    try:
                        st.session_state["filters_result"] = brandwatch_service.list_filters()
                    except (BrandwatchAPIError, RuntimeError) as exc:
                        st.session_state["filters_result"] = None
                        st.error(str(exc), icon=":material/error:")
                if st.session_state.get("filters_result") is not None:
                    st.json(st.session_state["filters_result"])
            with col4:
                if st.button("Afficher les métriques (/metrics)"):
                    try:
                        st.session_state["metrics_result"] = brandwatch_service.list_metrics()
                    except (BrandwatchAPIError, RuntimeError) as exc:
                        st.session_state["metrics_result"] = None
                        st.error(str(exc), icon=":material/error:")
                if st.session_state.get("metrics_result") is not None:
                    st.json(st.session_state["metrics_result"])
                    st.caption(
                        "Cherchez la clé pageType ci-dessus : la valeur correspondant à "
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
        st.info("Pas encore testé.", icon=":material/info:")
        return
    message = f"{result['message']} (vérifié à {result['checked_at']})"
    if result["ok"]:
        st.success(message, icon=":material/check_circle:")
    else:
        st.error(message, icon=":material/error:")


def render_selection_and_volume(brandwatch_service: BrandwatchService) -> None:
    projects_repo = AcquisitionProjectsRepository()
    with section("Étude", "Regroupe les datasets dans la bibliothèque, par exemple « Observatoire Peau »."):
        acquisition_projects = projects_repo.list_all()
        study_labels = {p["id"]: p["name"] for p in acquisition_projects}
        NEW_STUDY = "— Nouvelle étude —"
        study_options = [NEW_STUDY] + list(study_labels)

        default_study_index = 0
        prefill_study_id = st.session_state.pop("prefill_acquisition_project_id", None)
        if prefill_study_id in study_labels:
            default_study_index = study_options.index(prefill_study_id)

        study_choice = st.selectbox(
            "Étude",
            options=study_options,
            index=default_study_index,
            format_func=lambda o: NEW_STUDY if o == NEW_STUDY else study_labels[o],
        )
        new_study_name = None
        if study_choice == NEW_STUDY:
            new_study_name = st.text_input("Nom de la nouvelle étude")

    with section("Project et Query", "Les Projects et Queries existants dans Brandwatch Consumer Research."):
        if st.button("Charger les Projects depuis Brandwatch", icon=":material/sync:"):
            try:
                st.session_state["projects"] = brandwatch_service.sync_projects()
            except BrandwatchAPIError as exc:
                st.error(f"Échec de l'appel Brandwatch : {exc}", icon=":material/error:")

        projects = st.session_state.get("projects", brandwatch_service.list_cached_projects())
        if not projects:
            vide("Aucun Project en cache. Cliquez sur « Charger les Projects depuis Brandwatch ».")
            return

        project_labels = {p["id"]: p["name"] for p in projects}
        project_ids = list(project_labels)
        default_project_index = 0
        prefill_project_id = st.session_state.pop("prefill_project_id", None)
        if prefill_project_id in project_labels:
            default_project_index = project_ids.index(prefill_project_id)

        project_id = st.selectbox(
            "Project", options=project_ids, index=default_project_index, format_func=lambda pid: project_labels[pid]
        )

        if st.button("Charger les Queries de ce Project", icon=":material/sync:"):
            try:
                st.session_state["queries"] = brandwatch_service.sync_queries(project_id)
            except BrandwatchAPIError as exc:
                st.error(f"Échec de l'appel Brandwatch : {exc}", icon=":material/error:")

        queries = st.session_state.get("queries", brandwatch_service.list_cached_queries(project_id))
        if not queries:
            vide("Aucune Query en cache pour ce Project. Cliquez sur « Charger les Queries de ce Project ».")
            return

        query_labels = {q["id"]: q["name"] for q in queries}
        query_id = st.selectbox("Query", options=list(query_labels), format_func=lambda qid: query_labels[qid])

    with section("Période et filtres", "Seules les mentions Reddit sont récupérées ; les autres filtres sont facultatifs."):
        col1, col2 = st.columns(2)
        start_date = col1.date_input("Date de début", format="DD/MM/YYYY")
        end_date = col2.date_input("Date de fin", format="DD/MM/YYYY")

        extra_filters = _render_filter_builder(brandwatch_service, project_id)

        if st.button("Valider la sélection", type="primary", icon=":material/check:"):
            if start_date > end_date:
                st.error("La date de début est après la date de fin. Corrigez la période.", icon=":material/error:")
                return
            acquisition_project_id = study_choice if study_choice != NEW_STUDY else None
            if acquisition_project_id is None:
                if not new_study_name:
                    st.error(
                        "Nouvelle étude sans nom. Donnez-lui un nom, ou choisissez une étude existante.",
                        icon=":material/error:",
                    )
                    return
                acquisition_project_id = projects_repo.create(new_study_name)

            config_id = AcquisitionConfigsRepository().create(
                project_id=project_id,
                query_id=query_id,
                start_date=start_date,
                end_date=end_date,
                acquisition_project_id=acquisition_project_id,
                filters=extra_filters,
            )
            st.session_state["config_id"] = config_id
            st.session_state["config_project_id"] = project_id
            st.session_state["config_query_id"] = query_id
            st.session_state["config_start_date"] = str(start_date)
            st.session_state["config_end_date"] = str(end_date)
            st.session_state["config_filters"] = extra_filters
            st.session_state["acquisition_project_id"] = acquisition_project_id
            st.session_state.pop("dataset_id", None)
            st.success(
                f"Sélection enregistrée (configuration n° {config_id}). Le contrôle de volume est juste en dessous.",
                icon=":material/check_circle:",
            )

    _render_volume_section(brandwatch_service)


def _label_for(item: dict[str, Any]) -> str:
    return item.get("displayName") or item.get("name") or str(item.get("id"))


def _flatten_tree(items: list[dict[str, Any]], depth: int = 0) -> list[tuple[int, str]]:
    """Aplatit un arbre catégorie/sous-catégories (ou tag/sous-tags) en liste
    plate, avec une indentation visuelle par niveau. Les enfants peuvent être
    sous différents noms selon la ressource Brandwatch — pas confirmé dans la
    doc publique, donc on regarde plusieurs clés plausibles plutôt que d'en
    figer une seule."""
    flat: list[tuple[int, str]] = []
    for item in items:
        flat.append((item["id"], ("    " * depth) + _label_for(item)))
        children = item.get("children") or item.get("subCategories") or item.get("categories") or []
        if children:
            flat.extend(_flatten_tree(children, depth + 1))
    return flat


def _render_filter_builder(brandwatch_service: BrandwatchService, project_id: int) -> list[dict[str, str]]:
    """Selection Builder v1.1+ (voir docs/01-fonctionnelle.md §3) : catégorie,
    tag, langue, domaine, auteur, sentiment — en plus du filtre Reddit déjà
    systématique. Retourne la liste à stocker dans acquisition_configs.filters.

    Catégorie et tag attendent un ID Brandwatch, pas un texte libre (confirmé
    le 13/10/2026 : un essai en texte libre sur `tag` a échoué avec une
    erreur 400 côté Brandwatch) — chargés depuis GET /rulecategories et
    GET /ruletags plutôt que saisis à la main.
    """
    filters: list[dict[str, str]] = []

    def _mode_choice(parameter: str, container=st):
        return container.segmented_control(
            "Mode", options=["include", "exclude"], key=f"filter_mode_{parameter}", default="include",
            required=True, format_func=lambda m: "Inclure" if m == "include" else "Exclure",
        )

    with st.expander("Filtres supplémentaires (facultatif)", icon=":material/filter_list:"):
        st.subheader("Catégorie", anchor=False)
        if st.button("Charger les catégories de ce Project", icon=":material/sync:"):
            try:
                st.session_state[f"categories_{project_id}"] = brandwatch_service.list_categories(project_id)
            except (BrandwatchAPIError, RuntimeError) as exc:
                st.error(f"Échec de l'appel Brandwatch : {exc}", icon=":material/error:")
        categories = st.session_state.get(f"categories_{project_id}", [])
        if categories:
            category_labels = dict(_flatten_tree(categories))
            selected_category = st.selectbox(
                "Catégorie", options=[None] + list(category_labels),
                format_func=lambda cid: "—" if cid is None else category_labels[cid], key="filter_select_category",
            )
            cols = st.columns(2)
            category_scope = cols[0].segmented_control(
                "Portée", options=["category", "parentCategory"], key="filter_scope_category",
                default="category", required=True,
                format_func=lambda s: "Cette catégorie uniquement" if s == "category" else "Avec ses sous-catégories",
            )
            category_mode = _mode_choice("category", cols[1])
            if selected_category is not None:
                filters.append(
                    {"parameter": category_scope, "mode": category_mode, "native_value": str(selected_category)}
                )
        else:
            st.caption("Cliquez sur « Charger les catégories » pour choisir dans une liste (pas de saisie libre).")

        st.divider()
        st.subheader("Tag", anchor=False)
        if st.button("Charger les tags de ce Project", icon=":material/sync:"):
            try:
                st.session_state[f"tags_{project_id}"] = brandwatch_service.list_tags(project_id)
            except (BrandwatchAPIError, RuntimeError) as exc:
                st.error(f"Échec de l'appel Brandwatch : {exc}", icon=":material/error:")
        tags = st.session_state.get(f"tags_{project_id}", [])
        if tags:
            tag_labels = dict(_flatten_tree(tags))
            cols = st.columns([3, 1])
            selected_tag = cols[0].selectbox(
                "Tag", options=[None] + list(tag_labels),
                format_func=lambda tid: "—" if tid is None else tag_labels[tid], key="filter_select_tag",
            )
            tag_mode = _mode_choice("tag", cols[1])
            if selected_tag is not None:
                filters.append({"parameter": "tag", "mode": tag_mode, "native_value": str(selected_tag)})
        else:
            st.caption("Cliquez sur « Charger les tags » pour choisir dans une liste (pas de saisie libre).")

        st.divider()

        def _include_exclude_field(label: str, parameter: str) -> None:
            cols = st.columns([3, 1])
            value = cols[0].text_input(label, key=f"filter_value_{parameter}")
            mode = _mode_choice(parameter, cols[1])
            if value.strip():
                filters.append({"parameter": parameter, "mode": mode, "native_value": value.strip()})

        _include_exclude_field("Langue (code ISO, ex. fr)", "language")
        _include_exclude_field("Domaine (ex. reddit.com)", "domain")
        _include_exclude_field("Auteur (pseudo Reddit)", "author")

        sentiment_values = st.multiselect(
            "Sentiment (inclusion uniquement)", options=["positive", "negative", "neutral"],
            format_func={"positive": "Positif", "negative": "Négatif", "neutral": "Neutre"}.get,
        )
        if sentiment_values:
            filters.append({"parameter": "sentiment", "mode": "include", "native_value": ",".join(sentiment_values)})

    return filters


def _render_volume_section(brandwatch_service: BrandwatchService) -> None:
    with section(
        "Contrôle de volume",
        "Compare le volume affiché dans Brandwatch et celui renvoyé par l'API. Contrôle informatif : "
        "un écart n'empêche pas de passer à l'acquisition.",
    ):
        encadre_cle(
            "Les 48 dernières heures sont exclues de la comparaison : le contenu Reddit récent met du temps "
            "à arriver dans Brandwatch, un écart sur cette période ne signale pas un problème.",
            titre="À retenir",
        )

        config_id = st.session_state.get("config_id")
        if not config_id:
            vide("Aucune sélection validée. Validez une sélection ci-dessus pour activer le contrôle de volume.")
            return

        volume_service = VolumeService()
        effective_end_date = volume_service.effective_comparison_end_date(st.session_state["config_end_date"])
        start_label = _date(st.session_state["config_start_date"])
        end_label = _date(effective_end_date)

        st.caption(f"Configuration n° {config_id}")
        if effective_end_date != st.session_state["config_end_date"]:
            st.caption(
                f"La comparaison porte sur la période du {start_label} au {end_label}, et non jusqu'à la date "
                f"de fin de la sélection ({_date(st.session_state['config_end_date'])})."
            )

        ui_volume = st.number_input(
            f"Volume affiché dans Brandwatch Consumer Research du {start_label} au {end_label}",
            min_value=0,
            step=1,
        )
        diagnose = st.checkbox(
            "Comparer aussi sans le filtre Reddit (diagnostic en cas d'écart)"
        )

        if st.button("Vérifier le volume API", type="primary", icon=":material/fact_check:"):
            log_sink = _make_event_logger(st.empty())
            brandwatch_service.set_event_sink(log_sink)
            try:
                api_volume = brandwatch_service.count_mentions(
                    st.session_state["config_project_id"],
                    st.session_state["config_query_id"],
                    st.session_state["config_start_date"],
                    effective_end_date,
                    extra_filters=st.session_state.get("config_filters", []),
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
                st.warning(str(exc), icon=":material/warning:")
                return
            except (BrandwatchAPIError, RuntimeError) as exc:
                st.error(str(exc), icon=":material/error:")
                return
            finally:
                brandwatch_service.set_event_sink(None)

            result = volume_service.compare(config_id, int(ui_volume), api_volume)
            st.markdown(f"**Résultat** {badge_statut(result['status'])}")
            col1, col2, col3 = st.columns(3)
            col1.metric("Volume Brandwatch (interface)", _nombre(int(ui_volume)), border=True)
            col2.metric("Volume API (Reddit uniquement)", _nombre(api_volume), border=True)
            col3.metric(
                "Écart", f"{_nombre(result['difference'])} ({result['difference_pct']:.2f} %)".replace(".", ","),
                border=True,
            )
            if unfiltered_volume is not None:
                st.caption(
                    f"Volume API sans filtre Reddit (diagnostic) : {_nombre(unfiltered_volume)} "
                    f"(écart avec le filtré : {_nombre(unfiltered_volume - api_volume)})."
                )
                if unfiltered_volume != api_volume:
                    st.info(
                        "Le filtre Reddit exclut des mentions de cette Query : possible marquage incomplet "
                        "depuis la bascule du flux Reddit du 28/08/2026 (voir docs/06-decisions-et-risques.md).",
                        icon=":material/info:",
                    )


def render_acquisition(brandwatch_service: BrandwatchService) -> None:
    config_id = st.session_state.get("config_id")
    if not config_id:
        vide("Aucune sélection validée. Complétez d'abord l'étape « Sélection et volume ».")
        return

    with section(
        "Lancer l'acquisition",
        "Récupère les mentions Reddit de la sélection et les enregistre en base au fil de l'eau. "
        "Relancer reprend la même sélection : les mentions déjà en base ne sont pas dupliquées.",
    ):
        start = st.button("Lancer ou reprendre l'acquisition", type="primary", icon=":material/play_arrow:")
        progress_placeholder = st.empty()
        result_placeholder = st.empty()

    if not start:
        return

    with section("Journal", "Détail des appels Brandwatch en direct."):
        log_sink = _make_event_logger(st.empty())

    dataset_id = st.session_state.get("dataset_id")
    if dataset_id is None:
        dataset_id = DatasetsRepository().create(
            start_date=st.session_state["config_start_date"],
            end_date=st.session_state["config_end_date"],
            acquisition_project_id=st.session_state.get("acquisition_project_id"),
            config_id=config_id,
        )
        st.session_state["dataset_id"] = dataset_id

    acquisition_service = AcquisitionService(brandwatch_service)
    brandwatch_service.set_event_sink(log_sink)
    try:
        for progress in acquisition_service.run(
            config_id=config_id,
            project_id=st.session_state["config_project_id"],
            query_id=st.session_state["config_query_id"],
            start_date=st.session_state["config_start_date"],
            end_date=st.session_state["config_end_date"],
            dataset_id=dataset_id,
            extra_filters=st.session_state.get("config_filters", []),
            on_event=log_sink,
        ):
            _render_counters(progress_placeholder, progress)
    except (BrandwatchAPIError, RuntimeError) as exc:
        result_placeholder.error(f"Acquisition interrompue : {exc}", icon=":material/error:")
        return
    finally:
        brandwatch_service.set_event_sink(None)

    DatasetsRepository().update_status(dataset_id, "COMPLETE")
    result_placeholder.success(
        f"Acquisition terminée. Le dataset n° {dataset_id} est prêt pour l'export.", icon=":material/check_circle:"
    )


def render_export() -> None:
    with section("Générer le CSV", "Le fichier est produit depuis la base de données : cet écran n'appelle jamais Brandwatch."):
        default_dataset_id = st.session_state.get("dataset_id", 0)
        dataset_id = st.number_input("Numéro du dataset à exporter", min_value=1, value=default_dataset_id or 1, step=1)
        requested_by = st.text_input("Demandé par (nom ou email, facultatif)")

        if st.button("Générer le CSV", type="primary", icon=":material/table_view:"):
            file_name, content = ExportService().generate_csv(int(dataset_id), requested_by=requested_by or None)
            st.download_button(
                "Télécharger le CSV", data=content, file_name=file_name, mime="text/csv", icon=":material/download:"
            )


def render_dataset_library(brandwatch_service: BrandwatchService | None, brandwatch_setup_error: str | None) -> None:
    datasets = DatasetsRepository().list_with_stats()
    if not datasets:
        vide("Aucun dataset pour l'instant. Lancez d'abord une acquisition.")
        return

    with section("Datasets acquis", "Vue d'ensemble, indépendante de la session en cours."):
        st.dataframe(
            pd.DataFrame(
                {
                    "Dataset": [row["dataset_id"] for row in datasets],
                    "Étude": [row["acquisition_project_name"] or "(sans étude)" for row in datasets],
                    "Query": [row["bw_query_name"] or "(configuration introuvable)" for row in datasets],
                    "Début": [row["start_date"] for row in datasets],
                    "Fin": [row["end_date"] for row in datasets],
                    "Mentions": [row["mention_count"] for row in datasets],
                    "Statut": [libelle_statut(row["status"]) for row in datasets],
                }
            ),
            hide_index=True,
            width="stretch",
            column_config={
                "Dataset": st.column_config.NumberColumn(format="%d"),
                "Début": st.column_config.DateColumn(format="DD/MM/YYYY"),
                "Fin": st.column_config.DateColumn(format="DD/MM/YYYY"),
                "Mentions": st.column_config.NumberColumn(format="localized"),
            },
        )

    with section("Actions sur un dataset", "Rafraîchir, étendre la période ou repartir de la même sélection."):
        for row in datasets:
            study_label = row["acquisition_project_name"] or "(sans étude)"
            query_label = row["bw_query_name"] or "(configuration introuvable)"
            with st.expander(f"Dataset n° {row['dataset_id']} · {study_label} · {query_label}"):
                st.markdown(badge_statut(row["status"]))
                st.caption(
                    f"Project Brandwatch : {row['bw_project_name'] or '—'} · "
                    f"du {_date(row['start_date'])} au {_date(row['end_date'])} · "
                    f"{_nombre(row['mention_count'])} mention(s) · créé le {_date(row['created_at'])}"
                )

                if row["config_id"] is None:
                    st.warning(
                        "Pas de configuration associée (dataset créé avant cette fonctionnalité) : "
                        "rafraîchir et étendre ne sont pas disponibles pour ce dataset.",
                        icon=":material/warning:",
                    )
                    continue

                if brandwatch_service is None:
                    st.error(brandwatch_setup_error, icon=":material/error:")
                    continue

                with st.container(horizontal=True):
                    refresh = st.button(
                        "Rafraîchir le dataset", key=f"refresh_{row['dataset_id']}", icon=":material/refresh:",
                        help="Relance la même sélection, pour récupérer les mentions arrivées depuis.",
                    )
                    with st.popover("Étendre la période", icon=":material/date_range:"):
                        st.caption("Ajoute une période plus récente au même dataset.")
                        new_end = st.date_input(
                            "Nouvelle date de fin",
                            value=row["end_date"],
                            min_value=row["end_date"],
                            format="DD/MM/YYYY",
                            key=f"extend_date_{row['dataset_id']}",
                        )
                        extend = st.button(
                            "Lancer l'extension", key=f"extend_btn_{row['dataset_id']}", type="primary"
                        )
                    duplicate = st.button(
                        "Dupliquer la sélection", key=f"duplicate_{row['dataset_id']}",
                        icon=":material/content_copy:",
                        help="Pré-remplit l'écran « Sélection et volume » pour démarrer un dataset similaire.",
                    )

                if refresh:
                    _refresh_dataset(brandwatch_service, row)
                elif extend:
                    _extend_dataset(brandwatch_service, row, new_end)
                elif duplicate:
                    config = AcquisitionConfigsRepository().get(row["config_id"])
                    if config:
                        st.session_state["prefill_project_id"] = config["project_id"]
                        st.session_state["prefill_acquisition_project_id"] = row["acquisition_project_id"]
                        st.info(
                            f"Project et étude sont pré-remplis sur l'écran « Sélection et volume ». "
                            f"Query à resélectionner : {row['bw_query_name']}.",
                            icon=":material/info:",
                        )


def _refresh_dataset(brandwatch_service: BrandwatchService, row: dict) -> None:
    config = AcquisitionConfigsRepository().get(row["config_id"])
    if not config:
        st.error("Configuration introuvable : ce dataset ne peut pas être relancé.", icon=":material/error:")
        return

    acquisition_service = AcquisitionService(brandwatch_service)
    progress_placeholder = st.empty()
    log_sink = _make_event_logger(st.empty())
    brandwatch_service.set_event_sink(log_sink)
    try:
        for progress in acquisition_service.run(
            config_id=config["id"],
            project_id=config["project_id"],
            query_id=config["query_id"],
            start_date=str(config["start_date"]),
            end_date=str(config["end_date"]),
            dataset_id=row["dataset_id"],
            extra_filters=config.get("filters") or [],
            on_event=log_sink,
        ):
            _render_counters(progress_placeholder, progress)
    except (BrandwatchAPIError, RuntimeError) as exc:
        st.error(f"Rafraîchissement interrompu : {exc}", icon=":material/error:")
        return
    finally:
        brandwatch_service.set_event_sink(None)

    DatasetsRepository().update_status(row["dataset_id"], "COMPLETE")
    st.success("Dataset rafraîchi.", icon=":material/check_circle:")


def _extend_dataset(brandwatch_service: BrandwatchService, row: dict, new_end_date: date) -> None:
    if new_end_date <= row["end_date"]:
        st.error("La nouvelle date de fin n'est pas après la date de fin actuelle. Choisissez une date plus récente.", icon=":material/error:")
        return
    config = AcquisitionConfigsRepository().get(row["config_id"])
    if not config:
        st.error("Configuration introuvable : ce dataset ne peut pas être relancé.", icon=":material/error:")
        return

    extension_start = row["end_date"] + timedelta(days=1)
    new_config_id = AcquisitionConfigsRepository().create(
        project_id=config["project_id"],
        query_id=config["query_id"],
        start_date=extension_start,
        end_date=new_end_date,
        acquisition_project_id=row["acquisition_project_id"],
        filters=config.get("filters") or [],
    )

    acquisition_service = AcquisitionService(brandwatch_service)
    progress_placeholder = st.empty()
    log_sink = _make_event_logger(st.empty())
    brandwatch_service.set_event_sink(log_sink)
    try:
        for progress in acquisition_service.run(
            config_id=new_config_id,
            project_id=config["project_id"],
            query_id=config["query_id"],
            start_date=str(extension_start),
            end_date=str(new_end_date),
            dataset_id=row["dataset_id"],
            extra_filters=config.get("filters") or [],
            on_event=log_sink,
        ):
            _render_counters(progress_placeholder, progress)
    except (BrandwatchAPIError, RuntimeError) as exc:
        st.error(f"Extension interrompue : {exc}", icon=":material/error:")
        return
    finally:
        brandwatch_service.set_event_sink(None)

    DatasetsRepository().update_end_date(row["dataset_id"], new_end_date)
    DatasetsRepository().update_status(row["dataset_id"], "COMPLETE")
    st.success(f"Dataset étendu jusqu'au {_date(new_end_date)}.", icon=":material/check_circle:")


if __name__ == "__main__":
    main()
