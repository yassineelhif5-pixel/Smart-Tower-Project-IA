from django.core.cache import cache
from django.core.management import call_command
from rest_framework.test import APIClient, APITestCase

from configuration.models import AuditEvent

STRONG = "Tour-de-controle-2026!"


class AuthTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_demo", stdout=open("/dev/null", "w"))
        call_command("create_default_admin", stdout=open("/dev/null", "w"))

    def setUp(self):
        cache.clear()  # remet à zéro le compteur de tentatives de connexion

    def login(self, username="admin", password="admin"):
        return self.client.post("/api/auth/login", {"username": username, "password": password}, format="json")

    def test_unauthenticated_gets_401_with_uniform_error(self):
        r = self.client.get("/api/auth/me")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["code"], "UNAUTHENTICATED")
        self.assertEqual(set(r.json()), {"code", "message", "details", "traceId"})

    def test_wrong_password_is_refused_and_audited(self):
        r = self.login(password="mauvais")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["code"], "INVALID_CREDENTIALS")
        self.assertTrue(AuditEvent.objects.filter(event="Connexion refusée", entity="Utilisateur admin").exists())

    def test_unknown_user_gets_same_message(self):
        a, b = self.login(password="mauvais").json(), self.login(username="inconnu").json()
        self.assertEqual(a["message"], b["message"])

    def test_default_admin_must_change_password_first(self):
        r = self.login()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["mustChangePassword"])
        self.assertTrue(r.json()["isAdmin"])
        blocked = self.client.get("/api/admin/users")
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.json()["code"], "PASSWORD_CHANGE_REQUIRED")
        self.assertEqual(self.client.get("/api/projects").json()["code"], "PASSWORD_CHANGE_REQUIRED")

    def test_weak_new_password_is_rejected_with_field_details(self):
        self.login()
        r = self.client.post("/api/auth/change-password", {"current_password": "admin", "new_password": "admin2"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "VALIDATION_ERROR")
        self.assertTrue(all(d["field"] == "new_password" for d in r.json()["details"]))

    def test_change_password_unlocks_api_and_old_password_stops_working(self):
        self.login()
        r = self.client.post("/api/auth/change-password", {"current_password": "admin", "new_password": STRONG}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["mustChangePassword"])
        self.assertEqual(self.client.get("/api/admin/users").status_code, 200)
        self.client.post("/api/auth/logout")
        self.assertEqual(self.login().status_code, 401)
        self.assertEqual(self.login(password=STRONG).status_code, 200)

    def test_login_requires_csrf_token(self):
        client = APIClient(enforce_csrf_checks=True)
        r = client.post("/api/auth/login", {"username": "admin", "password": "admin"}, format="json")
        self.assertEqual(r.status_code, 403)
        client.get("/api/auth/csrf")
        token = client.cookies["csrftoken"].value
        r = client.post("/api/auth/login", {"username": "admin", "password": "admin"}, format="json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(r.status_code, 200)

    def test_login_attempts_are_throttled(self):
        statuses = [self.login(password="x").status_code for _ in range(11)]
        self.assertEqual(statuses[-1], 429)

    def test_demo_accounts_have_no_usable_password(self):
        self.assertEqual(self.login(username="s.mansouri", password="").status_code, 400)
        self.assertEqual(self.login(username="s.mansouri", password="admin").status_code, 401)
