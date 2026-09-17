# MVP Reddit — Dossier de pilotage

Ce dossier n'est pas du code : c'est le **paquet de pilotage** à donner à une session
Claude Code (ou à un·e développeur·se) pour qu'elle construise l'application.

## Contenu

| Fichier | Rôle |
|---|---|
| `CLAUDE.md` | Instructions de contexte pour Claude Code — à lire en premier |
| `docs/01-spec-fonctionnelle.md` | Ce que l'app doit faire, en distinguant le cœur du MVP et les renforts |
| `docs/02-architecture.md` | Comment c'est construit (couches, techno, flux) |
| `docs/03-modele-donnees.md` | Les tables PostgreSQL (Supabase) et leurs règles |
| `docs/04-plan-sprints.md` | Découpage en phases et estimation |
| `docs/05-brandwatch-api-notes.md` | Ce qu'on a vérifié dans la doc développeur Brandwatch, et ce qui reste à confirmer |
| `docs/06-decisions-et-risques.md` | Journal des décisions prises et des risques identifiés |
| `design-guidelines/` | Dossier vide à ta charge : dépose-y ta charte / composants Streamlit partagés |

## Statut au 17/09/2026

- Décision prise : hébergement **Supabase (plan Pro)**.
- Volume estimé : **~1 000 000 mentions** sur **4 requêtes Brandwatch**, période 2024–2026.
- Un chantier **séparé et urgent** existe en parallèle : sauvegarder les données Reddit
  "legacy" avant leur suppression le 30 septembre 2026. Ce chantier n'est **pas** couvert
  par ce dossier de pilotage (voir `docs/06-decisions-et-risques.md`, section "Risque calendaire").

## Comment utiliser ce dossier

1. Dépose ce dossier à la racine du repo GitHub dédié.
2. Ajoute tes fichiers de charte graphique dans `design-guidelines/`.
3. Ouvre une session Claude Code sur ce repo et demande-lui de lire `CLAUDE.md` en premier.
4. Complète les informations manquantes listées dans `docs/05-brandwatch-api-notes.md`
   (identifiants API, nom exact de certains paramètres) avant de lancer le développement.
