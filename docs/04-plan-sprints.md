# Plan de sprints — MVP Reddit

Hypothèse : infrastructure Supabase déjà créée (voir `docs/06-decisions-et-risques.md`),
donc pas de temps dédié à "monter un PostgreSQL" — juste la modélisation et les migrations.

| Phase | Contenu | Durée estimée |
|---|---|---:|
| **0 — POC API** | Authentification, 1 Project + 1 Query réels, Count API, comparaison au volume Brandwatch UI sur une période *avec au moins 3 jours de recul* (voir doc 01, §5). Confirmer le nom exact du paramètre de filtrage Reddit (doc 05). | 2 j |
| **1 — Socle** | Structure Streamlit, connexion Supabase, migrations SQL (doc 03), config/secrets, logging, BrandwatchConnector avec gestion du rate limit. | 3 j |
| **2 — Sélection** | Écran Project → Query → dates. Cache local des Projects/Queries (`bw_projects`, `bw_queries`). | 2 j |
| **3 — Volume + Acquisition** | VolumeService (UI vs API), AcquisitionService (pagination, retry, checkpoints), écriture par batch dans `reddit_mentions`. | 4-5 j |
| **4 — Export** | ExportService (CSV depuis PostgreSQL), écran Export, vérification qu'un export ne déclenche aucun appel API. | 2 j |
| **5 — Tests** | Petit dataset, gros dataset (proche de 1M mentions), interruption/reprise, doublons, export répété. | 2-3 j |

**Total estimé : 15-19 jours** de développement pour le cœur du MVP (v1). Les renforts
v1.1+ (Selection Builder complet, Dataset Library, versioning) s'ajoutent après, sans
remettre en cause ce qui précède grâce au schéma de données déjà complet dès la phase 1.

## Point de contrôle GO/NO-GO (fin de phase 0)

> Une sélection reproduite via l'API doit retourner un volume cohérent (±1 %, hors
> fenêtre des 48 dernières heures) avec celui affiché dans Brandwatch Consumer Research.

Le développement des phases 2 à 5 ne démarre pas tant que ce contrôle n'est pas validé
sur les 4 requêtes réelles du projet.

## Ressources

- Développeur Python/Streamlit : ~15-19 jours (cœur du MVP).
- Product Owner : 2-3 jours (choix des Queries de test, validation des volumes, recette).
- Data Governance/Legal : à confirmer, notamment sur la durée de rétention de 2024-2026
  une fois stockée en base (indépendamment du chantier de sauvetage legacy).
