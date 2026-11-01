"""Rattache toutes les données métier existantes au tenant « Demo ESN » (aucune donnée supprimée)."""
from django.db import migrations

MODELS = ["Client", "ClientContract", "PersonCapacity", "Project", "ProjectInternal", "ProjectFinance", "UserStory",
          "Action", "ActionComment", "Objective", "Todo", "TimeEntry", "Risk", "Issue", "ChangeRequest",
          "ChangeRequestAmount", "TestCampaign", "Defect", "Document", "Meeting", "ProjectAccess", "ActionAccess"]


def forward(apps, schema_editor):
    demo = apps.get_model("tenants", "Tenant").objects.get(slug="demo-esn")
    for name in MODELS:
        apps.get_model("projects", name).objects.filter(tenant__isnull=True).update(tenant=demo)


class Migration(migrations.Migration):
    dependencies = [("projects", "0003_tenant_columns"), ("tenants", "0002_default_tenant")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
