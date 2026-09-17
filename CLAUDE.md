# CLAUDE.md — Contexte projet pour Claude Code

Lis ce fichier en entier avant d'écrire la moindre ligne de code. Il résume les décisions
déjà prises, pour éviter de reproposer des choix déjà tranchés.

## Mission

Construire une application interne **Streamlit + PostgreSQL (Supabase)** qui transforme
une sélection Reddit déjà validée dans Brandwatch Consumer Research en un dataset
persistant, réutilisable et exportable en CSV — sans jamais réinterroger l'API Brandwatch
plus que nécessaire (le compte a une limite de **30 requêtes API / 10 minutes**).

Documents de référence, à lire dans l'ordre :
1. `docs/01-spec-fonctionnelle.md`
2. `docs/02-architecture.md`
3. `docs/03-modele-donnees.md`
4. `docs/05-brandwatch-api-notes.md`

## Le cœur du MVP (v1) — ne pas dévier

L'utilisateur a explicitement confirmé que la version 1 doit permettre, dans cet ordre :
1. **Fetcher** les Projects / Queries Brandwatch existants (pas de création/édition de Query).
2. **Filtrer** : sur la source Reddit uniquement, et sur une plage de dates.
3. **Générer un export CSV** du résultat, depuis PostgreSQL (jamais directement depuis l'API).

Tout le reste (Selection Builder complet avec 10+ types de filtres, versioning des
configurations, Dataset Library, réutilisation inter-études) est un **renfort v1.1+** :
utile, documenté dans la spec, mais ne doit pas bloquer la livraison du cœur ci-dessus.
Voir `docs/01-spec-fonctionnelle.md` pour la séparation exacte.

## Contraintes non négociables

- **Séparation des couches** : l'UI Streamlit n'appelle jamais l'API Brandwatch
  directement. Toujours UI → Service → Connector → API.
- **Aucun credential en clair** dans le code ou dans PostgreSQL. Utiliser les secrets
  Streamlit / variables d'environnement.
- **Aucune transformation du contenu** des mentions (pas de nettoyage, correction,
  traduction, ré-écriture) — le `raw_payload` est conservé tel quel.
- **Déduplication obligatoire** sur `(source, source_native_id)` — contrainte `UNIQUE`.
- **Écriture en base par batch**, jamais en attendant la fin complète d'une acquisition
  (voir section pagination de `docs/02-architecture.md`).
- **Pas de NLP, pas de LLM, pas de dashboards analytiques** dans ce MVP.

## Pièges spécifiques à ce projet (lire avant de coder le contrôle de volume)

- Le volume Brandwatch UI et le volume API peuvent diverger **sans qu'il y ait de bug** :
  le contenu Reddit met du temps à arriver (jusqu'à ~30h dans de rares cas). **Exclure une
  fenêtre de sécurité des dernières 48h** de toute comparaison UI/API, sinon le contrôle
  de volume échouera à tort sur des périodes récentes.
- Le 28 août 2026, Brandwatch a basculé sur un nouveau flux Reddit. Les données Reddit
  antérieures ("legacy") disparaissent le 30 septembre 2026 et ne sont **pas** dans le
  périmètre technique de cette application (chantier séparé, déjà en cours par ailleurs).
- Certains champs Reddit ont disparu de Brandwatch (flair auteur/post, NSFW, score,
  abonnés du subreddit, sujets de subreddit). Ne jamais les modéliser comme colonnes
  structurées dans `reddit_mentions` — seul `raw_payload` doit les capter s'ils existent
  encore quelque part dans la réponse brute.
- Le paramètre exact de filtrage "Reddit uniquement" côté API Brandwatch n'a pas encore
  été vérifié dans la doc publique (voir `docs/05-brandwatch-api-notes.md`, "À confirmer").
  Ne pas deviner un nom de paramètre : le vérifier avec un appel réel ou dans la doc
  "Available Filters" avant d'implémenter le filtre.

## Stack confirmée

- Python, Streamlit
- PostgreSQL via **Supabase (plan Pro)** — voir `docs/03-modele-donnees.md`
- Client HTTP pour l'API Brandwatch (OAuth token, voir `docs/05-brandwatch-api-notes.md`)

## Design

Les guidelines de design de l'organisation seront déposées dans `design-guidelines/`.
Si ce dossier contient des fichiers au moment où tu lis ceci, applique leurs règles
(couleurs, typographie, composants) à l'interface Streamlit. S'il est vide, utilise une
interface Streamlit sobre par défaut et signale l'absence de charte plutôt que d'inventer
une identité visuelle.
