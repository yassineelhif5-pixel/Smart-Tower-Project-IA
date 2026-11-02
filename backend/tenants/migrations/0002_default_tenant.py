"""Tenant « Demo ESN » : il reçoit toutes les données existantes avant le multi-tenant (lot 3a).

Le super administrateur peut le renommer. Aucune donnée n'est supprimée ni dupliquée.
"""
from django.db import migrations

SLUG, NAME = "demo-esn", "Demo ESN"


def create(apps, schema_editor):
    apps.get_model("tenants", "Tenant").objects.get_or_create(slug=SLUG, defaults={"name": NAME, "status": "active"})


class Migration(migrations.Migration):
    dependencies = [("tenants", "0001_initial")]
    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
