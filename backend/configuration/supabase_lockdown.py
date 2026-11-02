"""Verrouillage des tables Django sur une base Supabase.

Supabase expose le schéma `public` par son API REST (PostgREST) aux rôles `anon` et `authenticated`, avec
des droits accordés par défaut aux nouvelles tables. Sans précaution, quiconque connaît la clé publique du
projet pourrait lire les tables de Django (comptes, empreintes de mots de passe, sessions…).

Après chaque `migrate`, si ces rôles existent (base Supabase), chaque table Django reçoit :
- la sécurité au niveau des lignes (RLS) activée, sans aucune politique : `anon` et `authenticated` ne voient rien ;
- le retrait de tous les droits de `anon` et `authenticated`.
Django se connecte avec le propriétaire des tables, que la RLS ne restreint pas : l'application n'est pas affectée.
Sur une base PostgreSQL ordinaire (sans ces rôles), rien n'est fait.
"""
import logging

from django.db import connections

logger = logging.getLogger("supabase")
API_ROLES = ("anon", "authenticated")


def django_tables(connection):
    tables = set(connection.introspection.django_table_names(only_existing=True, include_views=False))
    existing = set(connection.introspection.table_names())
    tables |= {"django_migrations", "django_session", "django_content_type", "pct_cache"} & existing
    return sorted(tables)


def api_roles(connection):
    with connection.cursor() as cursor:
        cursor.execute("select rolname from pg_roles where rolname = any(%s)", [list(API_ROLES)])
        return [r[0] for r in cursor.fetchall()]


def lock_down(using="default"):
    """Renvoie le nombre de tables verrouillées (0 hors Supabase)."""
    connection = connections[using]
    if connection.vendor != "postgresql":
        return 0
    roles = api_roles(connection)
    if not roles:
        return 0
    quoted_roles = ", ".join(connection.ops.quote_name(r) for r in roles)
    tables = django_tables(connection)
    with connection.cursor() as cursor:
        for table in tables:
            name = connection.ops.quote_name(table)
            cursor.execute(f"alter table {name} enable row level security")
            cursor.execute(f"revoke all on table {name} from {quoted_roles}")
        # Séquences des identifiants de ces tables uniquement (les autres objets du schéma ne sont pas touchés).
        cursor.execute(
            "select distinct s.relname from pg_class s join pg_depend d on d.objid = s.oid "
            "join pg_class t on t.oid = d.refobjid where s.relkind = 'S' and t.relname = any(%s)", [tables])
        for (sequence,) in cursor.fetchall():
            cursor.execute(f"revoke all on sequence {connection.ops.quote_name(sequence)} from {quoted_roles}")
    logger.info("Supabase : %s tables Django fermées à l'API publique.", len(tables))
    return len(tables)


def on_post_migrate(sender, using="default", **kwargs):
    # Une seule fois par commande migrate : le signal est émis pour chaque application.
    if getattr(sender, "label", None) != "configuration":
        return
    lock_down(using)
