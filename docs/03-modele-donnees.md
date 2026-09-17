# Modèle de données — PostgreSQL (Supabase)

Toutes les tables sont créées dès le v1, même celles qui ne servent qu'aux renforts v1.1+
(voir `docs/01-spec-fonctionnelle.md`), pour éviter une migration de schéma plus tard.

## Tables

```
bw_projects            -- catalogue des Projects Brandwatch (cache local)
bw_queries             -- catalogue des Queries Brandwatch (cache local)
bw_filter_catalog       -- valeurs de filtres synchronisées (v1.1+)

acquisition_projects   -- une "étude" métier (ex. "Acné Reddit France 2026")
acquisition_configs    -- une configuration précise (project_id, query_id, dates, filtres)

volume_checks          -- historique des comparaisons UI vs API
acquisition_runs       -- historique des exécutions de récupération
coverage               -- ce qui est déjà couvert localement pour une config (v1.1+)

reddit_mentions        -- les mentions elles-mêmes
datasets               -- une sélection logique de mentions
dataset_mentions       -- table de liaison dataset <-> mention

exports                -- historique des exports CSV générés
```

## `reddit_mentions` — table centrale

```
id                  identifiant interne (clé primaire)
source              ex. "reddit" (permet d'accueillir d'autres sources plus tard)
source_native_id    identifiant de la mention côté Brandwatch/Reddit

published_at        date de publication
full_text           texte brut, non modifié
author               
url
language

raw_payload         JSON complet renvoyé par l'API, conservé tel quel

first_seen_at       première fois où cette mention a été récupérée
last_seen_at        dernière fois où elle a été revue par une acquisition
```

**Règle de déduplication** : contrainte `UNIQUE (source, source_native_id)`. Une mention
déjà acquise n'est jamais réinsérée — elle est mise à jour (`last_seen_at`) si revue.

**Règle de préservation** : aucun nettoyage, correction, traduction ou reformulation du
contenu au moment de l'acquisition. Toute analyse future se fait dans une couche dérivée
séparée, pas dans cette table.

**Ne pas modéliser en colonnes structurées** (uniquement dans `raw_payload` s'ils
existent encore) : flair auteur, flair post, spoiler, NSFW, score Reddit, abonnés du
subreddit, sujets du subreddit — ces champs disparaissent de Brandwatch au 28/08/2026
(voir `docs/06-decisions-et-risques.md`).

## `acquisition_configs`

```
project_id
query_id
start_date
end_date
timezone
filters          -- JSON structuré : [{parameter, mode, native_value, display_value}]
config_hash       -- hash déterministe des champs ci-dessus (v1.1+, identifie les doublons de config)
```

## `acquisition_runs`

```
run_id
config_id
status              CREATED | VALIDATING | READY | RUNNING | FAILED | COMPLETED | CANCELLED
expected_volume
requested_volume
received_volume
inserted_volume
existing_volume
started_at
completed_at
checkpoint          -- curseur API pour reprise après interruption
error_code
error_message
```

## `datasets` / `dataset_mentions`

```
datasets:
  dataset_id
  acquisition_project_id
  start_date
  end_date
  status              LOCAL | PARTIAL | STALE | COMPLETE

dataset_mentions:
  dataset_id
  mention_id
```

Une même mention peut appartenir à plusieurs datasets (relation many-to-many) — utile
si deux études se recoupent sur une même période/query.

## `volume_checks`

```
config_id
ui_volume           -- saisi manuellement par l'utilisateur
api_volume          -- calculé via l'appel Count
difference
difference_pct
status              MATCH | WARNING | MISMATCH
checked_at
excluded_recent_window  -- ex. "48h" — la fenêtre exclue de la comparaison (voir doc 01, section 5)
```

## Index et contraintes à prévoir dès le départ

- `UNIQUE (source, source_native_id)` sur `reddit_mentions`.
- Index sur `(query_id, published_at)` pour accélérer les vérifications de couverture.
- Index sur `dataset_mentions(dataset_id)` et `dataset_mentions(mention_id)`.
