# Lot 2 — Rapatrier Reddit dans la base principale (schéma `reddit`)

**But :** les tables Reddit quittent leur projet Supabase séparé et rejoignent le projet principal
(celui d'api-explorer et de Compass), dans un schéma `reddit`. L'application continue de fonctionner à l'identique.
**Dépend de :** `SPRINT_L0_mot_de_passe.md` (même dépôt).
**Décision :** validée par l'utilisateur le 21/10/2026 (chantier « gardening », lot 2) : déménager plutôt que
synchroniser deux bases. À consigner dans `docs/06-decisions-et-risques.md` ; mettre à jour
`docs/02-architecture.md` §7 et `docs/03-modele-donnees.md` (le schéma n'est plus `public`).

## Ce qui est fourni (déjà écrit et testé le 21/10/2026)
| Fichier | Rôle |
|---|---|
| `scripts/copier_vers_base_principale.py` | Mesure, copie et vérification. Une seule transaction : en cas d'échec, rien n'est écrit. |
| `config.py` | Nouveau secret `[supabase] schema` (défaut `public`), validé (lettres minuscules, chiffres, `_`). |
| `db/connection.py` | Fixe le schéma de travail à l'ouverture de chaque connexion ; adresse construite avec `URL.create` (les caractères spéciaux du mot de passe ne cassent plus la connexion) ; refuse le port 6543 ; `test_connection()` vérifie que le schéma contient les tables. |

Tests faits sur deux bases PostgreSQL 16 locales simulant les deux projets (rôles `anon` / `authenticated`
compris, 20 000 mentions avec accents, `;`, tabulations, retours à la ligne, antislashs, emojis, JSON imbriqué,
valeurs vides, trous dans les identifiants) :
- copie complète et vérifiée (nombre de lignes + empreinte du contenu de chaque ligne, table par table) ;
- erreur provoquée en cours de copie → rien d'écrit dans la cible ; relance réussie ;
- seconde copie refusée (schéma déjà présent) ; une ligne modifiée après coup est détectée par `verifier` ;
- après copie, les compteurs d'identifiants reprennent au bon numéro (prochaine mention = max + 1) ;
- RLS activée sur les 12 tables, aucun droit pour `anon` / `authenticated` ;
- l'application lit bien `reddit` (requête réelle de `DatasetsRepository.list_with_stats()`), `public` avec
  l'ancien réglage ; schéma absent, port 6543 ou nom de schéma invalide → message clair.

**Non testé ici : Supabase lui-même** (pooler, débit réseau entre deux projets). C'est l'objet de la procédure
ci-dessous, qui commence par la commande `mesurer`, sans écriture.

## Partie A — Code (Claude Code)
1. Intégrer les trois fichiers fournis. Relire le diff de `config.py` et `db/connection.py` avec l'utilisateur.
2. `.streamlit/secrets.toml.example` : sous `[supabase]`, ajouter `schema = "public"` avec le commentaire
   « `reddit` une fois la base déménagée (lot 2) ».
3. `requirements-dev.txt` : ajouter `psycopg[binary]` (le script l'utilise ; l'application garde `psycopg2`).
4. Tests sans base : `config.py` refuse un schéma invalide ; `get_engine()` refuse le port 6543.
   Test avec base (sauté si `RDDT_TEST_DATABASE_URL` est absente, jamais sur une base réelle) :
   le script copie un petit jeu `fake_*` de `public` vers `reddit` dans deux bases de test et `verifier` répond « identiques ».
5. `README.md` : section « Base de données » (schéma `reddit`, secret `schema`, Session pooler obligatoire).

Ce code peut être fusionné et déployé **avant** le déménagement : avec `schema = "public"` (ou absent),
l'application continue d'utiliser l'ancienne base sans changement.

## Partie B — Procédure de déménagement (l'utilisateur, ≈ 1 h, application à l'arrêt)
Où lancer le script : de préférence dans **GitHub Codespaces** sur ce dépôt (le `.devcontainer` existe) :
les données passent par la machine qui lance le script, et le réseau d'un Codespace est bien plus rapide
qu'une connexion domestique pour plusieurs Go. Un ordinateur portable convient aussi, s'il ne se met pas en veille.

1. **Préparer les deux adresses** (Supabase → Connect → **Session pooler**, port 5432, mot de passe en clair à
   la place de `[YOUR-PASSWORD]`), puis dans le terminal :
   ```bash
   pip install "psycopg[binary]"
   export REDDIT_SOURCE_URL='postgresql://postgres.<ancien-projet>:<mot-de-passe>@…pooler.supabase.com:5432/postgres'
   export BASE_PRINCIPALE_URL='postgresql://postgres.<projet-principal>:<mot-de-passe>@…pooler.supabase.com:5432/postgres'
   ```
   (Guillemets simples : ils protègent les caractères spéciaux du mot de passe.)
2. **Mesurer** (aucune écriture) : `python scripts/copier_vers_base_principale.py mesurer`
   → tailles par table et taille de la base principale après copie. Vérifier qu'elle reste sous l'espace
   disque du plan (8 Go inclus dans Supabase Pro, selon `docs/02-architecture.md`). Sinon, s'arrêter et en parler.
3. **Arrêter les écritures** : aucune acquisition en cours ; ne plus utiliser l'application jusqu'à l'étape 6.
4. **Copier** : `python scripts/copier_vers_base_principale.py copier`
   Le script crée le schéma `reddit` avec `db/migrations/*.sql`, copie les 12 tables, remet les compteurs
   d'identifiants, protège le schéma, **vérifie tout**, puis seulement enregistre. Attendu à la fin :
   « ✓ Copie terminée et vérifiée ». En cas d'erreur, rien n'est écrit : corriger et relancer.
5. **Revérifier à froid** : `python scripts/copier_vers_base_principale.py verifier` → « ✓ Les deux bases sont identiques ».
6. **Basculer** : Streamlit Cloud → Settings → Secrets de l'application Reddit, section `[supabase]` :
   `host`, `user`, `password` du **projet principal** (Session pooler, port 5432) et `schema = "reddit"`.
   Enregistrer : l'application redémarre.
7. **Contrôler** : ouvrir l'application, vérifier la liste des datasets et leurs volumes ; exporter un petit CSV.
8. **Ne pas exposer `reddit`** : Supabase → Project Settings → Data API → *Exposed schemas* ne doit pas
   contenir `reddit` (par défaut, il n'y est pas). Le script a déjà retiré tout droit aux rôles publics.
9. **Ancien projet** : le laisser en place, sans l'utiliser, 2 à 4 semaines. Puis, après une dernière
   commande `verifier` (des écarts sont normaux si l'application a écrit depuis dans la nouvelle base),
   le mettre en pause ou le supprimer depuis le tableau de bord Supabase.

Retour arrière possible jusqu'à l'étape 9 : remettre les anciens secrets (ancien projet, `schema = "public"`).
Les acquisitions faites entre-temps dans la nouvelle base ne seraient alors pas dans l'ancienne.

## Définition de terminé
- [ ] Partie A fusionnée ; tests verts.
- [ ] `mesurer`, `copier` et `verifier` exécutés sur les vraies bases ; résultats notés dans `docs/06-decisions-et-risques.md`.
- [ ] L'application tourne sur la base principale avec `schema = "reddit"`.
- [ ] Date de suppression de l'ancien projet notée.
