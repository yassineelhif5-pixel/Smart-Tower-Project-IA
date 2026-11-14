from django.db import migrations


def add_support_role(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Role.objects.update_or_create(
        code="support",
        defaults={"tenant_id": None, "label": "Support Control Tower", "question": "Les demandes d’assistance sont-elles traitées ?",
                  "money": False, "margin": False, "internal": True, "position": 90},
    )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0016_user_auth_mode_alter_rolecapability_code_and_more")]
    operations = [migrations.RunPython(add_support_role, migrations.RunPython.noop)]
