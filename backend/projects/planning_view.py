"""Planning détaillé, plan de charge et alertes automatiques d'un projet ; notifications des membres.

- Planning détaillé : tâches (qui fait quoi, période, avancement, retard) regroupées par phase.
- Plan de charge : charge restante des tâches ouvertes répartie par semaine et par personne, comparée à la
  capacité hebdomadaire (affectation Capacité, sinon heures/jour × 5).
- Alertes : tâches et phases en retard, glissements, tâches bloquées, surcharge, budget dépassé, fin de projet.
- Notifications : à l'ouverture de l'application, chaque membre reçoit les nouvelles alertes de ses projets
  (sans doublon sur 7 jours), dans la cloche à côté de son nom.
"""
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from configuration.models import Notification
from planning.services import hours_per_day

from .access import in_active_tenant, visible_projects
from .models import ACTION_STATUSES, Action, ProjectAccess, TimeEntry
from .workspace import _project, _rights, budget_of, live_phases

WEEKS = 8
LABELS = dict(ACTION_STATUSES)


def _monday(d):
    return d - timedelta(days=d.weekday())


def _remaining(t):
    for v in (t.raf, t.est):
        if v is not None and v > 0:
            return float(v)
    return 4.0  # tâche non chiffrée : une demi-journée par défaut


def project_alerts(project, today=None, live=None, tasks=None, load=None, with_budget=True):
    from methodology.models import VPhase
    today = today or timezone.localdate()
    tasks = tasks if tasks is not None else list(Action.objects.filter(project=project).select_related("owner"))
    phases = list(VPhase.objects.filter(project=project))
    live = live if live is not None else live_phases(project, phases, today)
    out = []
    late = [t for t in tasks if t.due and t.due < today and t.status != "done"]
    for t in sorted(late, key=lambda t: t.due)[:8]:
        days = (today - t.due).days
        out.append({"level": "crit" if days > 5 else "warn", "kind": "task_late",
                    "message": f"Tâche en retard de {days} j : {t.title}" + (f" ({t.owner.display_name})" if t.owner_id else " (non affectée)"),
                    "ref": t.id})
    if len(late) > 8:
        out.append({"level": "warn", "kind": "task_late", "message": f"… et {len(late) - 8} autre(s) tâche(s) en retard", "ref": "more"})
    soon = [t for t in tasks if t.due and today <= t.due <= today + timedelta(days=2) and t.status not in ("done",)]
    for t in soon[:5]:
        out.append({"level": "info", "kind": "task_due", "message": f"Échéance le {t.due:%d/%m} : {t.title}", "ref": t.id})
    for t in [t for t in tasks if t.status == "blocked"][:5]:
        out.append({"level": "crit", "kind": "task_blocked", "message": f"Tâche bloquée : {t.title}", "ref": t.id})
    for ph in phases:
        lv = live.get(ph.pk, {})
        end = ph.end
        if lv.get("status") == "late" or (end and end < today and lv.get("status") not in ("done", "skipped")):
            out.append({"level": "crit", "kind": "phase_late",
                        "message": f"Phase « {ph.name} » en retard (fin prévue le {end:%d/%m/%Y})" if end else f"Phase « {ph.name} » en retard",
                        "ref": f"phase-{ph.pk}"})
        elif ph.forecast_end and end and ph.forecast_end > end:
            out.append({"level": "warn", "kind": "phase_slip",
                        "message": f"Glissement de {(ph.forecast_end - end).days} j sur la phase « {ph.name} »", "ref": f"phase-{ph.pk}"})
    if project.end_date and project.end_date < today and any(t.status != "done" for t in tasks):
        out.append({"level": "crit", "kind": "project_late", "message": f"Date de fin du projet dépassée ({project.end_date:%d/%m/%Y})", "ref": "project"})
    elif project.end_date and today <= project.end_date <= today + timedelta(days=14):
        out.append({"level": "info", "kind": "project_end", "message": f"Fin du projet dans {(project.end_date - today).days} j", "ref": "project"})
    for m in (load or []):
        over = [w for w in m["weeks"] if w["capacity"] and w["hours"] > w["capacity"] * 1.1]
        if over:
            out.append({"level": "warn", "kind": "overload",
                        "message": f"Surcharge de {m['name']} : {len(over)} semaine(s) au-delà de sa capacité", "ref": f"user-{m['id']}"})
    if with_budget:
        b = budget_of(project)
        if b["rate"] is not None and b["rate"] > 100:
            out.append({"level": "crit", "kind": "budget", "message": f"Budget dépassé : {b['rate']} % consommé ou engagé", "ref": "budget"})
        elif b["rate"] is not None and b["rate"] > 85:
            out.append({"level": "warn", "kind": "budget", "message": f"Budget consommé ou engagé à {b['rate']} %", "ref": "budget"})
    order = {"crit": 0, "warn": 1, "info": 2}
    return sorted(out, key=lambda a: order[a["level"]])


def workload(project, tasks, today):
    """Charge restante par personne et par semaine (8 semaines), face à sa capacité hebdomadaire."""
    from methodology.models import TeamMemberAllocation
    hpd = float(hours_per_day(project.tenant) or 8)
    start = _monday(today)
    weeks = [start + timedelta(weeks=i) for i in range(WEEKS)]
    members = {a.user_id: a.user for a in ProjectAccess.objects.filter(project=project, user__is_active=True).select_related("user")}
    caps = {}
    for a in TeamMemberAllocation.objects.filter(project=project, active=True):
        caps[a.user_id] = float(a.hours_per_day or hpd) * int(a.days_per_week or 5) * (a.allocation_pct or 100) / 100 - float(a.meeting_hours_per_week or 0)
    rows = {uid: [0.0] * WEEKS for uid in members}
    for t in tasks:
        if t.status == "done" or not t.owner_id or t.owner_id not in rows:
            continue
        rem = _remaining(t)
        begin = max(t.start_date or today, today)
        end = max(t.due or (begin + timedelta(days=4)), begin)
        days = [begin + timedelta(days=i) for i in range((end - begin).days + 1)]
        days = [d for d in days if d.weekday() < 5] or [begin]
        per_day = rem / len(days)
        for d in days:
            idx = (_monday(d) - start).days // 7
            if 0 <= idx < WEEKS:
                rows[t.owner_id][idx] += per_day
            elif idx < 0:
                rows[t.owner_id][0] += per_day  # retard : reporté sur la semaine en cours
    spent = dict(TimeEntry.objects.filter(project=project).exclude(approval_status="rejected")
                 .values_list("person_id").annotate(h=Sum("hours")).values_list("person_id", "h"))
    out = []
    for uid, user in members.items():
        my = [t for t in tasks if t.owner_id == uid]
        cap = caps.get(uid, hpd * 5)
        out.append({
            "id": uid, "name": user.display_name,
            "tasks": len(my), "open": sum(1 for t in my if t.status != "done"), "done": sum(1 for t in my if t.status == "done"),
            "doing": sum(1 for t in my if t.status in ("doing", "review")), "late": sum(1 for t in my if t.due and t.due < today and t.status != "done"),
            "remaining": round(sum(_remaining(t) for t in my if t.status != "done"), 1), "spent": float(spent.get(uid) or 0),
            "progress": round(sum(1 for t in my if t.status == "done") / len(my) * 100) if my else None,
            "weeks": [{"week": w, "hours": round(h, 1), "capacity": round(cap, 1)} for w, h in zip(weeks, rows[uid])],
        })
    return sorted(out, key=lambda r: (-r["open"], r["name"])), weeks


class ProjectPlanningView(APIView):
    """Planning détaillé (tâches par phase), plan de charge et alertes du projet."""

    def get(self, request, pk):
        project = _project(request.user, pk)
        today = timezone.localdate()
        from methodology.models import VPhase
        phases = list(VPhase.objects.filter(project=project).order_by("order", "id"))
        live = live_phases(project, phases, today)
        tasks = list(Action.objects.filter(project=project).select_related("owner"))
        spent_by_task = dict(TimeEntry.objects.filter(project=project, action__isnull=False).exclude(approval_status="rejected")
                             .values_list("action_id").annotate(h=Sum("hours")).values_list("action_id", "h"))
        load, weeks = workload(project, tasks, today)
        rights = _rights(request.user, project)
        names = {ph.name.strip().lower(): ph.name for ph in phases}
        groups = {ph.name: [] for ph in phases}
        groups["Sans phase"] = []
        for t in sorted(tasks, key=lambda t: (t.start_date or t.due or today, t.due or today)):
            key = names.get((t.phase or "").strip().lower(), "Sans phase")
            est = float(t.est or 0)
            spent = float(spent_by_task.get(t.id) or 0)
            groups[key].append({
                "id": t.id, "title": t.title, "status": t.status, "statusLabel": LABELS.get(t.status, t.status),
                "owner": t.owner.display_name if t.owner_id else None, "start": t.start_date, "due": t.due,
                "est": est, "spent": spent, "raf": float(t.raf) if t.raf is not None else None,
                "progress": 100 if t.status == "done" else (min(95, round(spent / est * 100)) if est else (50 if t.status in ("doing", "review") else 0)),
                "late": bool(t.due and t.due < today and t.status != "done"),
                "lateDays": (today - t.due).days if t.due and t.due < today and t.status != "done" else 0,
            })
        return Response({
            "today": today, "weeks": weeks,
            "groups": [{"phase": k, "live": live.get(next((ph.pk for ph in phases if ph.name == k), None), {}), "tasks": v}
                       for k, v in groups.items() if v or k != "Sans phase"],
            "workload": load,
            "alerts": project_alerts(project, today, live, tasks, load, with_budget=rights["canSeeMoney"]),
            "doing": [x for g in groups.values() for x in g if x["status"] in ("doing", "review", "blocked")],
        })


class MyAlertsView(APIView):
    """Cloche de notifications : alertes automatiques des projets de l'utilisateur + notifications reçues."""

    def get(self, request):
        user = request.user
        if not in_active_tenant(user):
            return Response({"unread": 0, "items": [], "alerts": []})
        today = timezone.localdate()
        try:  # relance quotidienne des saisies de temps manquantes (une fois par jour et par entreprise)
            from .timesheet_reminders import run_daily
            run_daily(user.tenant, today)
        except Exception:
            pass
        try:  # échéances d'actions (une fois par jour) et récaps hebdomadaires programmés par les CP
            from .notif_jobs import run_all
            run_all(user.tenant)
        except Exception:
            pass
        try:  # CRA et factures du mois écoulé (une fois par jour et par entreprise)
            from clientspace.billing import run_monthly
            run_monthly(user.tenant, today)
        except Exception:
            pass
        since = timezone.now() - timedelta(days=7)
        recent = set(Notification.objects.filter(user=user, created_at__gte=since).values_list("title", flat=True))
        fresh, alerts = [], []
        for project in visible_projects(user).select_related("client")[:30]:
            try:  # relances automatiques programmées via l'assistant (au plus une fois par période)
                from .assistant import run_automations
                run_automations(project)
            except Exception:  # une automatisation en échec ne bloque jamais la cloche
                pass
            money = _rights(user, project)["canSeeMoney"]
            for a in project_alerts(project, today, with_budget=money):
                if a["level"] == "info" and a["kind"] != "task_due":
                    continue
                title = f"[{project.code}] {a['message']}"[:200]
                alerts.append({**a, "project": project.id, "projectCode": project.code, "title": title})
                if title not in recent and a["level"] in ("crit", "warn", "info"):
                    fresh.append(Notification(user=user, event="project_alert", title=title,
                                              body=f"{project.name} · {a['kind']} · {project.id}"))
                    recent.add(title)
        if fresh:
            Notification.objects.bulk_create(fresh)
        items = Notification.objects.filter(user=user)[:40]
        from .project_alerts import alert_details
        details = None

        def row(n):
            nonlocal details
            out = {"id": n.id, "title": n.title, "body": n.body, "text": n.body, "event": n.event, "createdAt": n.created_at,
                   "read": n.read_at is not None, "project": None, "ref": None, "alert": None, "doc": None, "question": None, "mail": None}
            if n.event != "project_alert":
                return out
            parts = n.body.split(" · ")
            out["project"] = parts.pop() if len(parts) > 1 else None
            if parts and parts[-1].startswith("#") and len(parts) > 1:
                out["ref"] = parts.pop()
            out["text"] = " · ".join(parts)
            if out["ref"] and out["ref"].startswith("#AL"):
                if details is None:
                    details = alert_details(user.tenant)
                out["alert"] = details.get(out["ref"][1:])
            elif out["ref"] and out["ref"].startswith("#DOC:"):
                out["doc"] = out["ref"][5:]
            elif out["ref"] and out["ref"].startswith("#Q:"):
                out["question"] = out["ref"][3:]
            elif out["ref"] and out["ref"].startswith("#MAIL:"):
                out["mail"] = out["ref"][6:]
            return out

        return Response({
            "unread": Notification.objects.filter(user=user, read_at__isnull=True).count(),
            "items": [row(n) for n in items],
            "alerts": alerts[:60],
        })

    def post(self, request):
        ids = request.data.get("ids")
        qs = Notification.objects.filter(user=request.user, read_at__isnull=True)
        if ids:
            qs = qs.filter(id__in=ids)
        qs.update(read_at=timezone.now())
        return Response(status=status.HTTP_204_NO_CONTENT)



class WeekActionsView(APIView):
    """Actions de la semaine : en cours, clôturées dans la semaine, en retard (état actuel, à chaque appel)."""

    def get(self, request, pk):
        from django.utils.dateparse import parse_date
        project = _project(request.user, pk)
        today = timezone.localdate()
        start = _monday(parse_date(str(request.query_params.get("week") or "")) or today)
        end = start + timedelta(days=6)
        from .access import visible_actions
        qs = (Action.objects.filter(project=project) if (request.user.is_app_admin or project.pm_id == request.user.id)
              else visible_actions(request.user).filter(project=project))
        tasks = list(qs.select_related("owner"))
        row = lambda t: {"id": t.id, "title": t.title, "status": t.status, "statusLabel": LABELS.get(t.status, t.status),  # noqa: E731
                         "owner": t.owner.display_name if t.owner_id else None, "due": t.due, "doneAt": t.done_at,
                         "phase": t.phase, "lateDays": (today - t.due).days if t.due and t.due < today and t.status != "done" else 0}
        in_week = lambda d: d is not None and start <= d <= end  # noqa: E731
        doing = [t for t in tasks if t.status != "done" and (t.status in ("doing", "review", "blocked")
                                                              or in_week(t.due) or in_week(t.start_date))]
        done = [t for t in tasks if t.status == "done" and (in_week(t.done_at) or (t.done_at is None and in_week(t.due)))]
        late = [t for t in tasks if t.status != "done" and t.due and t.due < min(today, end + timedelta(days=1))]
        return Response({
            "weekStart": start, "weekEnd": end, "today": today,
            "doing": [row(t) for t in sorted(doing, key=lambda t: (t.due or end))],
            "done": [row(t) for t in sorted(done, key=lambda t: (t.done_at or t.due or end), reverse=True)],
            "late": [row(t) for t in sorted(late, key=lambda t: t.due)],
            "canEdit": _rights(request.user, project)["canManageTasks"],
        })
