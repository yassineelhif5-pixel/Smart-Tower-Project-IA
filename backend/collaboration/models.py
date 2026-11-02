"""Discussions de projet et connecteur Microsoft Teams (Microsoft Graph), propres à chaque tenant.

- Le connecteur (une ligne par tenant) décrit l'application Microsoft Entra de l'entreprise : identifiant de
  l'annuaire, identifiant client, fonctionnalités autorisées. Le secret client est dans ServiceSecret
  (« teams_client_secret »), chiffré, jamais renvoyé.
- Chaque utilisateur autorise lui-même PCT à agir en son nom (permissions déléguées minimales) : ses jetons
  sont chiffrés au repos (MicrosoftToken). Microsoft n'autorise l'envoi de messages dans une conversation ou
  un canal qu'au nom d'un utilisateur.
- Une discussion est rattachée à un projet (et éventuellement à une action) ; ses messages sont internes,
  publiés dans Teams, ou les deux.
"""
import hashlib

from django.conf import settings
from django.db import models
from django.db.models import Q

from configuration import crypto
from tenants.models import TenantOwned

USER = settings.AUTH_USER_MODEL


class TeamsConnector(TenantOwned):
    STATUSES = [("not_configured", "Non configuré"), ("configured", "Configuré"), ("ok", "Vérifié"), ("error", "En erreur")]

    directory_id = models.CharField(max_length=64, blank=True, help_text="Identifiant de l'annuaire Microsoft Entra (tenant Microsoft)")
    client_id = models.CharField(max_length=64, blank=True, help_text="Identifiant de l'application (client)")
    enabled = models.BooleanField(default=False)
    allow_channels = models.BooleanField(default=False, help_text="Publier dans des canaux d'équipe")
    allow_channel_creation = models.BooleanField(default=False, help_text="Créer des canaux (permission supplémentaire)")
    allow_edit_in_teams = models.BooleanField(default=False, help_text="Répercuter modifications et suppressions dans Teams")
    status = models.CharField(max_length=16, choices=STATUSES, default="not_configured")
    last_check_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True)
    secret_expires_on = models.DateField(null=True, blank=True, help_text="Date d'expiration du secret client (rappel)")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant"], name="uniq_teams_connector")]


class MicrosoftToken(TenantOwned):
    """Autorisation déléguée d'un utilisateur. Jetons chiffrés (Fernet) ; jamais renvoyés au navigateur."""

    tenant_source = "user"
    user = models.OneToOneField(USER, on_delete=models.CASCADE, related_name="microsoft_token")
    ms_user_id = models.CharField(max_length=64, blank=True)
    ms_display_name = models.CharField(max_length=200, blank=True)
    ms_upn = models.CharField(max_length=254, blank=True)
    access_token_enc = models.TextField()
    refresh_token_enc = models.TextField(blank=True)
    expires_at = models.DateTimeField()
    scopes = models.TextField(blank=True, help_text="Permissions accordées par Microsoft")
    consented_at = models.DateTimeField(auto_now_add=True)
    refreshed_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    @property
    def access_token(self):
        return crypto.decrypt(self.access_token_enc)

    @property
    def refresh_token(self):
        return crypto.decrypt(self.refresh_token_enc) if self.refresh_token_enc else ""

    def store(self, access, refresh, expires_at, scopes=None):
        self.access_token_enc = crypto.encrypt(access)
        if refresh:
            self.refresh_token_enc = crypto.encrypt(refresh)
        self.expires_at = expires_at
        if scopes is not None:
            self.scopes = scopes
        self.revoked_at = None


DESTINATIONS = [("internal", "Interne PCT"), ("teams", "Microsoft Teams"), ("both", "PCT et Teams")]
TEAMS_KINDS = [("none", "Aucune"), ("oneOnOne", "Conversation individuelle"), ("group", "Conversation de groupe"),
               ("channel", "Canal d'équipe")]


class ProjectDiscussion(TenantOwned):
    tenant_source = ["project", "action", "created_by"]
    STATUSES = [("active", "Active"), ("archived", "Archivée"), ("error", "En erreur")]

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="discussions")
    action = models.ForeignKey("projects.Action", on_delete=models.CASCADE, null=True, blank=True, related_name="discussions")
    title = models.CharField(max_length=200)
    destination = models.CharField(max_length=10, choices=DESTINATIONS, default="internal")
    teams_kind = models.CharField(max_length=10, choices=TEAMS_KINDS, default="none")
    teams_chat_id = models.CharField(max_length=200, blank=True)
    teams_team_id = models.CharField(max_length=64, blank=True)
    teams_channel_id = models.CharField(max_length=200, blank=True)
    teams_root_message_id = models.CharField(max_length=64, blank=True, help_text="Fil du canal (message initial)")
    teams_web_url = models.URLField(max_length=1000, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default="active")
    last_error = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-last_message_at", "-id"]
        indexes = [models.Index(fields=["tenant", "project"])]

    def __str__(self):
        return self.title

    @property
    def uses_teams(self):
        return self.destination in ("teams", "both")

    @property
    def is_private(self):
        """Conversation individuelle ou de groupe : visible des seuls participants."""
        return self.teams_kind in ("oneOnOne", "group")


class DiscussionParticipant(TenantOwned):
    tenant_source = ["discussion", "user"]

    discussion = models.ForeignKey(ProjectDiscussion, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="discussion_participations")
    role = models.CharField(max_length=10, choices=[("owner", "Créateur"), ("member", "Membre")], default="member")
    joined_at = models.DateTimeField(auto_now_add=True)
    last_read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["discussion", "user"], name="uniq_discussion_user")]


PUBLICATION = [("internal", "Interne"), ("pending", "En cours d'envoi"), ("published", "Publié dans Teams"),
               ("failed", "Échec de publication")]


class DiscussionMessage(TenantOwned):
    tenant_source = ["discussion", "author"]

    discussion = models.ForeignKey(ProjectDiscussion, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    external_author = models.CharField(max_length=200, blank=True, help_text="Auteur Teams sans compte PCT rattaché")
    kind = models.CharField(max_length=10, choices=[("message", "Message"), ("system", "Système")], default="message")
    body = models.TextField()
    body_hash = models.CharField(max_length=64, blank=True)
    parent = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="replies")
    mentions = models.ManyToManyField(USER, blank=True, related_name="discussion_mentions")
    attachments = models.ManyToManyField("projects.Document", blank=True, related_name="discussion_messages")
    origin = models.CharField(max_length=6, choices=[("pct", "PCT"), ("teams", "Teams")], default="pct")
    publication_status = models.CharField(max_length=10, choices=PUBLICATION, default="internal")
    publication_error = models.CharField(max_length=300, blank=True)
    teams_message_id = models.CharField(max_length=64, blank=True)
    teams_modified_at = models.DateTimeField(null=True, blank=True)
    client_key = models.CharField(max_length=64, blank=True, help_text="Clé d'idempotence fournie par le navigateur")
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    history = models.JSONField(default=list, blank=True, help_text="Versions précédentes [{at, body}]")

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["discussion", "teams_message_id"], condition=~Q(teams_message_id=""),
                                    name="uniq_discussion_teams_message"),
            models.UniqueConstraint(fields=["discussion", "author", "client_key"], condition=~Q(client_key=""),
                                    name="uniq_message_client_key"),
        ]

    @staticmethod
    def hash_body(text):
        return hashlib.sha256(" ".join((text or "").split()).encode()).hexdigest()


class GraphSubscription(TenantOwned):
    """Abonnement aux notifications de modification Microsoft Graph pour une discussion Teams."""

    tenant_source = ["discussion", "owner"]
    discussion = models.ForeignKey(ProjectDiscussion, on_delete=models.CASCADE, related_name="subscriptions")
    owner = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="+", help_text="Compte dont l'autorisation sert à l'abonnement")
    subscription_id = models.CharField(max_length=64, unique=True)
    resource = models.CharField(max_length=400)
    client_state_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    status = models.CharField(max_length=10, choices=[("active", "Actif"), ("removed", "Supprimé"), ("error", "En erreur")],
                              default="active")
    last_error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    renewed_at = models.DateTimeField(null=True, blank=True)

    @staticmethod
    def hash_state(raw):
        return hashlib.sha256(raw.encode()).hexdigest()


class GraphNotificationReceipt(models.Model):
    """Notification déjà traitée : déduplication et protection contre le rejeu (purgée après 3 jours)."""

    key = models.CharField(max_length=64, unique=True)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, null=True, related_name="+")
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
