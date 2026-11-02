"""1.5.0 : règles de notification des rappels méthodologiques pour chaque tenant (PCT activé par défaut)."""
from django.db import migrations

NEW_EVENTS = ["week_start", "weekly_planning", "sprint_planning", "daily_scrum", "sprint_review", "retro_reminder",
              "sprint_close", "improvement_overdue"]
CHANNELS = ["inapp", "email", "teams", "slack"]


def forward(apps, schema_editor):
    Rule = apps.get_model("configuration", "NotificationRule")
    for tenant in apps.get_model("tenants", "Tenant").objects.all():
        for event in NEW_EVENTS:
            for kind in CHANNELS:
                Rule.objects.get_or_create(tenant=tenant, event=event, channel=kind, defaults={"enabled": kind == "inapp"})


def backward(apps, schema_editor):
    apps.get_model("configuration", "NotificationRule").objects.filter(event__in=NEW_EVENTS).delete()


class Migration(migrations.Migration):
    dependencies = [("configuration", "0009_methodology_notifications")]
    operations = [migrations.RunPython(forward, backward)]
