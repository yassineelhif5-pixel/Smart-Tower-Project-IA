"""Isolation multi-tenant (lot 3a) : deux entreprises, A (Demo ESN, données de démo) et B (créée par le Pilote).

Chaque test tente un accès croisé et vérifie qu'il échoue, ou qu'un réglage de B laisse A intact.
"""
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.db import transaction
from rest_framework.test import APIClient, APITestCase

from accounts.permissions import has_perm
from configuration.models import ApiRequestLog, ApiToken, AuditEvent, NotificationChannel, NotificationRule, ServiceSecret
from projects import models as m
from projects.access import visible
from tenants import services
from tenants.models import CrossTenantError, Tenant

User = get_user_model()
STRONG = "Tour-de-controle-2026!"
BUSINESS = [m.Client, m.ClientContract, m.PersonCapacity, m.Project, m.ProjectInternal, m.ProjectFinance, m.UserStory,
            m.Action, m.ActionComment, m.Objective, m.Todo, m.TimeEntry, m.Risk, m.Issue, m.ChangeRequest,
            m.ChangeRequestAmount, m.TestCampaign, m.Defect, m.Document, m.Meeting]


class TwoTenants(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_demo", stdout=StringIO())
        call_command("create_default_admin", stdout=StringIO())
        cls.a = Tenant.objects.get(slug="demo-esn")
        cls.admin_a = User.objects.get(username="admin")
        cls.admin_a.must_change_password = False
        cls.admin_a.save()
        cls.pilot = User.objects.create(username="pilote", role_id="superadmin", tenant=None)
        cls.b, cls.admin_b, _ = services.create_tenant(by=cls.pilot, name="Bêta Conseil", admin_username="admin.beta")
        cls.admin_b.must_change_password = False
        cls.admin_b.save()
        client_b = m.Client.objects.create(tenant=cls.b, code="beta-c", name="Client Bêta")
        cls.project_b = m.Project.objects.create(tenant=cls.b, id="pb1", code="NDL-MIG", name="Projet Bêta", client=client_b)
        cls.user_b = User.objects.create(username="dir.beta", role_id="direction", tenant=cls.b)
        cls.user_a = User.objects.get(person_code="nh")  # direction de A : voit tout A

    def as_user(self, user):
        # Recharge le compte, comme le fait chaque vraie requête (statut du tenant à jour).
        self.client.force_authenticate(User.objects.select_related("tenant").get(pk=user.pk))


class DataIsolationTests(TwoTenants):
    def test_project_code_is_unique_per_tenant_only(self):
        self.assertEqual(m.Project.objects.filter(code="NDL-MIG").count(), 2)

    def test_full_scope_roles_see_only_their_tenant(self):
        self.as_user(self.user_b)
        self.assertEqual([p["id"] for p in self.client.get("/api/v1/projects").json()], ["pb1"])
        self.assertEqual(self.client.get("/api/v1/projects/p1/actions").status_code, 404)
        self.as_user(self.user_a)
        ids = [p["id"] for p in self.client.get("/api/v1/projects").json()]
        self.assertNotIn("pb1", ids)
        self.assertEqual(self.client.get("/api/v1/projects/pb1/actions").status_code, 404)

    def test_visibility_rules_never_cross_tenants(self):
        for model in BUSINESS:
            self.assertFalse(visible(self.user_b, model).exclude(tenant=self.b).exists(), model.__name__)
            self.assertFalse(visible(self.user_a, model).exclude(tenant=self.a).exists(), model.__name__)
        self.assertEqual(visible(self.user_b, m.Project).count(), 1)

    def test_pilot_reads_no_business_data(self):
        for model in BUSINESS:
            self.assertFalse(visible(self.pilot, model).exists(), model.__name__)
        self.as_user(self.pilot)
        self.assertEqual(self.client.get("/api/v1/projects").json(), [])

    def test_cross_tenant_links_are_refused(self):
        with self.assertRaises(CrossTenantError):
            m.Action.objects.create(id="X-1", project=self.project_b, title="t", status="todo", owner=self.user_a)
        with self.assertRaises(CrossTenantError):
            m.Action.objects.create(id="X-2", tenant=self.a, project=self.project_b, title="t", status="todo")
        with self.assertRaises(CrossTenantError), transaction.atomic():
            self.project_b.team.add(self.user_a)
        with self.assertRaises(CrossTenantError):
            m.ProjectAccess.objects.create(user=self.user_b, project=m.Project.objects.get(id="p1"))
        self.assertFalse(self.project_b.team.exists())

    def test_consistency_command_detects_a_corrupted_link(self):
        call_command("check_tenants", stdout=StringIO())
        m.Action.objects.filter(id="A-1042").update(tenant=self.b)  # contourne save() : corruption volontaire
        with self.assertRaises(CommandError):
            call_command("check_tenants", stdout=StringIO())


class AdminIsolationTests(TwoTenants):
    def setUp(self):
        self.as_user(self.admin_b)

    def test_users_of_another_tenant_are_invisible(self):
        names = {u["username"] for u in self.client.get("/api/v1/admin/users").json()}
        self.assertEqual(names, {"admin.beta", "dir.beta"})
        uid = self.admin_a.id
        self.assertEqual(self.client.get(f"/api/v1/admin/users/{uid}").status_code, 404)
        self.assertEqual(self.client.patch(f"/api/v1/admin/users/{uid}", {"isActive": False}, format="json").status_code, 404)
        self.assertEqual(self.client.post(f"/api/v1/admin/users/{uid}/reset-password").status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/admin/users/{uid}/access").status_code, 404)
        self.assertTrue(User.objects.get(pk=uid).is_active)

    def test_created_user_lands_in_the_admins_tenant_whatever_the_payload(self):
        r = self.client.post("/api/v1/admin/users", {"username": "nouveau", "role": "dev", "tenant": self.a.id}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(User.objects.get(username="nouveau").tenant, self.b)

    def test_pilot_role_and_foreign_client_cannot_be_assigned(self):
        r = self.client.post("/api/v1/admin/users", {"username": "x1", "role": "superadmin"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/v1/admin/users", {"username": "x2", "role": "client", "client": "ndl"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(User.objects.filter(username__in=["x1", "x2"]).exists())

    def test_access_to_foreign_projects_and_tasks_is_refused(self):
        r = self.client.put(f"/api/v1/admin/users/{self.user_b.id}/access",
                            {"projects": [{"project": "p1", "canEdit": True}], "actions": [{"action": "A-1042"}]}, format="json")
        self.assertEqual(r.status_code, 404)
        self.assertFalse(self.user_b.project_accesses.exists())
        self.assertEqual([p["id"] for p in self.client.get("/api/v1/admin/projects").json()], ["pb1"])

    def test_rights_matrix_is_per_tenant(self):
        dev_a = User.objects.get(person_code="as")
        self.assertTrue(has_perm(dev_a, "action", "read"))
        flags = {"action": [False, False, False, False, False]}
        self.assertEqual(self.client.put("/api/v1/admin/roles/dev/permissions", {"permissions": flags}, format="json").status_code, 200)
        dev_a = User.objects.get(pk=dev_a.pk)
        self.assertTrue(has_perm(dev_a, "action", "read"))   # A inchangé
        self.assertEqual(self.client.put("/api/v1/admin/roles/superadmin/permissions", {"permissions": flags}, format="json").status_code, 404)
        self.assertNotIn("superadmin", [r["code"] for r in self.client.get("/api/v1/admin/roles").json()["roles"]])

    def test_secrets_and_notifications_are_per_tenant(self):
        s = ServiceSecret(tenant=self.a, key="smtp_password")
        s.set_value("secret-de-A")
        s.save()
        self.assertFalse(next(x for x in self.client.get("/api/v1/admin/secrets").json() if x["key"] == "smtp_password")["isSet"])
        self.client.put("/api/v1/admin/secrets/smtp_password", {"value": "secret-de-B-123"}, format="json")
        self.assertEqual(ServiceSecret.value_of(self.a, "smtp_password"), "secret-de-A")
        self.assertEqual(ServiceSecret.value_of(self.b, "smtp_password"), "secret-de-B-123")
        self.client.put("/api/v1/admin/notifications/rules", {"rules": {"risk_critical": {"inapp": False}}}, format="json")
        self.assertTrue(NotificationRule.objects.get(tenant=self.a, event="risk_critical", channel="inapp").enabled)
        self.assertFalse(NotificationRule.objects.get(tenant=self.b, event="risk_critical", channel="inapp").enabled)
        self.assertEqual(NotificationChannel.objects.filter(tenant=self.b).count(), 4)

    def test_tokens_are_per_tenant(self):
        _, _ = ApiToken.issue(name="jeton A", user=self.admin_a)
        token_a = ApiToken.objects.get(name="jeton A")
        self.assertEqual(self.client.get("/api/v1/admin/api/tokens").json(), [])
        self.assertEqual(self.client.post(f"/api/v1/admin/api/tokens/{token_a.id}/revoke").status_code, 404)
        r = self.client.post("/api/v1/admin/api/tokens", {"name": "x", "user": self.admin_a.id}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(ApiToken.objects.get(pk=token_a.pk).revoked_at)

    def test_token_of_b_never_reads_a(self):
        _, raw = ApiToken.issue(name="jeton B", user=self.user_b)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        self.assertEqual([p["id"] for p in client.get("/api/v1/projects").json()], ["pb1"])

    def test_audit_and_api_logs_are_per_tenant(self):
        self.client.get("/api/v1/admin/users")
        rows = self.client.get("/api/v1/admin/audit").json()
        self.assertTrue(all(AuditEvent.objects.filter(trace=r["trace"], tenant=self.b).exists() for r in rows))
        self.as_user(self.admin_a)
        self.client.get("/api/v1/projects")
        self.as_user(self.admin_b)
        logs = self.client.get("/api/v1/admin/api/logs").json()
        self.assertTrue(logs)
        self.assertTrue(all(l["user"] in ("admin.beta", "dir.beta", None) for l in logs))
        self.assertTrue(ApiRequestLog.objects.filter(tenant=self.a).exists())

    def test_tenant_admin_cannot_reach_the_platform(self):
        for url in ("/api/v1/platform/tenants", f"/api/v1/platform/tenants/{self.a.id}", "/api/v1/platform/audit",
                    "/api/v1/admin/database"):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertEqual(self.client.patch(f"/api/v1/platform/tenants/{self.b.id}", {"status": "active"}, format="json").status_code, 403)


class PilotTests(TwoTenants):
    def setUp(self):
        self.as_user(self.pilot)

    def test_pilot_cannot_use_tenant_administration(self):
        for url in ("/api/v1/admin/users", "/api/v1/admin/roles", "/api/v1/admin/secrets", "/api/v1/admin/audit"):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_tenant_creation_is_controlled_and_audited(self):
        r = self.client.post("/api/v1/platform/tenants", {"name": "Gamma SA", "adminUsername": "admin.gamma"}, format="json")
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertEqual(body["slug"], "gamma-sa")
        self.assertTrue(body["temporaryPassword"])
        gamma = Tenant.objects.get(slug="gamma-sa")
        admin = User.objects.get(username="admin.gamma")
        self.assertEqual((admin.tenant, admin.role_id, admin.must_change_password), (gamma, "admin", True))
        self.assertTrue(has_perm(admin, "user", "update"))
        self.assertTrue(AuditEvent.objects.filter(tenant=None, event="Entreprise créée", actor=self.pilot).exists())
        dup = self.client.post("/api/v1/platform/tenants", {"name": "Gamma SA", "adminUsername": "autre"}, format="json")
        self.assertEqual(dup.status_code, 400)

    def test_tenant_detail_shows_accounts_but_no_business_data(self):
        body = self.client.get(f"/api/v1/platform/tenants/{self.a.id}").json()
        self.assertIn("userList", body)
        self.assertFalse({"projects", "actions", "documents"} & set(body))

    def test_suspension_blocks_the_tenant_and_only_it(self):
        r = self.client.patch(f"/api/v1/platform/tenants/{self.b.id}", {"status": "suspended"}, format="json")
        self.assertEqual(r.status_code, 400)  # motif obligatoire
        r = self.client.patch(f"/api/v1/platform/tenants/{self.b.id}", {"status": "suspended", "reason": "Impayé"}, format="json")
        self.assertEqual(r.json()["status"], "suspended")

        self.as_user(self.user_b)
        r = self.client.get("/api/v1/projects")
        self.assertEqual((r.status_code, r.json()["code"]), (403, "TENANT_INACTIVE"))
        self.assertEqual(self.client.get("/api/v1/auth/me").json()["code"], "TENANT_INACTIVE")
        self.assertFalse(visible(User.objects.get(pk=self.user_b.pk), m.Project).exists())

        self.as_user(self.user_a)
        self.assertEqual(self.client.get("/api/v1/projects").status_code, 200)

        cache.clear()
        self.admin_b.set_password(STRONG)
        self.admin_b.save()
        login = APIClient(enforce_csrf_checks=False).post("/api/v1/auth/login", {"username": "admin.beta", "password": STRONG}, format="json")
        self.assertEqual((login.status_code, login.json()["code"]), (403, "TENANT_INACTIVE"))

        self.as_user(self.pilot)
        self.assertEqual(self.client.patch(f"/api/v1/platform/tenants/{self.b.id}", {"status": "active"}, format="json").status_code, 200)
        self.as_user(self.user_b)
        self.assertEqual(self.client.get("/api/v1/projects").status_code, 200)

    def test_forbidden_status_transition(self):
        self.client.patch(f"/api/v1/platform/tenants/{self.b.id}", {"status": "archived", "reason": "Fin de contrat"}, format="json")
        r = self.client.patch(f"/api/v1/platform/tenants/{self.b.id}", {"status": "active"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_me_describes_tenant_and_profile(self):
        me = self.client.get("/api/v1/auth/me").json()
        self.assertEqual((me["isPlatformAdmin"], me["isAdmin"], me["tenant"]), (True, False, None))
        self.as_user(self.admin_b)
        me = self.client.get("/api/v1/auth/me").json()
        self.assertEqual((me["isPlatformAdmin"], me["isAdmin"], me["tenant"]["slug"]), (False, True, "beta-conseil"))

    def test_pilot_creation_command(self):
        out = StringIO()
        call_command("create_pilot", "pilote2", stdout=out)
        user = User.objects.get(username="pilote2")
        self.assertTrue(user.is_platform_admin and user.must_change_password and user.tenant_id is None)
        with self.assertRaises(CommandError):
            call_command("create_pilot", "pilote2", stdout=StringIO())
