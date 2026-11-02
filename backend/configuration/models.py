import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from tenants.models import TenantOwned

from . import crypto

# Secrets que le serveur sait utiliser aujourd'hui. Un nouveau connecteur ajoute ici sa clé.
SECRET_CATALOG = {
    "smtp_password": {"label": "Mot de passe SMTP", "used_by": "Notifications · e-mail"},
    "teams_webhook_url": {"label": "URL du webhook Teams", "used_by": "Notifications · Teams"},
    "slack_webhook_url": {"label": "URL du webhook Slack", "used_by": "Notifications · Slack"},
    "teams_client_secret": {"label": "Secret client de l'application Microsoft", "used_by": "Connecteur Microsoft Teams"},
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
    # Calendrier (1.4.0)
    ("date_changed", "Modification de date"),
    ("owner_changed", "Changement de responsable"),
    ("action_blocked", "Action bloquée"),
    ("deadline_reminder", "Rappel avant échéance"),
    ("milestone_reminder", "Rappel de jalon"),
    # Collaboration (1.4.0)
    ("discussion_message", "Nouveau message de discussion"),
    # Méthodologie (1.5.0)
    ("week_start", "Début de semaine"),
    ("weekly_planning", "Rappel de préparation de la semaine"),
    ("sprint_planning", "Rappel de Sprint Planning"),
    ("daily_scrum", "Rappel de Daily Scrum"),
    ("sprint_review", "Rappel de Sprint Review"),
    ("retro_reminder", "Rappel de rétrospective"),
    ("sprint_close", "Rappel de clôture du sprint"),
    ("improvement_overdue", "Action d'amélioration non réalisée"),
]

TOKEN_PREFIX = "pct_"


class ServiceSecret(TenantOwned):
    """Secret chiffré au repos, propre à un tenant. Jamais renvoyé par l'API : seulement « défini » et ses 4 derniers caractères."""

    key = models.CharField(max_length=40, choices=[(k, v["label"]) for k, v in SECRET_CATALOG.items()])
    ciphertext = models.TextField()
    hint = models.CharField(max_length=4)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "key"], name="uniq_tenant_secret")]

    def set_value(self, value):
        self.ciphertext = crypto.encrypt(value)
        self.hint = value[-4:] if len(value) >= 8 else ""

    def get_value(self):
        return crypto.decrypt(self.ciphertext)

    @classmethod
    def value_of(cls, tenant, key):
        row = cls.objects.filter(tenant=tenant, key=key).first()
        return row.get_value() if row else None


class ApiToken(TenantOwned):
    """Jeton d'accès pour une application tierce. Agit avec les droits de l'utilisateur rattaché.

    Seule l'empreinte SHA-256 est stockée : le jeton n'est affiché qu'une fois, à la création.
    """

    name = models.CharField(max_length=120)
    prefix = models.CharField(max_length=12)
    token_hash = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_tokens")
    tenant_source = "user"
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
    # Tenant de l'appelant ; vide pour un appel anonyme ou du super administrateur.
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["-at"]


class NotificationChannel(TenantOwned):
    """Canal d'envoi d'un tenant. Les paramètres non secrets sont ici ; le secret est dans ServiceSecret (CHANNEL_SECRET)."""

    kind = models.CharField(max_length=10, choices=CHANNELS)
    enabled = models.BooleanField(default=False)
    settings = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "kind"], name="uniq_tenant_channel")]


class NotificationRule(TenantOwned):
    """Règle d'un tenant : tel événement est-il envoyé sur tel canal ? `channel` contient le type de canal (inapp, email…)."""

    event = models.CharField(max_length=30, choices=EVENTS)
    channel = models.CharField(max_length=10, choices=CHANNELS, db_column="channel_id")
    enabled = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "event", "channel"], name="uniq_tenant_event_channel")]


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


class AppSetting(TenantOwned):
    """app_settings (Supabase) : réglages métier d'un tenant — cycle de vie, seuils d'alerte, conversion des temps."""

    key = models.CharField(max_length=40)
    value = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]
        constraints = [models.UniqueConstraint(fields=["tenant", "key"], name="uniq_tenant_setting")]


class AuditEvent(models.Model):
    """Journal d'audit. Protégé en base : aucune ligne ne peut être modifiée (déclencheur PostgreSQL) ;
    seule la purge planifiée supprime les lignes plus anciennes que la durée de conservation."""

    """Journal d'audit : mêmes colonnes que AUDIT dans index.html (date, auteur, objet, événement, avant, après, trace)."""

    at = models.DateTimeField(default=timezone.now, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    entity = models.CharField(max_length=200)
    event = models.CharField(max_length=120)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    trace = models.CharField(max_length=16)
    # Tenant concerné ; vide pour un événement de la plateforme (création de tenant, changement de statut…).
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    ip = models.GenericIPAddressField(null=True, blank=True, help_text="Adresse de l'auteur, si connue")
    result = models.CharField(max_length=10, default="success",
                              choices=[("success", "Réussi"), ("failure", "Échec"), ("denied", "Refusé")])

    class Meta:
        ordering = ["-at"]


class UserNotificationPreference(TenantOwned):
    """Préférence d'un utilisateur : recevoir (ou non) tel événement sur tel canal.

    Sans ligne, la règle du tenant s'applique. Une préférence ne peut que restreindre : elle n'active pas un
    canal que l'administrateur du tenant a désactivé.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_preferences")
    tenant_source = "user"
    event = models.CharField(max_length=30, choices=EVENTS)
    channel = models.CharField(max_length=10, choices=CHANNELS)
    enabled = models.BooleanField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "event", "channel"], name="uniq_user_event_channel")]
