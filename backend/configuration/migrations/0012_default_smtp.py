"""Pré-remplit le canal e-mail des entreprises avec la configuration SMTP par défaut (DEFAULT_SMTP_SETTINGS).

Seuls les canaux sans serveur SMTP sont complétés : une configuration déjà saisie n'est jamais écrasée.
Le canal reste désactivé ; l'administrateur saisit la clé SMTP puis l'active dans Configuration › Notifications.
"""
from django.conf import settings
from django.db import migrations


def fill_defaults(apps, schema_editor):
    Channel = apps.get_model("configuration", "NotificationChannel")
    Tenant = apps.get_model("tenants", "Tenant")
    defaults = dict(settings.DEFAULT_SMTP_SETTINGS)
    for tenant in Tenant.objects.all():
        channel, _ = Channel.objects.get_or_create(tenant=tenant, kind="email", defaults={"enabled": False, "settings": {}})
        if not (channel.settings or {}).get("host"):
            channel.settings = {**defaults, **{k: v for k, v in (channel.settings or {}).items() if v}}
            channel.save(update_fields=["settings"])


class Migration(migrations.Migration):
    dependencies = [("configuration", "0011_sso_secret"), ("tenants", "0004_tenant_address_tenant_city_tenant_contact_email_and_more")]
    operations = [migrations.RunPython(fill_defaults, migrations.RunPython.noop)]
