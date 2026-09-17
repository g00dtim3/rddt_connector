# Décisions et risques

## Décisions actées

| Date | Décision |
|---|---|
| 17/09/2026 | Hébergement PostgreSQL : **Supabase, plan Pro** (8 Go inclus, pas de pause après inactivité). |
| 17/09/2026 | Volume estimé pour le périmètre visé : **~1 000 000 mentions**, **4 requêtes Brandwatch**, période 2024-2026. |
| 17/09/2026 | Périmètre du cœur du MVP (v1) : fetch Projects/Queries existants, filtre Reddit + dates, export CSV. Le reste de la spec détaillée passe en renfort v1.1+. |
| 17/09/2026 | Choix "dossier de pilotage" (specs + plan) plutôt qu'un squelette de code déjà écrit — la session Claude Code qui développera partira de ces documents. |

## Risque calendaire — données Reddit "legacy"

- Le 28 août 2026, Brandwatch a changé de fournisseur/flux Reddit.
- Les données Reddit "legacy" (issues de l'ancien flux, donc grosso modo tout ce qui
  précède fin août 2026) **ne seront plus disponibles après le 30 septembre 2026**.
- Le nouveau flux ne remonte que 13 mois en arrière depuis le 28/08/2026, soit environ
  à partir de juillet 2025.
- **Conséquence directe pour ce projet** : l'année 2024 et le premier semestre 2025 ne
  seront récupérables nulle part après le 30 septembre 2026, ni via l'app en construction
  (qui ne sera pas prête à temps), ni via l'API après cette date.
- Ce risque a été signalé le 17/09/2026. Un chantier de sauvegarde séparé (export minimal,
  hors périmètre de ce dossier de pilotage) a été proposé pour couvrir cette urgence — à
  traiter indépendamment du planning ci-dessus, quelle que soit la décision prise sur son
  exécution.
- **Point de vigilance pour la suite du MVP v1.1+** : une fois passé le 30 septembre, les
  4 requêtes ne pourront plus alimenter le dataset 2024-2026 que pour leur portion
  couverte par le nouveau flux (~juillet 2025 →). Le champ `published_at` en base
  permettra de savoir, a posteriori, quelle portion du dataset vient de quelle source.

## Risque : latence d'ingestion Reddit

- Une partie du contenu Reddit met jusqu'à ~30h à être traité par Brandwatch (89 % arrive
  en moins de 3h, mais une queue longue existe).
- Impact direct sur le contrôle de volume UI vs API (doc 01, §5) : comparer un volume sur
  les derniers jours donnera un écart artificiel non lié à un bug de configuration.
- Mitigation retenue : exclure une fenêtre de sécurité (48h) des comparaisons de volume.

## Risque : métadonnées Reddit supprimées côté Brandwatch

- Depuis le 28/08/2026, plusieurs champs disparaissent (flair auteur/post, spoiler, NSFW,
  score Reddit, abonnés/sujets de subreddit) et le Potential Audience/Engagement Score
  Reddit changent ou disparaissent.
- Sans impact sur le périmètre du MVP (pas d'analytique/scoring dans ce projet), mais à
  garder en tête si des colonnes structurées basées sur ces champs sont un jour ajoutées
  côté renfort v1.1+ : elles ne doivent pas être promises comme fiables pour du contenu
  ancien vs nouveau.

## Risque : accès API non confirmé

- Au 17/09/2026, l'accès API du compte Brandwatch existe mais son type exact n'est pas
  connu. Ce projet a seulement besoin de l'API Consumer Research standard (pas de
  l'add-on payant "Analysis API"). À vérifier en tentant une authentification OAuth réelle
  avant la phase 0 du plan de sprints.

## Ouvert / à trancher plus tard

- Politique de rétention des données une fois en base (durée de conservation de
  `reddit_mentions`) — nécessite un avis Legal/Data Governance, distinct de l'urgence du
  30/09.
- Multi-utilisateurs sur le même Supabase : si plusieurs personnes utilisent l'app en
  même temps, envisager une file d'attente sur les appels API pour ne pas cumuler les
  requêtes de plusieurs sessions au-delà du rate limit de 30/10min.
