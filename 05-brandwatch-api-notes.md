# Notes techniques — API Brandwatch (Consumer Research)

Vérifié le 17/09/2026 sur la documentation publique developers.brandwatch.com.
À confirmer / compléter avant développement : voir section "À confirmer" en bas.

## Authentification

```
POST https://api.brandwatch.com/oauth/token
  ?username=[email]
  &password=[password]      (en corps de requête, urlencodé)
  &grant_type=api-password
  &client_id=brandwatch-api-client
```

Réponse :
```json
{
  "access_token": "....",
  "token_type": "bearer",
  "expires_in": 31535999,
  "scope": "read trust write"
}
```

- `expires_in` : ~1 an par défaut pour un utilisateur API.
- Seuls les comptes avec permission "Regular" ou "Admin" peuvent accéder à l'API.
- Le token se transmet ensuite via l'en-tête `Authorization: Bearer <token>`.

## Rate limiting

- **30 requêtes API / 10 minutes**, par client (compte), pas par utilisateur.
- Chaque réponse contient les en-têtes `x-rate-limit` (ex. `30/10m`) et
  `x-rate-limit-used` — à utiliser pour ralentir proactivement plutôt que d'attendre
  une erreur 429.
- Dépassement → `HTTP 429 Too Many Requests`.

## Récupération des mentions

```
GET https://api.brandwatch.com/projects/{projectId}/data/mentions
  ?queryId={queryId}
  &startDate=YYYY-MM-DD
  &endDate=YYYY-MM-DD
  &pageSize=...
  &orderBy=date
  &orderDirection=asc
```

- `pageSize` : entier de 1 à 5000 (max absolu 5000 par appel).
- Avec `page` + `pageSize` seuls : **limite dure de 10 000 mentions récupérables**.
- Au-delà : utiliser le `cursor` retourné dans la réponse (`nextCursor`) — voir le
  tutoriel officiel "Paging through historical Mentions".
- Exemple de réponse (mentions omises) :
```json
{
  "results": [...],
  "resultsPage": 0,
  "resultsPageSize": 100,
  "resultsTotal": 234,
  "nextCursor": "AQ=AA=AWbKauTY=Mlz58Vk=dypaHA",
  "startDate": "...",
  "endDate": "..."
}
```

Pour ~1 000 000 de mentions à récupérer sur 4 requêtes, avec `pageSize=5000`, ça
représente environ 200 appels — largement dans le budget de rate limit si étalé dans le
temps (pas de contrainte de vitesse dans ce projet), mais à séquencer proprement pour ne
pas saturer le compte si d'autres personnes l'utilisent en même temps.

## Comptage (Count)

La doc publique référence un endpoint de type "Total Mentions" dans la section
"Data Retrieval" de l'API Mentions — le détail exact (paramètres, chemin précis) n'a pas
encore été extrait dans cette session. **À vérifier avant la phase 0** (voir ci-dessous).

## Projects / Queries

- `GET /projects/summary` (ou équivalent listé sous "Retrieving Projects") pour lister
  les Projects accessibles.
- Section "Retrieving Queries" pour lister les Queries d'un Project.

## Filtres disponibles

La doc référence une section "Available Filters" (langues, localisation, objets/logos,
exclusions). Le nom exact du paramètre permettant de restreindre à la source Reddit
uniquement n'a pas encore été confirmé.

## Analysis API — hors périmètre

Il existe une "Analysis API" séparée, facturée à la requête, pour des analyses ad hoc
sans Query sauvegardée. **Ce projet n'en a pas besoin** : tout se fait avec l'API
Consumer Research standard (Projects, Queries, Mentions), déjà couverte par l'accès API
existant du compte.

## À confirmer avant la phase 0 (POC)

- [ ] Nom exact du endpoint et des paramètres pour le **Count** (nombre de mentions sans
      les récupérer entièrement).
- [ ] Nom exact du paramètre pour filtrer sur **Reddit uniquement** (probablement un
      filtre de type "page type" / "content type" — à vérifier dans "Available Filters").
- [ ] Confirmer quel type d'accès API est activé sur le compte (cf. `docs/06-decisions-
      et-risques.md`, l'utilisateur ne le savait pas au 17/09/2026) — un simple test
      d'obtention de token suffit à le vérifier.
- [ ] Vérifier si les 4 requêtes concernées sont déjà bien rattachées au nouveau flux
      Reddit (post-28/08/2026) ou encore sur l'ancien projet — impacte directement la
      disponibilité des données via l'API à partir du 30/09/2026.
