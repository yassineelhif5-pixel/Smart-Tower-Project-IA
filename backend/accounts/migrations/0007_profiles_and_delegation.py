"""Phase 3 : profils « Responsable de licences » et « Lecture seule », droits d'administration par défaut.

- Matrice métier : le Responsable de licences n'a aucun droit métier ; la Lecture seule consulte tous les modules
  métier sans rien modifier (ni utilisateurs ni paramétrage).
- Droits d'administration (accounts.capabilities) : modèle sans tenant, puis copie dans chaque tenant existant.
"""
from django.db import migrations

MODULES = ["project", "client", "planning", "action", "budget", "resource", "document", "test", "risk", "report", "user", "settings"]
FLAGS = ["can_read", "can_create", "can_update", "can_delete", "can_approve"]
READ_ONLY = {"project", "client", "planning", "action", "document", "test", "risk", "report"}
CAPABILITIES = {
    "license_manager": ["company.view", "users.view", "licenses.view", "licenses.assign", "licenses.release",
                        "sessions.view", "requests.view", "requests.create", "requests.cancel"],
    "manager": ["company.view", "users.view"],
    "direction": ["company.view", "users.view", "licenses.view", "requests.view", "audit.view"],
}


def forward(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    RoleCapability = apps.get_model("accounts", "RoleCapability")
    Tenant = apps.get_model("tenants", "Tenant")
    Role.objects.update_or_create(code="license_manager", defaults=dict(
        label="Responsable de licences", question="Les licences de l'entreprise sont-elles bien utilisées ?",
        money=False, margin=False, internal=True, position=10))
    Role.objects.update_or_create(code="readonly", defaults=dict(
        label="Lecture seule", question="Où en sont les projets ?", money=False, margin=False, internal=True, position=11))
    tenants = list(Tenant.objects.all())
    for role, readable in (("license_manager", set()), ("readonly", READ_ONLY)):
        for module in MODULES:
            values = {f: (f == "can_read" and module in readable) for f in FLAGS}
            for tenant in [None, *tenants]:
                RolePermission.objects.get_or_create(role_id=role, module=module, tenant=tenant, defaults=values)
    for role, codes in CAPABILITIES.items():
        for code in codes:
            for tenant in [None, *tenants]:
                RoleCapability.objects.get_or_create(role_id=role, code=code, tenant=tenant)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0006_rolecapability_usercapability"), ("tenants", "0002_default_tenant")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
