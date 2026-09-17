# Architecture — MVP Reddit

## 1. Principe général

```
Streamlit UI
     │  (jamais d'appel API direct depuis l'UI)
     ▼
Services métier
     ├── BrandwatchService   (Projects, Queries, Count, Mentions)
     ├── VolumeService       (comparaison UI/API, statut MATCH/WARNING/MISMATCH)
     ├── CoverageService     (ce qui est déjà en base vs ce qui manque)
     ├── AcquisitionService  (orchestration du fetch + pagination + retry)
     └── ExportService       (génération du CSV depuis PostgreSQL)
     │
     ▼
BrandwatchConnector (HTTP, auth, gestion du rate limit)
     │
     ▼
API Brandwatch

Services
     │
     ▼
Repositories (une classe par table, aucune requête SQL brute dans les Services)
     │
     ▼
PostgreSQL (Supabase)
```

## 2. Pourquoi cette séparation

- Si demain l'app doit s'intégrer au futur "Social & Reviews Data Hub", seul le
  Connector change (nouvelle source = nouveau Connector), pas les Services ni l'UI.
- Ça permet de tester `VolumeService` et `CoverageService` sans jamais appeler l'API
  réelle (mock du Connector).

## 3. Authentification Brandwatch

- OAuth via `POST https://api.brandwatch.com/oauth/token` (grant_type=api-password).
- Le token a une durée de vie longue par défaut (~1 an) — le stocker de façon sûre
  (secret manager / variables d'environnement), jamais en base.
- Voir `docs/05-brandwatch-api-notes.md` pour le détail des appels.

## 4. Pagination et rate limiting (BrandwatchConnector)

- Limite de débit : **30 requêtes / 10 minutes par compte**. Le Connector doit lire les
  en-têtes `x-rate-limit` / `x-rate-limit-used` de chaque réponse et ralentir de
  lui-même avant de recevoir une erreur 429, plutôt que de gérer l'erreur après coup.
- `pageSize` maximum : 5000 mentions par appel.
- Au-delà de 10 000 résultats, obligation de paginer via `cursor` (pas `page`/`pageSize`
  seuls) — voir tutoriel Brandwatch "Paging through historical Mentions".
- Le Connector expose une méthode qui retourne un itérateur de pages, pour que
  `AcquisitionService` puisse écrire en base après chaque page reçue (voir section 5).

## 5. Persistance par batch

Après **chaque page** reçue de l'API (pas à la fin de toute l'acquisition) :
1. Valider la page (champs attendus présents).
2. Upsert des mentions dans `reddit_mentions` (dédup sur `source, source_native_id`).
3. Enregistrer l'appartenance au dataset (`dataset_mentions`).
4. Sauvegarder le curseur/checkpoint courant dans `acquisition_runs`.
5. Continuer sur la page suivante.

Objectif : si le process est interrompu (crash, coupure réseau) après 40 000 mentions
sur 80 000, relancer l'acquisition ne doit refaire l'appel API que pour les 40 000
restantes, pas tout reprendre à zéro.

## 6. Retry

- Retry automatique (avec backoff) : rate limit (429), timeout, erreurs 5xx temporaires,
  problème réseau.
- Pas de retry automatique : authentification invalide, permission insuffisante,
  requête ou filtre invalide — ces erreurs doivent remonter clairement à l'utilisateur.

## 7. Stockage — Supabase

- Décision (17/09/2026) : **Supabase, plan Pro** (8 Go de base inclus, pas de mise en
  pause après inactivité — contrairement au plan gratuit).
- Connexion depuis Streamlit via chaîne de connexion PostgreSQL standard
  (psycopg2 / SQLAlchemy) — Supabase expose un Postgres classique, pas besoin de son
  SDK spécifique pour ce cas d'usage (pas d'auth utilisateurs finaux, pas de Realtime).
- Secrets de connexion (host, user, password) dans les secrets Streamlit / variables
  d'environnement — jamais commités dans le repo.

## 8. Export CSV

- Toujours généré **depuis PostgreSQL**, jamais depuis un flux API en direct.
- Conséquence directe : un export peut être régénéré à volonté sans consommer de
  quota Brandwatch.
- Format : UTF-8, en-tête, échappement CSV standard, contenu source inchangé (pas de
  nettoyage/normalisation).
