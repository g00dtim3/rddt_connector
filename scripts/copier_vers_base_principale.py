"""
Copie la base Reddit (ancien projet Supabase, schéma `public`) vers la base principale
(schéma `reddit`), en une seule opération « tout ou rien ».

Trois commandes, à lancer depuis la racine du dépôt :

    python scripts/copier_vers_base_principale.py mesurer    # tailles, aucune écriture
    python scripts/copier_vers_base_principale.py copier     # crée le schéma, copie, vérifie, valide
    python scripts/copier_vers_base_principale.py verifier   # recompare les deux bases, aucune écriture

Les adresses des deux bases sont lues dans deux variables d'environnement, jamais en argument
(pour qu'aucun mot de passe ne reste dans l'historique du terminal) :

    REDDIT_SOURCE_URL     chaîne « Session pooler » de l'ANCIEN projet Reddit
    BASE_PRINCIPALE_URL   chaîne « Session pooler » du projet principal (api-explorer + Compass)

Principes :
- La source n'est jamais modifiée : elle est lue dans une transaction en lecture seule.
- Toute la copie se fait dans UNE transaction sur la base principale. Si une étape échoue,
  ou si la vérification trouve un écart, rien n'est enregistré : on peut relancer.
- La vérification compare, table par table, le nombre de lignes ET une empreinte du contenu
  de chaque ligne (calculée de la même façon des deux côtés, sur le même instantané de la source).
- Les tables sont créées avec les scripts du dépôt (db/migrations/*.sql), comme pour une
  installation neuve : le schéma copié est donc exactement celui que l'application attend.

Dépendance : pip install "psycopg[binary]"
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

try:
    import psycopg
    from psycopg import sql
except ImportError:  # message clair plutôt qu'une trace Python
    sys.exit('Bibliothèque manquante : lancez  pip install "psycopg[binary]"  puis recommencez.')

SCHEMA_CIBLE = "reddit"
MIGRATIONS = Path(__file__).resolve().parent.parent / "db" / "migrations"

# Ordre imposé par les clés étrangères : une table est copiée après celles qu'elle référence.
TABLES = [
    "bw_projects",
    "bw_queries",
    "bw_filter_catalog",
    "acquisition_projects",
    "acquisition_configs",
    "volume_checks",
    "acquisition_runs",
    "coverage",
    "reddit_mentions",
    "datasets",
    "dataset_mentions",
    "exports",
]


class Arret(Exception):
    """Arrêt volontaire, avec un message pour l'utilisateur (aucune trace Python)."""


# ─── Connexions ───────────────────────────────────────────────────────────────

def _url(nom_variable: str) -> str:
    valeur = os.environ.get(nom_variable, "").strip()
    if not valeur:
        raise Arret(f"Variable d'environnement manquante : {nom_variable} (voir le haut du script).")
    if ":6543/" in valeur:
        raise Arret(f"{nom_variable} pointe vers le port 6543 (Transaction pooler). "
                     "Utilisez la chaîne « Session pooler » (port 5432) : la copie a besoin d'une session continue.")
    return valeur


def _connecter(url: str, *, lecture_seule: bool) -> psycopg.Connection:
    conn = psycopg.connect(url, autocommit=False)
    if lecture_seule:
        conn.read_only = True
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ  # un seul instantané pour tout
    with conn.cursor() as cur:
        # Même représentation texte des dates des deux côtés (nécessaire pour comparer les empreintes).
        cur.execute("SET TimeZone = 'UTC'")
        cur.execute("SET DateStyle = 'ISO, YMD'")
        cur.execute("SET IntervalStyle = 'postgres'")
        cur.execute("SET extra_float_digits = 3")
        cur.execute("SET statement_timeout = 0")
    return conn


def _hote(url: str) -> str:
    """Hôte et identifiant de projet, pour l'affichage (jamais le mot de passe)."""
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    return f"{parts.username or '?'}@{parts.hostname or '?'}"


# ─── Lectures ─────────────────────────────────────────────────────────────────

def _tables_du_schema(conn, schema: str) -> list[str]:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = %s AND table_type = 'BASE TABLE' ORDER BY table_name",
        (schema,),
    ).fetchall()
    return [r[0] for r in rows]


def _colonnes(conn, schema: str, table: str) -> list[tuple[str, str]]:
    rows = conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
        (schema, table),
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def _empreinte(conn, schema: str, table: str) -> tuple[int, int]:
    """(nombre de lignes, somme des empreintes MD5 des lignes). Indépendant de l'ordre des lignes."""
    q = sql.SQL(
        "SELECT count(*), COALESCE(sum(('x' || substr(md5(t::text), 1, 15))::bit(60)::bigint), 0) "
        "FROM {}.{} AS t"
    ).format(sql.Identifier(schema), sql.Identifier(table))
    n, somme = conn.execute(q).fetchone()
    return int(n), int(somme)


def _taille(octets: int) -> str:
    for unite in ("o", "Ko", "Mo", "Go"):
        if octets < 1024 or unite == "Go":
            return f"{octets:.0f} {unite}" if unite == "o" else f"{octets:.1f} {unite}"
        octets /= 1024
    return str(octets)


def _verifier_tables_source(source, *, ignorer_inconnues: bool) -> None:
    presentes = set(_tables_du_schema(source, "public"))
    manquantes = [t for t in TABLES if t not in presentes]
    if manquantes:
        raise Arret("La source ne contient pas les tables attendues : " + ", ".join(manquantes)
                    + ". Vérifiez que REDDIT_SOURCE_URL désigne bien l'ancien projet Reddit.")
    inconnues = sorted(presentes - set(TABLES))
    if inconnues:
        message = ("Tables présentes dans la source mais inconnues de l'application (elles ne seront PAS copiées) : "
                   + ", ".join(inconnues))
        if not ignorer_inconnues:
            raise Arret(message + ". Si c'est voulu, relancez avec --ignorer-tables-inconnues.")
        print("⚠ " + message)


# ─── Commandes ────────────────────────────────────────────────────────────────

def mesurer() -> int:
    src_url, dst_url = _url("REDDIT_SOURCE_URL"), _url("BASE_PRINCIPALE_URL")
    with _connecter(src_url, lecture_seule=True) as source, _connecter(dst_url, lecture_seule=True) as cible:
        print(f"Source : {_hote(src_url)}")
        rows = source.execute(
            "SELECT relname, pg_total_relation_size(relid), n_live_tup FROM pg_stat_user_tables "
            "WHERE schemaname = 'public' ORDER BY pg_total_relation_size(relid) DESC"
        ).fetchall()
        print(f"\n{'Table':<24}{'Taille':>12}{'Lignes (environ)':>20}")
        total_tables = 0
        for nom, octets, lignes in rows:
            total_tables += octets
            print(f"{nom:<24}{_taille(octets):>12}{lignes:>20,}".replace(",", " "))
        taille_source = source.execute("SELECT pg_database_size(current_database())").fetchone()[0]
        taille_cible = cible.execute("SELECT pg_database_size(current_database())").fetchone()[0]
        print(f"\nTables Reddit à copier      : {_taille(total_tables)}")
        print(f"Base principale aujourd'hui : {_taille(taille_cible)}  ({_hote(dst_url)})")
        print(f"Base principale après copie : environ {_taille(taille_cible + total_tables)}")
        print(f"(Base source complète : {_taille(taille_source)}.)")
        print("\nRepère : comparez le total « après copie » à l'espace disque de votre projet principal "
              "(Supabase → Project Settings → Usage / Billing) avant de lancer la copie.")
        if _tables_du_schema(cible, SCHEMA_CIBLE):
            print(f"\n⚠ Le schéma « {SCHEMA_CIBLE} » contient déjà des tables dans la base principale : "
                  "la commande « copier » refusera de continuer.")
    return 0


def copier(*, ignorer_inconnues: bool) -> int:
    src_url, dst_url = _url("REDDIT_SOURCE_URL"), _url("BASE_PRINCIPALE_URL")
    if src_url == dst_url:
        raise Arret("REDDIT_SOURCE_URL et BASE_PRINCIPALE_URL sont identiques : rien à copier.")
    debut = time.monotonic()
    source = _connecter(src_url, lecture_seule=True)
    cible = _connecter(dst_url, lecture_seule=False)
    try:
        print(f"Source : {_hote(src_url)}  →  Cible : {_hote(dst_url)}, schéma « {SCHEMA_CIBLE} »\n")
        _verifier_tables_source(source, ignorer_inconnues=ignorer_inconnues)

        existe = cible.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
                               (SCHEMA_CIBLE,)).fetchone()
        if existe:
            raise Arret(f"Le schéma « {SCHEMA_CIBLE} » existe déjà dans la base principale. "
                        "La copie ne s'exécute que sur un schéma absent, pour ne jamais mélanger deux copies. "
                        "Si une copie a déjà réussi, utilisez la commande « verifier ».")

        # 1. Schéma et tables, avec les scripts du dépôt (dans la transaction).
        print("1/4 Création du schéma et des tables…")
        cible.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(SCHEMA_CIBLE)))
        cible.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(SCHEMA_CIBLE)))
        scripts = sorted(MIGRATIONS.glob("*.sql"))
        if not scripts:
            raise Arret(f"Aucun script de création trouvé dans {MIGRATIONS}.")
        for script in scripts:
            cible.execute(script.read_text(encoding="utf-8"))
            print(f"    {script.name}")
        cible.execute("SET LOCAL search_path TO DEFAULT")

        # 2. Les colonnes doivent être identiques (sinon une colonne ajoutée à la main serait perdue).
        for table in TABLES:
            col_src, col_dst = _colonnes(source, "public", table), _colonnes(cible, SCHEMA_CIBLE, table)
            if col_src != col_dst:
                raise Arret(f"Structure différente pour la table {table} :\n  source : {col_src}\n  cible  : {col_dst}\n"
                            "Ajoutez la modification manquante dans db/migrations/ puis relancez.")

        # 3. Copie, table par table, en flux (rien n'est chargé en mémoire).
        print("2/4 Copie des données…")
        for table in TABLES:
            noms = [c for c, _ in _colonnes(source, "public", table)]
            liste = sql.SQL(", ").join(sql.Identifier(c) for c in noms)
            lire = sql.SQL("COPY (SELECT {} FROM public.{}) TO STDOUT").format(liste, sql.Identifier(table))
            ecrire = sql.SQL("COPY {}.{} ({}) FROM STDIN").format(
                sql.Identifier(SCHEMA_CIBLE), sql.Identifier(table), liste)
            t0, volume = time.monotonic(), 0
            with source.cursor().copy(lire) as sortie, cible.cursor().copy(ecrire) as entree:
                for bloc in sortie:
                    entree.write(bloc)
                    volume += len(bloc)
            n = cible.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(
                sql.Identifier(SCHEMA_CIBLE), sql.Identifier(table))).fetchone()[0]
            print(f"    {table:<22}{n:>12,} lignes  {_taille(volume):>10}  {time.monotonic() - t0:6.1f} s"
                  .replace(",", " "))

        # 4. Compteurs d'identifiants : la prochaine ligne créée prendra le numéro suivant le plus grand copié.
        print("3/4 Mise à jour des compteurs d'identifiants et des droits…")
        for table in TABLES:
            if "id" not in [c for c, _ in _colonnes(cible, SCHEMA_CIBLE, table)]:
                continue  # table de liaison sans identifiant propre (ex. dataset_mentions)
            seq = cible.execute("SELECT pg_get_serial_sequence(%s, 'id')",
                                (f"{SCHEMA_CIBLE}.{table}",)).fetchone()[0]
            if seq:
                cible.execute(
                    sql.SQL("SELECT setval(%s, COALESCE((SELECT max(id) FROM {}.{}), 1), "
                            "(SELECT max(id) FROM {}.{}) IS NOT NULL)").format(
                        sql.Identifier(SCHEMA_CIBLE), sql.Identifier(table),
                        sql.Identifier(SCHEMA_CIBLE), sql.Identifier(table)),
                    (seq,))
        # Comme bulk_export : sécurité au niveau des lignes sans politique, et aucun droit pour les rôles publics.
        for table in TABLES:
            cible.execute(sql.SQL("ALTER TABLE {}.{} ENABLE ROW LEVEL SECURITY").format(
                sql.Identifier(SCHEMA_CIBLE), sql.Identifier(table)))
        for role in ("anon", "authenticated"):
            if cible.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone():
                for ordre in ("REVOKE ALL ON SCHEMA {} FROM {}",
                              "REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM {}",
                              "REVOKE ALL ON ALL SEQUENCES IN SCHEMA {} FROM {}"):
                    cible.execute(sql.SQL(ordre).format(sql.Identifier(SCHEMA_CIBLE), sql.Identifier(role)))

        # 5. Vérification AVANT d'enregistrer : même instantané de la source que celui copié.
        print("4/4 Vérification (nombre de lignes et contenu de chaque ligne)…")
        ecarts = _comparer(source, cible)
        if ecarts:
            raise Arret("Écart détecté, rien n'a été enregistré :\n  - " + "\n  - ".join(ecarts))

        cible.commit()
        print(f"\n✓ Copie terminée et vérifiée en {time.monotonic() - debut:.0f} s. "
              f"Le schéma « {SCHEMA_CIBLE} » est enregistré dans la base principale.")
        print("  Étape suivante : basculer l'application (voir SPRINT_L2, partie « Bascule »).")
        return 0
    except BaseException:
        cible.rollback()
        raise
    finally:
        source.rollback()
        source.close()
        cible.close()


def _comparer(source, cible) -> list[str]:
    ecarts = []
    for table in TABLES:
        n_src, h_src = _empreinte(source, "public", table)
        n_dst, h_dst = _empreinte(cible, SCHEMA_CIBLE, table)
        etat = "✓" if (n_src, h_src) == (n_dst, h_dst) else "✗"
        print(f"    {etat} {table:<22}{n_src:>12,} → {n_dst:>12,}".replace(",", " "))
        if n_src != n_dst:
            ecarts.append(f"{table} : {n_src} lignes dans la source, {n_dst} dans la cible")
        elif h_src != h_dst:
            ecarts.append(f"{table} : même nombre de lignes mais contenu différent")
    return ecarts


def verifier() -> int:
    src_url, dst_url = _url("REDDIT_SOURCE_URL"), _url("BASE_PRINCIPALE_URL")
    with _connecter(src_url, lecture_seule=True) as source, _connecter(dst_url, lecture_seule=True) as cible:
        if not _tables_du_schema(cible, SCHEMA_CIBLE):
            raise Arret(f"Le schéma « {SCHEMA_CIBLE} » est absent ou vide dans la base principale.")
        print("Comparaison source → cible (nombre de lignes et contenu) :")
        ecarts = _comparer(source, cible)
    if ecarts:
        print("\n✗ Écarts :\n  - " + "\n  - ".join(ecarts))
        print("  Normal si l'application a écrit dans l'une des deux bases depuis la copie.")
        return 1
    print("\n✓ Les deux bases sont identiques.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Copie de la base Reddit vers la base principale (schéma reddit).")
    ap.add_argument("commande", choices=["mesurer", "copier", "verifier"])
    ap.add_argument("--ignorer-tables-inconnues", action="store_true",
                    help="Copier quand même si la source contient des tables inconnues (elles ne sont pas copiées).")
    a = ap.parse_args()
    try:
        if a.commande == "mesurer":
            return mesurer()
        if a.commande == "copier":
            return copier(ignorer_inconnues=a.ignorer_tables_inconnues)
        return verifier()
    except Arret as exc:
        print(f"\n✗ {exc}", file=sys.stderr)
        return 2
    except psycopg.Error as exc:
        # Le message de PostgreSQL ne contient pas le mot de passe ; on n'affiche pas la chaîne de connexion.
        print(f"\n✗ Erreur de la base : {exc.__class__.__name__} : {str(exc).strip()}", file=sys.stderr)
        print("  Rien n'a été enregistré dans la base principale.", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
