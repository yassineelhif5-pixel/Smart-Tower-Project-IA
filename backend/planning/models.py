"""Calendrier intelligent : planification des actions, jalons et réunions.

Pas de doublon avec les actions existantes : un événement lié à une action (`action`, une seule planification
par action) en est le planning. Ses dates, son statut, sa priorité et son responsable sont recopiés sur l'action,
qui reste l'objet métier. Un événement sans action est un jalon, une réunion ou une tâche de planning.

Les dates sont stockées en UTC (`start`, `end`, fin exclusive) avec le fuseau d'origine (`timezone`) : un
événement « journée entière » couvre de minuit à minuit dans ce fuseau.
"""
from django.conf import settings
from django.db import models
from django.db.models import F, Q

from projects.models import ACTION_STATUSES
from tenants.models import TenantOwned

USER = settings.AUTH_USER_MODEL

KINDS = [("action", "Action"), ("milestone", "Jalon"), ("meeting", "Réunion"), ("task", "Tâche")]
STATUSES = ACTION_STATUSES + [("cancelled", "Annulée")]
OPEN_STATUSES = ("todo", "planned", "doing", "review", "blocked")
PRIORITIES = [("low", "Basse"), ("normal", "Normale"), ("high", "Haute"), ("critical", "Critique")]
# Libellés de priorité des actions existantes (index.html) <-> priorité du calendrier.
ACTION_PRIO_TO_EVENT = {"Basse": "low", "Faible": "low", "Normale": "normal", "Moyenne": "normal", "Haute": "high",
                        "Critique": "critical", "Bloquante": "critical"}
EVENT_PRIO_TO_ACTION = {"low": "Basse", "normal": "Normale", "high": "Haute", "critical": "Critique"}


class CalendarEvent(TenantOwned):
    tenant_source = ["project", "action", "created_by"]

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, null=True, blank=True, related_name="calendar_events")
    action = models.OneToOneField("projects.Action", on_delete=models.CASCADE, null=True, blank=True, related_name="calendar_event")
    kind = models.CharField(max_length=10, choices=KINDS, default="task")
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    phase = models.CharField(max_length=60, blank=True)
    start = models.DateTimeField()
    end = models.DateTimeField(help_text="Fin exclusive (UTC)")
    timezone = models.CharField(max_length=64, default="Europe/Paris")
    all_day = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=STATUSES, default="planned")
    priority = models.CharField(max_length=10, choices=PRIORITIES, default="normal")
    progress = models.PositiveSmallIntegerField(default=0)
    created_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    late_notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["start", "id"]
        indexes = [models.Index(fields=["tenant", "start"]), models.Index(fields=["tenant", "end"])]
        constraints = [
            models.CheckConstraint(condition=Q(end__gte=F("start")), name="event_end_after_start"),
            models.CheckConstraint(condition=Q(progress__lte=100), name="event_progress_max_100"),
        ]

    def __str__(self):
        return self.title

    @property
    def is_open(self):
        return self.status in OPEN_STATUSES


ROLES = [("owner", "Responsable"), ("contributor", "Contributeur"), ("reviewer", "Relecteur")]
ASSIGNMENT_STATUSES = [("assigned", "Affecté"), ("accepted", "Accepté"), ("declined", "Refusé"), ("done", "Terminé")]


class CalendarAssignment(TenantOwned):
    tenant_source = ["event", "user"]

    event = models.ForeignKey(CalendarEvent, on_delete=models.CASCADE, related_name="assignments")
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="calendar_assignments")
    role = models.CharField(max_length=12, choices=ROLES, default="contributor")
    estimated_workload = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True, help_text="Heures")
    actual_workload = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True, help_text="Heures")
    assignment_status = models.CharField(max_length=10, choices=ASSIGNMENT_STATUSES, default="assigned")

    class Meta:
        ordering = ["event", "-role", "id"]
        constraints = [
            models.UniqueConstraint(fields=["event", "user"], name="uniq_event_user"),
            models.UniqueConstraint(fields=["event"], condition=Q(role="owner"), name="one_owner_per_event"),
        ]


CHANNEL_CHOICES = [("inapp", "Dans l'application"), ("email", "E-mail"), ("teams", "Microsoft Teams")]
REMINDER_STATUSES = [("pending", "Prévu"), ("sent", "Envoyé"), ("failed", "Échec"), ("cancelled", "Annulé")]
REMINDER_KINDS = [("deadline", "Avant échéance"), ("milestone", "Jalon"), ("custom", "Personnalisé")]


class CalendarReminder(TenantOwned):
    tenant_source = ["event", "user"]

    event = models.ForeignKey(CalendarEvent, on_delete=models.CASCADE, related_name="reminders")
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="calendar_reminders")
    remind_at = models.DateTimeField()
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES, default="inapp")
    kind = models.CharField(max_length=10, choices=REMINDER_KINDS, default="custom")
    status = models.CharField(max_length=10, choices=REMINDER_STATUSES, default="pending")
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["remind_at", "id"]
        indexes = [models.Index(fields=["status", "remind_at"])]


DEPENDENCY_TYPES = [("FS", "Fin → Début"), ("SS", "Début → Début"), ("FF", "Fin → Fin"), ("SF", "Début → Fin")]


class CalendarDependency(TenantOwned):
    tenant_source = ["predecessor", "successor"]

    predecessor = models.ForeignKey(CalendarEvent, on_delete=models.CASCADE, related_name="successor_links")
    successor = models.ForeignKey(CalendarEvent, on_delete=models.CASCADE, related_name="predecessor_links")
    dependency_type = models.CharField(max_length=2, choices=DEPENDENCY_TYPES, default="FS")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["predecessor", "successor"], name="uniq_dependency"),
            models.CheckConstraint(condition=~Q(predecessor=F("successor")), name="dependency_not_self"),
        ]


class CalendarFeedToken(TenantOwned):
    """Abonnement ICS personnel (Outlook, Google Agenda…) : lecture seule, révocable. Seule l'empreinte est stockée."""

    tenant_source = "user"
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="calendar_feed_tokens")
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)


# --------------------------------------------------------------------------- synchronisation externe (préparée)
PROVIDERS = [("outlook", "Microsoft Outlook"), ("m365", "Microsoft 365"), ("google", "Google Agenda")]


class ExternalCalendarLink(TenantOwned):
    """Agenda externe d'un utilisateur (synchronisation bidirectionnelle à venir). Aucun fournisseur n'est encore actif."""

    tenant_source = "user"
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="external_calendars")
    provider = models.CharField(max_length=10, choices=PROVIDERS)
    external_calendar_id = models.CharField(max_length=300)
    sync_token = models.TextField(blank=True, help_text="Jeton de synchronisation incrémentale du fournisseur")
    enabled = models.BooleanField(default=False)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "provider", "external_calendar_id"], name="uniq_external_calendar")]


class ExternalEventMapping(TenantOwned):
    """Correspondance événement PCT <-> événement externe : évite les doublons et détecte les conflits (etag, empreinte)."""

    tenant_source = ["event", "link"]
    event = models.ForeignKey(CalendarEvent, on_delete=models.CASCADE, related_name="external_mappings")
    link = models.ForeignKey(ExternalCalendarLink, on_delete=models.CASCADE, related_name="mappings")
    external_event_id = models.CharField(max_length=300)
    etag = models.CharField(max_length=200, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, help_text="Empreinte du dernier état synchronisé")
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["link", "external_event_id"], name="uniq_external_event"),
            models.UniqueConstraint(fields=["event", "link"], name="uniq_event_link"),
        ]
