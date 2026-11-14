"""Connecteurs accordés par le Pilote à un client : tous les projets du client (actuels et futurs) en bénéficient.

Stockage : AppSetting « client_connector_grants » par entreprise : {code_client: [connecteurs]}.
L'activation crée ou active l'autorisation sur chaque projet du client ; le retrait la désactive sur ces projets
(le Pilote peut ensuite réactiver un projet précis). Un projet créé plus tard reçoit les connecteurs de son client.
"""
from django.shortcuts import get_object_or_404

from config.errors import ApiError
from configuration import audit
from configuration.models import AppSetting

KEY = "client_connector_grants"


def _row(tenant_id):
    row = AppSetting.objects.filter(tenant_id=tenant_id, key=KEY).first()
    return row, dict(row.value) if row and isinstance(row.value, dict) else {}


def client_grants_all():
    out = {}
    for row in AppSetting.objects.filter(key=KEY):
        for client, codes in (row.value or {}).items():
            out[(row.tenant_id, client)] = set(codes or [])
    return out


def codes_for(tenant_id, client_code):
    return set((_row(tenant_id)[1]).get(client_code) or [])


def set_client_grant(by, tenant_id, client_code, connector, enabled):
    from projects.models import Client, Project
    from .models import CONNECTOR_CATALOG, ProjectConnectorGrant
    client = get_object_or_404(Client.objects.select_related("tenant"), pk=client_code, **({"tenant_id": tenant_id} if tenant_id else {}))
    row, data = _row(client.tenant_id)
    codes = set(data.get(client.code) or [])
    codes = codes | {connector} if enabled else codes - {connector}
    data[client.code] = sorted(codes)
    AppSetting.objects.update_or_create(tenant_id=client.tenant_id, key=KEY, defaults={"value": data})
    n = 0
    for p in Project.objects.filter(client=client):
        ProjectConnectorGrant.objects.update_or_create(project=p, connector=connector,
                                                       defaults={"tenant": p.tenant, "enabled": enabled, "assigned_by": by})
        n += 1
    label = dict(CONNECTOR_CATALOG).get(connector, connector)
    audit.record(by, f"{label} · client {client.name}",
                 "Connecteur accordé au client (tous ses projets)" if enabled else "Connecteur retiré au client (tous ses projets)",
                 "", f"{n} projet(s)", tenant=client.tenant)
    return n


def apply_to_new_project(project):
    from .models import ProjectConnectorGrant
    for code in codes_for(project.tenant_id, project.client_id):
        ProjectConnectorGrant.objects.get_or_create(project=project, connector=code, defaults={"tenant": project.tenant, "enabled": True})
