"""Discussions et connecteur Microsoft Teams (1.4.0). Microsoft Graph est entièrement simulé : aucun appel réseau."""
from datetime import timedelta
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from configuration.models import Notification, ServiceSecret, UserNotificationPreference
from projects.models import Project
from tenants import services as tenant_services

from . import graph
from . import services as S
from .models import DiscussionMessage, GraphNotificationReceipt, GraphSubscription, MicrosoftToken, ProjectDiscussion, TeamsConnector

User = get_user_model()
BASE = "https://pct.example.com"


class FakeGraph:
    """Microsoft Graph simulé : enregistre chaque appel, renvoie des réponses plausibles ou programmées."""

    def __init__(self):
        self.calls = []
        self.fail = {}           # fragment d'URL -> (statut, corps)
        self.listing = []        # réponse de GET …/messages
        self.items = {}          # id -> message (GET …/messages/{id})
        self.counter = 0

    def __call__(self, method, url, headers=None, body=None, form=None):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "body": body, "form": form})
        for fragment, (status, payload) in self.fail.items():
            if fragment in url:
                return status, {}, payload
        path = urlparse(url).path
        if "oauth2/v2.0/token" in url:
            return 200, {}, {"access_token": f"at-{len(self.calls)}", "refresh_token": "rt-new", "expires_in": 3600,
                             "scope": " ".join(graph.BASE_SCOPES)}
        if path.endswith("/me"):
            return 200, {}, {"id": "ms-sm", "displayName": "E. Navarro", "userPrincipalName": "e.navarro@demo-esn.fr"}
        if method == "POST" and path.endswith("/chats"):
            return 201, {}, {"id": "19:chat@thread.v2", "webUrl": "https://teams.microsoft.com/l/chat/19"}
        if method == "POST" and (path.endswith("/messages") or path.endswith("/replies")):
            self.counter += 1
            return 201, {}, {"id": f"m{self.counter}", "lastModifiedDateTime": timezone.now().isoformat()}
        if method == "POST" and path.endswith("/subscriptions"):
            return 201, {}, {"id": f"sub-{len(self.calls)}"}
        if method == "PATCH" and "/subscriptions/" in path:
            return 200, {}, {}
        if method == "GET" and path.endswith("/messages"):
            return 200, {}, {"value": self.listing}
        if method == "GET" and "/messages/" in path:
            mid = path.rsplit("/", 1)[-1]
            return (200, {}, self.items[mid]) if mid in self.items else (404, {}, {"error": {"code": "NotFound"}})
        if method in ("PATCH",) or path.endswith("/softDelete"):
            return 204, {}, None
        if path.endswith("/joinedTeams"):
            return 200, {}, {"value": [{"id": "team-1", "displayName": "Delivery"}]}
        return 404, {}, {"error": {"code": "NotFound"}}

    def find(self, method, fragment):
        return [c for c in self.calls if c["method"] == method and fragment in c["url"]]


def remote(mid, text, sender_id="ms-ext", name="Externe", minutes=0, **extra):
    at = (timezone.now() + timedelta(minutes=minutes)).isoformat()
    return {"id": mid, "messageType": "message", "createdDateTime": at, "lastModifiedDateTime": at,
            "from": {"user": {"id": sender_id, "displayName": name}}, "body": {"contentType": "html", "content": text}, **extra}


@override_settings(PUBLIC_BASE_URL=BASE)
class Base(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_demo", stdout=open("/dev/null", "w"))
        cls.sm = User.objects.get(person_code="sm")
        cls.ib = User.objects.get(person_code="ib")
        cls.tl = User.objects.get(person_code="tl")
        cls.kd = User.objects.get(person_code="kd")
        cls.nb = User.objects.get(person_code="nb")
        cls.admin = User.objects.get(person_code="hb")
        cls.tenant = cls.sm.tenant
        cls.pilot = User.objects.create(username="pilote.collab", role_id="superadmin", tenant=None)
        cls.t2, cls.admin2, _ = tenant_services.create_tenant(by=cls.pilot, name="Autre SA", admin_username="admin.autre2")
        cls.admin2.must_change_password = False
        cls.admin2.save()
        cls.connector = TeamsConnector.objects.create(tenant=cls.tenant, directory_id="11111111-2222-3333-4444-555555555555",
                                                      client_id="66666666-7777-8888-9999-000000000000", enabled=True,
                                                      allow_channels=True, status="configured")
        secret = ServiceSecret(tenant=cls.tenant, key="teams_client_secret")
        secret.set_value("super-secret-value-123")
        secret.save()
        for user, ms in ((cls.sm, "ms-sm"), (cls.ib, "ms-ib")):
            t = MicrosoftToken(tenant=cls.tenant, user=user, ms_user_id=ms, ms_upn=user.email)
            t.store("at-initial", "rt-initial", timezone.now() + timedelta(hours=1), " ".join(graph.BASE_SCOPES))
            t.save()

    def setUp(self):
        self.fake = FakeGraph()
        patcher = mock.patch.object(graph, "transport", self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def as_user(self, user):
        c = APIClient()
        c.force_authenticate(User.objects.get(pk=user.pk))
        return c

    def discussion(self, user=None, **data):
        payload = {"project": "p1", "title": "Recette lot 2", "destination": "internal", **data}
        return self.as_user(user or self.sm).post("/api/v1/discussions", payload, format="json")


class InternalDiscussionTests(Base):
    def test_post_mention_edit_delete_and_history(self):
        d = self.discussion(participants=[self.ib.pk], message="Bonjour").json()
        self.assertEqual(d["destination"], "internal")
        c = self.as_user(self.sm)
        Notification.objects.all().delete()
        r = c.post(f"/api/v1/discussions/{d['id']}/messages", {"body": "Tu peux relire ?", "mentions": [self.ib.pk],
                                                               "clientKey": "k-1"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        m = r.json()
        self.assertEqual(m["publicationStatus"], "internal")
        self.assertTrue(Notification.objects.filter(user=self.ib, event="comment_mention").exists())
        # Idempotence : même clé, même message.
        again = c.post(f"/api/v1/discussions/{d['id']}/messages", {"body": "Tu peux relire ?", "clientKey": "k-1"}, format="json")
        self.assertEqual(again.json()["id"], m["id"])
        # Réponse dans le fil.
        reply = self.as_user(self.ib).post(f"/api/v1/discussions/{d['id']}/messages", {"body": "Oui", "parent": m["id"]}, format="json")
        self.assertEqual(reply.json()["parent"], m["id"])
        # Seul l'auteur modifie ou supprime son message ; l'historique est conservé.
        self.assertEqual(self.as_user(self.ib).patch(f"/api/v1/messages/{m['id']}", {"body": "x"}, format="json").status_code, 403)
        self.assertEqual(c.patch(f"/api/v1/messages/{m['id']}", {"body": "Tu peux relire stp ?"}, format="json").json()["historyCount"], 1)
        self.assertEqual(self.as_user(self.ib).delete(f"/api/v1/messages/{m['id']}").status_code, 403)
        self.assertEqual(c.delete(f"/api/v1/messages/{m['id']}").status_code, 204)
        rows = c.get(f"/api/v1/discussions/{d['id']}/messages").json()
        deleted = next(x for x in rows if x["id"] == m["id"])
        self.assertEqual((deleted["deleted"], deleted["body"]), (True, ""))
        self.assertEqual(len(c.get(f"/api/v1/messages/{m['id']}").json()["history"]), 2)
        self.assertFalse(self.fake.calls)  # rien n'est parti vers Microsoft

    def test_participants_must_see_the_project(self):
        r = self.discussion(participants=[self.nb.pk])
        self.assertEqual(r.status_code, 400)

    def test_user_preference_silences_notifications(self):
        UserNotificationPreference.objects.create(tenant=self.tenant, user=self.ib, event="discussion_message",
                                                  channel="inapp", enabled=False)
        d = self.discussion(participants=[self.ib.pk]).json()
        Notification.objects.all().delete()
        self.as_user(self.sm).post(f"/api/v1/discussions/{d['id']}/messages", {"body": "Info"}, format="json")
        self.assertFalse(Notification.objects.filter(user=self.ib).exists())
        prefs = self.as_user(self.ib).get("/api/v1/me/notification-preferences").json()
        row = next(e for e in prefs["events"] if e["event"] == "discussion_message")
        self.assertFalse(row["channels"]["inapp"]["enabled"])

    def test_comments_were_imported(self):
        self.assertTrue(ProjectDiscussion.objects.filter(title__startswith="Commentaires · ").exists())


class AccessTests(Base):
    def test_pilot_cannot_read_discussions(self):
        d = self.discussion(message="Contenu confidentiel du client").json()
        c = self.as_user(self.pilot)
        self.assertEqual(c.get("/api/v1/discussions").status_code, 403)
        self.assertEqual(c.get(f"/api/v1/discussions/{d['id']}/messages").status_code, 403)
        self.assertEqual(c.get(f"/api/v1/discussions/{d['id']}").status_code, 403)

    def test_tenant_isolation(self):
        d = self.discussion(message="Interne").json()
        c = self.as_user(self.admin2)
        self.assertEqual(c.get("/api/v1/discussions").json(), [])
        self.assertEqual(c.get(f"/api/v1/discussions/{d['id']}/messages").status_code, 404)
        self.assertEqual(c.post(f"/api/v1/discussions/{d['id']}/messages", {"body": "intrus"}, format="json").status_code, 404)
        self.assertEqual(self.discussion(self.admin2).status_code, 404)

    def test_out_of_scope_user_does_not_see_project_discussion(self):
        d = self.discussion().json()
        self.assertEqual(self.as_user(self.nb).get(f"/api/v1/discussions/{d['id']}").status_code, 404)

    def test_private_teams_chat_visible_to_participants_only(self):
        d = self.discussion(destination="teams", teamsKind="group", participants=[self.ib.pk, self.tl.pk]).json()
        self.assertEqual(self.as_user(self.tl).get(f"/api/v1/discussions/{d['id']}").status_code, 200)
        self.assertEqual(self.as_user(self.kd).get(f"/api/v1/discussions/{d['id']}").status_code, 404)  # voit le projet, pas la conversation
        self.assertEqual(self.as_user(self.admin).get(f"/api/v1/discussions/{d['id']}").status_code, 404)


class TeamsPublishTests(Base):
    def test_create_group_chat_with_structured_message_and_subscription(self):
        r = self.discussion(destination="both", teamsKind="group", participants=[self.ib.pk, self.tl.pk], message="Lancement")
        self.assertEqual(r.status_code, 201, r.content)
        d = ProjectDiscussion.objects.get(pk=r.json()["id"])
        create = self.fake.find("POST", "/chats")[0]
        self.assertEqual(create["body"]["chatType"], "group")
        self.assertEqual(len(create["body"]["members"]), 3)
        self.assertTrue(any(self.tl.email in m["user@odata.bind"] for m in create["body"]["members"]))  # sans compte relié : e-mail
        first = self.fake.find("POST", "/chats/19%3Achat%40thread.v2/messages")[0]["body"]["body"]["content"]
        self.assertIn("NDL-MIG", first)
        self.assertIn(f"{BASE}/#collaboration/{d.pk}", first)
        self.assertIn("Lancement", first)
        self.assertEqual(d.messages.get(body="Lancement").publication_status, "published")
        sub = GraphSubscription.objects.get(discussion=d)
        body = self.fake.find("POST", "/subscriptions")[0]["body"]
        self.assertEqual(body["notificationUrl"], f"{BASE}/api/v1/teams/webhook")
        self.assertEqual(body["lifecycleNotificationUrl"], f"{BASE}/api/v1/teams/lifecycle")
        self.assertNotEqual(sub.client_state_hash, body["clientState"])  # seule l'empreinte est stockée
        self.assertEqual(sub.client_state_hash, GraphSubscription.hash_state(body["clientState"]))

    def test_one_on_one_needs_two_people(self):
        self.assertEqual(self.discussion(destination="teams", teamsKind="oneOnOne").status_code, 400)
        r = self.discussion(destination="teams", teamsKind="oneOnOne", participants=[self.ib.pk])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.fake.find("POST", "/chats")[0]["body"]["chatType"], "oneOnOne")

    def test_channel_discussion_posts_replies_in_thread(self):
        r = self.discussion(destination="teams", teamsKind="channel", teamId="team-1", channelId="19:chan")
        self.assertEqual(r.status_code, 201, r.content)
        d = ProjectDiscussion.objects.get(pk=r.json()["id"])
        self.assertEqual(d.teams_root_message_id, "m1")
        self.as_user(self.sm).post(f"/api/v1/discussions/{d.pk}/messages", {"body": "Suite"}, format="json")
        self.assertTrue(self.fake.find("POST", "/messages/m1/replies"))
        self.assertFalse(self.fake.find("POST", "/chats"))  # canal ≠ conversation : aucune conversation créée

    def test_graph_error_marks_failed_then_retry(self):
        d = self.discussion(destination="teams", teamsKind="oneOnOne", participants=[self.ib.pk]).json()
        self.fake.fail["/chats/19%3Achat%40thread.v2/messages"] = (403, {"error": {"code": "Forbidden"}})
        m = self.as_user(self.sm).post(f"/api/v1/discussions/{d['id']}/messages", {"body": "Test"}, format="json").json()
        self.assertEqual(m["publicationStatus"], "failed")
        self.assertIn("permission", m["publicationError"])
        self.assertTrue(m["canRetry"])
        self.fake.fail.clear()
        r = self.as_user(self.sm).post(f"/api/v1/messages/{m['id']}/retry")
        self.assertEqual(r.json()["publicationStatus"], "published")

    def test_unlinked_user_gets_clear_error(self):
        r = self.discussion(self.tl, destination="teams", teamsKind="oneOnOne", participants=[self.sm.pk])
        self.assertEqual((r.status_code, r.json()["code"]), (409, "TEAMS_NOT_LINKED"))
        self.assertFalse(ProjectDiscussion.objects.filter(created_by=self.tl, destination="teams").exists())  # annulé

    def test_mentions_use_teams_ids_when_linked(self):
        d = self.discussion(destination="teams", teamsKind="oneOnOne", participants=[self.ib.pk]).json()
        self.as_user(self.sm).post(f"/api/v1/discussions/{d['id']}/messages", {"body": "Regarde", "mentions": [self.ib.pk]}, format="json")
        sent = self.fake.find("POST", "/messages")[-1]["body"]
        self.assertEqual(sent["mentions"][0]["mentioned"]["user"]["id"], "ms-ib")
        self.assertIn('<at id="0">', sent["body"]["content"])


class TokenTests(Base):
    def test_expired_token_is_refreshed_and_stays_encrypted(self):
        token = MicrosoftToken.objects.get(user=self.sm)
        token.expires_at = timezone.now() - timedelta(minutes=1)
        token.save()
        self.discussion(destination="teams", teamsKind="oneOnOne", participants=[self.ib.pk])
        refresh = self.fake.find("POST", "oauth2/v2.0/token")[0]
        self.assertEqual(refresh["form"]["grant_type"], "refresh_token")
        token.refresh_from_db()
        self.assertGreater(token.expires_at, timezone.now())
        self.assertNotIn("rt-new", token.refresh_token_enc)
        self.assertEqual(token.refresh_token, "rt-new")

    def test_revoked_consent_requires_reconnection(self):
        token = MicrosoftToken.objects.get(user=self.sm)
        token.expires_at = timezone.now() - timedelta(minutes=1)
        token.save()
        self.fake.fail["oauth2/v2.0/token"] = (400, {"error": "invalid_grant"})
        r = self.discussion(destination="teams", teamsKind="oneOnOne", participants=[self.ib.pk])
        self.assertEqual((r.status_code, r.json()["code"]), (409, "TEAMS_RECONSENT_REQUIRED"))
        token.refresh_from_db()
        self.assertIsNotNone(token.revoked_at)
        status = self.as_user(self.sm).get("/api/v1/teams/connection-status").json()
        self.assertEqual((status["linked"], status["needsReconsent"]), (False, True))

    def test_oauth_flow_with_state_and_pkce(self):
        MicrosoftToken.objects.filter(user=self.sm).delete()
        c = APIClient()
        c.force_login(User.objects.get(pk=self.sm.pk))
        url = c.post("/api/v1/teams/oauth/start").json()["url"]
        q = parse_qs(urlparse(url).query)
        self.assertEqual(q["code_challenge_method"], ["S256"])
        self.assertIn("ChatMessage.Send", q["scope"][0])
        self.assertNotIn("Channel.Create", q["scope"][0])  # création de canal non activée : non demandée
        bad = c.get("/api/v1/teams/oauth/callback", {"code": "c", "state": "forged"})
        self.assertIn("teams=error", bad["Location"])
        url = c.post("/api/v1/teams/oauth/start").json()["url"]
        state = parse_qs(urlparse(url).query)["state"][0]
        ok = c.get("/api/v1/teams/oauth/callback", {"code": "c", "state": state})
        self.assertTrue(ok["Location"].endswith("#collaboration?teams=linked"))
        token = MicrosoftToken.objects.get(user=self.sm)
        self.assertEqual(token.ms_user_id, "ms-sm")
        exchange = self.fake.find("POST", "oauth2/v2.0/token")[0]["form"]
        self.assertTrue(exchange["code_verifier"])
        # Rejeu du même état : refusé.
        self.assertIn("teams=error", c.get("/api/v1/teams/oauth/callback", {"code": "c", "state": state})["Location"])


class SyncTests(Base):
    def make(self):
        r = self.discussion(destination="both", teamsKind="oneOnOne", participants=[self.ib.pk])
        return ProjectDiscussion.objects.get(pk=r.json()["id"])

    def test_sync_creates_once_ignores_system_and_own_messages(self):
        d = self.make()
        own = self.as_user(self.sm).post(f"/api/v1/discussions/{d.pk}/messages", {"body": "Depuis PCT"}, format="json").json()
        own_id = DiscussionMessage.objects.get(pk=own["id"]).teams_message_id
        self.fake.listing = [
            remote(own_id, "Depuis PCT", "ms-sm", minutes=-1),                     # notre propre message : déjà connu
            remote("t-1", "<p>Réponse <b>Teams</b></p>", "ms-ext", "Client X"),     # nouveau
            remote("t-2", "Ajout de membre", "ms-ext", messageType="systemEventMessage"),
        ]
        self.assertEqual(S.synchronize(d)["created"], 1)
        self.assertEqual(S.synchronize(d)["created"], 0)  # déduplication
        new = d.messages.get(teams_message_id="t-1")
        self.assertEqual((new.body, new.external_author, new.origin), ("Réponse Teams", "Client X", "teams"))
        self.assertEqual(d.messages.filter(teams_message_id=own_id).count(), 1)
        # Modification côté Teams plus récente : reprise, avec historique.
        self.fake.listing = [remote("t-1", "Réponse corrigée", "ms-ext", "Client X", minutes=5)]
        self.assertEqual(S.synchronize(d)["updated"], 1)
        new.refresh_from_db()
        self.assertEqual((new.body, len(new.history)), ("Réponse corrigée", 1))
        # Suppression côté Teams.
        self.fake.listing = [remote("t-1", "", "ms-ext", minutes=6, deletedDateTime=timezone.now().isoformat())]
        self.assertEqual(S.synchronize(d)["deleted"], 1)

    def test_loop_prevention_when_notification_arrives_before_publish_returns(self):
        d = self.make()
        pending = S._create_message(d, self.sm, "Message en vol", status="pending")
        result = S._ingest(d, remote("t-9", "Message en vol", "ms-sm", "E. Navarro"))
        self.assertIsNone(result)
        pending.refresh_from_db()
        self.assertEqual((pending.teams_message_id, pending.publication_status), ("t-9", "published"))
        self.assertEqual(d.messages.filter(body="Message en vol").count(), 1)

    def test_teams_author_with_linked_account_is_mapped(self):
        d = self.make()
        self.fake.listing = [remote("t-3", "Vu", "ms-ib", "S. Mansouri")]
        S.synchronize(d)
        self.assertEqual(d.messages.get(teams_message_id="t-3").author_id, self.ib.pk)


class WebhookTests(Base):
    def setup_sub(self):
        r = self.discussion(destination="both", teamsKind="oneOnOne", participants=[self.ib.pk])
        d = ProjectDiscussion.objects.get(pk=r.json()["id"])
        state = self.fake.find("POST", "/subscriptions")[0]["body"]["clientState"]
        return d, GraphSubscription.objects.get(discussion=d), state

    def test_validation_handshake(self):
        r = APIClient().post("/api/v1/teams/webhook?validationToken=abc%20123")
        self.assertEqual((r.status_code, r.content.decode(), r["Content-Type"]), (200, "abc 123", "text/plain"))
        r = APIClient().post("/api/v1/teams/lifecycle?validationToken=xyz")
        self.assertEqual(r.content.decode(), "xyz")

    def test_notification_is_authenticated_processed_once(self):
        d, sub, state = self.setup_sub()
        self.fake.items["t-5"] = remote("t-5", "Par webhook", "ms-ext", "Partenaire")
        note = {"value": [{"subscriptionId": sub.subscription_id, "clientState": state, "changeType": "created",
                           "resource": "chats('19:chat@thread.v2')/messages('t-5')",
                           "resourceData": {"@odata.etag": "1"}}]}
        forged = {"value": [{**note["value"][0], "clientState": "faux"}]}
        self.assertEqual(APIClient().post("/api/v1/teams/webhook", forged, format="json").status_code, 202)
        self.assertFalse(d.messages.filter(teams_message_id="t-5").exists())
        self.assertEqual(APIClient().post("/api/v1/teams/webhook", note, format="json").status_code, 202)
        self.assertEqual(d.messages.filter(teams_message_id="t-5").count(), 1)
        gets = len(self.fake.find("GET", "/messages/t-5"))
        APIClient().post("/api/v1/teams/webhook", note, format="json")  # rejeu
        self.assertEqual(len(self.fake.find("GET", "/messages/t-5")), gets)
        self.assertEqual(GraphNotificationReceipt.objects.count(), 1)

    def test_lifecycle_and_renewal(self):
        d, sub, state = self.setup_sub()
        payload = {"value": [{"subscriptionId": sub.subscription_id, "clientState": state, "lifecycleEvent": "reauthorizationRequired"}]}
        APIClient().post("/api/v1/teams/lifecycle", payload, format="json")
        self.assertTrue(self.fake.find("PATCH", "/subscriptions/"))
        sub.expires_at = timezone.now() + timedelta(hours=1)
        sub.save()
        self.assertEqual(S.renew_subscriptions()["renewed"], 1)
        sub.refresh_from_db()
        self.assertGreater(sub.expires_at, timezone.now() + timedelta(days=2))

    def test_cron_command_runs(self):
        self.setup_sub()
        call_command("sync_teams", stdout=open("/dev/null", "w"))
        call_command("process_calendar", stdout=open("/dev/null", "w"))


@override_settings(PUBLIC_BASE_URL="")
class NoPublicUrlTests(Base):
    def test_without_public_url_no_subscription_is_created(self):
        r = self.discussion(destination="teams", teamsKind="oneOnOne", participants=[self.ib.pk])
        self.assertEqual(r.status_code, 201)
        self.assertFalse(self.fake.find("POST", "/subscriptions"))


class AdminTests(Base):
    def test_connector_admin_never_returns_secret(self):
        c = self.as_user(self.admin)
        row = c.get("/api/v1/admin/teams").json()
        self.assertTrue(row["secretSet"])
        self.assertNotIn("super-secret-value-123", str(row))
        r = c.put("/api/v1/admin/teams", {"clientSecret": "nouveau-secret-abcd", "allowChannelCreation": True}, format="json")
        self.assertEqual((r.status_code, r.json()["secretHint"]), (200, "abcd"))
        self.assertIn("Channel.Create", r.json()["scopes"])
        self.assertNotIn("nouveau-secret", ServiceSecret.objects.get(tenant=self.tenant, key="teams_client_secret").ciphertext)
        self.assertEqual(c.put("/api/v1/admin/teams", {"clientId": "pas-un-guid"}, format="json").status_code, 400)
        self.assertEqual(self.as_user(self.sm).get("/api/v1/admin/teams").status_code, 403)
        self.assertEqual(self.as_user(self.pilot).get("/api/v1/admin/teams").status_code, 403)

    def test_credentials_check(self):
        c = self.as_user(self.admin)
        self.assertTrue(c.post("/api/v1/admin/teams/check").json()["ok"])
        self.fake.fail["oauth2/v2.0/token"] = (401, {"error": "invalid_client"})
        r = c.post("/api/v1/admin/teams/check").json()
        self.assertEqual((r["ok"], r["status"]), (False, "error"))

    def test_disabled_connector_blocks_teams(self):
        TeamsConnector.objects.filter(tenant=self.tenant).update(enabled=False)
        r = self.discussion(destination="teams", teamsKind="oneOnOne", participants=[self.ib.pk])
        self.assertEqual((r.status_code, r.json()["code"]), (409, "TEAMS_NOT_CONFIGURED"))
        self.assertEqual(self.discussion().status_code, 201)  # l'interne reste disponible

    def test_channel_creation_needs_flag_and_approve(self):
        r = self.as_user(self.sm).post("/api/v1/teams/teams/team-1/channels", {"name": "NDL-MIG"}, format="json")
        self.assertEqual(r.status_code, 409)  # création de canal non activée
        self.assertEqual(self.as_user(self.ib).post("/api/v1/teams/teams/team-1/channels", {"name": "x"}, format="json").status_code, 403)


class ProjectFixture(Base):
    def test_project_exists(self):
        self.assertTrue(Project.objects.filter(pk="p1").exists())
