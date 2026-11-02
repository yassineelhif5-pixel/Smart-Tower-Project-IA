"""1.4.0 : module « collaboration » (discussions, Microsoft Teams) dans la matrice des droits.

Lignes ajoutées au modèle (tenant vide) et à chaque tenant existant ; les lignes déjà présentes ne sont pas modifiées.
Droits par défaut (voir, créer, modifier, supprimer, valider) :
"""
from django.db import migrations

DEFAULTS = {
    "admin": "11111", "direction": "11100", "manager": "11101", "commercial": "11100", "cdp": "11111",
    "techlead": "11101", "consultant": "11100", "dev": "11100", "testeur": "11100", "client": "11100",
    "superadmin": "00000", "license_manager": "00000", "readonly": "10000",
}
FLAGS = ["can_read", "can_create", "can_update", "can_delete", "can_approve"]


def forward(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    Tenant = apps.get_model("tenants", "Tenant")
    tenants = [None] + list(Tenant.objects.all())
    for role in Role.objects.all():
        flags = DEFAULTS.get(role.code, "10000" if role.code not in ("superadmin",) else "00000")
        values = {f: v == "1" for f, v in zip(FLAGS, flags)}
        for tenant in tenants:
            if tenant is not None and role.code == "superadmin":
                continue
            RolePermission.objects.get_or_create(role=role, module="collaboration", tenant=tenant, defaults=values)


def backward(apps, schema_editor):
    apps.get_model("accounts", "RolePermission").objects.filter(module="collaboration").delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0008_collaboration_module"), ("tenants", "0002_default_tenant")]
    operations = [migrations.RunPython(forward, backward)]
