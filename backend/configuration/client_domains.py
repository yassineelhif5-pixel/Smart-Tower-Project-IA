"""Domaines e-mail autorisés pour un client (un ou plusieurs), gérés par l'administrateur de l'entreprise
(le Pilote les gère aussi depuis Domaines SSO). Effets :
- une demande d'accès SSO d'une adresse de ce domaine est rattachée au client (profil client proposé) ;
- un compte créé avec une adresse de ce domaine est rattaché d'office au client s'il est externe.
Garde-fous : un domaine appartient à une seule entreprise ; les messageries publiques sont refusées.
"""
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response

from config.errors import ApiError
from projects.models import Client
from tenants.domain_utils import normalize_domain
from tenants.models import TenantDomain

from . import audit
from .views import AdminView

PUBLIC = {"gmail.com", "googlemail.com", "outlook.com", "outlook.fr", "hotmail.com", "hotmail.fr", "live.com", "live.fr",
          "msn.com", "yahoo.com", "yahoo.fr", "icloud.com", "me.com", "aol.com", "orange.fr", "wanadoo.fr", "free.fr",
          "sfr.fr", "laposte.net", "gmx.fr", "gmx.com", "proton.me", "protonmail.com", "yopmail.com", "bbox.fr"}


def client_for_email(tenant, email):
    """Client rattaché au domaine de l'adresse (domaine actif de l'entreprise), sinon None."""
    if not email or "@" not in email:
        return None
    row = TenantDomain.objects.select_related("client").filter(tenant=tenant, enabled=True, client__isnull=False,
                                                                domain=email.rsplit("@", 1)[-1].strip().lower()).first()
    return row.client if row else None


def _row(r):
    return {"id": r.pk, "domain": r.domain, "client": r.client_id, "clientName": r.client.name if r.client_id else None,
            "enabled": r.enabled, "createdAt": r.created_at, "createdBy": r.created_by.username if r.created_by else None}


class ClientDomainsView(AdminView):
    """GET : domaines de l'entreprise et clients. POST {domain, client} : autorise un domaine pour un client."""

    def get(self, request):
        rows = TenantDomain.objects.filter(tenant=self.tenant).select_related("client", "created_by").order_by("client__name", "domain")
        return Response({"domains": [_row(r) for r in rows],
                         "clients": [{"code": c.code, "name": c.name} for c in Client.objects.filter(tenant=self.tenant).order_by("name")]})

    def post(self, request):
        try:
            domain = normalize_domain(str(request.data.get("domain") or ""))
        except ValueError as exc:
            raise ApiError("VALIDATION_ERROR", str(exc)) from exc
        if domain in PUBLIC:
            raise ApiError("VALIDATION_ERROR", "Les domaines de messagerie publique ne peuvent pas être autorisés pour un client.")
        client = get_object_or_404(Client, pk=request.data.get("client"), tenant=self.tenant)
        row = TenantDomain.objects.filter(domain=domain).first()
        if row and row.tenant_id != self.tenant.pk:
            raise ApiError("DOMAIN_ALREADY_ASSIGNED", "Ce domaine est déjà utilisé par une autre entreprise. Contactez le Pilote.", status.HTTP_409_CONFLICT)
        if row:
            row.client, row.enabled = client, True
            row.save(update_fields=["client", "enabled", "updated_at"])
        else:
            row = TenantDomain.objects.create(domain=domain, tenant=self.tenant, client=client, enabled=True, created_by=request.user)
        audit.record(request.user, f"Domaine {domain}", "Domaine autorisé pour un client", "", client.name)
        return self.get(request)


class ClientDomainDetailView(AdminView):
    """PATCH {client?, enabled?} : change le client ou désactive le domaine."""

    def patch(self, request, pk):
        row = get_object_or_404(TenantDomain.objects.select_related("client"), pk=pk, tenant=self.tenant)
        before = f"{row.client.name if row.client_id else 'entreprise'} · {'actif' if row.enabled else 'inactif'}"
        if "client" in request.data:
            code = request.data.get("client")
            row.client = get_object_or_404(Client, pk=code, tenant=self.tenant) if code else None
        if "enabled" in request.data:
            row.enabled = bool(request.data["enabled"])
        row.save(update_fields=["client", "enabled", "updated_at"])
        audit.record(request.user, f"Domaine {row.domain}", "Domaine client modifié", before,
                     f"{row.client.name if row.client_id else 'entreprise'} · {'actif' if row.enabled else 'inactif'}")
        return Response(_row(row))
