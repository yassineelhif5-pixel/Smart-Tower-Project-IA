"""Phases 3 à 6 : offres, abonnements, licences, demandes, délégation, élévation de privilèges, concurrence, audit.

Les comptes d'un tenant soumis aux licences se connectent réellement (POST /auth/login) : la session doit
détenir une licence, ce que force_authenticate ne simule pas.
"""
import threading
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.db import DatabaseError, connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from accounts.permissions import has_perm
from configuration.models import AuditEvent, Notification
from licensing import models as L
from licensing import services
from tenants import services as tenant_services
from tenants.models import Tenant

User = get_user_model()
PWD = "Tour-de-controle-2026!"


def demo_version():
    return L.Offer.objects.get(code="demo").current_version


class Base(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pilot = User.objects.create(username="pilote", role_id="superadmin", tenant=None)
        cls.pilot.set_password(PWD)
        cls.pilot.save()
        cls.t, cls.admin, _ = tenant_services.create_tenant(by=cls.pilot, name="Acme", admin_username="admin.acme",
                                                            version=demo_version())
        cls.admin.set_password(PWD)
        cls.admin.must_change_password = False
        cls.admin.save()

    def setUp(self):
        cache.clear()

    def user(self, username, role="dev", tenant=None, active=True):
        u = User.objects.create(username=username, role_id=role, tenant=tenant or self.t, is_active=active)
        u.set_password(PWD)
        u.save()
        return u

    def login(self, username):
        client = APIClient()
        r = client.post("/api/v1/auth/login", {"username": username, "password": PWD}, format="json")
        return client, r

    def as_pilot(self):
        c = APIClient()
        c.force_authenticate(User.objects.get(pk=self.pilot.pk))
        return c


class OfferTests(Base):
    def test_initial_offers_are_data_not_code(self):
        self.assertEqual(list(L.Offer.objects.values_list("code", flat=True)), ["demo", "starter", "pro", "enterprise"])
        demo = demo_version()
        self.assertEqual((demo.is_published, demo.duration_days), (True, 7))
        self.assertFalse(L.Offer.objects.get(code="pro").current_version)  # brouillon : le Pilote le complète

    def test_pilot_manages_offers_and_versions(self):
        c = self.as_pilot()
        pro = L.Offer.objects.get(code="pro")
        draft = pro.versions.get()
        r = c.patch(f"/api/v1/platform/versions/{draft.id}", {"price": "490.00", "maxUsers": 50, "namedLicenses": 20,
                                                              "concurrentLicenses": 5, "publish": True}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(c.patch(f"/api/v1/platform/versions/{draft.id}", {"price": "1"}, format="json").status_code, 409)
        r = c.post(f"/api/v1/platform/offers/{pro.id}/versions", {"price": "520.00", "publish": True}, format="json")
        self.assertEqual((r.status_code, r.json()["number"], r.json()["maxUsers"]), (201, 2, 50))  # copie de v1
        self.assertEqual(pro.current_version.price, 520)
        self.assertEqual(c.post("/api/v1/platform/offers", {"code": "xl", "name": "XL"}, format="json").status_code, 201)
        self.assertTrue(AuditEvent.objects.filter(event="Version créée", tenant=None).exists())

    def test_tenant_admin_has_no_access_to_commercial_settings(self):
        client, _ = self.login("admin.acme")
        for url in ("/api/v1/platform/offers", "/api/v1/platform/dashboard", "/api/v1/platform/requests"):
            self.assertEqual(client.get(url).status_code, 403, url)
        self.assertEqual(client.post(f"/api/v1/platform/tenants/{self.t.id}/allocations",
                                     {"kind": "named", "delta": 50, "reason": "moi"}, format="json").status_code, 403)
        self.assertEqual(client.post(f"/api/v1/platform/offers/{L.Offer.objects.get(code='demo').id}/versions",
                                     {"price": "0"}, format="json").status_code, 403)
        self.assertEqual(services.stock(self.t)[L.NAMED]["total"], 3)


class SubscriptionAndStockTests(Base):
    def test_tenant_created_with_offer_gets_subscription_stock_and_admin_license(self):
        sub = services.current_subscription(self.t)
        self.assertEqual((sub.status, sub.end_date), (L.ACTIVE, timezone.localdate() + timedelta(days=7)))
        st = services.stock(self.t)
        self.assertEqual((st[L.NAMED]["total"], st[L.NAMED]["used"], st[L.CONCURRENT]["total"]), (3, 1, 2))
        self.assertEqual(services.named_license_of(self.admin).tenant, self.t)

    def test_stock_can_only_shrink_by_free_licenses(self):
        c = self.as_pilot()
        url = f"/api/v1/platform/tenants/{self.t.id}/allocations"
        self.assertEqual(c.post(url, {"kind": "named", "delta": -3, "reason": "retrait"}, format="json").json()["code"], "STOCK_IN_USE")
        r = c.post(url, {"kind": "named", "delta": -2, "reason": "retrait"}, format="json")
        self.assertEqual((r.status_code, r.json()["stock"]["named"]["total"]), (201, 1))
        r = c.post(url, {"kind": "named", "delta": 10, "reason": "Contrat signé"}, format="json")
        self.assertEqual(r.json()["stock"]["named"]["available"], 10)
        self.assertEqual(c.post(url, {"kind": "named", "delta": 5, "reason": ""}, format="json").status_code, 400)
        self.assertEqual(L.LicenseAllocation.objects.filter(tenant=self.t).count(), 4)  # 2 initiales + 2 mouvements

    def test_suspension_and_expiry_block_access_without_deleting_data(self):
        dev = self.user("dev1")
        c = self.as_pilot()
        url = f"/api/v1/platform/tenants/{self.t.id}/subscription"
        self.assertEqual(c.patch(url, {"status": "suspended"}, format="json").status_code, 400)  # motif obligatoire
        c.patch(url, {"status": "suspended", "reason": "Impayé"}, format="json")
        self.assertEqual(self.login("dev1")[1].json()["code"], "SUBSCRIPTION_SUSPENDED")
        c.patch(url, {"status": "active"}, format="json")
        self.assertEqual(self.login("dev1")[1].status_code, 200)

        L.Subscription.objects.filter(tenant=self.t).update(end_date=timezone.localdate() - timedelta(days=1))
        cache.clear()
        self.assertEqual(self.login("dev1")[1].json()["code"], "SUBSCRIPTION_EXPIRED")
        self.assertTrue(User.objects.filter(pk=dev.pk).exists())
        self.assertEqual(L.License.objects.filter(tenant=self.t).count(), 5)  # rien n'est supprimé
        r = c.patch(url, {"status": "active"}, format="json")
        self.assertEqual(r.status_code, 400)  # il faut d'abord reporter l'échéance
        r = c.patch(url, {"status": "active", "endDate": str(timezone.localdate() + timedelta(days=30))}, format="json")
        self.assertEqual(r.json()["subscription"]["status"], L.ACTIVE)

    def test_user_quota_of_the_offer(self):
        client, _ = self.login("admin.acme")
        for i in range(4):  # Demo : 5 utilisateurs actifs, l'administrateur compris
            self.assertEqual(client.post("/api/v1/admin/users", {"username": f"u{i}", "role": "dev"}, format="json").status_code, 201)
        r = client.post("/api/v1/admin/users", {"username": "u5", "role": "dev"}, format="json")
        self.assertEqual((r.status_code, r.json()["code"]), (400, "USER_QUOTA_REACHED"))


class NamedLicenseTests(Base):
    def test_assign_release_reassign_with_history(self):
        a, b = self.user("alice"), self.user("bob")
        client, _ = self.login("admin.acme")
        free = L.License.objects.filter(tenant=self.t, kind=L.NAMED, status=L.AVAILABLE).first()
        r = client.post(f"/api/v1/licensing/licenses/{free.id}/assign", {"user": a.id}, format="json")
        self.assertEqual(r.json()["holder"]["username"], "alice")
        other = L.License.objects.filter(tenant=self.t, kind=L.NAMED, status=L.AVAILABLE).first()
        self.assertEqual(client.post(f"/api/v1/licensing/licenses/{other.id}/assign", {"user": a.id}, format="json").json()["code"], "ALREADY_LICENSED")
        self.assertEqual(client.post(f"/api/v1/licensing/licenses/{free.id}/assign", {"user": b.id}, format="json").json()["code"], "LICENSE_UNAVAILABLE")
        r = client.post(f"/api/v1/licensing/licenses/{free.id}/reassign", {"user": b.id}, format="json")
        self.assertEqual(r.json()["holder"]["username"], "bob")
        client.post(f"/api/v1/licensing/licenses/{free.id}/release", {"reason": "Départ"}, format="json")
        self.assertEqual(L.License.objects.get(pk=free.pk).status, L.AVAILABLE)
        self.assertEqual(L.LicenseAssignment.objects.filter(license=free).count(), 2)
        self.assertEqual(set(AuditEvent.objects.filter(tenant=self.t, entity=f"Licence {free.number}").values_list("event", flat=True)),
                         {"Licence affectée", "Licence libérée"})

    def test_deactivating_a_user_returns_the_license(self):
        a = self.user("alice")
        client, _ = self.login("admin.acme")
        lic = L.License.objects.filter(tenant=self.t, kind=L.NAMED, status=L.AVAILABLE).first()
        client.post(f"/api/v1/licensing/licenses/{lic.id}/assign", {"user": a.id}, format="json")
        client.patch(f"/api/v1/admin/users/{a.id}", {"isActive": False}, format="json")
        self.assertEqual(L.License.objects.get(pk=lic.pk).status, L.AVAILABLE)

    def test_other_tenant_licenses_and_users_are_out_of_reach(self):
        other, other_admin, _ = tenant_services.create_tenant(by=self.pilot, name="Globex", admin_username="admin.globex",
                                                              version=demo_version())
        foreign = L.License.objects.filter(tenant=other, kind=L.NAMED, status=L.AVAILABLE).first()
        mine = L.License.objects.filter(tenant=self.t, kind=L.NAMED, status=L.AVAILABLE).first()
        client, _ = self.login("admin.acme")
        self.assertEqual(client.post(f"/api/v1/licensing/licenses/{foreign.id}/assign", {"user": self.admin.id}, format="json").status_code, 404)
        self.assertEqual(client.post(f"/api/v1/licensing/licenses/{mine.id}/assign", {"user": other_admin.id}, format="json").status_code, 404)
        self.assertNotIn(foreign.number, [l["number"] for l in client.get("/api/v1/licensing/licenses").json()["licenses"]])


class ConcurrentLicenseTests(Base):
    def test_capacity_is_enforced_and_freed(self):
        for name in ("c1", "c2", "c3"):
            self.user(name)
        s1, r1 = self.login("c1")
        s2, r2 = self.login("c2")
        self.assertEqual((r1.status_code, r2.status_code), (200, 200))
        _, r3 = self.login("c3")
        self.assertEqual((r3.status_code, r3.json()["code"]), (403, "LICENSE_CAPACITY_REACHED"))
        self.assertEqual(services.stock(self.t)[L.CONCURRENT]["available"], 0)
        s1.post("/api/v1/auth/logout")
        self.assertEqual(self.login("c3")[1].status_code, 200)

    def test_idle_session_expires_and_frees_its_license(self):
        self.user("c1"), self.user("c2"), self.user("c3")
        c1, _ = self.login("c1")
        self.login("c2")
        L.ConcurrentSession.objects.filter(user__username="c1").update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.login("c3")[1].status_code, 200)  # la session inactive a rendu sa licence
        r = c1.get("/api/v1/auth/me")
        self.assertEqual((r.status_code, r.json()["code"]), (401, "LICENSE_SESSION_ENDED"))

    def test_admin_revokes_a_session(self):
        self.user("c1")
        c1, _ = self.login("c1")
        admin, _ = self.login("admin.acme")
        sessions = admin.get("/api/v1/licensing/sessions").json()
        target = next(s for s in sessions if s["user"]["username"] == "c1")
        self.assertEqual(target["mode"], "concurrente")
        self.assertEqual(admin.post(f"/api/v1/licensing/sessions/{target['id']}/revoke").status_code, 204)
        self.assertEqual(c1.get("/api/v1/projects").json()["code"], "LICENSE_SESSION_ENDED")

    def test_password_change_keeps_the_license_session(self):
        user = self.user("c1")
        user.must_change_password = True
        user.save()
        client, r = self.login("c1")
        self.assertTrue(r.json()["mustChangePassword"])
        r = client.post("/api/v1/auth/change-password", {"current_password": PWD, "new_password": "Nouveau-mot-2026!"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(client.get("/api/v1/auth/me").status_code, 200)
        self.assertEqual(L.ConcurrentSession.objects.filter(user=user, ended_at__isnull=True).count(), 1)

    def test_no_license_at_all(self):
        self.as_pilot().post(f"/api/v1/platform/tenants/{self.t.id}/allocations",
                             {"kind": "concurrent", "delta": -2, "reason": "retrait"}, format="json")
        self.user("solo")
        self.assertEqual(self.login("solo")[1].json()["code"], "NO_LICENSE")
        self.assertTrue(AuditEvent.objects.filter(event="Connexion refusée (licence)", result="denied").exists())

    def test_me_access_describes_the_license(self):
        self.user("c1")
        client, _ = self.login("c1")
        body = client.get("/api/v1/me/access").json()
        self.assertEqual((body["license"]["mode"], body["company"]["name"], body["role"]["code"]), ("concurrente", "Acme", "dev"))
        self.assertTrue(body["session"]["expiresAt"])
        admin, _ = self.login("admin.acme")
        self.assertEqual(admin.get("/api/v1/me/access").json()["license"]["mode"], "nominative")


class ConcurrencyRaceTests(TransactionTestCase):
    """Dix connexions simultanées pour deux licences concurrentes : exactement deux réussissent."""

    serialized_rollback = True

    def test_simultaneous_reservations_never_share_a_license(self):
        pilot = User.objects.create(username="pilote-race", role_id="superadmin")
        tenant, _, _ = tenant_services.create_tenant(by=pilot, name="Race", admin_username="admin.race", version=demo_version())
        users = [User.objects.create(username=f"r{i}", role_id="dev", tenant=tenant) for i in range(10)]
        barrier, results = threading.Barrier(10), []

        def connect(user):
            try:
                barrier.wait()
                services.open_session(user, f"key-{user.pk}")
                results.append("ok")
            except services.LicenseError as exc:
                results.append(exc.code)
            except DatabaseError as exc:
                results.append(type(exc).__name__)
            finally:
                connection.close()

        threads = [threading.Thread(target=connect, args=(u,)) for u in users]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results.count("ok"), 2, results)
        self.assertEqual(results.count("LICENSE_CAPACITY_REACHED"), 8, results)
        open_ = L.ConcurrentSession.objects.filter(tenant=tenant, ended_at__isnull=True)
        self.assertEqual(open_.count(), 2)
        self.assertEqual(len(set(open_.values_list("license_id", flat=True))), 2)


class RequestWorkflowTests(Base):
    def test_full_cycle_with_partial_approval_and_fulfilment(self):
        admin, _ = self.login("admin.acme")
        r = admin.post("/api/v1/licensing/requests", {"kind": "named", "quantity": 5, "justification": "Nouvelle équipe"}, format="json")
        req_id = r.json()["id"]
        self.assertEqual(r.json()["status"], L.SUBMITTED)
        self.assertTrue(Notification.objects.filter(user=self.pilot).exists())
        # Le tenant ne peut ni décider ni exécuter sa propre demande.
        self.assertEqual(admin.post(f"/api/v1/platform/requests/{req_id}/decide", {"status": "APPROVED"}, format="json").status_code, 403)

        pilot = self.as_pilot()
        r = pilot.post(f"/api/v1/platform/requests/{req_id}/decide", {"status": "PARTIALLY_APPROVED", "quantityGranted": 5}, format="json")
        self.assertEqual(r.status_code, 400)  # partiel = moins que demandé
        r = pilot.post(f"/api/v1/platform/requests/{req_id}/decide", {"status": "PARTIALLY_APPROVED", "quantityGranted": 3,
                                                                     "comment": "3 maintenant"}, format="json")
        self.assertEqual(r.json()["status"], L.PARTIALLY_APPROVED)
        self.assertEqual(services.stock(self.t)[L.NAMED]["total"], 3)  # approuvée n'est pas exécutée
        r = pilot.post(f"/api/v1/platform/requests/{req_id}/fulfil", {}, format="json")
        self.assertEqual(r.json()["status"], L.FULFILLED)
        self.assertEqual(services.stock(self.t)[L.NAMED]["total"], 6)
        self.assertTrue(L.LicenseAllocation.objects.filter(request_id=req_id, delta=3).exists())
        self.assertEqual([e["to"] for e in r.json()["events"]], ["DRAFT", "SUBMITTED", "PARTIALLY_APPROVED", "FULFILLED"])
        self.assertEqual(pilot.post(f"/api/v1/platform/requests/{req_id}/fulfil", {}, format="json").status_code, 400)

    def test_information_loop_rejection_and_cancellation(self):
        admin, _ = self.login("admin.acme")
        req = admin.post("/api/v1/licensing/requests", {"kind": "concurrent", "quantity": 2, "justification": "Pic"}, format="json").json()
        pilot = self.as_pilot()
        self.assertEqual(pilot.post(f"/api/v1/platform/requests/{req['id']}/decide", {"status": "ADDITIONAL_INFORMATION_REQUIRED"},
                                    format="json").status_code, 400)  # commentaire obligatoire
        pilot.post(f"/api/v1/platform/requests/{req['id']}/decide", {"status": "ADDITIONAL_INFORMATION_REQUIRED",
                                                                    "comment": "Pour quelle durée ?"}, format="json")
        r = admin.post(f"/api/v1/licensing/requests/{req['id']}/submit", {"comment": "Trois mois"}, format="json")
        self.assertEqual(r.json()["status"], L.SUBMITTED)
        r = pilot.post(f"/api/v1/platform/requests/{req['id']}/decide", {"status": "REJECTED", "comment": "Budget"}, format="json")
        self.assertEqual(r.json()["status"], L.REJECTED)
        self.assertEqual(admin.post(f"/api/v1/licensing/requests/{req['id']}/cancel", {}, format="json").status_code, 400)
        other = admin.post("/api/v1/licensing/requests", {"kind": "offer", "targetOffer": L.Offer.objects.get(code="pro").id,
                                                          "justification": "Croissance"}, format="json").json()
        self.assertEqual(admin.post(f"/api/v1/licensing/requests/{other['id']}/cancel", {}, format="json").json()["status"], L.CANCELLED_R)

    def test_requests_are_private_to_their_tenant(self):
        admin, _ = self.login("admin.acme")
        req = admin.post("/api/v1/licensing/requests", {"kind": "named", "quantity": 1, "justification": "x"}, format="json").json()
        other, other_admin, _ = tenant_services.create_tenant(by=self.pilot, name="Globex", admin_username="admin.globex",
                                                              version=demo_version())
        other_admin.set_password(PWD)
        other_admin.must_change_password = False
        other_admin.save()
        client, _ = self.login("admin.globex")
        self.assertEqual(client.get(f"/api/v1/licensing/requests/{req['id']}").status_code, 404)
        self.assertEqual(client.get("/api/v1/licensing/requests").json(), [])


class DelegationAndPrivilegeTests(Base):
    def test_license_manager_role_manages_licenses_only(self):
        self.user("resp", role="license_manager")
        self.user("alice")
        resp, _ = self.login("resp")
        lic = L.License.objects.filter(tenant=self.t, kind=L.NAMED, status=L.AVAILABLE).first()
        alice = User.objects.get(username="alice")
        self.assertEqual(resp.post(f"/api/v1/licensing/licenses/{lic.id}/assign", {"user": alice.id}, format="json").status_code, 200)
        self.assertEqual(resp.get("/api/v1/admin/users").status_code, 403)
        self.assertEqual(resp.get("/api/v1/platform/tenants").status_code, 403)
        self.assertEqual(resp.get("/api/v1/licensing/sessions").status_code, 200)

    def test_readonly_and_standard_profiles_cannot_administer(self):
        ro = self.user("lecteur", role="readonly")
        self.assertTrue(has_perm(User.objects.get(pk=ro.pk), "project", "read"))
        self.assertFalse(has_perm(User.objects.get(pk=ro.pk), "project", "update"))
        client, _ = self.login("lecteur")
        lic = L.License.objects.filter(tenant=self.t, kind=L.NAMED, status=L.AVAILABLE).first()
        self.assertEqual(client.post(f"/api/v1/licensing/licenses/{lic.id}/assign", {"user": ro.id}, format="json").status_code, 403)
        self.assertEqual(client.get("/api/v1/licensing/overview").status_code, 403)

    def test_individual_delegation_and_its_limits(self):
        manager = self.user("chef", role="manager")
        admin, _ = self.login("admin.acme")
        r = admin.put(f"/api/v1/admin/users/{manager.id}/capabilities",
                      {"overrides": [{"code": "licenses.view", "granted": True}]}, format="json")
        self.assertIn("licenses.view", r.json()["effective"])
        r = admin.put(f"/api/v1/admin/users/{manager.id}/capabilities",
                      {"overrides": [{"code": "roles.administer", "granted": True}]}, format="json")
        self.assertEqual(r.status_code, 400)
        r = admin.put(f"/api/v1/admin/users/{self.admin.id}/capabilities", {"overrides": []}, format="json")
        self.assertEqual(r.status_code, 400)  # pas sur soi-même
        self.assertEqual(admin.put("/api/v1/admin/capabilities", {"roles": {"admin": []}}, format="json").status_code, 400)
        self.assertEqual(admin.put("/api/v1/admin/capabilities", {"roles": {"dev": ["offers.create"]}}, format="json").status_code, 400)
        r = admin.put("/api/v1/admin/capabilities", {"roles": {"dev": ["licenses.view"]}}, format="json")
        self.assertIn("licenses.view", next(x for x in r.json()["roles"] if x["code"] == "dev")["capabilities"])

    def test_offer_features_limit_modules_and_delegation(self):
        version = services.current_subscription(self.t).offer_version
        L.OfferVersion.objects.filter(pk=version.pk).update(features=["project", "action"])
        dev = self.user("dev2")
        dev = User.objects.get(pk=dev.pk)
        self.assertTrue(has_perm(dev, "action", "read"))
        self.assertFalse(has_perm(dev, "budget", "read") or has_perm(dev, "document", "read"))
        admin, _ = self.login("admin.acme")
        r = admin.put("/api/v1/admin/capabilities", {"roles": {"dev": ["licenses.view"]}}, format="json")
        self.assertEqual(r.json()["code"], "FEATURE_NOT_IN_OFFER")


class AuditTests(Base):
    def test_sensitive_operations_record_ip_result_and_cannot_be_altered(self):
        self.user("alice")
        admin, _ = self.login("admin.acme")
        lic = L.License.objects.filter(tenant=self.t, kind=L.NAMED, status=L.AVAILABLE).first()
        admin.post(f"/api/v1/licensing/licenses/{lic.id}/assign", {"user": User.objects.get(username="alice").id}, format="json")
        event = AuditEvent.objects.filter(event="Licence affectée").latest("at")
        self.assertEqual((event.ip, event.result, event.tenant, event.actor.username), ("127.0.0.1", "success", self.t, "admin.acme"))
        with self.assertRaises(DatabaseError), transaction.atomic():
            AuditEvent.objects.filter(pk=event.pk).update(event="falsifié")
        self.assertEqual(AuditEvent.objects.get(pk=event.pk).event, "Licence affectée")

    def test_audit_export_requires_its_own_right_and_is_isolated(self):
        self.user("lecteur", role="direction")  # direction : audit.view sans audit.export
        reader, _ = self.login("lecteur")
        self.assertEqual(reader.get("/api/v1/licensing/audit").status_code, 200)
        self.assertEqual(reader.get("/api/v1/licensing/audit?export=csv").status_code, 403)
        admin, _ = self.login("admin.acme")
        r = admin.get("/api/v1/licensing/audit?export=csv")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode("utf-8-sig")
        self.assertIn("admin.acme", body)
        self.assertNotIn("Demo ESN", body)
        self.assertTrue(AuditEvent.objects.filter(event="Journal exporté", tenant=self.t).exists())

    def test_consistency_command_covers_licenses(self):
        call_command("check_tenants", stdout=StringIO())
        other, other_admin, _ = tenant_services.create_tenant(by=self.pilot, name="Globex", admin_username="admin.globex")
        lic = L.License.objects.filter(tenant=self.t, kind=L.NAMED, status=L.AVAILABLE).first()
        L.LicenseAssignment.objects.create(tenant=self.t, license=lic, user=other_admin)  # corruption volontaire
        with self.assertRaises(CommandError):
            call_command("check_tenants", stdout=StringIO())

    def test_expiry_command(self):
        L.Subscription.objects.filter(tenant=self.t).update(end_date=timezone.localdate() - timedelta(days=1))
        out = StringIO()
        call_command("expire_licenses", stdout=out)
        self.assertIn("1 abonnement(s) expiré(s)", out.getvalue())
        self.assertEqual(L.Subscription.objects.get(tenant=self.t).status, L.EXPIRED)

    def test_pilot_dashboard(self):
        body = self.as_pilot().get("/api/v1/platform/dashboard").json()
        self.assertEqual(body["tenants"]["total"], Tenant.objects.count())
        self.assertEqual(body["licenses"]["allocated"], 5)
        self.assertEqual(body["licenses"]["used"], 1)
        self.assertIn({"offer": "Demo", "tenants": 1}, body["byOffer"])
