"""Rattache les comptes existants au tenant « Demo ESN », crée le rôle de super administrateur
et donne au tenant sa propre copie de la matrice des droits (la matrice sans tenant reste le modèle
copié à la création de chaque nouveau tenant)."""
from django.db import migrations

MODULES = ["project", "client", "planning", "action", "budget", "resource", "document", "test", "risk", "report", "user", "settings"]
FLAGS = ["can_read", "can_create", "can_update", "can_delete", "can_approve"]


def forward(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    User = apps.get_model("accounts", "User")
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    demo = Tenant.objects.get(slug="demo-esn")

    User.objects.filter(tenant__isnull=True).exclude(role_id="superadmin").update(tenant=demo)

    Role.objects.update_or_create(code="superadmin", defaults=dict(
        label="Pilote (Super Admin Global)", question="La plateforme, ses entreprises et leurs licences sont-elles maîtrisées ?",
        money=False, margin=False, internal=True, position=99))
    for module in MODULES:
        RolePermission.objects.get_or_create(role_id="superadmin", module=module, tenant=None,
                                             defaults={f: False for f in FLAGS})

    for row in RolePermission.objects.filter(tenant__isnull=True).exclude(role_id="superadmin"):
        RolePermission.objects.get_or_create(role_id=row.role_id, module=row.module, tenant=demo,
                                             defaults={f: getattr(row, f) for f in FLAGS})


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_tenant"), ("tenants", "0002_default_tenant")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
