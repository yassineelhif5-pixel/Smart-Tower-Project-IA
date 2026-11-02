"""1.4.0 : règles de notification des nouveaux événements (calendrier, discussions) pour chaque tenant existant.
Comme pour les autres événements, seul le canal « Dans l'application » est activé par défaut."""
from django.db import migrations

NEW_EVENTS = ["date_changed", "owner_changed", "action_blocked", "deadline_reminder", "milestone_reminder", "discussion_message"]
CHANNELS = ["inapp", "email", "teams", "slack"]


def forward(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    NotificationRule = apps.get_model("configuration", "NotificationRule")
    for tenant in Tenant.objects.all():
        for event in NEW_EVENTS:
            for kind in CHANNELS:
                NotificationRule.objects.get_or_create(tenant=tenant, event=event, channel=kind,
                                                       defaults={"enabled": kind == "inapp"})


def backward(apps, schema_editor):
    apps.get_model("configuration", "NotificationRule").objects.filter(event__in=NEW_EVENTS).delete()


class Migration(migrations.Migration):
    dependencies = [("configuration", "0007_calendar_notifications")]
    operations = [migrations.RunPython(forward, backward)]
