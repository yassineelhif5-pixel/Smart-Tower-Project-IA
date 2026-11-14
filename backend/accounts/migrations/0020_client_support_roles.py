"""Profils de support client N1 / N2 / N3 : mêmes droits que « Consultant » (dont la saisie de temps), recopiés
dans la matrice modèle et dans la matrice de chaque entreprise."""
from django.db import migrations

ROLES = [("support_n1", "Support N1", "Les demandes de premier niveau sont-elles traitées ?", 70),
         ("support_n2", "Support N2", "Les incidents fonctionnels sont-ils résolus ?", 71),
         ("support_n3", "Support N3", "Les incidents techniques et correctifs sont-ils livrés ?", 72)]


def add_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    source = list(RolePermission.objects.filter(role_id="consultant"))
    for code, label, question, position in ROLES:
        Role.objects.update_or_create(code=code, defaults={"tenant_id": None, "label": label, "question": question, "money": False,
                                                           "margin": False, "internal": True, "position": position})
        for p in source:
            RolePermission.objects.get_or_create(role_id=code, module=p.module, tenant_id=p.tenant_id, defaults={
                "can_read": p.can_read, "can_create": p.can_create, "can_update": p.can_update,
                "can_delete": p.can_delete, "can_approve": p.can_approve})


class Migration(migrations.Migration):
    dependencies = [("accounts", "0019_userphoto")]
    operations = [migrations.RunPython(add_roles, migrations.RunPython.noop)]
