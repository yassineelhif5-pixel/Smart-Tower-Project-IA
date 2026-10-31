import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from . import crypto

# Secrets que le serveur sait utiliser aujourd'hui. Un nouveau connecteur ajoute ici sa clé.
SECRET_CATALOG = {
    "smtp_password": {"label": "Mot de passe SMTP", "used_by": "Notifications · e-mail"},
    "teams_webhook_url": {"label": "URL du webhook Teams", "used_by": "Notifications · Teams"},
    "slack_webhook_url": {"label": "URL du webhook Slack", "used_by": "Notifications · Slack"},
}

CHANNELS = [("inapp", "Dans l'application"), ("email", "E-mail (SMTP)"), ("teams", "Microsoft Teams"), ("slack", "Slack")]
CHANNEL_SECRET = {"email": "smtp_password", "teams": "teams_webhook_url", "slack": "slack_webhook_url"}

# Événements repris de « Préférences de notification » et de la règle R-KD-01 de index.html.
EVENTS = [
    ("action_assigned", "Action assignée"),
    ("action_late", "Action en retard"),
    ("validation_requested", "Validation demandée"),
    ("budget_risk", "Budget en risque"),
    ("risk_critical", "Risque critique"),
    ("comment_mention", "Commentaire et mention"),
    ("document_new", "Nouveau document"),
    ("scope_changed", "Changement de périmètre"),
    ("key_date_reminder", "Rappel des dates clés"),
]

TOKEN_PREFIX = "pct_"


class ServiceSecret(models.Model):
    """Secret chiffré au repos. Jamais renvoyé par l'API : seulement « défini » et ses 4 derniers caractères."""

    key = models.CharField(primary_key=True, max_length=40, choices=[(k, v["label"]) for k, v in SECRET_CATALOG.items()])
    ciphertext = models.TextField()
    hint = models.CharField(max_length=4)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")

    def set_value(self, value):
        self.ciphertext = crypto.encrypt(value)
        self.hint = value[-4:] if len(value) >= 8 else ""

    def get_value(self):
        return crypto.decrypt(self.ciphertext)

    @classmethod
    def value_of(cls, key):
        row = cls.objects.filter(key=key).first()
        return row.get_value() if row else None


class ApiToken(models.Model):
    """Jeton d'accès pour une application tierce. Agit avec les droits de l'utilisateur rattaché.

    Seule l'empreinte SHA-256 est stockée : le jeton n'est affiché qu'une fois, à la création.
    """

    name = models.CharField(max_length=120)
    prefix = models.CharField(max_length=12)
    token_hash = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_tokens")
    read_only = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @staticmethod
    def hash(raw):
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def issue(cls, **fields):
        raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
        token = cls.objects.create(prefix=raw[:12], token_hash=cls.hash(raw), **fields)
        return token, raw

    @property
    def is_valid(self):
        return self.revoked_at is None and (self.expires_at is None or self.expires_at > timezone.now())


class ApiRequestLog(models.Model):
    """Journal des appels /api/ (sans corps de requête, sans paramètres, sans adresse IP)."""

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=300)
    status = models.PositiveSmallIntegerField()
    duration_ms = models.FloatField()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    token = models.ForeignKey(ApiToken, on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        ordering = ["-at"]


class NotificationChannel(models.Model):
    """Canal d'envoi. Les paramètres non secrets sont ici ; le secret est dans ServiceSecret (CHANNEL_SECRET)."""

    kind = models.CharField(primary_key=True, max_length=10, choices=CHANNELS)
    enabled = models.BooleanField(default=False)
    settings = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class NotificationRule(models.Model):
    event = models.CharField(max_length=30, choices=EVENTS)
    channel = models.ForeignKey(NotificationChannel, on_delete=models.CASCADE, related_name="rules")
    enabled = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["event", "channel"], name="uniq_event_channel")]


class Notification(models.Model):
    """Notification dans l'application (canal « inapp »)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    event = models.CharField(max_length=30, choices=EVENTS)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class AuditEvent(models.Model):
    """Journal d'audit : mêmes colonnes que AUDIT dans index.html (date, auteur, objet, événement, avant, après, trace)."""

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    entity = models.CharField(max_length=200)
    event = models.CharField(max_length=120)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    trace = models.CharField(max_length=16)

    class Meta:
        ordering = ["-at"]
