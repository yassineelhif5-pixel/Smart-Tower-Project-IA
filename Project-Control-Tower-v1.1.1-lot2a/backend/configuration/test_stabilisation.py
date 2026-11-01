"""Lot 2a (stabilisation) : version de l'API, documentation OpenAPI, cache partagé, purge des journaux,
rotation de la clé de chiffrement. Chaque test protège un comportement existant ou nouveau."""
from datetime import timedelta
from io import StringIO

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.db import connection
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from configuration.models import ApiRequestLog, ApiToken, AuditEvent, ServiceSecret
from configuration.tests import AdminBase


class ApiVersionTests(AdminBase):
    def test_v1_and_legacy_paths_serve_the_same_data(self):
        self.client.force_authenticate(self.consultant)
        v1, legacy = self.client.get("/api/v1/projects"), self.client.get("/api/projects")
        self.assertEqual(v1.status_code, 200)
        self.assertEqual(v1.json(), legacy.json())

    def test_v1_keeps_the_same_protections(self):
        self.assertEqual(APIClient().get("/api/v1/projects").status_code, 401)
        self.assertEqual(APIClient().get("/api/v1/health").json(), {"status": "ok"})
        self.client.force_authenticate(self.consultant)
        self.assertEqual(self.client.get("/api/v1/admin/users").status_code, 403)

    def test_endpoint_list_shows_only_v1_once(self):
        paths = [e["path"] for e in self.client.get("/api/v1/admin/api/endpoints").json()]
        self.assertTrue(paths)
        self.assertTrue(all(p.startswith("/api/v1/") for p in paths))
        self.assertEqual(len(paths), len(set(paths)))
        self.assertIn("/api/v1/projects", paths)


class OpenApiTests(AdminBase):
    def test_admin_gets_the_schema_of_v1(self):
        r = self.client.get("/api/v1/schema", HTTP_ACCEPT="application/vnd.oai.openapi+json")
        self.assertEqual(r.status_code, 200)
        schema = r.json()
        self.assertIn("openapi", schema)
        self.assertIn("/api/v1/projects", schema["paths"])
        self.assertFalse(any(not p.startswith("/api/v1/") for p in schema["paths"]))

    def test_admin_gets_the_swagger_page(self):
        r = self.client.get("/api/v1/docs")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"swagger", r.content.lower())

    def test_schema_is_refused_to_non_admins_and_tokens(self):
        self.client.force_authenticate(self.consultant)
        self.assertEqual(self.client.get("/api/v1/schema").status_code, 403)
        self.assertEqual(APIClient().get("/api/v1/schema").status_code, 403)
        _, raw = ApiToken.issue(name="t", user=self.admin, read_only=True)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        self.assertEqual(client.get("/api/v1/schema").status_code, 403)


class SharedCacheTests(AdminBase):
    def test_login_counter_is_stored_in_postgres(self):
        self.assertEqual(settings.CACHES["default"]["BACKEND"], "django.core.cache.backends.db.DatabaseCache")
        cache.clear()
        client = APIClient()
        client.post("/api/v1/auth/login", {"username": "admin", "password": "faux"}, format="json")
        with connection.cursor() as cur:
            cur.execute("select count(*) from pct_cache")
            self.assertGreater(cur.fetchone()[0], 0)
        cache.clear()


class PurgeLogsTests(AdminBase):
    def make_old(self, model, days, **fields):
        row = model.objects.create(**fields)
        model.objects.filter(pk=row.pk).update(at=timezone.now() - timedelta(days=days))
        return row

    @override_settings(API_LOG_RETENTION_DAYS=90, AUDIT_LOG_RETENTION_DAYS=365)
    def test_purge_removes_only_expired_rows_and_is_audited(self):
        old_api = self.make_old(ApiRequestLog, 91, method="GET", path="/api/v1/projects", status=200, duration_ms=1)
        new_api = self.make_old(ApiRequestLog, 89, method="GET", path="/api/v1/projects", status=200, duration_ms=1)
        old_audit = self.make_old(AuditEvent, 366, entity="x", event="ancien", trace="1")
        new_audit = self.make_old(AuditEvent, 300, entity="x", event="récent", trace="2")
        call_command("purge_logs", stdout=StringIO())
        self.assertFalse(ApiRequestLog.objects.filter(pk=old_api.pk).exists())
        self.assertTrue(ApiRequestLog.objects.filter(pk=new_api.pk).exists())
        self.assertFalse(AuditEvent.objects.filter(pk=old_audit.pk).exists())
        self.assertTrue(AuditEvent.objects.filter(pk=new_audit.pk).exists())
        self.assertTrue(AuditEvent.objects.filter(event="Purge planifiée").exists())

    def test_dry_run_deletes_nothing(self):
        self.make_old(ApiRequestLog, 400, method="GET", path="/api/v1/x", status=200, duration_ms=1)
        before = ApiRequestLog.objects.count(), AuditEvent.objects.count()
        out = StringIO()
        call_command("purge_logs", "--dry-run", stdout=out)
        self.assertIn("Simulation", out.getvalue())
        self.assertEqual((ApiRequestLog.objects.count(), AuditEvent.objects.count()), before)


class KeyRotationTests(AdminBase):
    def test_rotation_keeps_secrets_readable_after_old_key_is_removed(self):
        old, new = settings.FIELD_ENCRYPTION_KEY, Fernet.generate_key().decode()
        secret = ServiceSecret(key="smtp_password")
        secret.set_value("mot-de-passe-smtp")
        secret.save()
        with override_settings(FIELD_ENCRYPTION_KEY=f"{new},{old}"):
            self.assertEqual(ServiceSecret.value_of("smtp_password"), "mot-de-passe-smtp")
            call_command("rotate_secrets", stdout=StringIO())
        with override_settings(FIELD_ENCRYPTION_KEY=new):
            self.assertEqual(ServiceSecret.value_of("smtp_password"), "mot-de-passe-smtp")
        self.assertTrue(AuditEvent.objects.filter(event="Rotation de la clé de chiffrement").exists())

    def test_secret_is_unreadable_without_its_key(self):
        secret = ServiceSecret(key="smtp_password")
        secret.set_value("mot-de-passe-smtp")
        secret.save()
        with override_settings(FIELD_ENCRYPTION_KEY=Fernet.generate_key().decode()):
            with self.assertRaises(ImproperlyConfigured):
                ServiceSecret.value_of("smtp_password")
