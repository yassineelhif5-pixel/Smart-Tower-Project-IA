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
import uuid

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
    module_features = models.JSONField(null=True, blank=True, help_text="Modules limités pour une activation par voucher ; null = modules de la version d'offre")
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
INSTALLED = "INSTALLED"
REQUEST_STATUSES = [(s, s) for s in (DRAFT, SUBMITTED, UNDER_REVIEW, INFO_REQUIRED, APPROVED, PARTIALLY_APPROVED,
                                     REJECTED, CANCELLED_R, FULFILLED, INSTALLED)]


class OfferVoucher(models.Model):
    """Code d'activation à usage unique. Seule son empreinte est conservée en base."""

    batch_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    offer_version = models.ForeignKey(OfferVersion, on_delete=models.PROTECT, related_name="vouchers")
    features = models.JSONField(null=True, blank=True, help_text="Sélection de modules propre à ce code ; null = modules de l'offre")
    code_hash = models.CharField(max_length=64, unique=True)
    code_hint = models.CharField(max_length=8)
    target_tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, null=True, blank=True, related_name="offer_vouchers")
    request = models.ForeignKey("licensing.LicenseRequest", on_delete=models.SET_NULL, null=True, blank=True, related_name="vouchers")
    created_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, related_name="created_offer_vouchers")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    redeemed_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="redeemed_offer_vouchers")
    redeemed_tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, null=True, blank=True, related_name="redeemed_offer_vouchers")
    redeemed_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="revoked_offer_vouchers")
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "id"]


class MaintenanceEntitlement(models.Model):
    tenant = models.OneToOneField("tenants.Tenant", on_delete=models.CASCADE, related_name="maintenance_entitlement")
    enabled = models.BooleanField(default=False)
    plan = models.CharField(max_length=80, default="Maintenance Control Tower")
    starts_at = models.DateField(null=True, blank=True)
    ends_at = models.DateField(null=True, blank=True)
    assigned_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, related_name="maintenance_grants")
    updated_at = models.DateTimeField(auto_now=True)


class SupportRequest(models.Model):
    STATUSES = [("new", "Nouvelle"), ("triaged", "À traiter"), ("in_progress", "En cours"), ("resolved", "Résolue"), ("closed", "Clôturée")]
    CATEGORIES = [("maintenance", "Maintenance"), ("assistance", "Assistance"), ("incident", "Incident"), ("question", "Question")]
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="support_requests")
    requester = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, related_name="support_requests")
    title = models.CharField(max_length=180)
    description = models.TextField(max_length=10000)
    category = models.CharField(max_length=16, choices=CATEGORIES, default="assistance")
    status = models.CharField(max_length=16, choices=STATUSES, default="new")
    assigned_to = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_support_requests")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    ai_status = models.CharField(max_length=16, default="pending", choices=[("pending", "En attente"), ("ready", "Analyse prête"), ("unavailable", "IA non configurée"), ("error", "Erreur IA")])
    ai_analysis = models.TextField(blank=True)
    ai_reply = models.TextField(blank=True)
    ai_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class SupportAIConfig(models.Model):
    """Configuration globale de THOR. La clé du fournisseur reste chiffrée au repos."""
    enabled = models.BooleanField(default=False)
    model = models.CharField(max_length=120, default="gpt-4o-mini")
    token_limit = models.PositiveIntegerField(default=800)
    api_key_ciphertext = models.TextField(blank=True)
    api_key_hint = models.CharField(max_length=4, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def current(cls):
        row, _ = cls.objects.get_or_create(pk=1)
        return row

    def set_api_key(self, value):
        from configuration import crypto
        self.api_key_ciphertext = crypto.encrypt(value) if value else ""
        self.api_key_hint = value[-4:] if len(value) >= 8 else ""

    def get_api_key(self):
        from configuration import crypto
        return crypto.decrypt(self.api_key_ciphertext) if self.api_key_ciphertext else ""


class LicenseRequest(models.Model):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, related_name="license_requests")
    kind = models.CharField(max_length=12, choices=REQUEST_KINDS)
    quantity = models.PositiveIntegerField(null=True, blank=True)
    quantity_granted = models.PositiveIntegerField(null=True, blank=True)
    target_offer = models.ForeignKey(Offer, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    target_version = models.ForeignKey(OfferVersion, on_delete=models.PROTECT, null=True, blank=True, related_name="offer_requests")
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


class Payment(models.Model):
    """Paiement Stripe (Checkout) d'une offre ou d'un lot de licences ; appliqué automatiquement une fois payé."""

    PENDING, PAID, APPLIED, FAILED, EXPIRED, CANCELLED = "pending", "paid", "applied", "failed", "expired", "cancelled"
    STATUSES = [(PENDING, "En attente"), (PAID, "Payé"), (APPLIED, "Payé et appliqué"), (FAILED, "Échec"),
                (EXPIRED, "Expiré"), (CANCELLED, "Abonnement résilié")]
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, related_name="payments")
    created_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, related_name="+")
    kind = models.CharField(max_length=10, choices=[("offer", "Offre"), ("licenses", "Licences")])
    offer_version = models.ForeignKey(OfferVersion, on_delete=models.PROTECT, null=True, blank=True, related_name="payments")
    license_kind = models.CharField(max_length=10, choices=LICENSE_KINDS, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    unit_amount = models.PositiveIntegerField(help_text="Montant unitaire en centimes")
    amount = models.PositiveIntegerField(help_text="Montant total en centimes")
    currency = models.CharField(max_length=3, default="EUR")
    interval = models.CharField(max_length=10, blank=True, help_text="month, year ou vide (paiement unique)")
    request = models.ForeignKey(LicenseRequest, on_delete=models.SET_NULL, null=True, blank=True, related_name="payments")
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING)
    stripe_session = models.CharField(max_length=255, unique=True, null=True, blank=True)
    stripe_customer = models.CharField(max_length=255, blank=True)
    stripe_subscription = models.CharField(max_length=255, blank=True)
    checkout_url = models.URLField(max_length=1000, blank=True)
    error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
