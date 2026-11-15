"""Notifications planifiées : échéances d'actions et récapitulatif hebdomadaire par projet (paramétré par le CP).

GET/PUT /projects/<pk>/weekly-recap          réglages du récap (chef de projet du projet ou administrateur)
POST    /projects/<pk>/weekly-recap/send     {preview: true} → aperçu ; sinon envoi immédiat aux destinataires
Exécution : une fois par jour (échéances) et au créneau choisi (récap), depuis la cloche ou la commande send_notifications.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.errors import ApiError
from configuration import audit
from configuration.models import AppSetting

from .access import in_active_tenant, visible_projects
from .models import Action, Project, ProjectAccess, TimeEntry

DUE_KEY, RECAP_KEY = "notif_due_state", "weekly_recap"
DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
DEFAULT = {"enabled": False, "weekday": 4, "hour": 16, "audience": {"pm": True, "team": True, "client": False}, "emails": [],
           "sections": {"done": True, "late": True, "upcoming": True, "hours": True, "validations": True, "budget": False}}


def _link():
    from configuration.mailer import app_url
    return f"{app_url()}/#projets"


# --------------------------------------------------------------------------- échéances
def run_due(tenant, today=None):
    """Une fois par jour : actions arrivées à échéance aujourd'hui, et actions dont l'échéance est dépassée d'hier."""
    from configuration.mailer import dispatch
    today = today or timezone.localdate()
    with transaction.atomic():
        row, _ = AppSetting.objects.select_for_update().get_or_create(tenant=tenant, key=DUE_KEY, defaults={"value": {}})
        if (row.value or {}).get("last") == today.isoformat():
            return 0
        row.value = {"last": today.isoformat()}
        row.save(update_fields=["value"])
    n = 0
    qs = (Action.objects.filter(project__tenant=tenant, project__status="active", due__in=[today, today - timedelta(days=1)])
          .exclude(status="done").select_related("project", "owner", "project__pm"))
    for a in qs:
        today_due = a.due == today
        targets = [u for u in (a.owner, a.project.pm if not today_due else None) if u is not None]
        if not targets:
            continue
        dispatch("action_due", targets, (f"Échéance aujourd'hui : {a.title}" if today_due else f"Échéance dépassée : {a.title}"),
                 ("Cette action arrive à échéance aujourd'hui." if today_due else "L'échéance de cette action est dépassée depuis hier."),
                 project=a.project, link=_link(),
                 details={"Action": f"{a.id} — {a.title}", "Échéance": a.due.strftime("%d/%m/%Y"), "Statut": a.get_status_display(),
                          "Responsable": a.owner.display_name if a.owner_id else "—"})
        n += 1
    return n


# --------------------------------------------------------------------------- récap hebdomadaire
def _all(tenant):
    row = AppSetting.objects.filter(tenant=tenant, key=RECAP_KEY).first()
    return row.value if row and isinstance(row.value, dict) else {}


def conf_of(project):
    c = _all(project.tenant).get(project.id) or {}
    return {**DEFAULT, **c, "audience": {**DEFAULT["audience"], **(c.get("audience") or {})},
            "sections": {**DEFAULT["sections"], **(c.get("sections") or {})}}


def recipients(project, conf):
    User = get_user_model()
    a = conf["audience"]
    ids = set()
    if a.get("pm") and project.pm_id:
        ids.add(project.pm_id)
    if a.get("team"):
        ids |= set(ProjectAccess.objects.filter(project=project, user__is_active=True, user__role__internal=True).values_list("user_id", flat=True))
        if project.tl_id:
            ids.add(project.tl_id)
    if a.get("client"):
        ids |= set(ProjectAccess.objects.filter(project=project, user__is_active=True, user__role__internal=False).values_list("user_id", flat=True))
        ids |= set(User.objects.filter(client_id=project.client_id, is_active=True, role__internal=False).values_list("pk", flat=True))
    return list(User.objects.filter(pk__in=ids, is_active=True))


def build(project, conf, today=None):
    """(titre, corps texte, détails) du récap de la semaine écoulée."""
    from planning.services import hours_per_day
    today = today or timezone.localdate()
    since = today - timedelta(days=7)
    s = conf["sections"]
    acts = list(Action.objects.filter(project=project).select_related("owner"))
    parts = []
    details = {}
    if s.get("done"):
        done = [a for a in acts if a.status == "done" and a.done_at and a.done_at > since]
        details["Actions terminées (7 j)"] = len(done)
        parts.append(f"✅ Actions terminées cette semaine ({len(done)})" + "".join(f"\n  • {a.title} — {a.owner.display_name if a.owner_id else '—'}" for a in done[:10]))
    if s.get("late"):
        late = sorted([a for a in acts if a.status != "done" and a.due and a.due < today], key=lambda a: a.due)
        details["Actions en retard"] = len(late)
        parts.append(f"⏰ Actions en retard ({len(late)})" + "".join(f"\n  • {a.title} — échéance {a.due:%d/%m} — {a.owner.display_name if a.owner_id else '—'}" for a in late[:10]))
    if s.get("upcoming"):
        up = sorted([a for a in acts if a.status != "done" and a.due and today <= a.due <= today + timedelta(days=7)], key=lambda a: a.due)
        details["Échéances à 7 jours"] = len(up)
        parts.append(f"📅 Échéances des 7 prochains jours ({len(up)})" + "".join(f"\n  • {a.due:%d/%m} — {a.title} — {a.owner.display_name if a.owner_id else '—'}" for a in up[:10]))
    if s.get("hours"):
        hpd = Decimal(str(hours_per_day(project.tenant) or 8))
        per = defaultdict(Decimal)
        for e in TimeEntry.objects.filter(project=project, work_date__gt=since, work_date__lte=today).exclude(approval_status__in=["draft", "rejected"]).select_related("person"):
            per[e.person.display_name] += e.hours
        tot = sum(per.values(), Decimal("0"))
        details["Temps saisi (7 j)"] = f"{(tot / hpd).quantize(Decimal('0.01'))} j"
        parts.append(f"🕒 Temps saisi sur la semaine : {(tot / hpd).quantize(Decimal('0.01'))} j"
                     + "".join(f"\n  • {n} : {(h / hpd).quantize(Decimal('0.01'))} j" for n, h in sorted(per.items(), key=lambda x: -x[1])))
    if s.get("validations"):
        pend = TimeEntry.objects.filter(project=project, approval_status__in=["pending", "client"]).count()
        details["Saisies en attente de validation"] = pend
        parts.append(f"📝 Saisies de temps en attente de validation : {pend}")
    if s.get("budget"):
        fin = getattr(project, "finance", None)
        if fin is not None and fin.approved:
            rate = (Decimal(fin.consumed or 0) / Decimal(fin.approved) * 100).quantize(Decimal("0.1"))
            details["Budget consommé"] = f"{rate} %"
            parts.append(f"💶 Budget consommé : {rate} % ({fin.consumed} / {fin.approved} €)")
    title = f"Récap hebdomadaire — {project.name} (semaine du {since + timedelta(days=1):%d/%m} au {today:%d/%m})"
    return title, "\n\n".join(parts) or "Aucune activité sur la période.", details


def send_recap(project, conf, by=None):
    from configuration.mailer import dispatch, render, send_mail
    title, body, details = build(project, conf)
    users = recipients(project, conf)
    res = dispatch("weekly_recap", users, title, body, project=project, details=details, link=_link(), actor=None)
    extra = [e for e in conf.get("emails") or [] if e and "@" in e]
    if extra:
        text, html = render(f"[{project.code}] {title}", body, details, _link(), project.tenant.name, "weekly_recap")
        send_mail(project.tenant_id, extra, f"[{project.code}] {title}", text, html, "weekly_recap")
    audit.record(by, f"Projet {project.code}", "Récap hebdomadaire envoyé", "",
                 f"{len(users)} destinataire(s) + {len(extra)} adresse(s)" + ("" if by else " (automatique)"), tenant=project.tenant)
    return {"recipients": [u.display_name for u in users], "extra": extra, **res}


def run_weekly(tenant, now=None):
    now = timezone.localtime(now or timezone.now())
    week = f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"
    done = []
    data = _all(tenant)
    for pid, c in list(data.items()):
        if not c.get("enabled") or c.get("lastSent") == week:
            continue
        if now.weekday() != int(c.get("weekday", 4)) or now.hour < int(c.get("hour", 16)):
            continue
        project = Project.objects.filter(tenant=tenant, pk=pid, status="active").select_related("pm", "client").first()
        if project is None:
            continue
        with transaction.atomic():
            row = AppSetting.objects.select_for_update().get(tenant=tenant, key=RECAP_KEY)
            fresh = dict(row.value or {})
            if (fresh.get(pid) or {}).get("lastSent") == week:
                continue
            fresh[pid] = {**(fresh.get(pid) or {}), "lastSent": week}
            row.value = fresh
            row.save(update_fields=["value"])
        send_recap(project, conf_of(project))
        done.append(project.code)
    return done


def run_all(tenant):
    """Point d'entrée quotidien (cloche, commande planifiée)."""
    try:
        run_due(tenant)
    except Exception:  # noqa: BLE001
        pass
    try:
        run_weekly(tenant)
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------- API
def _project(request, pk, edit=False):
    if not in_active_tenant(request.user):
        raise ApiError("FORBIDDEN_PERMISSION", "Accès réservé aux utilisateurs d'une entreprise.", status.HTTP_403_FORBIDDEN)
    p = get_object_or_404(visible_projects(request.user).select_related("pm", "client"), pk=pk)
    can = request.user.is_app_admin or p.pm_id == request.user.id
    if edit and not can:
        raise ApiError("FORBIDDEN_PERMISSION", "Le récap hebdomadaire est paramétré par le chef de projet.", status.HTTP_403_FORBIDDEN)
    return p, can


class WeeklyRecapView(APIView):
    def get(self, request, pk):
        p, can = _project(request, pk)
        c = conf_of(p)
        return Response({**c, "canEdit": can, "days": DAYS, "recipients": [u.display_name for u in recipients(p, c)],
                         "emailActive": bool(__import__("configuration.mailer", fromlist=["tenant_channel"]).tenant_channel(p.tenant_id))})

    def put(self, request, pk):
        p, _ = _project(request, pk, edit=True)
        d = request.data or {}
        c = conf_of(p)
        c["enabled"] = bool(d.get("enabled", c["enabled"]))
        c["weekday"] = max(0, min(6, int(d.get("weekday", c["weekday"]))))
        c["hour"] = max(0, min(23, int(d.get("hour", c["hour"]))))
        c["audience"] = {k: bool((d.get("audience") or c["audience"]).get(k, False)) for k in DEFAULT["audience"]}
        c["sections"] = {k: bool((d.get("sections") or c["sections"]).get(k, False)) for k in DEFAULT["sections"]}
        emails = d.get("emails", c["emails"])
        if isinstance(emails, str):
            emails = [e.strip() for e in emails.replace(";", ",").split(",")]
        bad = [e for e in emails if e and ("@" not in e or " " in e)]
        if bad:
            raise ApiError("VALIDATION_ERROR", f"Adresse(s) invalide(s) : {', '.join(bad)}")
        c["emails"] = [e for e in emails if e][:20]
        with transaction.atomic():
            row, _ = AppSetting.objects.select_for_update().get_or_create(tenant=p.tenant, key=RECAP_KEY, defaults={"value": {}})
            data = dict(row.value or {})
            data[p.id] = {**(data.get(p.id) or {}), **c}
            row.value = data
            row.save(update_fields=["value"])
        audit.record(request.user, f"Projet {p.code}", "Récap hebdomadaire paramétré", "",
                     f"{'actif' if c['enabled'] else 'inactif'} · {DAYS[c['weekday']]} {c['hour']} h")
        return self.get(request, pk)


class WeeklyRecapSendView(APIView):
    def post(self, request, pk):
        p, _ = _project(request, pk, edit=True)
        c = conf_of(p)
        if (request.data or {}).get("preview"):
            from configuration.mailer import render
            title, body, details = build(p, c)
            text, html = render(f"[{p.code}] {title}", body, details, _link(), p.tenant.name, "weekly_recap")
            return Response({"title": title, "text": text, "html": html, "recipients": [u.display_name for u in recipients(p, c)] + c["emails"]})
        return Response(send_recap(p, c, by=request.user))
