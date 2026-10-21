# Lot 0 — Mot de passe sur l'application Reddit

**But :** l'application ne s'affiche, n'appelle Brandwatch et ne touche à la base qu'après saisie du mot de passe.
**Pourquoi maintenant :** l'application n'a aucune protection. Si son URL Streamlit est publique, n'importe qui peut
lancer des acquisitions (qui consomment le quota de 30 requêtes / 10 min) ou exporter les mentions.
**Décision :** validée par l'utilisateur le 21/10/2026 (chantier « gardening », lot 0).

## Ce qui est fourni
- `auth.py` (racine du dépôt) : module **déjà écrit et testé**, repris d'`api-explorer/auth.py`
  (5 essais puis blocage 5 min, mot de passe d'au moins 16 caractères, `hmac.compare_digest`,
  saisie effacée de la session). Ne pas le réécrire.
- `tests/test_auth.py` : 6 tests (page factice, sans base ni API).

## Tâches
1. `app.py` : appeler `exiger_mot_de_passe()` juste après `st.set_page_config(...)` (ligne ~29),
   avant tout appel aux Services.
   ```python
   from auth import exiger_mot_de_passe
   st.set_page_config(page_title="MVP Reddit — Brandwatch → PostgreSQL", layout="wide")
   exiger_mot_de_passe()      # rien ne s'exécute après tant que le mot de passe n'est pas saisi
   ```
   Les imports en haut de `app.py` ne se connectent à rien (vérifié : `get_engine()` n'ouvre la connexion qu'au
   premier appel). Ils peuvent rester où ils sont.
2. Le dépôt n'a pas encore de tests : créer `requirements-dev.txt` (`-r requirements.txt` + `pytest`) et
   `tests/__init__.py`.
3. `.streamlit/secrets.toml.example` : ajouter en haut `APP_PASSWORD = ""` avec un commentaire
   (« au moins 16 caractères, jamais dans Git »).
4. `README.md` : une section « Accès » de trois lignes.

## Hors périmètre
- Le regroupement de la base (lot 2, `SPRINT_L2_base_principale.md`) : sprint séparé, à faire après celui-ci.

## Tests
- `pytest tests/test_auth.py` : 6 tests verts.

## À faire par l'utilisateur (après fusion)
- Streamlit Cloud → Settings → Secrets, **en haut du fichier**, avant `[brandwatch]` :
  `APP_PASSWORD = "…"` (au moins 16 caractères, aléatoire).
- Ouvrir l'application dans une fenêtre privée : seul l'écran « Accès protégé » doit apparaître.

## Définition de terminé
- [ ] `app.py` appelle `exiger_mot_de_passe()` juste après `st.set_page_config`.
- [ ] `pytest` vert.
- [ ] `docs/06-decisions-et-risques.md` : décision du 21/10/2026 ajoutée. Un commit sur une branche, une pull request.
