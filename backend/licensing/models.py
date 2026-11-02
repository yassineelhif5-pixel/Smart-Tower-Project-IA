"""Gestion commerciale et technique des licences (phases 4 et 5).

Distinctions du cahier des charges :
- Offer / OfferVersion : offre commerciale et ses versions (prix, durée, quotas, fonctionnalités). Une version
  utilisée par un abonnement n'est plus modifiable : une évolution crée une nouvelle version.
- Contract : engagement contractuel d'une entreprise.
- Subscription : souscription d'un tenant à une version d'offre, sur une période.
- LicenseAllocation : mouvements du stock attribué au tenant par le Pilote (historique, jamais modifié).
- License : une licence (nominative ou concurrente) du stock du tenant.
- LicenseAssignment : affectation d'une licence nominative à un utilisateur (historisée).
- ConcurrentSession : session ouverte ; elle occupe une licence concurrente si l'utilisateur n'a pas de licence nominative.
- LicenseRequest / LicenseRequestEvent : demandes du tenant et circuit d'approbation du Pilote.

Aucun tarif ni quota n'est écrit dans le code : tout est en base et modifiable par le Pilote.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

USER = settings.AUTH_USER_MODEL

NAMED, CONCURRENT = "named", "concurrent"
LICENSE_KINDS = [(NAMED, "Nominative"), (CONCURRENT, "Concurrente")]
LICENSE_MODELS = [(NAMED, "Nominatives"), (CONCURRENT, "Concurrentes"), ("mixed", "Nominatives et concurrentes")]


class Offer(models.Model):
    code = models.SlugField(max_length=30, unique=True)
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, help_text="Une offre désactivée ne peut plus être souscrite")
    position = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "name"]

    def __str__(self):
        return self.name

    @property
    def current_version(self):
        return self.versions.filter(is_published=True).order_by("-number").first()


class OfferVersion(models.Model):
    offer = models.ForeignKey(Offer, on_delete=models.PROTECT, related_name="versions")
    number = models.PositiveIntegerField()
    is_published = models.BooleanField(default=False, help_text="Seule une version publiée peut être souscrite")
    price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="Prix par période, hors taxes")
    currency = models.CharField(max_length=3, default="EUR")
    billing_period = models.CharField(max_length=10, choices=[("month", "Mensuel"), ("year", "Annuel"), ("once", "Unique")], default="month")
    duration_days = models.PositiveIntegerField(null=True, blank=True, help_text="Durée d'abonnement par défaut ; vide = sans terme")
    trial_days = models.PositiveIntegerField(default=0, help_text="Période d'essai")
    license_model = models.CharField(max_length=10, choices=LICENSE_MODELS, default="mixed")
    max_users = models.PositiveIntegerField(null=True, blank=True, help_text="Utilisateurs actifs maximum ; vide = illimité")
    named_licenses = models.PositiveIntegerField(default=0, help_text="Stock nominatif attribué à la souscription")
    concurrent_licenses = models.PositiveIntegerField(default=0, help_text="Stock concurrent attribué à la souscription")
    max_sessions_per_user = models.PositiveIntegerField(null=True, blank=True, help_text="Connexions simultanées par utilisateur")
    features = models.JSONField(default=list, blank=True, help_text="Modules accessibles ; liste vide = tous")
    limits = models.JSONField(default=dict, blank=True, help_text="Autres limites configurables")
    conditions = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["offer", "-number"]
        constraints = [models.UniqueConstraint(fields=["offer", "number"], name="uniq_offer_version")]

    def __str__(self):
        return f"{self.offer.name} v{self.number}"

    @property
    def in_use(self):
        return self.subscriptions.exists()


class Contract(models.Model):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, related_name="contracts")
    reference = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=12, choices=[("draft", "Brouillon"), ("active", "Actif"), ("ended", "Terminé"),
                                                      ("terminated", "Résilié")], default="active")
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    terms = models.TextField(blank=True, help_text="Conditions particulières")
    created_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]


TRIAL, ACTIVE, SUSPENDED, EXPIRED, CANCELLED = "trial", "active", "suspended", "expired", "cancelled"
SUB_STATUSES = [(TRIAL, "Essai"), (ACTIVE, "Actif"), (SUSPENDED, "Suspendu"), (EXPIRED, "Expiré"), (CANCELLED, "Résilié")]
CURRENT = (TRIAL, ACTIVE, SUSPENDED)


class Subscription(models.Model):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, related_name="subscriptions")
    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, null=True, blank=True, related_name="subscriptions")
    offer_version = models.ForeignKey(OfferVersion, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=10, choices=SUB_STATUSES, default=ACTIVE)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True, help_text="Vide = sans terme")
    trial_end = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-start_date", "-id"]
        constraints = [models.UniqueConstraint(fields=["tenant"], condition=Q(status__in=CURRENT), name="one_current_subscription")]


class LicenseAllocation(models.Model):
    """Mouvement du stock d'un tenant (+ attribution, − retrait). Historique : jamais modifié ni supprimé."""

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, related_name="license_allocations")
    subscription = models.ForeignKey(Subscription, on_delete=models.PROTECT, null=True, blank=True, related_name="allocations")
    kind = models.CharField(max_length=10, choices=LICENSE_KINDS)
    delta = models.IntegerField()
    reason = models.CharField(max_length=300)
    request = models.ForeignKey("licensing.LicenseRequest", on_delete=models.PROTECT, null=True, blank=True, related_name="allocations")
    by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, related_name="+")
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at", "-id"]
        constraints = [models.CheckConstraint(condition=~Q(delta=0), name="allocation_not_zero")]


AVAILABLE, ASSIGNED, IN_USE, REVOKED = "available", "assigned", "in_use", "revoked"
LICENSE_STATUSES = [(AVAILABLE, "Disponible"), (ASSIGNED, "Affectée"), (IN_USE, "Occupée"), (REVOKED, "Retirée")]


class License(models.Model):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, related_name="licenses")
    number = models.CharField(max_length=40, unique=True)
    kind = models.CharField(max_length=10, choices=LICENSE_KINDS)
    status = models.CharField(max_length=10, choices=LICENSE_STATUSES, default=AVAILABLE)
    allocation = models.ForeignKey(LicenseAllocation, on_delete=models.PROTECT, related_name="licenses")
    revoked_by_allocation = models.ForeignKey(LicenseAllocation, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["number"]
        indexes = [models.Index(fields=["tenant", "kind", "status"])]


class LicenseAssignment(models.Model):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, related_name="+")
    license = models.ForeignKey(License, on_delete=models.PROTECT, related_name="assignments")
    user = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="license_assignments")
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, related_name="+")
    released_at = models.DateTimeField(null=True, blank=True)
    released_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    release_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-assigned_at"]
        constraints = [
            # Une licence n'a qu'un titulaire à la fois, et un utilisateur qu'une licence nominative.
            models.UniqueConstraint(fields=["license"], condition=Q(released_at__isnull=True), name="one_holder_per_license"),
            models.UniqueConstraint(fields=["user"], condition=Q(released_at__isnull=True), name="one_named_license_per_user"),
        ]


class ConcurrentSession(models.Model):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, related_name="+")
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="license_sessions")
    license = models.ForeignKey(License, on_delete=models.PROTECT, null=True, blank=True, related_name="sessions",
                                help_text="Licence concurrente occupée ; vide si l'utilisateur a une licence nominative")
    session_key = models.CharField(max_length=64, db_index=True)
    started_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=20, blank=True, choices=[
        ("logout", "Déconnexion"), ("expired", "Expiration"), ("revoked", "Révoquée"), ("replaced", "Remplacée")])

    class Meta:
        ordering = ["-started_at"]
        constraints = [models.UniqueConstraint(fields=["license"], condition=Q(ended_at__isnull=True), name="one_session_per_concurrent_license")]


REQUEST_KINDS = [("named", "Licences nominatives supplémentaires"), ("concurrent", "Licences concurrentes supplémentaires"),
                 ("quota", "Augmentation de quota"), ("offer", "Évolution d'offre"), ("option", "Option contractuelle")]
DRAFT, SUBMITTED, UNDER_REVIEW, INFO_REQUIRED = "DRAFT", "SUBMITTED", "UNDER_REVIEW", "ADDITIONAL_INFORMATION_REQUIRED"
APPROVED, PARTIALLY_APPROVED, REJECTED, CANCELLED_R, FULFILLED = "APPROVED", "PARTIALLY_APPROVED", "REJECTED", "CANCELLED", "FULFILLED"
REQUEST_STATUSES = [(s, s) for s in (DRAFT, SUBMITTED, UNDER_REVIEW, INFO_REQUIRED, APPROVED, PARTIALLY_APPROVED,
                                     REJECTED, CANCELLED_R, FULFILLED)]


class LicenseRequest(models.Model):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, related_name="license_requests")
    kind = models.CharField(max_length=12, choices=REQUEST_KINDS)
    quantity = models.PositiveIntegerField(null=True, blank=True)
    quantity_granted = models.PositiveIntegerField(null=True, blank=True)
    target_offer = models.ForeignKey(Offer, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    justification = models.TextField(blank=True)
    status = models.CharField(max_length=32, choices=REQUEST_STATUSES, default=DRAFT)
    created_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    fulfilled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class LicenseRequestEvent(models.Model):
    """Historique d'une demande : changements de statut et commentaires (Pilote ou tenant)."""

    request = models.ForeignKey(LicenseRequest, on_delete=models.CASCADE, related_name="events")
    at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, related_name="+")
    from_status = models.CharField(max_length=32, blank=True)
    to_status = models.CharField(max_length=32, blank=True)
    comment = models.TextField(blank=True)

    class Meta:
        ordering = ["at", "id"]
