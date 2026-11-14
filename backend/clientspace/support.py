"""Support N1/N2/N3 : licence accordée à l'entreprise par le Pilote, contrats activés par client par l'administrateur.

Les membres d'un contrat (profils Support N1/N2/N3 couverts) reçoivent l'accès à tous les projets du client, présents et
futurs, saisissent leurs temps sur ces projets et suivent le même circuit de validation et de CRA que le run.
"""
from configuration.models import AppSetting
from projects.models import Project, ProjectAccess

from .models import LEVEL_ROLE, SupportContract

LICENSE_KEY = "support_license"


def license_of(tenant):
    row = AppSetting.objects.filter(tenant=tenant, key=LICENSE_KEY).first()
    v = row.value if row and isinstance(row.value, dict) else {}
    levels = [lv for lv in v.get("levels", ["N1", "N2", "N3"]) if lv in LEVEL_ROLE]
    return {"enabled": bool(v.get("enabled", False)), "levels": levels, "maxClients": v.get("maxClients")}


def save_license(tenant, data):
    lic = license_of(tenant)
    if "enabled" in data:
        lic["enabled"] = bool(data["enabled"])
    if isinstance(data.get("levels"), list):
        lic["levels"] = [lv for lv in data["levels"] if lv in LEVEL_ROLE]
    if "maxClients" in data:
        lic["maxClients"] = int(data["maxClients"]) if str(data["maxClients"] or "").isdigit() else None
    AppSetting.objects.update_or_create(tenant=tenant, key=LICENSE_KEY, defaults={"value": lic})
    return lic


def active(contract, today=None):
    from django.utils import timezone
    today = today or timezone.localdate()
    return (contract.enabled and license_of(contract.tenant)["enabled"]
            and (contract.starts_on is None or contract.starts_on <= today) and (contract.ends_on is None or contract.ends_on >= today))


def sync_access(contract, by=None):
    """Ouvre l'accès des membres couverts à tous les projets du client ; retire les accès ouverts par le contrat sinon."""
    wanted = set()
    if active(contract):
        roles = {LEVEL_ROLE[lv] for lv in contract.levels if lv in license_of(contract.tenant)["levels"]}
        members = [u for u in contract.members.filter(is_active=True) if u.role_id in roles]
        for project in Project.objects.filter(client=contract.client).exclude(status="closed"):
            for u in members:
                wanted.add((u.pk, project.pk))
    before = {tuple(x) for x in (contract.granted or [])}
    granted = before & wanted
    for user_id, project_id in wanted - before:
        _, created = ProjectAccess.objects.get_or_create(tenant=contract.tenant, project_id=project_id, user_id=user_id,
                                                         defaults={"can_edit": True, "granted_by": by})
        if created:  # un accès qui existait déjà n'appartient pas au contrat : il ne sera jamais retiré par lui
            granted.add((user_id, project_id))
    for user_id, project_id in before - wanted:
        ProjectAccess.objects.filter(project_id=project_id, user_id=user_id).delete()
    contract.granted = sorted([list(x) for x in granted])
    SupportContract.objects.filter(pk=contract.pk).update(granted=contract.granted)
    return len(wanted)
