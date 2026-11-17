"""Profil « AMOA » (maîtrise d'ouvrage) : rédige et valide les user stories de test. Mêmes droits que « Testeur »,
recopiés dans la matrice modèle et dans celle de chaque entreprise."""
from django.db import migrations


def add_role(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    Role.objects.update_or_create(code="amoa", defaults={"tenant_id": None, "label": "AMOA",
                                                         "question": "Le produit répond-il au besoin métier ?", "money": False,
                                                         "margin": False, "internal": True, "position": 45})
    for p in RolePermission.objects.filter(role_id="testeur"):
        RolePermission.objects.get_or_create(role_id="amoa", module=p.module, tenant_id=p.tenant_id, defaults={
            "can_read": p.can_read, "can_create": p.can_create, "can_update": p.can_update,
            "can_delete": p.can_delete, "can_approve": p.can_approve})


class Migration(migrations.Migration):
    dependencies = [("accounts", "0023_invitation")]
    operations = [migrations.RunPython(add_role, migrations.RunPython.noop)]
