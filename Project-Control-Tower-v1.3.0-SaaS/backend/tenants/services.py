"""Opérations du Pilote sur les tenants : création contrôlée et changement de statut, toujours audités."""
import secrets

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from accounts.capabilities import RoleCapability
from accounts.models import ADMIN_ROLE, PLATFORM_ROLE, RolePermission
from configuration import audit
from configuration.models import CHANNELS, EVENTS, NotificationChannel, NotificationRule

from .models import STATUSES, TRANSITIONS, Tenant

FLAGS = ["can_read", "can_create", "can_update", "can_delete", "can_approve"]


class TenantError(ValueError):
    """Refus métier, avec un message lisible par le Pilote."""


def provision(tenant):
    """Donne à un tenant sa matrice des droits (copie du modèle) et ses canaux de notification par défaut."""
    for row in RolePermission.objects.filter(tenant__isnull=True).exclude(role_id=PLATFORM_ROLE):
        RolePermission.objects.get_or_create(role_id=row.role_id, module=row.module, tenant=tenant,
                                             defaults={f: getattr(row, f) for f in FLAGS})
    for row in RoleCapability.objects.filter(tenant__isnull=True):
        RoleCapability.objects.get_or_create(tenant=tenant, role_id=row.role_id, code=row.code)
    for kind, _ in CHANNELS:
        NotificationChannel.objects.get_or_create(tenant=tenant, kind=kind, defaults={"enabled": kind == "inapp"})
        for event, _ in EVENTS:
            NotificationRule.objects.get_or_create(tenant=tenant, event=event, channel=kind,
                                                   defaults={"enabled": kind == "inapp"})


@transaction.atomic
def create_tenant(*, by, name, slug=None, admin_username, admin_email="", admin_first_name="", admin_last_name="",
                  version=None, contract_reference="", end_date=None):
    """Crée une entreprise cliente et son premier administrateur (mot de passe provisoire, à changer).

    Avec une version d'offre : l'abonnement et son stock initial sont créés, et le premier administrateur
    reçoit une licence nominative s'il en existe une (sinon il utilisera une licence concurrente).
    """
    User = get_user_model()
    slug = slugify(slug or name)[:50]
    if not slug:
        raise TenantError("Le nom de l'entreprise doit contenir des lettres ou des chiffres.")
    if Tenant.objects.filter(slug=slug).exists():
        raise TenantError(f"L'identifiant « {slug} » est déjà utilisé par une autre entreprise.")
    if User.objects.filter(username=admin_username).exists():
        raise TenantError(f"L'identifiant de connexion « {admin_username} » est déjà utilisé.")
    tenant = Tenant.objects.create(slug=slug, name=name.strip(), created_by=by)
    provision(tenant)
    password = secrets.token_urlsafe(12)
    admin = User(username=admin_username, email=admin_email, first_name=admin_first_name, last_name=admin_last_name,
                 tenant=tenant, role_id=ADMIN_ROLE, must_change_password=True)
    admin.set_password(password)
    admin.save()
    audit.record(by, f"Entreprise {tenant.name}", "Entreprise créée", "", f"identifiant {slug}", tenant=None)
    audit.record(by, f"Utilisateur {admin.username}", "Premier administrateur créé", "", "", tenant=tenant)
    if version is not None:
        from licensing import models as L
        from licensing import services as licensing
        try:
            licensing.create_subscription(by=by, tenant=tenant, version=version, end_date=end_date,
                                          contract_reference=contract_reference)
        except licensing.LicenseError as exc:
            raise TenantError(exc.message) from exc
        seat = L.License.objects.filter(tenant=tenant, kind=L.NAMED, status=L.AVAILABLE).order_by("number").first()
        if seat is not None:
            licensing.assign(by=by, license=seat, user=admin)
    return tenant, admin, password


@transaction.atomic
def change_status(*, by, tenant, status, reason=""):
    if status not in dict(STATUSES):
        raise TenantError("Statut inconnu.")
    if status == tenant.status:
        return tenant
    if status not in TRANSITIONS[tenant.status]:
        raise TenantError(f"Passage de « {tenant.get_status_display()} » à « {dict(STATUSES)[status]} » non autorisé.")
    if not reason.strip() and status != "active":
        raise TenantError("Indiquez le motif de ce changement de statut.")
    before = tenant.get_status_display()
    tenant.status, tenant.status_reason, tenant.status_changed_at = status, reason.strip()[:300], timezone.now()
    tenant.save(update_fields=["status", "status_reason", "status_changed_at"])
    audit.record(by, f"Entreprise {tenant.name}", "Statut modifié", before, f"{tenant.get_status_display()} · {reason.strip()}", tenant=None)
    return tenant
