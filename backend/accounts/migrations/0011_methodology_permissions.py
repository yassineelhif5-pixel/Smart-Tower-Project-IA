"""1.5.0 : modules « capacity » (capacité, disponibilités) et « methodology » (Cycle en V, Scrum, rétrospectives).

Lignes ajoutées au modèle (tenant vide) et à chaque tenant ; les lignes existantes ne sont pas modifiées.
Droits (voir, créer, modifier, supprimer, valider)."""
from django.db import migrations

DEFAULTS = {
    "capacity": {"admin": "11111", "direction": "10000", "manager": "11111", "commercial": "10000", "cdp": "11111",
                 "techlead": "11101", "consultant": "10000", "dev": "10000", "testeur": "10000", "client": "00000",
                 "superadmin": "00000", "license_manager": "00000", "readonly": "10000"},
    "methodology": {"admin": "11111", "direction": "10000", "manager": "11101", "commercial": "10000", "cdp": "11111",
                    "techlead": "11101", "consultant": "11100", "dev": "11100", "testeur": "11100", "client": "00000",
                    "superadmin": "00000", "license_manager": "00000", "readonly": "10000"},
}
FLAGS = ["can_read", "can_create", "can_update", "can_delete", "can_approve"]


def forward(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    tenants = [None] + list(apps.get_model("tenants", "Tenant").objects.all())
    for module, table in DEFAULTS.items():
        for role in Role.objects.all():
            flags = table.get(role.code, "00000")
            values = {f: v == "1" for f, v in zip(FLAGS, flags)}
            for tenant in tenants:
                if tenant is not None and role.code == "superadmin":
                    continue
                RolePermission.objects.get_or_create(role=role, module=module, tenant=tenant, defaults=values)


def backward(apps, schema_editor):
    apps.get_model("accounts", "RolePermission").objects.filter(module__in=list(DEFAULTS)).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0010_methodology_modules"), ("tenants", "0002_default_tenant")]
    operations = [migrations.RunPython(forward, backward)]
