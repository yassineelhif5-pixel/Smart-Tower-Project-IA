"""Droits d'administration délégables à l'intérieur d'un tenant (RBAC dynamique, phase 3).

Deux niveaux complémentaires :
- la matrice métier existante (RolePermission : module × consulter/créer/modifier/supprimer/valider) ;
- ce catalogue de droits d'administration (activer, attribuer, libérer, exporter, administrer…), par rôle
  et par tenant, avec des exceptions individuelles par utilisateur.

Les privilèges du Pilote (offres, prix, contrats, stock de licences, approbation des demandes) ne figurent
PAS dans ce catalogue : ils ne peuvent donc jamais être délégués, ni même attribués par erreur. Ils sont
réservés aux vues de la plateforme (permission IsPlatformAdmin).
"""
from django.conf import settings
from django.db import models

from .models import ADMIN_ROLE

# code, domaine, action
CATALOG = [
    ("company.view", "Entreprise", "Consulter"),
    ("users.view", "Utilisateurs", "Consulter"),
    ("users.create", "Utilisateurs", "Créer"),
    ("users.update", "Utilisateurs", "Modifier"),
    ("users.activate", "Utilisateurs", "Activer / désactiver"),
    ("roles.administer", "Rôles et permissions", "Administrer"),
    ("licenses.view", "Licences", "Consulter"),
    ("licenses.assign", "Licences", "Attribuer"),
    ("licenses.release", "Licences", "Libérer"),
    ("sessions.view", "Sessions", "Consulter"),
    ("sessions.revoke", "Sessions", "Révoquer"),
    ("requests.view", "Demandes de licences", "Consulter"),
    ("requests.create", "Demandes de licences", "Créer"),
    ("requests.cancel", "Demandes de licences", "Annuler"),
    ("audit.view", "Journal d'activité", "Consulter"),
    ("audit.export", "Journal d'activité", "Exporter"),
]
CODES = {c for c, _, _ in CATALOG}
# Droits jamais délégables à un autre rôle que l'administrateur : ils permettraient de s'attribuer davantage.
NOT_DELEGABLE = {"roles.administer"}

DEFAULTS = {
    "license_manager": ["company.view", "users.view", "licenses.view", "licenses.assign", "licenses.release",
                        "sessions.view", "requests.view", "requests.create", "requests.cancel"],
    "manager": ["company.view", "users.view"],
    "direction": ["company.view", "users.view", "licenses.view", "requests.view", "audit.view"],
}


class RoleCapability(models.Model):
    """Droit d'administration accordé à un rôle. tenant vide = modèle copié à la création d'un tenant."""

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    role = models.ForeignKey("accounts.Role", on_delete=models.CASCADE, related_name="capabilities")
    code = models.CharField(max_length=40, choices=[(c, f"{d} · {a}") for c, d, a in CATALOG])

    class Meta:
        app_label = "accounts"
        constraints = [
            models.UniqueConstraint(fields=["role", "code"], condition=models.Q(tenant__isnull=True), name="uniq_capability_template"),
            models.UniqueConstraint(fields=["tenant", "role", "code"], condition=models.Q(tenant__isnull=False), name="uniq_tenant_capability"),
        ]


class UserCapability(models.Model):
    """Exception individuelle : accorde (granted=True) ou retire (False) un droit à un utilisateur précis."""

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="capability_overrides")
    code = models.CharField(max_length=40, choices=[(c, f"{d} · {a}") for c, d, a in CATALOG])
    granted = models.BooleanField()
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    granted_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "accounts"
        constraints = [models.UniqueConstraint(fields=["user", "code"], name="uniq_user_capability")]


def has_capability(user, code):
    """Vrai si l'utilisateur dispose du droit d'administration `code` dans son tenant (actif)."""
    if code not in CODES:
        raise ValueError(f"Droit inconnu : {code}")
    if not (user and user.is_authenticated and user.is_active and user.tenant_id and user.tenant.status == "active"):
        return False
    if user.role_id == ADMIN_ROLE:
        return True  # l'administrateur du tenant garde tous les droits : aucun verrouillage possible
    override = UserCapability.objects.filter(user=user, tenant_id=user.tenant_id, code=code).first()
    if override is not None:
        return override.granted and code not in NOT_DELEGABLE
    return RoleCapability.objects.filter(tenant_id=user.tenant_id, role_id=user.role_id, code=code).exists()


def capabilities_of(user):
    return sorted(c for c in CODES if has_capability(user, c))
