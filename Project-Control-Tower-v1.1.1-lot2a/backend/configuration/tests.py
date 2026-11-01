from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient, APITestCase

from configuration.models import ApiRequestLog, ApiToken, AuditEvent, Notification, ServiceSecret

User = get_user_model()
STRONG = "Tour-de-controle-2026!"


class AdminBase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_demo", stdout=open("/dev/null", "w"))
        call_command("create_default_admin", stdout=open("/dev/null", "w"))
        cls.admin = User.objects.get(username="admin")
        cls.admin.must_change_password = False
        cls.admin.email = "admin@demo-esn.fr"
        cls.admin.save()
        cls.consultant = User.objects.get(person_code="ib")
        cls.client_user = User.objects.get(person_code="lf")

    def setUp(self):
        self.client.force_authenticate(self.admin)


class AccessControlTests(AdminBase):
    def test_non_admin_is_refused(self):
        self.client.force_authenticate(self.consultant)
        for url in ("/api/admin/users", "/api/admin/database", "/api/admin/secrets", "/api/admin/notifications", "/api/admin/audit"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 403, url)
            self.assertEqual(r.json()["code"], "FORBIDDEN_PERMISSION")

    def test_admin_api_token_cannot_reach_configuration(self):
        _, raw = ApiToken.issue(name="t", user=self.admin, read_only=False)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        self.assertEqual(client.get("/api/admin/users").status_code, 403)
        self.assertEqual(client.get("/api/projects").status_code, 200)

    def test_health_is_public_and_without_details(self):
        r = APIClient().get("/api/health")
        self.assertEqual(r.json(), {"status": "ok"})


class UserManagementTests(AdminBase):
    def test_create_user_returns_temporary_password_once(self):
        r = self.client.post("/api/admin/users", {"username": "j.durand", "firstName": "Jeanne", "lastName": "Durand",
                                                  "email": "j.durand@demo-esn.fr", "role": "consultant"}, format="json")
        self.assertEqual(r.status_code, 201)
        temp = r.json()["temporaryPassword"]
        self.assertNotIn("password", r.json())
        self.assertTrue(r.json()["mustChangePassword"])
        self.assertNotIn("temporaryPassword", self.client.get(f"/api/admin/users/{r.json()['id']}").json())
        client = APIClient()
        login = client.post("/api/auth/login", {"username": "j.durand", "password": temp}, format="json")
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.json()["mustChangePassword"])
        self.assertTrue(AuditEvent.objects.filter(event="Compte créé", entity="Utilisateur j.durand").exists())

    def test_weak_chosen_password_is_rejected(self):
        r = self.client.post("/api/admin/users", {"username": "x", "role": "dev", "password": "1234"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("password", [d["field"] for d in r.json()["details"]])

    def test_client_account_requires_client(self):
        r = self.client.post("/api/admin/users", {"username": "c1", "role": "client"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/admin/users", {"username": "c1", "role": "client", "client": "ndl"}, format="json")
        self.assertEqual(r.status_code, 201)

    def test_promote_user_to_admin_gives_configuration_access(self):
        r = self.client.patch(f"/api/admin/users/{self.consultant.id}", {"role": "admin"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.client.force_authenticate(User.objects.get(pk=self.consultant.pk))
        self.assertEqual(self.client.get("/api/admin/users").status_code, 200)
        self.assertTrue(AuditEvent.objects.filter(event="Rôle modifié", old_value="consultant", new_value="admin").exists())

    def test_admin_cannot_demote_or_deactivate_self(self):
        for payload in ({"role": "consultant"}, {"isActive": False}):
            r = self.client.patch(f"/api/admin/users/{self.admin.id}", payload, format="json")
            self.assertEqual(r.status_code, 400, payload)
        self.assertEqual(User.objects.get(pk=self.admin.pk).role_id, "admin")

    def test_last_active_admin_is_protected(self):
        User.objects.filter(role_id="admin").exclude(pk=self.admin.pk).update(is_active=False)
        other = User.objects.create(username="admin2", role_id="admin")
        self.client.force_authenticate(other)
        r = self.client.patch(f"/api/admin/users/{self.admin.id}", {"isActive": False}, format="json")
        self.assertEqual(r.status_code, 200)  # il reste admin2
        r = self.client.patch(f"/api/admin/users/{other.id}", {"role": "dev"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_reset_password_forces_change(self):
        r = self.client.post(f"/api/admin/users/{self.consultant.id}/reset-password")
        temp = r.json()["temporaryPassword"]
        user = User.objects.get(pk=self.consultant.pk)
        self.assertTrue(user.check_password(temp) and user.must_change_password)


class AccessManagementTests(AdminBase):
    def visible(self, user):
        c = APIClient()
        c.force_authenticate(User.objects.get(pk=user.pk))
        return sorted(p["id"] for p in c.get("/api/projects").json())

    def test_project_access_changes_scope_and_notifies_user(self):
        r = self.client.put(f"/api/admin/users/{self.consultant.id}/access",
                            {"projects": [{"project": "p4", "canEdit": False}], "actions": []}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.visible(self.consultant), ["p4"])
        self.assertTrue(Notification.objects.filter(user=self.consultant, event="scope_changed").exists())
        self.assertTrue(AuditEvent.objects.filter(event="Accès projets et tâches").exists())

    def test_single_task_access_for_client(self):
        c = APIClient()
        c.force_authenticate(self.client_user)
        ids = [a["id"] for a in c.get("/api/projects/p1/actions").json()]
        self.assertNotIn("A-1042", ids)  # tâche technique interne
        current = self.client.get(f"/api/admin/users/{self.client_user.id}/access").json()
        current["actions"] = [{"action": "A-1042", "canEdit": False}]
        self.client.put(f"/api/admin/users/{self.client_user.id}/access", current, format="json")
        ids = [a["id"] for a in c.get("/api/projects/p1/actions").json()]
        self.assertIn("A-1042", ids)

    def test_unknown_project_is_rejected(self):
        r = self.client.put(f"/api/admin/users/{self.consultant.id}/access", {"projects": [{"project": "zz"}], "actions": []}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_matrix_change_applies_immediately(self):
        c = APIClient()
        c.force_authenticate(self.consultant)
        self.assertTrue(c.get("/api/projects/p1/actions").json())
        perms = self.client.get("/api/admin/roles").json()
        consultant = next(r for r in perms["roles"] if r["code"] == "consultant")
        flags = consultant["permissions"]["action"]
        flags[0] = False
        r = self.client.put("/api/admin/roles/consultant/permissions", {"permissions": {"action": flags}}, format="json")
        self.assertEqual(r.status_code, 200)
        c.force_authenticate(User.objects.get(pk=self.consultant.pk))
        owners = {a["owner"] for a in c.get("/api/projects/p1/actions").json()}
        self.assertLessEqual(owners, {self.consultant.display_name})


class TokenAndSecretTests(AdminBase):
    def test_token_lifecycle(self):
        r = self.client.post("/api/admin/api/tokens", {"name": "Power BI", "user": self.consultant.id, "readOnly": True}, format="json")
        self.assertEqual(r.status_code, 201)
        raw = r.json()["token"]
        listed = self.client.get("/api/admin/api/tokens").json()
        self.assertNotIn(raw, str(listed))
        self.assertNotIn("token_hash", str(listed))
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        self.assertEqual(api.get("/api/projects").status_code, 200)
        self.assertEqual(api.post("/api/notifications").status_code, 403)  # lecture seule
        self.client.post(f"/api/admin/api/tokens/{r.json()['id']}/revoke")
        self.assertEqual(api.get("/api/projects").status_code, 401)

    def test_secret_is_encrypted_and_never_returned(self):
        value = "smtp-mot-de-passe-tres-long-9876"
        r = self.client.put("/api/admin/secrets/smtp_password", {"value": value}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["hint"], "••••9876")
        self.assertNotIn(value, str(self.client.get("/api/admin/secrets").json()))
        row = ServiceSecret.objects.get(key="smtp_password")
        self.assertNotIn(value, row.ciphertext)
        self.assertEqual(row.get_value(), value)
        self.assertFalse(AuditEvent.objects.filter(new_value__contains=value).exists())

    def test_webhook_url_must_be_official_https_host(self):
        for url in ("http://hooks.slack.com/services/x", "https://169.254.169.254/latest", "https://evil.example/hooks.slack.com"):
            r = self.client.put("/api/admin/secrets/slack_webhook_url", {"value": url}, format="json")
            self.assertEqual(r.status_code, 400, url)
        r = self.client.put("/api/admin/secrets/slack_webhook_url", {"value": "https://hooks.slack.com/services/T/B/x"}, format="json")
        self.assertEqual(r.status_code, 200)


class NotificationTests(AdminBase):
    def configure_email(self):
        return self.client.put("/api/admin/notifications/channels/email", {"enabled": True, "settings": {
            "host": "smtp.example.org", "port": 587, "username": "pct", "from_address": "pct@demo-esn.fr", "security": "starttls"}}, format="json")

    def test_email_requires_host(self):
        r = self.client.put("/api/admin/notifications/channels/email", {"enabled": True, "settings": {}}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.configure_email().status_code, 200)

    def test_webhook_channel_requires_url(self):
        r = self.client.put("/api/admin/notifications/channels/teams", {"enabled": True}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_email_test_is_sent_with_saved_settings(self):
        self.configure_email()
        with mock.patch("configuration.notify.EmailMessage.send") as send:
            r = self.client.post("/api/admin/notifications/channels/email/test", {}, format="json")
        self.assertEqual(r.status_code, 200)
        send.assert_called_once()

    def test_failed_test_returns_502_without_secret(self):
        self.configure_email()
        self.client.put("/api/admin/secrets/smtp_password", {"value": "secret-a-ne-pas-montrer"}, format="json")
        with mock.patch("configuration.notify.EmailMessage.send", side_effect=ConnectionRefusedError("secret-a-ne-pas-montrer")):
            r = self.client.post("/api/admin/notifications/channels/email/test", {}, format="json")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.json()["code"], "CHANNEL_TEST_FAILED")
        self.assertNotIn("secret-a-ne-pas-montrer", str(r.json()))

    def test_webhook_test_posts_json(self):
        self.client.put("/api/admin/secrets/teams_webhook_url", {"value": "https://acme.webhook.office.com/webhookb2/x"}, format="json")
        self.client.put("/api/admin/notifications/channels/teams", {"enabled": True}, format="json")
        response = mock.MagicMock(status=200)
        response.__enter__.return_value = response
        with mock.patch("configuration.notify.urllib.request.urlopen", return_value=response) as urlopen:
            r = self.client.post("/api/admin/notifications/channels/teams/test", {}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Message de test", urlopen.call_args[0][0].data)

    def test_rules_update(self):
        r = self.client.put("/api/admin/notifications/rules", {"rules": {"risk_critical": {"email": True}}}, format="json")
        self.assertTrue(r.json()["rules"]["risk_critical"]["email"])
        r = self.client.put("/api/admin/notifications/rules", {"rules": {"inconnu": {"email": True}}}, format="json")
        self.assertEqual(r.status_code, 400)


class StatusTests(AdminBase):
    def test_database_status(self):
        r = self.client.get("/api/admin/database").json()
        self.assertTrue(r["connected"])
        self.assertEqual(r["migrations"]["pending"], [])
        self.assertNotIn("PASSWORD", str(r).upper().replace("PASSWORD_", ""))
        self.assertEqual(r["configuredBy"], "DATABASE_URL")

    def test_endpoints_and_logs(self):
        endpoints = {e["path"]: e for e in self.client.get("/api/admin/api/endpoints").json()}
        # La liste montre la version courante /api/v1/ (lot 2a) ; /api/ reste servi en alias.
        self.assertEqual(endpoints["/api/v1/admin/users"]["access"], "admin")
        self.assertEqual(endpoints["/api/v1/health"]["access"], "public")
        self.client.get("/api/projects")
        self.assertTrue(ApiRequestLog.objects.filter(path="/api/projects", status=200).exists())
        stats = self.client.get("/api/admin/api/stats?hours=1").json()
        self.assertGreaterEqual(stats["requests"], 1)
        self.assertEqual(self.client.get("/api/admin/api/stats?hours=abc").status_code, 400)
