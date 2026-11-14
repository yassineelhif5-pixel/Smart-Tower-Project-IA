"""Hébergement Vercel : préfixe /api, hôtes autorisés, maintenance planifiée protégée, verrouillage Supabase."""
from django.db import connection
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from config.vercel import ApiPrefixMiddleware
from configuration import supabase_lockdown


class ApiPrefixTests(SimpleTestCase):
    def seen(self, path):
        captured = {}
        ApiPrefixMiddleware(lambda r: captured.setdefault("path", r.path_info))(RequestFactory().get(path))
        return captured["path"]

    def test_prefix_is_restored_only_when_missing(self):
        self.assertEqual(self.seen("/v1/health"), "/api/v1/health")
        self.assertEqual(self.seen("/api/v1/health"), "/api/v1/health")


class CronTests(TestCase):
    def test_disabled_without_secret(self):
        with self.settings(CRON_SECRET=""):
            self.assertEqual(APIClient().get("/api/v1/cron/maintenance").status_code, 404)

    @override_settings(CRON_SECRET="s3cret-de-test")
    def test_requires_the_shared_secret(self):
        self.assertEqual(APIClient().get("/api/v1/cron/maintenance").status_code, 401)
        bad = APIClient(HTTP_AUTHORIZATION="Bearer faux")
        self.assertEqual(bad.get("/api/v1/cron/maintenance").status_code, 401)
        ok = APIClient(HTTP_AUTHORIZATION="Bearer s3cret-de-test").get("/api/v1/cron/maintenance")
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.json()["done"])


class SupabaseLockdownTests(TestCase):
    """Sur une base qui a les rôles de l'API Supabase, les tables Django leur sont fermées."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.cursor() as c:
            for role in ("anon", "authenticated"):
                c.execute(f"do $$ begin create role {role} nologin; exception when duplicate_object then null; end $$")

    def test_tables_get_rls_and_lose_api_grants(self):
        with connection.cursor() as c:
            c.execute("grant select on table accounts_user to anon, authenticated")
        locked = supabase_lockdown.lock_down()
        self.assertGreater(locked, 40)
        with connection.cursor() as c:
            c.execute("select relrowsecurity from pg_class where relname = 'accounts_user'")
            self.assertTrue(c.fetchone()[0])
            c.execute("select has_table_privilege('anon', 'accounts_user', 'select'), "
                      "has_table_privilege('authenticated', 'django_session', 'select')")
            self.assertEqual(c.fetchone(), (False, False))
            c.execute("select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                      "where n.nspname = current_schema() and c.relkind = 'r' and c.relname = any(%s) "
                      "and not c.relrowsecurity", [supabase_lockdown.django_tables(connection)])
            self.assertEqual(c.fetchone()[0], 0)
        # L'application elle-même (propriétaire des tables) continue de lire et d'écrire.
        self.assertEqual(APIClient().get("/api/v1/health").json(), {"status": "ok"})
