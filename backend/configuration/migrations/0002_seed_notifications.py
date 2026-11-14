"""Canaux de notification et règles par défaut : seul le canal « dans l'application » est actif,
pour tous les événements, comme la cloche de notifications de index.html."""
from django.db import migrations

CHANNELS = ["inapp", "email", "teams", "slack"]
EVENTS = ["action_assigned", "action_late", "validation_requested", "budget_risk", "risk_critical",
          "comment_mention", "document_new", "scope_changed", "key_date_reminder"]


def seed(apps, schema_editor):
    Channel = apps.get_model("configuration", "NotificationChannel")
    Rule = apps.get_model("configuration", "NotificationRule")
    for kind in CHANNELS:
        Channel.objects.get_or_create(kind=kind, defaults={"enabled": kind == "inapp", "settings": {}})
        for event in EVENTS:
            Rule.objects.get_or_create(event=event, channel_id=kind, defaults={"enabled": kind == "inapp"})


class Migration(migrations.Migration):
    dependencies = [("configuration", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
