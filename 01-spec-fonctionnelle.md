# Spécification fonctionnelle — MVP Reddit

## 1. Objectif

Transformer une sélection Reddit déjà qualifiée dans Brandwatch Consumer Research en un
dataset persistant dans PostgreSQL, réutilisable, et exportable en CSV — en consommant le
moins d'appels API possible.

## 2. Cœur du MVP (v1) — confirmé par l'utilisateur le 17/09/2026

```
Choisir un Project Brandwatch
        ↓
Choisir une Query Brandwatch (dans ce Project)
        ↓
Filtrer : source = Reddit uniquement
        ↓
Filtrer : plage de dates (début / fin)
        ↓
Récupérer les mentions correspondantes (API, avec pagination)
        ↓
Stocker en PostgreSQL (déduplication automatique)
        ↓
Générer un export CSV depuis PostgreSQL
```

### Écrans nécessaires pour le v1

- **Sélection** : liste des Projects → liste des Queries du Project choisi → dates de
  début/fin.
- **Volume** : afficher le nombre de mentions Reddit trouvées par l'API avant de lancer
  la récupération complète (évite de lancer un fetch de plusieurs centaines de milliers
  de mentions par erreur).
- **Acquisition** : barre de progression pendant la pagination (nombre traité / attendu).
- **Export** : bouton "Générer le CSV" — doit fonctionner **sans appel API** si les
  données demandées sont déjà en base (voir section 4).

### Critères d'acceptation v1

- [ ] Se connecter à l'API Brandwatch et lister les Projects.
- [ ] Lister les Queries d'un Project.
- [ ] Récupérer le nombre de mentions Reddit pour une Query + une plage de dates
      (avant tout fetch complet).
- [ ] Récupérer l'intégralité des mentions Reddit correspondantes, avec pagination
      automatique (l'utilisateur ne gère jamais de curseur à la main).
- [ ] Stocker les mentions en PostgreSQL sans doublon, même si la même récupération
      est relancée deux fois.
- [ ] Reprendre une acquisition interrompue sans tout refaire depuis le début.
- [ ] Exporter un CSV (UTF-8, en-têtes, échappement standard) depuis les données déjà
      en base, pour une Query + plage de dates données.
- [ ] Un second export de la même sélection ne déclenche aucun appel à l'API Brandwatch.

## 3. Renforts v1.1+ (documentés mais non bloquants pour la livraison du cœur)

Ces éléments viennent de la spec détaillée d'origine et restent la cible à moyen terme,
mais ne doivent pas retarder le cœur ci-dessus :

- **Selection Builder complet** : filtres supplémentaires (langue, sentiment, catégorie,
  tag, domaine, auteur, inclusion/exclusion). Le v1 ne filtre que sur Reddit + dates.
- **Configuration Hash + Versioning** : détecter qu'une configuration a déjà été utilisée,
  gérer plusieurs versions d'une même étude.
- **Logique de couverture avancée** : reconnaître qu'une période est *partiellement*
  déjà en base et ne récupérer que le manquant (le v1 peut se contenter de dédupliquer
  au niveau de la mention, sans optimisation de plage de dates).
- **Dataset Library** : vue d'ensemble de tous les datasets déjà acquis, avec actions
  Dupliquer / Étendre / Rafraîchir le volume.
- **Manifest d'export** technique complet (config_hash, IDs des runs, versions).
- **Écran Settings** dédié (test de connexion, refresh de token, statut).

> Recommandation : construire le v1 en gardant `docs/03-modele-donnees.md` tel quel
> (les tables des renforts existent dès le départ, même peu utilisées), pour ne pas avoir
> à migrer le schéma plus tard.

## 4. Règle de protection des quotas (s'applique dès le v1)

Avant tout appel de récupération de mentions :
1. Vérifier si des mentions pour cette Query existent déjà en base sur la plage de dates
   demandée.
2. Si oui : ne récupérer via l'API **que** ce qui manque réellement (ou, en v1 simplifié,
   accepter un déclenchement manuel explicite "Forcer le rafraîchissement" plutôt qu'une
   détection fine de plage manquante).
3. Un export ne doit jamais déclencher de nouvel appel API : il lit uniquement PostgreSQL.

## 5. Contrôle de volume (UI vs API)

But : vérifier que ce que l'API renvoie correspond à ce que l'utilisateur voit dans
Brandwatch, **avant** de lancer une récupération complète.

| | Volume |
|---|---:|
| Brandwatch UI (saisi par l'utilisateur) | ex. 82 410 |
| Brandwatch API (calculé) | ex. 82 387 |
| Écart | -23 (-0,03 %) |

- Seuil recommandé : ±1 %.
- **Important** : exclure les dernières 48h de la comparaison (latence d'ingestion
  Reddit côté Brandwatch, voir `docs/06-decisions-et-risques.md`), sinon des faux
  écarts apparaîtront systématiquement sur les périodes récentes.

## 6. Ce qui est explicitement hors périmètre (non-objectifs)

- Reviews, X (Twitter), toute autre source que Reddit.
- Analyse NLP, LLM, classification thématique.
- Dashboards analytiques.
- Création ou modification de Queries Brandwatch (le v1 ne fait que lire des Queries
  déjà créées et validées dans Brandwatch).
- Récupération des données Reddit "legacy" (avant le 28 août 2026) — chantier séparé,
  voir `docs/06-decisions-et-risques.md`.
