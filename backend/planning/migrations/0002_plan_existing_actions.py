"""1.4.0 : chaque action datée existante reçoit son événement de calendrier (journée entière, fuseau Europe/Paris).
Aucune donnée n'est modifiée ni supprimée ; le retour arrière supprime seulement les événements ainsi créés."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import migrations

PRIO = {"Basse": "low", "Faible": "low", "Normale": "normal", "Moyenne": "normal", "Haute": "high",
        "Critique": "critical", "Bloquante": "critical"}


def forward(apps, schema_editor):
    Action = apps.get_model("projects", "Action")
    Event = apps.get_model("planning", "CalendarEvent")
    Assignment = apps.get_model("planning", "CalendarAssignment")
    tz = ZoneInfo("Europe/Paris")
    for a in Action.objects.filter(calendar_event__isnull=True):
        first, last = a.start_date or a.due, a.due or a.start_date
        if not first:
            continue
        if last < first:
            first, last = last, first
        progress = 100 if a.status == "done" else (int(min(100, float(a.done) / float(a.est) * 100)) if a.est and a.done else 0)
        e = Event.objects.create(
            tenant_id=a.tenant_id, project_id=a.project_id, action=a, kind="action", title=a.title[:300], phase=a.phase,
            start=datetime.combine(first, time.min, tzinfo=tz), end=datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz),
            timezone="Europe/Paris", all_day=True, status=a.status, priority=PRIO.get(a.prio, "normal"), progress=progress,
            completed_at=datetime.combine(a.done_at, time(12), tzinfo=tz) if a.done_at else None)
        if a.owner_id:
            Assignment.objects.create(tenant_id=a.tenant_id, event=e, user_id=a.owner_id, role="owner",
                                      estimated_workload=a.est, actual_workload=a.done)


def backward(apps, schema_editor):
    apps.get_model("planning", "CalendarEvent").objects.filter(kind="action", action__isnull=False).delete()


class Migration(migrations.Migration):
    dependencies = [("planning", "0001_initial"), ("projects", "0005_tenant_required")]
    operations = [migrations.RunPython(forward, backward)]
