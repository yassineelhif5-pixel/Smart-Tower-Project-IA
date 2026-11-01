"""Tenants : un tenant par entreprise cliente de la plateforme SaaS.

Toutes les données métier et de configuration portent une colonne `tenant`. Le tenant d'une requête
est toujours déduit côté serveur de l'utilisateur connecté (jamais d'une valeur envoyée par le navigateur).
Voir MULTI_TENANT_ARCHITECTURE.md et TENANT_ISOLATION.md.
"""
from django.conf import settings
from django.db import models

DEFAULT_TENANT_SLUG = "demo-esn"

ACTIVE, SUSPENDED, DISABLED, ARCHIVED = "active", "suspended", "disabled", "archived"
STATUSES = [
    (ACTIVE, "Actif"),
    (SUSPENDED, "Suspendu"),        # accès bloqué temporairement (impayé, incident…), données conservées
    (DISABLED, "Désactivé"),        # accès bloqué durablement, données conservées
    (ARCHIVED, "Archivé"),          # client parti, données conservées en lecture par la plateforme seulement
]
# Changements de statut autorisés (le super administrateur ne peut pas sauter d'archivé à actif sans réactivation).
TRANSITIONS = {
    ACTIVE: {SUSPENDED, DISABLED, ARCHIVED},
    SUSPENDED: {ACTIVE, DISABLED, ARCHIVED},
    DISABLED: {ACTIVE, ARCHIVED},
    ARCHIVED: {DISABLED},
}


class Tenant(models.Model):
    slug = models.SlugField(max_length=50, unique=True, help_text="Identifiant court, ex. « demo-esn »")
    name = models.CharField(max_length=120)
    status = models.CharField(max_length=10, choices=STATUSES, default=ACTIVE)
    status_reason = models.CharField(max_length=300, blank=True)
    status_changed_at = models.DateTimeField(null=True, blank=True)
    language = models.CharField(max_length=5, default="fr", help_text="Langue par défaut du tenant")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def is_active(self):
        return self.status == ACTIVE


class TenantOwned(models.Model):
    """Base des modèles rattachés à un tenant.

    `tenant_source` nomme la relation dont le tenant est hérité (ex. "project") : à l'enregistrement, le
    tenant est repris de ce parent s'il manque, et un parent d'un autre tenant est refusé. Les créations
    en masse (bulk_create) contournent save() : elles doivent fixer le tenant explicitement.
    """

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, related_name="+")
    tenant_source = None

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        sources = self.tenant_source if isinstance(self.tenant_source, (list, tuple)) else [self.tenant_source]
        for name in filter(None, sources):
            parent = getattr(self, name, None)
            parent_tenant = getattr(parent, "tenant_id", None) if parent is not None else None
            if parent_tenant is None:
                continue
            if self.tenant_id is None:
                self.tenant_id = parent_tenant
            elif self.tenant_id != parent_tenant:
                raise CrossTenantError(f"{type(self).__name__} : {name} appartient à un autre tenant.")
        super().save(*args, **kwargs)


class CrossTenantError(ValueError):
    """Tentative de relier deux objets de tenants différents."""
