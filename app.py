"""Point d'entrée Streamlit — MVP Reddit (voir docs/01-spec-fonctionnelle.md).

Règle de séparation des couches (docs/02-architecture.md) : cet écran
n'appelle jamais l'API Brandwatch ni PostgreSQL directement, uniquement les
Services (`services/`).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Callable

import streamlit as st

from auth import exiger_mot_de_passe
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

st.set_page_config(page_title="MVP Reddit — Brandwatch → PostgreSQL", layout="wide")
exiger_mot_de_passe()  # rien ne s'exécute après tant que le mot de passe n'est pas saisi


def _make_event_logger(placeholder) -> Callable[[str], None]:
    """Journal en direct (mode verbose) : accumule les événements et les affiche
    dans `placeholder` au fur et à mesure, même pendant une pause/retry qui
    bloque le reste du script (Streamlit est mono-thread par session)."""
    lines: list[str] = []

    def _log(message: str) -> None:
        lines.append(f"{datetime.now().strftime('%H:%M:%S')} — {message}")
        placeholder.code("\n".join(lines[-40:]))

    return _log

SCREENS = [
    "0. Connexions",
    "1. Sélection & Volume",
    "2. Acquisition",
    "3. Export",
    "4. Dataset Library",
]


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

    if brandwatch_service is None and screen in {"1. Sélection & Volume", "2. Acquisition"}:
        st.error(brandwatch_setup_error)
        st.info("Va à l'écran « 0. Connexions » pour le détail.")
        return

    if screen == "1. Sélection & Volume":
        render_selection_and_volume(brandwatch_service)
    elif screen == "2. Acquisition":
        render_acquisition(brandwatch_service)
    elif screen == "3. Export":
        render_export()
    elif screen == "4. Dataset Library":
        render_dataset_library(brandwatch_service, brandwatch_setup_error)


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


def render_selection_and_volume(brandwatch_service: BrandwatchService) -> None:
    st.header("1. Sélection & Volume — Project, Query, dates, puis contrôle")

    st.subheader("Étude")
    st.caption("Regroupe les datasets dans la Dataset Library (écran 4) — ex. « Observatoire Peau ».")
    projects_repo = AcquisitionProjectsRepository()
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

    st.divider()

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
    project_ids = list(project_labels)
    default_project_index = 0
    prefill_project_id = st.session_state.pop("prefill_project_id", None)
    if prefill_project_id in project_labels:
        default_project_index = project_ids.index(prefill_project_id)

    project_id = st.selectbox(
        "Project", options=project_ids, index=default_project_index, format_func=lambda pid: project_labels[pid]
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
        "Rappel : le contrôle de volume ci-dessous exclura automatiquement les "
        "dernières 48h — le contenu Reddit récent met du temps à arriver côté Brandwatch."
    )

    extra_filters = _render_filter_builder(brandwatch_service, project_id)

    if st.button("Valider la sélection"):
        if start_date > end_date:
            st.error("La date de début doit précéder la date de fin.")
            return
        acquisition_project_id = study_choice if study_choice != NEW_STUDY else None
        if acquisition_project_id is None:
            if not new_study_name:
                st.error("Donne un nom à la nouvelle étude, ou choisis-en une existante.")
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
        st.success(f"Sélection enregistrée (config #{config_id}). Le contrôle de volume est juste en dessous.")

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
    with st.expander("Filtres supplémentaires (optionnel)"):
        def _mode_radio(parameter: str):
            return st.radio(
                "Mode", options=["include", "exclude"], key=f"filter_mode_{parameter}",
                format_func=lambda m: "Inclure" if m == "include" else "Exclure", horizontal=True,
            )

        st.write("**Catégorie**")
        if st.button("Charger les catégories de ce Project"):
            try:
                st.session_state[f"categories_{project_id}"] = brandwatch_service.list_categories(project_id)
            except (BrandwatchAPIError, RuntimeError) as exc:
                st.error(f"Échec de l'appel Brandwatch : {exc}")
        categories = st.session_state.get(f"categories_{project_id}", [])
        if categories:
            category_labels = dict(_flatten_tree(categories))
            selected_category = st.selectbox(
                "Catégorie", options=[None] + list(category_labels),
                format_func=lambda cid: "—" if cid is None else category_labels[cid], key="filter_select_category",
            )
            cols = st.columns(2)
            category_scope = cols[0].radio(
                "Portée", options=["category", "parentCategory"], key="filter_scope_category",
                format_func=lambda s: "Cette catégorie uniquement" if s == "category" else "Cette catégorie + ses sous-catégories",
                horizontal=True,
            )
            category_mode = cols[1].radio(
                "Mode", options=["include", "exclude"], key="filter_mode_category",
                format_func=lambda m: "Inclure" if m == "include" else "Exclure", horizontal=True,
            )
            if selected_category is not None:
                filters.append(
                    {"parameter": category_scope, "mode": category_mode, "native_value": str(selected_category)}
                )
        else:
            st.caption("Clique sur « Charger les catégories » pour choisir dans une liste (pas de nom sans ça).")

        st.divider()
        st.write("**Tag**")
        if st.button("Charger les tags de ce Project"):
            try:
                st.session_state[f"tags_{project_id}"] = brandwatch_service.list_tags(project_id)
            except (BrandwatchAPIError, RuntimeError) as exc:
                st.error(f"Échec de l'appel Brandwatch : {exc}")
        tags = st.session_state.get(f"tags_{project_id}", [])
        if tags:
            tag_labels = dict(_flatten_tree(tags))
            cols = st.columns([3, 1])
            selected_tag = cols[0].selectbox(
                "Tag", options=[None] + list(tag_labels),
                format_func=lambda tid: "—" if tid is None else tag_labels[tid], key="filter_select_tag",
            )
            tag_mode = cols[1].radio(
                "Mode", options=["include", "exclude"], key="filter_mode_tag",
                format_func=lambda m: "Inclure" if m == "include" else "Exclure", horizontal=True,
            )
            if selected_tag is not None:
                filters.append({"parameter": "tag", "mode": tag_mode, "native_value": str(selected_tag)})
        else:
            st.caption("Clique sur « Charger les tags » pour choisir dans une liste (pas de texte libre).")

        st.divider()

        def _include_exclude_field(label: str, parameter: str) -> None:
            cols = st.columns([3, 1])
            value = cols[0].text_input(label, key=f"filter_value_{parameter}")
            mode = cols[1].radio(
                "Mode", options=["include", "exclude"], key=f"filter_mode_{parameter}",
                format_func=lambda m: "Inclure" if m == "include" else "Exclure", horizontal=True,
            )
            if value.strip():
                filters.append({"parameter": parameter, "mode": mode, "native_value": value.strip()})

        _include_exclude_field("Langue (code ISO, ex. fr)", "language")
        _include_exclude_field("Domaine (ex. reddit.com)", "domain")
        _include_exclude_field("Auteur (pseudo Reddit)", "author")

        sentiment_values = st.multiselect(
            "Sentiment (inclusion uniquement)", options=["positive", "negative", "neutral"]
        )
        if sentiment_values:
            filters.append({"parameter": "sentiment", "mode": "include", "native_value": ",".join(sentiment_values)})

    return filters


def _render_volume_section(brandwatch_service: BrandwatchService) -> None:
    st.divider()
    st.subheader("Volume — comparaison UI vs API")
    st.caption(
        "Ce contrôle est informatif : un MISMATCH n'empêche pas de passer à "
        "l'étape 2. Acquisition si tu juges que c'est pertinent quand même."
    )

    config_id = st.session_state.get("config_id")
    if not config_id:
        st.info("Valide une sélection ci-dessus pour activer le contrôle de volume.")
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
    st.header("2. Acquisition — récupération et stockage")

    config_id = st.session_state.get("config_id")
    if not config_id:
        st.info("Complète d'abord l'étape 1. Sélection & Volume.")
        return

    if st.button("Lancer / reprendre l'acquisition"):
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
                extra_filters=st.session_state.get("config_filters", []),
                on_event=log_sink,
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
    st.header("3. Export — CSV depuis PostgreSQL")
    st.caption("Cet écran ne déclenche jamais d'appel à l'API Brandwatch.")

    default_dataset_id = st.session_state.get("dataset_id", 0)
    dataset_id = st.number_input("ID du dataset à exporter", min_value=1, value=default_dataset_id or 1, step=1)
    requested_by = st.text_input("Demandé par (nom ou email, optionnel)")

    if st.button("Générer le CSV"):
        file_name, content = ExportService().generate_csv(int(dataset_id), requested_by=requested_by or None)
        st.download_button("Télécharger le CSV", data=content, file_name=file_name, mime="text/csv")


def render_dataset_library(brandwatch_service: BrandwatchService | None, brandwatch_setup_error: str | None) -> None:
    st.header("4. Dataset Library — tous les datasets acquis")
    st.caption(
        "Vue d'ensemble indépendante de la session en cours — regroupée par étude "
        "(voir l'écran 1. Sélection & Volume pour créer/choisir une étude)."
    )

    datasets = DatasetsRepository().list_with_stats()
    if not datasets:
        st.info("Aucun dataset pour l'instant. Complète d'abord une Acquisition (étape 2).")
        return

    for row in datasets:
        study_label = row["acquisition_project_name"] or "(sans étude)"
        query_label = row["bw_query_name"] or "(configuration introuvable)"
        with st.expander(
            f"Dataset #{row['dataset_id']} — {study_label} — {query_label} — "
            f"{row['start_date']} → {row['end_date']} — {row['mention_count']} mention(s) — {row['status']}"
        ):
            st.write(f"Project Brandwatch : {row['bw_project_name'] or '—'}")
            st.write(f"Créé le : {row['created_at']}")

            if row["config_id"] is None:
                st.warning(
                    "Pas de configuration associée (dataset créé avant cette fonctionnalité) : "
                    "Rafraîchir et Étendre ne sont pas disponibles pour ce dataset."
                )
                continue

            if brandwatch_service is None:
                st.error(brandwatch_setup_error)
                continue

            col1, col2, col3 = st.columns(3)

            with col1:
                st.caption("Relance la même sélection, pour récupérer les mentions arrivées depuis.")
                if st.button("Rafraîchir", key=f"refresh_{row['dataset_id']}"):
                    _refresh_dataset(brandwatch_service, row)

            with col2:
                with st.popover("Étendre"):
                    st.caption("Ajoute une période plus récente au même dataset.")
                    new_end = st.date_input(
                        "Nouvelle date de fin",
                        value=row["end_date"],
                        min_value=row["end_date"],
                        key=f"extend_date_{row['dataset_id']}",
                    )
                    if st.button("Lancer l'extension", key=f"extend_btn_{row['dataset_id']}"):
                        _extend_dataset(brandwatch_service, row, new_end)

            with col3:
                st.caption("Pré-remplit l'écran Sélection pour démarrer un nouveau dataset similaire.")
                if st.button("Dupliquer la sélection", key=f"duplicate_{row['dataset_id']}"):
                    config = AcquisitionConfigsRepository().get(row["config_id"])
                    if config:
                        st.session_state["prefill_project_id"] = config["project_id"]
                        st.session_state["prefill_acquisition_project_id"] = row["acquisition_project_id"]
                        st.info(
                            f"Va à l'écran « 1. Sélection & Volume » : Project et Étude sont pré-remplis. "
                            f"Query à resélectionner : {row['bw_query_name']}."
                        )


def _refresh_dataset(brandwatch_service: BrandwatchService, row: dict) -> None:
    config = AcquisitionConfigsRepository().get(row["config_id"])
    if not config:
        st.error("Configuration introuvable.")
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
            progress_placeholder.write(
                f"Reçues : {progress['received']} — nouvelles : {progress['inserted']} — "
                f"déjà en base : {progress['existing']}"
            )
    except (BrandwatchAPIError, RuntimeError) as exc:
        st.error(f"Rafraîchissement interrompu : {exc}")
        return
    finally:
        brandwatch_service.set_event_sink(None)

    DatasetsRepository().update_status(row["dataset_id"], "COMPLETE")
    st.success("Dataset rafraîchi.")


def _extend_dataset(brandwatch_service: BrandwatchService, row: dict, new_end_date: date) -> None:
    if new_end_date <= row["end_date"]:
        st.error("La nouvelle date de fin doit être postérieure à la date de fin actuelle.")
        return
    config = AcquisitionConfigsRepository().get(row["config_id"])
    if not config:
        st.error("Configuration introuvable.")
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
            progress_placeholder.write(
                f"Reçues : {progress['received']} — nouvelles : {progress['inserted']} — "
                f"déjà en base : {progress['existing']}"
            )
    except (BrandwatchAPIError, RuntimeError) as exc:
        st.error(f"Extension interrompue : {exc}")
        return
    finally:
        brandwatch_service.set_event_sink(None)

    DatasetsRepository().update_end_date(row["dataset_id"], new_end_date)
    DatasetsRepository().update_status(row["dataset_id"], "COMPLETE")
    st.success(f"Dataset étendu jusqu'au {new_end_date}.")


if __name__ == "__main__":
    main()
