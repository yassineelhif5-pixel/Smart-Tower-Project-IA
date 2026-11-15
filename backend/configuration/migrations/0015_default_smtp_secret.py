"""Applique la configuration SMTP par défaut (.env : DEFAULT_SMTP_*, dont la clé DEFAULT_SMTP_PASSWORD) aux entreprises
existantes, sans écraser une configuration déjà saisie. La clé est stockée chiffrée (ServiceSecret « smtp_password »)."""
from django.db import migrations


def apply(apps, schema_editor):
    from configuration.smtp_tools import apply_defaults
    from tenants.models import Tenant
    for tenant in Tenant.objects.all():
        apply_defaults(tenant)


class Migration(migrations.Migration):
    dependencies = [("configuration", "0014_platformsetting")]
    operations = [migrations.RunPython(apply, migrations.RunPython.noop)]
