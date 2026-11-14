"""Relances automatiques de saisie des temps.

Chaque jour ouvré (au plus une fois par jour et par entreprise), on cherche, sur les N derniers jours ouvrés (hier inclus,
aujourd'hui exclu), les membres des projets actifs qui n'ont saisi aucune heure. Chacun reçoit une notification dans
l'application et un e-mail ; le chef de projet reçoit la liste de son équipe. Déclenché à la consultation de la cloche
(sans planificateur) ou par la commande `python manage.py remind_timesheets` (tâche planifiée).
"""
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from configuration.models import AppSetting, Notification, NotificationChannel

from .models import Project, ProjectAccess, TimeEntry

SETTING, STATE = "timesheet_reminders", "timesheet_reminders_state"
# Profils qui saisissent des temps (les autres — direction, client, commercial, admin… — ne sont pas relancés).
TIME_ROLES = {"cdp", "techlead", "consultant", "dev", "testeur", "support_n1", "support_n2", "support_n3"}
DEFAULTS = {"enabled": True, "lookbackDays": 5, "email": True}


def settings_of(tenant):
    row = AppSetting.objects.filter(tenant=tenant, key=SETTING).first()
    v = row.value if row and isinstance(row.value, dict) else {}
    return {**DEFAULTS, **{k: v[k] for k in DEFAULTS if k in v}}


def save_settings(tenant, data):
    conf = settings_of(tenant)
    if "enabled" in data:
        conf["enabled"] = bool(data["enabled"])
    if "email" in data:
        conf["email"] = bool(data["email"])
    if "lookbackDays" in data:
        conf["lookbackDays"] = max(1, min(20, int(data["lookbackDays"] or 5)))
    AppSetting.objects.update_or_create(tenant=tenant, key=SETTING, defaults={"value": conf})
    return conf


def working_days(today, n):
    days, d = [], today
    while len(days) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            days.append(d)
    return sorted(days)


def missing_for_project(project, today=None, lookback=None):
    """{user: [jours sans aucune heure saisie (tous projets confondus)]} pour l'équipe du projet."""
    today = today or timezone.localdate()
    days = working_days(today, lookback or settings_of(project.tenant)["lookbackDays"])
    if project.start_date:
        days = [d for d in days if d >= project.start_date]
    if not days:
        return {}
    accesses = (ProjectAccess.objects.filter(project=project, user__is_active=True, user__role_id__in=TIME_ROLES)
                .select_related("user", "user__role"))
    out = {}
    for acc in accesses:
        since = timezone.localtime(acc.granted_at).date() if acc.granted_at else days[0]
        mine = [d for d in days if d >= since]
        if not mine:
            continue
        logged = dict(TimeEntry.objects.filter(person=acc.user, work_date__in=mine).exclude(approval_status="rejected")
                      .values_list("work_date").annotate(h=Sum("hours")))
        empty = [d for d in mine if not logged.get(d)]
        if empty:
            out[acc.user] = empty
    return out


def _fmt(days):
    return ", ".join(d.strftime("%a %d/%m").replace("Mon", "lun.").replace("Tue", "mar.").replace("Wed", "mer.")
                     .replace("Thu", "jeu.").replace("Fri", "ven.") for d in days)


def _send(user, title, body, email=True):
    Notification.objects.create(user=user, event="key_date_reminder", title=title[:200], body=body[:2000])
    if not (email and user.email):
        return "inapp"
    channel = NotificationChannel.objects.filter(tenant_id=user.tenant_id, kind="email", enabled=True).first()
    if channel is None:
        return "inapp (e-mail non configuré)"
    from configuration.notify import ChannelError, send_email
    try:
        send_email(channel, [user.email], title, body)
        return "inapp+email"
    except ChannelError:
        return "inapp (échec e-mail)"


def remind_project(project, by=None, today=None):
    """Relance les membres sans saisie et le chef de projet. Renvoie le détail envoyé."""
    conf = settings_of(project.tenant)
    missing = missing_for_project(project, today)
    sent = []
    for user, days in missing.items():
        how = _send(user, f"[{project.code}] Saisie de temps manquante ({len(days)} jour(s))",
                    f"Bonjour {user.first_name or user.display_name}, aucune heure n'est saisie pour : {_fmt(days)}. "
                    f"Merci de compléter votre saisie de temps (menu « Saisie de temps ») : le budget du projet {project.name} "
                    "est calculé automatiquement à partir de ces saisies.", conf["email"])
        sent.append({"user": user.display_name, "days": [d.isoformat() for d in days], "via": how})
    if missing and project.pm and project.pm.is_active:
        lines = [f"• {u.display_name} : {_fmt(d)}" for u, d in missing.items()]
        how = _send(project.pm, f"[{project.code}] {len(missing)} membre(s) sans saisie de temps",
                    "Saisies manquantes sur les derniers jours ouvrés :\n" + "\n".join(lines)
                    + "\nChaque membre concerné a été relancé. Sans saisie, la consommation budgétaire est sous-estimée.", conf["email"])
        sent.append({"user": project.pm.display_name, "role": "chef de projet", "via": how})
    if by is not None or missing:
        from configuration import audit
        audit.record(by, f"Projet {project.code}", "Relance de saisie des temps", "",
                     f"{len(missing)} membre(s) relancé(s)" + (" (automatique)" if by is None else ""), tenant=project.tenant)
    return {"missing": [{"user": u.display_name, "userId": u.pk, "days": [d.isoformat() for d in d_]} for u, d_ in missing.items()],
            "sent": sent}


def run_daily(tenant, today=None):
    """Relance automatique : une fois par jour ouvré et par entreprise."""
    today = today or timezone.localdate()
    if today.weekday() >= 5 or not settings_of(tenant)["enabled"]:
        return None
    row, _ = AppSetting.objects.get_or_create(tenant=tenant, key=STATE, defaults={"value": {}})
    if (row.value or {}).get("last") == today.isoformat():
        return None
    row.value = {"last": today.isoformat()}
    row.save(update_fields=["value"])
    return [remind_project(p, None, today) for p in Project.objects.filter(tenant=tenant, status="active").select_related("pm")]
