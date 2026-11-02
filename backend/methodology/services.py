"""Règles du pilotage méthodologique. Les vues ne font qu'appeler ces fonctions.

Droits (matrice du tenant, filtrée par l'offre) :
- module « capacity » : Voir la capacité ; Modifier = disponibilités et affectations ; Valider = jours fériés.
- module « methodology » : Voir ; Créer/Modifier = planifier, objectifs, backlog, sprints, cérémonies,
  rétrospectives, actions d'amélioration ; Valider = valider la semaine, démarrer/clôturer un sprint, changer
  de méthodologie, clôture forcée d'une rétrospective.
Une écriture exige en plus de pouvoir modifier le projet (périmètre complet, accès « modification ») ou d'être
membre de son équipe. Les rôles Scrum (PO, SM, Developers) ne donnent aucun droit PCT : ils ne servent qu'aux
validations propres à Scrum (le Product Owner priorise et valide le Sprint Backlog, l'équipe s'engage).
L'assistance (« assist ») ne fait que proposer : rien n'est validé, affecté ou modifié sans action explicite.
"""
import logging
import re
import secrets
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from accounts.permissions import has_perm
from configuration import audit
from configuration.models import AppSetting
from configuration.notify import notify
from planning import services as planning
from planning.models import CalendarAssignment, CalendarEvent
from projects.access import has_full_scope, in_active_tenant, visible_actions, visible_projects
from projects.models import Action, ProjectAccess, TimeEntry

from . import capacity as cap
from .models import (ALL_FEATURES, DEFAULT_COLUMNS, DEFAULT_SETTINGS, DEFAULT_V_PHASES, FEATURES, KINDS,
                     RETRO_CATEGORIES, ImprovementAction, MethodologyReminder, ProductBacklogItem, ProjectMethodology,
                     Retrospective, RetrospectiveFeedback, RetrospectiveParticipant, ScrumDaily, ScrumDailyEntry, Sprint,
                     SprintBacklogItem, SprintGoal, SprintReview, TeamCapacity, TeamMemberAllocation, VPhase,
                     WeeklyGoal, WeeklyGoalAction, WeeklyPlan)

logger = logging.getLogger("methodology")
User = get_user_model()
ACTION_PRIO = {"low": "Basse", "normal": "Normale", "high": "Haute", "critical": "Critique"}
PRIO_RANK = {"Critique": 0, "Bloquante": 0, "Haute": 1, "Normale": 2, "Moyenne": 2, "Basse": 3, "Faible": 3}
REMINDER_EVENT = {"week_start": "week_start", "weekly_planning": "weekly_planning", "sprint_planning": "sprint_planning",
                  "daily": "daily_scrum", "sprint_review": "sprint_review", "retro": "retro_reminder",
                  "retro_report": "retro_reminder", "sprint_close": "sprint_close", "improvement_overdue": "improvement_overdue"}
MAX_ATTEMPTS = 3


class MethodError(Exception):
    def __init__(self, code, message, http_status=400, details=None):
        super().__init__(message)
        self.code, self.message, self.http_status, self.details = code, message, http_status, details or []


def forbid(message="Action non autorisée avec vos droits."):
    return MethodError("FORBIDDEN_PERMISSION", message, 403)


# --------------------------------------------------------------------------- accès
def project_for(user, pk):
    if not in_active_tenant(user):
        raise forbid()
    p = visible_projects(user).filter(pk=pk).select_related("pm").first()
    if p is None:
        raise MethodError("NOT_FOUND", "Projet introuvable.", 404)
    return p


def is_member(user, project):
    return TeamMemberAllocation.objects.filter(project=project, user=user, active=True).exists()


def can_edit_project(user, project):
    return has_full_scope(user) or project.pm_id == user.pk or ProjectAccess.objects.filter(
        user=user, project=project, can_edit=True).exists()


def require(user, project, verb="read", module="methodology", member_ok=True):
    if not in_active_tenant(user) or project.tenant_id != user.tenant_id or not has_perm(user, module, verb):
        raise forbid()
    if verb == "read":
        return
    if verb != "approve" and member_ok and is_member(user, project):
        return
    if not can_edit_project(user, project):
        raise forbid("Vous ne pouvez pas modifier ce projet.")


def allowed(user, project, verb, module="methodology", member_ok=True):
    try:
        require(user, project, verb, module, member_ok)
        return True
    except MethodError:
        return False


def scrum_role(user, project):
    a = TeamMemberAllocation.objects.filter(project=project, user=user, active=True).first()
    return a.scrum_role if a else ""


# --------------------------------------------------------------------------- méthodologie
def methodology(project):
    m = ProjectMethodology.objects.filter(project=project).first()
    if m is None:
        from .bootstrap import kind_of
        m = ProjectMethodology.objects.create(tenant=project.tenant, project=project, kind=kind_of(project.method))
    return m


def tenant_conf(tenant):
    row = AppSetting.objects.filter(tenant=tenant, key="methodology").first()
    return {"reminderHours": [48, 24, 0], "allowAnonymous": False, **(row.value if row else {})}


def settings_of(project):
    m = methodology(project)
    conf = {**DEFAULT_SETTINGS, **(m.settings or {})}
    t = tenant_conf(project.tenant)
    if "reminderHours" not in (m.settings or {}):
        conf["reminderHours"] = t["reminderHours"]
    return conf


def require_feature(project, feature):
    if feature not in methodology(project).enabled():
        raise MethodError("FEATURE_DISABLED", "Fonctionnalité non activée pour la méthodologie de ce projet.", 409)


def impact(project, kind, features=None):
    """Analyse d'impact d'un changement de méthodologie. Aucune donnée n'est supprimée : elle est masquée."""
    m = methodology(project)
    if kind not in dict(KINDS):
        raise MethodError("VALIDATION_ERROR", "Méthodologie inconnue.")
    target = [f for f in (features or []) if f in ALL_FEATURES] if kind == "custom" else FEATURES[kind]
    before = set(m.enabled())
    off, on = sorted(before - set(target)), sorted(set(target) - before)
    data = {
        "from": m.kind, "to": kind, "enabled": on, "disabled": off,
        "activeSprints": Sprint.objects.filter(project=project, status__in=("active", "planned")).count(),
        "backlogItems": ProductBacklogItem.objects.filter(project=project).exclude(status__in=("done", "removed")).count(),
        "openWeeklyPlans": WeeklyPlan.objects.filter(project=project).exclude(state="closed").count(),
        "phases": VPhase.objects.filter(project=project).count(),
        "openRetros": Retrospective.objects.filter(project=project).exclude(status="closed").count(),
    }
    warnings = []
    if "scrum" in off and data["activeSprints"]:
        warnings.append(f"{data['activeSprints']} sprint(s) en cours ou planifié(s) ne seront plus affichés : clôturez-les d'abord.")
    if "weekly" in off and data["openWeeklyPlans"]:
        warnings.append(f"{data['openWeeklyPlans']} semaine(s) non clôturée(s) ne seront plus suivies.")
    if "phases" in off and data["phases"]:
        warnings.append(f"{data['phases']} phase(s) seront masquées (conservées).")
    data["warnings"] = warnings
    return data


@transaction.atomic
def change_methodology(user, project, kind, features=None, confirm=False):
    require(user, project, "approve")
    m = methodology(project)
    data = impact(project, kind, features)
    if kind == m.kind and kind != "custom":
        return m
    if not confirm:
        raise MethodError("METHODOLOGY_IMPACT", "Changement de méthodologie : confirmez après lecture de l'analyse d'impact.", 409, data)
    m.history = (m.history or []) + [{"at": timezone.now().isoformat(), "by": user.username, "from": m.kind, "to": kind,
                                      "impact": {k: data[k] for k in ("enabled", "disabled", "warnings")}}]
    m.kind = kind
    m.features = [f for f in (features or []) if f in ALL_FEATURES] if kind == "custom" else []
    m.save()
    if "phases" in m.enabled() and not VPhase.objects.filter(project=project).exists():
        for i, name in enumerate(DEFAULT_V_PHASES):
            VPhase.objects.create(tenant=project.tenant, project=project, order=i, name=name)
    audit.record(user, f"Projet {project.code}", "Méthodologie modifiée", data["from"], kind)
    return m


def save_settings(user, project, data):
    require(user, project, "update", member_ok=False)
    m = methodology(project)
    s = dict(m.settings or {})
    if "productiveRatio" in data:
        r = float(data["productiveRatio"])
        if not 0.3 <= r <= 1:
            raise MethodError("VALIDATION_ERROR", "Le ratio productif est compris entre 0,3 et 1.")
        s["productiveRatio"] = r
    if "sprintWeeks" in data:
        if int(data["sprintWeeks"]) not in (1, 2, 3, 4):
            raise MethodError("VALIDATION_ERROR", "Durée de sprint : 1 à 4 semaines.")
        s["sprintWeeks"] = int(data["sprintWeeks"])
    if "boardColumns" in data:
        s["boardColumns"] = _columns(project, data["boardColumns"])
    if "retroFrequency" in data:
        if data["retroFrequency"] not in ("sprint", "weekly", "monthly", "phase", "milestone", "project", "none"):
            raise MethodError("VALIDATION_ERROR", "Fréquence de rétrospective inconnue.")
        s["retroFrequency"] = data["retroFrequency"]
    if "reminderHours" in data:
        hours = sorted({int(h) for h in data["reminderHours"]}, reverse=True)
        if any(h < 0 or h > 336 for h in hours) or len(hours) > 6:
            raise MethodError("VALIDATION_ERROR", "Rappels : jusqu'à 6 délais entre 0 et 336 heures.")
        s["reminderHours"] = hours
    for key in ("dailyTime", "weeklyPlanningTime"):
        if key in data:
            if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(data[key])):
                raise MethodError("VALIDATION_ERROR", "Heure au format HH:MM.")
            s[key] = data[key]
    for key, low, high in (("dailyMinutes", 5, 60), ("weeklyPlanningDay", 0, 4)):
        if key in data:
            v = int(data[key])
            if not low <= v <= high:
                raise MethodError("VALIDATION_ERROR", f"Valeur hors limites pour {key}.")
            s[key] = v
    if "dailyInCalendar" in data:
        s["dailyInCalendar"] = bool(data["dailyInCalendar"])
    if "timezone" in data:
        try:
            ZoneInfo(str(data["timezone"]))
        except Exception as exc:
            raise MethodError("VALIDATION_ERROR", "Fuseau horaire inconnu.") from exc
        s["timezone"] = data["timezone"]
    m.settings = s
    m.save(update_fields=["settings", "updated_at"])
    audit.record(user, f"Projet {project.code}", "Paramètres méthodologiques modifiés")
    return m


def _columns(project, columns):
    """Colonnes du Sprint Board : clés stables ; une colonne contenant des éléments d'un sprint ouvert ne disparaît pas."""
    if not isinstance(columns, list) or not 2 <= len(columns) <= 10:
        raise MethodError("VALIDATION_ERROR", "Le tableau compte de 2 à 10 colonnes.")
    clean, keys = [], set()
    for c in columns:
        key = re.sub(r"[^a-z0-9_]", "", str(c.get("key", "")).lower())[:30]
        label = str(c.get("label", "")).strip()[:40]
        if not key or not label or key in keys:
            raise MethodError("VALIDATION_ERROR", "Chaque colonne a une clé unique et un libellé.")
        keys.add(key)
        clean.append({"key": key, "label": label, "done": bool(c.get("done"))})
    if not any(c["done"] for c in clean):
        raise MethodError("VALIDATION_ERROR", "Au moins une colonne doit signifier « terminé ».")
    used = set(SprintBacklogItem.objects.filter(sprint__project=project, sprint__status__in=("planned", "active"),
                                                removed_at__isnull=True).values_list("column", flat=True))
    missing = used - keys
    if missing:
        raise MethodError("VALIDATION_ERROR", f"Colonnes encore utilisées dans un sprint ouvert : {', '.join(sorted(missing))}.")
    return clean


def save_tenant_conf(user, data):
    if not has_perm(user, "settings", "update"):
        raise forbid()
    value = tenant_conf(user.tenant)
    if "reminderHours" in data:
        value["reminderHours"] = sorted({int(h) for h in data["reminderHours"] if 0 <= int(h) <= 336}, reverse=True)[:6]
    if "allowAnonymous" in data:
        value["allowAnonymous"] = bool(data["allowAnonymous"])
    AppSetting.objects.update_or_create(tenant=user.tenant, key="methodology", defaults={"value": value})
    audit.record(user, "Méthodologie", "Politique de l'entreprise modifiée", "", str(value))
    return value


# --------------------------------------------------------------------------- calendrier
def _tz(project):
    return ZoneInfo(settings_of(project)["timezone"])


def _at(project, day, hhmm):
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, time(h, m), tzinfo=_tz(project))


def _event(project, by, title, start, end, kind="meeting", users=(), owner=None, all_day=False, description=""):
    e = CalendarEvent.objects.create(tenant=project.tenant, project=project, kind=kind, title=title[:300],
                                     description=description, start=start, end=end, all_day=all_day,
                                     timezone=str(_tz(project)), created_by=by, status="planned")
    for u in {u.pk: u for u in users if u}.values():
        CalendarAssignment.objects.create(tenant=project.tenant, event=e, user=u,
                                          role="owner" if owner and u.pk == owner.pk else "contributor")
    return e


def _team(project, roles=None):
    qs = TeamMemberAllocation.objects.filter(project=project, active=True).select_related("user")
    if roles:
        qs = qs.filter(scrum_role__in=roles)
    return [a.user for a in qs if a.user.is_active]


def _remind(project, kind, at, users, title, body="", key="", **links):
    if at <= timezone.now() - timedelta(hours=1):
        return None
    try:
        with transaction.atomic():
            r = MethodologyReminder.objects.create(tenant=project.tenant, project=project, kind=kind, remind_at=at,
                                                   title=title[:200], body=body, dedupe_key=key[:160], **links)
            r.users.set([u for u in users if u])
            return r
    except IntegrityError:
        return None  # déjà programmé : jamais deux fois le même rappel


def working_days(start, end):
    return [d for d in cap.days(start, end) if d.weekday() < 5]


# --------------------------------------------------------------------------- Cycle en V : semaine
def week_of(day):
    return day - timedelta(days=day.weekday())


def plan_for(project, week_start, create=True):
    week_start = week_of(week_start)
    plan = WeeklyPlan.objects.filter(project=project, week_start=week_start).first()
    if plan is None and create:
        plan, _ = WeeklyPlan.objects.get_or_create(project=project, week_start=week_start, defaults={"tenant": project.tenant})
    return plan


def _open_actions(project):
    return Action.objects.filter(project=project).exclude(status="done").select_related("owner")


def _remaining_hours(a):
    est = Decimal(a.est or 0)
    done = Decimal(a.done or 0)
    return max(est - done, Decimal("0")) if est else Decimal("0")


def prepare_week(user, project, week_start):
    """Assistant de préparation : reliquat, reports, disponibilités, capacité, propositions, conflits."""
    require(user, project, "read")
    require_feature(project, "weekly")
    week_start = week_of(week_start)
    end = week_start + timedelta(days=4)
    prev = week_start - timedelta(days=7)
    plan = plan_for(project, week_start)
    visible = set(visible_actions(user).filter(project=project).values_list("pk", flat=True))
    opened = [a for a in _open_actions(project) if a.pk in visible]
    unfinished = [a for a in opened if a.due and prev <= a.due < week_start]
    carried = [a for a in opened if a.due and a.due < prev]
    capacity = cap.team_capacity(project, week_start, end)
    # Proposition (jamais appliquée seule) : priorité, échéance, puis reliquat — dans la limite de la capacité.
    budget = Decimal(str(capacity["totals"]["productive"]))
    ranked = sorted(opened, key=lambda a: (a.status != "blocked", PRIO_RANK.get(a.prio, 2), a.due or date.max))
    planned_ids = set(WeeklyGoalAction.objects.filter(goal__plan=plan).values_list("action_id", flat=True))
    proposals, used = [], Decimal("0")
    for a in ranked:
        if a.status == "blocked":
            continue
        h = _remaining_hours(a) or Decimal("4")
        fits = used + h <= budget
        proposals.append({**action_row(a), "hours": float(h), "suggested": fits and a.pk not in planned_ids,
                          "planned": a.pk in planned_ids})
        if fits:
            used += h
    lo, hi = week_start, end
    events = list(planning.events_in(CalendarEvent.objects.filter(tenant=project.tenant), lo, hi))
    visible_ids = set(planning.visible_events(user).values_list("pk", flat=True))
    conflicts = [c for c in planning.detect_conflicts(project.tenant, events, lo, hi, visible_ids=visible_ids)
                 if any(e.project_id == project.pk for e in events if e.pk in c["events"])]
    return {
        "plan": plan_row(plan, user), "weekStart": week_start.isoformat(), "weekEnd": end.isoformat(),
        "unfinished": [action_row(a) for a in unfinished], "carriedOver": [action_row(a) for a in carried],
        "capacity": capacity, "proposals": proposals[:60], "proposedHours": float(used), "conflicts": conflicts,
    }


def action_row(a):
    return {"id": a.pk, "title": a.title, "status": a.status, "priority": a.prio, "due": a.due.isoformat() if a.due else None,
            "phase": a.phase, "owner": {"id": a.owner_id, "name": a.owner.display_name} if a.owner_id else None,
            "estimate": float(a.est or 0), "done": float(a.done or 0), "block": a.block}


def plan_row(plan, user=None):
    return {"id": plan.pk, "weekStart": plan.week_start.isoformat(), "state": plan.state, "status": plan.status,
            "statusLabel": plan.get_status_display(), "validatedBy": plan.validated_by.display_name if plan.validated_by_id else None,
            "validatedAt": plan.validated_at, "meeting": plan.meeting, "meetingEvent": plan.meeting_event_id,
            "review": plan.review, "goals": [goal_row(g) for g in plan.goals.prefetch_related("links__action__owner", "phases")]}


def goal_row(g):
    return {"id": g.pk, "title": g.title, "expectedResults": g.expected_results, "deliverables": g.deliverables,
            "phases": [{"id": p.pk, "name": p.name} for p in g.phases.all()],
            "owner": {"id": g.owner_id, "name": g.owner.display_name} if g.owner_id else None, "priority": g.priority,
            "risks": g.risks, "successCriteria": g.success_criteria, "status": g.status, "result": g.result,
            "actions": [{**action_row(link.action), "plannedHours": float(link.planned_hours or 0),
                         "carriedOver": link.carried_over} for link in g.links.all()]}


def _member_tenant(tenant, uid):
    u = User.objects.filter(pk=uid, tenant=tenant, is_active=True).first()
    if u is None:
        raise MethodError("VALIDATION_ERROR", "Collaborateur inconnu dans votre entreprise.")
    return u


def _member(project, uid):
    u = User.objects.filter(pk=uid, tenant=project.tenant, is_active=True).first()
    if uid and u is None:
        raise MethodError("VALIDATION_ERROR", "Collaborateur inconnu dans votre entreprise.")
    return u


@transaction.atomic
def save_goal(user, plan, data, goal=None):
    project = plan.project
    require(user, project, "create" if goal is None else "update", member_ok=False)
    if plan.state == "closed":
        raise MethodError("CONFLICT", "Semaine clôturée.", 409)
    goal = goal or WeeklyGoal(tenant=project.tenant, plan=plan, order=plan.goals.count())
    for field, key in (("title", "title"), ("expected_results", "expectedResults"), ("deliverables", "deliverables"),
                       ("risks", "risks"), ("success_criteria", "successCriteria"), ("result", "result")):
        if key in data:
            setattr(goal, field, str(data[key] or "")[:5000 if field != "title" else 300])
    if "priority" in data and data["priority"] in ACTION_PRIO:
        goal.priority = data["priority"]
    if "status" in data and data["status"] in dict(WeeklyGoal._meta.get_field("status").choices):
        goal.status = data["status"]
    if "owner" in data:
        goal.owner = _member(project, data["owner"])
    if not goal.title.strip():
        raise MethodError("VALIDATION_ERROR", "L'objectif doit être formulé.")
    goal.save()
    if "phases" in data:
        goal.phases.set(VPhase.objects.filter(project=project, pk__in=data["phases"] or []))
    if "actions" in data:
        keep = []
        prev_week = plan.week_start - timedelta(days=7)
        for item in data["actions"] or []:
            a = visible_actions(user).filter(project=project, pk=item.get("action")).first()
            if a is None:
                raise MethodError("VALIDATION_ERROR", "Action introuvable dans ce projet.")
            carried = bool(a.due and a.due < plan.week_start and a.status != "done") or \
                WeeklyGoalAction.objects.filter(goal__plan__project=project, goal__plan__week_start=prev_week, action=a).exists()
            WeeklyGoalAction.objects.update_or_create(goal=goal, action=a, defaults={
                "tenant": project.tenant, "planned_hours": item.get("hours"), "carried_over": carried})
            keep.append(a.pk)
        goal.links.exclude(action_id__in=keep).delete()
    return goal


def delete_goal(user, goal):
    require(user, goal.plan.project, "delete", member_ok=False)
    if goal.plan.state == "closed":
        raise MethodError("CONFLICT", "Semaine clôturée.", 409)
    goal.delete()


def assign_actions(user, plan, items, confirm=False):
    """Affectation des actions de la semaine via le calendrier (conflits et surcharge expliqués, jamais forcés)."""
    project = plan.project
    require(user, project, "update", member_ok=False)
    start, end = plan.week_start, plan.week_start + timedelta(days=4)
    saved = []
    for item in items:
        a = visible_actions(user).filter(project=project, pk=item.get("action")).first()
        if a is None:
            raise MethodError("VALIDATION_ERROR", "Action introuvable.")
        event = CalendarEvent.objects.filter(action=a).first()
        data = {"assignments": [{"user": int(item["user"]), "role": "owner", "estimatedWorkload": item.get("hours")}]}
        if not event:
            data.update({"action": a.pk, "start": max(start, a.start_date or start).isoformat(),
                         "end": min(end, a.due or end).isoformat() if (a.due or end) >= start else end.isoformat(), "allDay": True})
        try:
            saved.append(planning.save_event(user, data, event=event, confirm=confirm))
        except planning.ConflictsPending as exc:
            raise MethodError("CALENDAR_CONFLICTS", f"« {a.title} » : {exc.message}", 409, exc.conflicts) from exc
        except planning.PlanningError as exc:
            raise MethodError(exc.code, exc.message, exc.http_status, exc.details) from exc
    return saved


@transaction.atomic
def validate_week(user, plan, confirm=False):
    project = plan.project
    require(user, project, "approve")
    if not plan.goals.exists():
        raise MethodError("VALIDATION_ERROR", "Définissez au moins un objectif de la semaine avant de valider.")
    end = plan.week_start + timedelta(days=4)
    c = cap.team_capacity(project, plan.week_start, end)
    if c["overloaded"] and not confirm:
        raise MethodError("CAPACITY_OVERLOAD", "Des collaborateurs sont surchargés cette semaine : confirmez ou réaffectez.", 409,
                          [{"user": m["user"], "planned": m["planned"], "available": m["productive"]}
                           for m in c["members"] if m["state"] == "over"])
    plan.state, plan.validated_by, plan.validated_at = "validated", user, timezone.now()
    if plan.status == "not_started" and timezone.localdate() >= plan.week_start:
        plan.status = "in_progress"
    plan.save()
    TeamCapacity.objects.create(tenant=project.tenant, project=project, start=plan.week_start, end=end, weekly_plan=plan,
                                theoretical=c["totals"]["theoretical"], available=c["totals"]["productive"],
                                planned=c["totals"]["planned"], details={"members": c["members"]})
    members = _team(project) or ([project.pm] if project.pm_id else [])
    notify("weekly_planning", [u for u in members if u.pk != user.pk], f"Semaine validée — {project.code}",
           " · ".join(g.title for g in plan.goals.all())[:500])
    audit.record(user, f"Projet {project.code}", "Planning de la semaine validé", "", plan.week_start.isoformat())
    return plan


def track_week(plan):
    """Suivi : actions prévues / terminées / en cours / bloquées / reportées, charge prévue et consommée."""
    end = plan.week_start + timedelta(days=4)
    goals, totals = [], Counter()
    planned_h = consumed_h = Decimal("0")
    for g in plan.goals.prefetch_related("links__action"):
        acts = [link.action for link in g.links.all()]
        st = Counter(a.status for a in acts)
        reported = [a for a in acts if a.status != "done" and a.due and a.due <= end and plan.state == "closed"]
        hours = sum((Decimal(link.planned_hours or 0) for link in g.links.all()), Decimal("0"))
        used = TimeEntry.objects.filter(action__in=acts, work_date__range=(plan.week_start, end)).aggregate(h=Sum("hours"))["h"] or 0
        done = st.get("done", 0)
        rate = round(done / len(acts) * 100) if acts else 0
        suggested = "not_started" if not acts or (done == 0 and not st.get("doing")) else (
            "achieved" if done == len(acts) else "partial" if done else "in_progress")
        goals.append({"id": g.pk, "title": g.title, "status": g.status, "suggestedStatus": suggested, "planned": len(acts),
                      "done": done, "doing": st.get("doing", 0) + st.get("review", 0), "blocked": st.get("blocked", 0),
                      "reported": len(reported), "plannedHours": float(hours), "consumedHours": float(used), "rate": rate})
        totals.update({"planned": len(acts), "done": done, "doing": st.get("doing", 0) + st.get("review", 0),
                       "blocked": st.get("blocked", 0), "reported": len(reported)})
        planned_h += hours
        consumed_h += Decimal(used)
    deliverables = sum(1 for g in plan.goals.all() if g.status == "achieved" and g.deliverables)
    return {"goals": goals, "totals": dict(totals), "plannedHours": float(planned_h), "consumedHours": float(consumed_h),
            "rate": round(totals["done"] / totals["planned"] * 100) if totals["planned"] else 0,
            "deliverablesDone": deliverables, "status": plan.status}


@transaction.atomic
def close_week(user, plan, data):
    """Bilan automatique de fin de semaine : prévu / obtenu, écarts, causes, risques, actions correctives."""
    project = plan.project
    require(user, project, "approve")
    t = track_week(plan)
    statuses = data.get("goalStatuses") or {}
    gaps = []
    for g in plan.goals.prefetch_related("links__action"):
        chosen = statuses.get(str(g.pk))
        if chosen in dict(WeeklyGoal._meta.get_field("status").choices):
            g.status = chosen
        elif g.status in ("not_started", "in_progress"):
            g.status = next(x["suggestedStatus"] for x in t["goals"] if x["id"] == g.pk)
        if g.status == "in_progress":
            g.status = "partial"
        g.save(update_fields=["status"])
        for link in g.links.all():
            a = link.action
            if a.status != "done":
                gaps.append({"goal": g.title, "action": a.title, "status": a.status, "cause": a.block or "",
                             "owner": a.owner.display_name if a.owner_id else None})
    values = [g.status for g in plan.goals.all()]
    plan.status = "achieved" if values and all(v == "achieved" for v in values) else (
        "missed" if values and all(v in ("missed", "not_started") for v in values) else "partial")
    plan.review = {
        "generatedAt": timezone.now().isoformat(), "by": user.display_name, "tracking": t, "gaps": gaps,
        "causes": str(data.get("causes", ""))[:4000] or "; ".join(sorted({x["cause"] for x in gaps if x["cause"]}))[:4000],
        "risks": str(data.get("risks", ""))[:4000], "correctiveActions": str(data.get("correctiveActions", ""))[:4000],
        "summary": f"{t['totals'].get('done', 0)} action(s) terminée(s) sur {t['totals'].get('planned', 0)} ; "
                   f"{t['consumedHours']:.1f} h consommées pour {t['plannedHours']:.1f} h prévues ; "
                   f"objectifs : {', '.join(f'{g.title} ({g.get_status_display()})' for g in plan.goals.all())}.",
    }
    plan.state = "closed"
    plan.save()
    audit.record(user, f"Projet {project.code}", "Semaine clôturée", "", f"{plan.week_start} · {plan.get_status_display()}")
    return plan


def save_meeting(user, plan, data):
    """Réunion hebdomadaire : ordre du jour, participants, décisions ; ses actions deviennent des actions PCT."""
    project = plan.project
    require(user, project, "update", member_ok=False)
    meeting = dict(plan.meeting or {})
    for key in ("agenda", "objectives", "progress", "problems", "decisions"):
        if key in data:
            meeting[key] = str(data[key] or "")[:8000]
    if "participants" in data:
        meeting["participants"] = [u.pk for u in User.objects.filter(pk__in=data["participants"] or [], tenant=project.tenant)]
    created = []
    for item in data.get("actions") or []:
        if not str(item.get("title", "")).strip():
            continue
        created.append(_new_action(project, user, item["title"], _member(project, item.get("owner")),
                                   _date(item.get("due")), "Réunion hebdomadaire", item.get("priority", "normal")).pk)
    meeting["actions"] = list(meeting.get("actions", [])) + created
    if data.get("schedule") and not plan.meeting_event_id:
        s = settings_of(project)
        day = plan.week_start + timedelta(days=int(s["weeklyPlanningDay"]))
        start = _at(project, day, s["weeklyPlanningTime"])
        users = list(User.objects.filter(pk__in=meeting.get("participants") or [])) or _team(project)
        ev = _event(project, user, f"Réunion hebdomadaire — {project.code}", start, start + timedelta(minutes=60),
                    users=users, owner=user, description=meeting.get("agenda", ""))
        plan.meeting_event = ev
    meeting["report"] = meeting_report(project, plan, meeting)
    plan.meeting = meeting
    plan.save(update_fields=["meeting", "meeting_event"])
    return plan


def meeting_report(project, plan, m):
    names = ", ".join(u.display_name for u in User.objects.filter(pk__in=m.get("participants") or []))
    acts = Action.objects.filter(pk__in=m.get("actions") or []).select_related("owner")
    lines = [f"Compte rendu — réunion hebdomadaire {project.code}, semaine du {plan.week_start:%d/%m/%Y}",
             f"Participants : {names or '—'}", "", f"Ordre du jour : {m.get('agenda', '')}",
             f"Objectifs : {m.get('objectives', '')}", f"Avancement : {m.get('progress', '')}",
             f"Problèmes : {m.get('problems', '')}", f"Décisions : {m.get('decisions', '')}", "", "Actions :"]
    lines += [f"- {a.title} — {a.owner.display_name if a.owner_id else 'sans responsable'}"
              f"{f' — échéance {a.due:%d/%m/%Y}' if a.due else ''}" for a in acts] or ["- aucune"]
    return "\n".join(lines)


def _date(v):
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError as exc:
        raise MethodError("VALIDATION_ERROR", f"Date invalide : {v}.") from exc


def _new_action(project, by, title, owner, due, kind, priority="normal"):
    for _ in range(5):
        pk = f"A-{secrets.token_hex(4).upper()}"
        if not Action.objects.filter(pk=pk).exists():
            break
    a = Action.objects.create(tenant=project.tenant, id=pk, project=project, title=str(title)[:300], owner=owner,
                              status="todo", type=kind, due=due, prio=ACTION_PRIO.get(priority, "Normale"),
                              history=[{"at": timezone.now().isoformat(), "by": by.username, "event": f"Créée ({kind})"}])
    return a


# --------------------------------------------------------------------------- phases Cycle en V
def save_phase(user, project, data, phase=None):
    require(user, project, "update" if phase else "create", member_ok=False)
    require_feature(project, "phases")
    phase = phase or VPhase(tenant=project.tenant, project=project, order=VPhase.objects.filter(project=project).count())
    for f in ("name", "validation_criteria", "risks"):
        key = {"validation_criteria": "validationCriteria"}.get(f, f)
        if key in data:
            setattr(phase, f, str(data[key] or "")[:5000 if f != "name" else 120])
    for f, key in (("start", "start"), ("end", "end"), ("forecast_end", "forecastEnd")):
        if key in data:
            setattr(phase, f, _date(data[key]))
    if "owner" in data:
        phase.owner = _member(project, data["owner"])
    if "status" in data and data["status"] in dict(VPhase._meta.get_field("status").choices):
        phase.status = data["status"]
    if "progress" in data:
        phase.progress = max(0, min(100, int(data["progress"])))
    if "deliverables" in data:
        phase.deliverables = [{"title": str(d.get("title", ""))[:200], "done": bool(d.get("done")),
                               "document": d.get("document")} for d in data["deliverables"] if d.get("title")]
    if "order" in data:
        phase.order = int(data["order"])
    if not phase.name.strip():
        raise MethodError("VALIDATION_ERROR", "Nom de phase obligatoire.")
    if phase.start and phase.end and phase.end < phase.start:
        raise MethodError("VALIDATION_ERROR", "La fin de phase précède son début.")
    phase.save()
    if "dependsOn" in data:
        phase.depends_on.set(VPhase.objects.filter(project=project, pk__in=data["dependsOn"] or []).exclude(pk=phase.pk))
    return phase


# --------------------------------------------------------------------------- Scrum : backlog
def _log(obj, user, event, **extra):
    obj.history = (obj.history or [])[-199:] + [{"at": timezone.now().isoformat(), "by": user.username, "event": event, **extra}]


def can_prioritize(user, project):
    return scrum_role(user, project) == "po" or allowed(user, project, "approve")


BACKLOG_FIELDS = {"title": "title", "description": "description", "userStory": "user_story", "acceptance": "acceptance",
                  "team": "team", "key": "key"}


@transaction.atomic
def save_item(user, project, data, item=None):
    require(user, project, "create" if item is None else "update")
    require_feature(project, "scrum")
    creating = item is None
    if creating:
        last = ProductBacklogItem.objects.filter(project=project).order_by("-rank").first()
        item = ProductBacklogItem(tenant=project.tenant, project=project, rank=(last.rank + 1) if last else 1)
    changes = []
    for key, field in BACKLOG_FIELDS.items():
        if key in data:
            value = str(data[key] or "")[:300 if field in ("title",) else 120 if field == "team" else 20 if field == "key" else 8000]
            if getattr(item, field) != value:
                changes.append(key)
                setattr(item, field, value)
    if "kind" in data:
        if data["kind"] not in dict(ProductBacklogItem._meta.get_field("kind").choices):
            raise MethodError("VALIDATION_ERROR", "Type d'élément inconnu.")
        item.kind = data["kind"]
    if "priority" in data and data["priority"] in ACTION_PRIO:
        changes.append("priority")
        item.priority = data["priority"]
    for key, field in (("storyPoints", "story_points"), ("estimateHours", "estimate_hours")):
        if key in data:
            v = data[key]
            v = None if v in (None, "") else Decimal(str(v))
            if v is not None and v < 0:
                raise MethodError("VALIDATION_ERROR", "Estimation négative.")
            if getattr(item, field) != v:
                changes.append(key)
                setattr(item, field, v)
    if "status" in data:
        if data["status"] not in ("new", "ready", "removed", "done"):
            raise MethodError("VALIDATION_ERROR", "Statut non modifiable ici (la sélection passe par le Sprint Planning).")
        changes.append("status")
        item.status = data["status"]
    if "assignee" in data:
        item.assignee = _member(project, data["assignee"])
        changes.append("assignee")
    if "parent" in data:
        parent = ProductBacklogItem.objects.filter(project=project, pk=data["parent"], kind__in=("epic", "feature")).first() \
            if data["parent"] else None
        if data["parent"] and parent is None:
            raise MethodError("VALIDATION_ERROR", "Parent introuvable (Epic ou Feature du projet).")
        item.parent = parent
    if not item.title.strip():
        raise MethodError("VALIDATION_ERROR", "Titre obligatoire.")
    _log(item, user, "Créé" if creating else "Modifié", fields=changes)
    item.save()
    if "dependencies" in data:
        deps = ProductBacklogItem.objects.filter(project=project, pk__in=data["dependencies"] or []).exclude(pk=item.pk)
        item.dependencies.set(deps)
    if "attachments" in data:
        from projects.access import visible
        from projects.models import Document
        item.attachments.set(visible(user, Document).filter(project=project, pk__in=data["attachments"] or []))
    return item


@transaction.atomic
def reorder(user, project, ids):
    """Priorisation (glisser-déposer) : Product Owner, ou droit « Méthodologie · Valider »."""
    require(user, project, "update")
    if not can_prioritize(user, project):
        raise forbid("Seul le Product Owner (ou un responsable habilité) priorise le backlog.")
    items = {i.pk: i for i in ProductBacklogItem.objects.filter(project=project, pk__in=ids)}
    if len(items) != len(set(ids)):
        raise MethodError("VALIDATION_ERROR", "Élément inconnu dans la liste.")
    rest = ProductBacklogItem.objects.filter(project=project).exclude(pk__in=ids).order_by("rank", "id")
    order = [items[i] for i in ids] + list(rest)
    for rank, item in enumerate(order, start=1):
        if item.rank != rank:
            if item.pk in items:
                _log(item, user, "Priorité modifiée", **{"from": item.rank, "to": rank})
            item.rank = rank
            item.save(update_fields=["rank", "history"])


# --------------------------------------------------------------------------- Scrum : sprints
def sprint_for(user, pk):
    s = Sprint.objects.select_related("project").filter(pk=pk).first()
    if s is None or s.project_id not in set(visible_projects(user).values_list("pk", flat=True)):
        raise MethodError("NOT_FOUND", "Sprint introuvable.", 404)
    return s


@transaction.atomic
def create_sprint(user, project, data):
    require(user, project, "create", member_ok=False)
    require_feature(project, "scrum")
    last = Sprint.objects.filter(project=project).order_by("-number").first()
    weeks = int(data.get("weeks") or settings_of(project)["sprintWeeks"])
    if weeks not in (1, 2, 3, 4):
        raise MethodError("VALIDATION_ERROR", "Durée de sprint : 1 à 4 semaines.")
    start = _date(data.get("start")) or (week_of(last.end + timedelta(days=3)) if last else week_of(timezone.localdate() + timedelta(days=7)))
    end = _date(data.get("end")) or start + timedelta(days=weeks * 7 - 3)
    if end < start:
        raise MethodError("VALIDATION_ERROR", "La fin précède le début.")
    overlap = Sprint.objects.filter(project=project, start__lte=end, end__gte=start).exclude(status="cancelled")
    if overlap.exists() and not data.get("confirm"):
        raise MethodError("SPRINT_OVERLAP", "Ce sprint chevauche un autre sprint du projet.", 409,
                          [{"sprint": s.label, "start": s.start.isoformat(), "end": s.end.isoformat()} for s in overlap])
    s = Sprint.objects.create(tenant=project.tenant, project=project, number=(last.number + 1) if last else 1, start=start,
                              end=end, name=str(data.get("name") or "")[:120], team=str(data.get("team") or "")[:120],
                              status="preparing")
    if data.get("goal"):
        SprintGoal.objects.create(tenant=project.tenant, sprint=s, objective=str(data["goal"]))
    s.events = {"planning": _event(project, user, f"Sprint Planning — {s.label} ({project.code})", _at(project, start, "09:30"),
                                   _at(project, start, "11:30"), users=_team(project), owner=user).pk}
    s.save(update_fields=["events"])
    _remind(project, "sprint_planning", _at(project, start, "09:30") - timedelta(hours=24), _team(project),
            f"Sprint Planning demain — {s.label}", project.code, key=f"sprint_planning:{s.pk}", sprint=s)
    audit.record(user, f"Projet {project.code}", "Sprint créé", "", f"{s.label} {start} → {end}")
    return s


def velocity_history(project, before=None, limit=6):
    qs = Sprint.objects.filter(project=project, status="done").exclude(completed_points__isnull=True)
    if before:
        qs = qs.filter(number__lt=before.number)
    rows = list(qs.order_by("-number")[:limit])[::-1]
    values = [float(s.completed_points) for s in rows]
    recent = values[-3:]
    return {"sprints": [{"number": s.number, "label": s.label, "committed": float(s.committed_points or 0),
                         "completed": float(s.completed_points)} for s in rows],
            "average": round(sum(recent) / len(recent), 1) if recent else None}


def sprint_capacity(sprint):
    c = cap.team_capacity(sprint.project, sprint.start, sprint.end, scrum_only=True)
    if not c["members"]:
        c = cap.team_capacity(sprint.project, sprint.start, sprint.end)
    return c


def planning_view(user, sprint):
    """Assistant de Sprint Planning : rien n'est sélectionné sans validation du PO et de l'équipe."""
    project = sprint.project
    require(user, project, "read")
    require_feature(project, "scrum")
    backlog = list(ProductBacklogItem.objects.filter(project=project).exclude(status__in=("done", "removed"))
                   .exclude(kind="epic").prefetch_related("dependencies").select_related("parent", "assignee"))
    selected = {e.item_id: e for e in sprint.items.filter(removed_at__isnull=True)}
    vel = velocity_history(project, sprint)
    capacity = sprint_capacity(sprint)
    budget = Decimal(str(vel["average"])) if vel["average"] else None
    hours = Decimal(str(capacity["totals"]["productive"]))
    used_pts = used_h = Decimal("0")
    rows = []
    for item in backlog:
        if item.status == "selected" and item.pk not in selected:
            continue  # déjà dans un autre sprint
        pts = item.story_points or Decimal("0")
        h = item.estimate_hours or Decimal("0")
        fits = (budget is None or used_pts + pts <= budget) and (not h or used_h + h <= hours)
        if fits and item.status == "ready":
            used_pts += pts
            used_h += h
        rows.append({**item_row(item), "selected": item.pk in selected,
                     "suggested": fits and item.status == "ready" and item.pk not in selected})
    sel_pts = sum((e.points or 0) for e in selected.values())
    sel_h = sum((e.item.estimate_hours or 0) for e in sprint.items.filter(removed_at__isnull=True).select_related("item"))
    return {"sprint": sprint_row(sprint, user), "backlog": rows, "velocity": vel, "capacity": capacity,
            "selectedPoints": float(sel_pts), "selectedHours": float(sel_h),
            "dependencyIssues": dependency_issues(sprint), "canPrioritize": can_prioritize(user, project),
            "myScrumRole": scrum_role(user, project)}


def dependency_issues(sprint):
    out = []
    chosen = set(sprint.items.filter(removed_at__isnull=True).values_list("item_id", flat=True))
    for e in sprint.items.filter(removed_at__isnull=True).select_related("item").prefetch_related("item__dependencies"):
        for d in e.item.dependencies.all():
            if d.status != "done" and d.pk not in chosen:
                out.append({"item": e.item.title, "dependsOn": d.title, "status": d.get_status_display()})
    return out


@transaction.atomic
def select_items(user, sprint, ids, confirm=False):
    project = sprint.project
    require(user, project, "update")
    if sprint.status in ("done", "cancelled"):
        raise MethodError("CONFLICT", "Sprint terminé.", 409)
    items = list(ProductBacklogItem.objects.filter(project=project, pk__in=ids).exclude(status__in=("done", "removed")))
    if len(items) != len(set(ids)):
        raise MethodError("VALIDATION_ERROR", "Élément indisponible (terminé, retiré ou d'un autre projet).")
    other = SprintBacklogItem.objects.filter(item__in=items, removed_at__isnull=True,
                                             sprint__status__in=("preparing", "planned", "active")).exclude(sprint=sprint)
    if other.exists():
        raise MethodError("VALIDATION_ERROR", "Un élément est déjà dans un autre sprint ouvert.")
    pts = sum((i.story_points or 0) for i in items)
    hrs = sum((i.estimate_hours or 0) for i in items)
    vel = velocity_history(project, sprint)["average"]
    capacity = sprint_capacity(sprint)["totals"]["productive"]
    warnings = []
    if vel and pts > Decimal(str(vel)) * Decimal("1.2"):
        warnings.append({"type": "points", "message": f"{pts} points sélectionnés pour une vélocité moyenne de {vel}."})
    if hrs and hrs > Decimal(str(capacity)):
        warnings.append({"type": "capacity", "message": f"{hrs} h estimées pour {capacity} h de capacité productive."})
    now = timezone.now()
    current = {e.item_id: e for e in sprint.items.all()}
    for idx, item in enumerate(items):
        e = current.get(item.pk)
        if e is None:
            SprintBacklogItem.objects.create(tenant=project.tenant, sprint=sprint, item=item, points=item.story_points,
                                             assignee=item.assignee, added_at=now, order=idx,
                                             column=settings_of(project)["boardColumns"][0]["key"])
        elif e.removed_at:
            e.removed_at, e.added_at = None, now
            e.save(update_fields=["removed_at", "added_at"])
        item.status = "selected"
        item.save(update_fields=["status"])
    for item_id, e in current.items():
        if item_id not in {i.pk for i in items} and not e.removed_at:
            if sprint.status == "active":
                e.removed_at = now  # traçabilité du périmètre en cours de sprint
                e.save(update_fields=["removed_at"])
            else:
                e.delete()
            ProductBacklogItem.objects.filter(pk=item_id, status="selected").update(status="ready")
    deps = dependency_issues(sprint)
    if (warnings or deps) and not confirm:
        transaction.set_rollback(True)
        raise MethodError("SPRINT_CHECKS", "Vérifications du Sprint Backlog : confirmez ou ajustez la sélection.", 409,
                          warnings + [{"type": "dependency", "message": f"« {d['item']} » dépend de « {d['dependsOn']} » ({d['status']})."} for d in deps])
    sprint.committed_points = pts
    sprint.po_validated_at = sprint.team_validated_at = None  # toute modification redemande les validations
    sprint.po_validated_by = sprint.team_validated_by = None
    if sprint.status == "preparing" and items:
        sprint.status = "planned"
    sprint.save()
    return sprint


@transaction.atomic
def save_goal_sprint(user, sprint, data):
    project = sprint.project
    require(user, project, "update")
    goal = getattr(sprint, "goal", None) or SprintGoal(tenant=project.tenant, sprint=sprint, objective="")
    for key, field in (("objective", "objective"), ("value", "value"), ("expectedResults", "expected_results"),
                       ("successCriteria", "success_criteria"), ("risks", "risks")):
        if key in data:
            setattr(goal, field, str(data[key] or "")[:5000])
    if "owner" in data:
        goal.owner = _member(project, data["owner"])
    if "status" in data and data["status"] in dict(SprintGoal.STATES):
        goal.status = data["status"]
    if "progress" in data:
        goal.progress = max(0, min(100, int(data["progress"])))
    if not goal.objective.strip():
        raise MethodError("VALIDATION_ERROR", "Formulez l'objectif du sprint (un résultat, pas une liste de tâches).")
    goal.save()
    if "items" in data:
        goal.items.set(ProductBacklogItem.objects.filter(project=project, pk__in=data["items"] or []))
    ev = sprint.events.get("sprint")
    if ev:
        CalendarEvent.objects.filter(pk=ev).update(title=f"{sprint.label} — {goal.objective}"[:300])
    return goal


def validate_sprint(user, sprint, role):
    project = sprint.project
    require(user, project, "read")
    if not has_perm(user, "methodology", "update"):
        raise forbid()
    mine = scrum_role(user, project)
    if role == "po":
        has_po = TeamMemberAllocation.objects.filter(project=project, scrum_role="po", active=True).exists()
        if mine != "po" and (has_po or not allowed(user, project, "approve")):
            raise forbid("La validation du Product Owner est réservée au Product Owner de l'équipe.")
        sprint.po_validated_by, sprint.po_validated_at = user, timezone.now()
    elif role == "team":
        if mine not in ("sm", "dev") and not allowed(user, project, "approve"):
            raise forbid("L'engagement de l'équipe est porté par le Scrum Master ou un développeur.")
        sprint.team_validated_by, sprint.team_validated_at = user, timezone.now()
    else:
        raise MethodError("VALIDATION_ERROR", "Validation « po » ou « team ».")
    sprint.save()
    return sprint


@transaction.atomic
def start_sprint(user, sprint):
    project = sprint.project
    require(user, project, "approve")
    goal = getattr(sprint, "goal", None)
    missing = []
    if not goal or not goal.objective.strip():
        missing.append("Sprint Goal")
    if not sprint.items.filter(removed_at__isnull=True).exists():
        missing.append("Sprint Backlog")
    if not sprint.po_validated_at:
        missing.append("validation du Product Owner")
    if not sprint.team_validated_at:
        missing.append("engagement de l'équipe")
    if missing:
        raise MethodError("VALIDATION_ERROR", f"Avant de démarrer : {', '.join(missing)}.")
    if Sprint.objects.filter(project=project, status="active").exclude(pk=sprint.pk).exists():
        raise MethodError("CONFLICT", "Un autre sprint est en cours : clôturez-le d'abord.", 409)
    c = sprint_capacity(sprint)
    sprint.capacity_hours = Decimal(str(c["totals"]["productive"]))
    sprint.status, sprint.started_at = "active", timezone.now()
    TeamCapacity.objects.create(tenant=project.tenant, project=project, start=sprint.start, end=sprint.end, sprint=sprint,
                                theoretical=c["totals"]["theoretical"], available=c["totals"]["productive"],
                                planned=c["totals"]["planned"], details={"members": c["members"]})
    _ceremonies(user, sprint)
    sprint.save()
    notify("sprint_planning", [u for u in _team(project) if u.pk != user.pk], f"{sprint.label} démarré — {project.code}",
           goal.objective[:500])
    audit.record(user, f"Projet {project.code}", "Sprint démarré", "", sprint.label)
    return sprint


def _ceremonies(user, sprint):
    """Cérémonies dans le calendrier et rappels (idempotent)."""
    project, s = sprint.project, settings_of(sprint.project)
    team = _team(project)
    sm = _team(project, ["sm"])
    ev = dict(sprint.events or {})
    goal = getattr(sprint, "goal", None)
    tz = _tz(project)
    if not ev.get("sprint"):
        ev["sprint"] = _event(project, user, f"{sprint.label} — {goal.objective if goal else ''}",
                              datetime.combine(sprint.start, time.min, tzinfo=tz),
                              datetime.combine(sprint.end + timedelta(days=1), time.min, tzinfo=tz),
                              kind="task", users=team, all_day=True, description="Sprint Goal").pk
    if not ev.get("review"):
        start = _at(project, sprint.end, "14:00")
        ev["review"] = _event(project, user, f"Sprint Review — {sprint.label}", start, start + timedelta(hours=1, minutes=30),
                              users=team, owner=sm[0] if sm else user).pk
        _remind(project, "sprint_review", start - timedelta(hours=24), team, f"Sprint Review demain — {sprint.label}",
                project.code, key=f"sprint_review:{sprint.pk}", sprint=sprint)
    if s["dailyInCalendar"] and not ev.get("daily"):
        ids = []
        for d in working_days(sprint.start, sprint.end):
            start = _at(project, d, s["dailyTime"])
            ids.append(_event(project, user, f"Daily Scrum — {sprint.label}", start, start + timedelta(minutes=int(s["dailyMinutes"])),
                              users=team, owner=sm[0] if sm else None).pk)
            _remind(project, "daily", start - timedelta(minutes=15), team, f"Daily Scrum dans 15 min — {sprint.label}",
                    project.code, key=f"daily:{sprint.pk}:{d.isoformat()}", sprint=sprint)
        ev["daily"] = ids
    _remind(project, "sprint_close", _at(project, sprint.end, "17:00"), sm or ([project.pm] if project.pm_id else []),
            f"Clôture du sprint aujourd'hui — {sprint.label}", project.code, key=f"sprint_close:{sprint.pk}", sprint=sprint)
    sprint.events = ev


def board_columns(project):
    return settings_of(project)["boardColumns"] or DEFAULT_COLUMNS


@transaction.atomic
def move_item(user, entry, data):
    sprint, project = entry.sprint, entry.sprint.project
    require(user, project, "update")
    if sprint.status not in ("planned", "active"):
        raise MethodError("CONFLICT", "Le tableau n'est modifiable que pour un sprint planifié ou en cours.", 409)
    cols = {c["key"]: c for c in board_columns(project)}
    now = timezone.now()
    if "column" in data and data["column"] != entry.column:
        if data["column"] not in cols:
            raise MethodError("VALIDATION_ERROR", "Colonne inconnue.")
        _log(entry, user, "Déplacé", **{"from": entry.column, "to": data["column"]})
        entry.column = data["column"]
        done = cols[entry.column]["done"]
        entry.done_at = (entry.done_at or now) if done else None
        entry.item.status = "done" if done else "selected"
        entry.item.save(update_fields=["status"])
    if "order" in data:
        entry.order = max(0, int(data["order"]))
    if "assignee" in data:
        entry.assignee = _member(project, data["assignee"])
        _log(entry, user, "Affecté", to=entry.assignee.display_name if entry.assignee else None)
    if "blocked" in data:
        entry.blocked = bool(data["blocked"])
        entry.block_reason = str(data.get("blockReason") or "")[:300] if entry.blocked else ""
        _log(entry, user, "Bloqué" if entry.blocked else "Débloqué", reason=entry.block_reason)
    if "remainingHours" in data:
        entry.remaining_hours = None if data["remainingHours"] in (None, "") else Decimal(str(data["remainingHours"]))
    entry.save()
    return entry


def save_daily(user, sprint, day, data):
    project = sprint.project
    require(user, project, "create")
    if not sprint.start <= day <= sprint.end:
        raise MethodError("VALIDATION_ERROR", "Date hors du sprint.")
    daily, _ = ScrumDaily.objects.get_or_create(sprint=sprint, date=day, defaults={"tenant": project.tenant})
    if "notes" in data:
        daily.notes = str(data["notes"] or "")[:8000]
        daily.save(update_fields=["notes"])
    if "entry" in data:
        e, _ = ScrumDailyEntry.objects.get_or_create(daily=daily, user=user, defaults={"tenant": project.tenant})
        d = data["entry"] or {}
        for key, field in (("progress", "progress"), ("plan", "plan"), ("impediment", "impediment"), ("resolution", "resolution")):
            if key in d:
                setattr(e, field, str(d[key] or "")[:4000])
        if "impedimentStatus" in d and d["impedimentStatus"] in dict(ScrumDailyEntry.IMPEDIMENT):
            e.impediment_status = d["impedimentStatus"]
        elif e.impediment and not e.impediment_status:
            e.impediment_status = "open"
        if "resolutionOwner" in d:
            e.resolution_owner = _member(project, d["resolutionOwner"])
        if "resolutionDue" in d:
            e.resolution_due = _date(d["resolutionDue"])
        e.save()
    return daily


def update_impediment(user, entry, data):
    require(user, entry.daily.sprint.project, "update")
    if "status" in data and data["status"] in dict(ScrumDailyEntry.IMPEDIMENT):
        entry.impediment_status = data["status"]
    if "resolution" in data:
        entry.resolution = str(data["resolution"] or "")[:4000]
    if "resolutionOwner" in data:
        entry.resolution_owner = _member(entry.daily.sprint.project, data["resolutionOwner"])
    if "resolutionDue" in data:
        entry.resolution_due = _date(data["resolutionDue"])
    entry.save()
    return entry


def save_review(user, sprint, data):
    project = sprint.project
    require(user, project, "update")
    r = getattr(sprint, "review", None) or SprintReview(tenant=project.tenant, sprint=sprint)
    for key, field in (("increment", "increment"), ("demos", "demos"), ("feedback", "feedback"), ("decisions", "decisions"),
                       ("backlogChanges", "backlog_changes")):
        if key in data:
            setattr(r, field, str(data[key] or "")[:8000])
    if data.get("held"):
        r.held_at = r.held_at or timezone.now()
    r.report = review_report(sprint, r)
    r.save()
    return r


def review_report(sprint, r):
    entries = sprint.items.filter(removed_at__isnull=True).select_related("item")
    done = [e.item for e in entries if e.done_at]
    undone = [e.item for e in entries if not e.done_at]
    goal = getattr(sprint, "goal", None)
    return "\n".join([
        f"Sprint Review — {sprint.label} ({sprint.project.code}), {sprint.start:%d/%m} → {sprint.end:%d/%m/%Y}",
        f"Objectif initial : {goal.objective if goal else '—'} ({goal.get_status_display() if goal else '—'})", "",
        f"Incrément réalisé : {r.increment}", "User Stories terminées :", *([f"- {i.key or ''} {i.title}" for i in done] or ["- aucune"]),
        "User Stories non terminées :", *([f"- {i.key or ''} {i.title}" for i in undone] or ["- aucune"]), "",
        f"Démonstrations : {r.demos}", f"Retours des parties prenantes : {r.feedback}", f"Décisions : {r.decisions}",
        f"Évolutions du Product Backlog : {r.backlog_changes}"])


@transaction.atomic
def close_sprint(user, sprint, data):
    project = sprint.project
    require(user, project, "approve")
    if sprint.status != "active":
        raise MethodError("CONFLICT", "Seul un sprint en cours peut être clôturé.", 409)
    goal = getattr(sprint, "goal", None)
    status = data.get("goalStatus")
    if status not in ("achieved", "partial", "missed"):
        raise MethodError("VALIDATION_ERROR", "Indiquez explicitement si le Sprint Goal est atteint (il ne se déduit pas des tâches).")
    if goal:
        goal.status = status
        goal.save(update_fields=["status", "updated_at"])
    entries = list(sprint.items.filter(removed_at__isnull=True).select_related("item"))
    sprint.completed_points = sum((e.points or 0) for e in entries if e.done_at)
    target = data.get("unfinished", "backlog")
    nxt = Sprint.objects.filter(project=project, number__gt=sprint.number, status__in=("preparing", "planned")).order_by("number").first()
    now = timezone.now()
    for e in entries:
        if e.done_at:
            continue
        if target == "next" and nxt:
            SprintBacklogItem.objects.get_or_create(sprint=nxt, item=e.item, defaults={
                "tenant": project.tenant, "points": e.item.story_points, "added_at": now, "assignee": e.assignee,
                "column": board_columns(project)[0]["key"]})
        else:
            e.item.status = "ready"
            e.item.save(update_fields=["status"])
    sprint.status, sprint.closed_at = "done", now
    sprint.save()
    retro = None
    if settings_of(project)["retroFrequency"] == "sprint" or "scrum" in methodology(project).enabled():
        when = _at(project, sprint.end, "16:00")
        if when < now:
            d = timezone.localdate() + timedelta(days=1)
            while d.weekday() >= 5:
                d += timedelta(days=1)
            when = _at(project, d, "10:00")
        retro = create_retro(user, project, {"trigger": "sprint", "sprint": sprint.pk, "scheduledAt": when.isoformat(),
                                             "title": f"Rétrospective — {sprint.label}"}, dedupe=f"sprint:{sprint.pk}")
    audit.record(user, f"Projet {project.code}", "Sprint clôturé", "", f"{sprint.label} · objectif {status}")
    return sprint, retro


def sprint_metrics(sprint):
    """Indicateurs du sprint calculés depuis les données réelles (jamais déduits du seul % de tâches)."""
    project = sprint.project
    today = timezone.localdate()
    days_ = working_days(sprint.start, sprint.end)
    elapsed = sum(1 for d in days_ if d <= today)
    entries = list(sprint.items.select_related("item", "assignee"))
    active = [e for e in entries if not e.removed_at]
    tz = _tz(project)

    def local(dt):
        return dt.astimezone(tz).date() if dt else None

    committed = sum((e.points or 0) for e in active)
    done = sum((e.points or 0) for e in active if e.done_at)
    burndown, burnup = [], []
    total_days = len(days_)
    start_scope = sum((e.points or 0) for e in entries if local(e.added_at) <= sprint.start and
                      (not e.removed_at or local(e.removed_at) > sprint.start))
    for i, d in enumerate(days_):
        scope = sum((e.points or 0) for e in entries if local(e.added_at) <= d and (not e.removed_at or local(e.removed_at) > d))
        completed = sum((e.points or 0) for e in entries if e.done_at and local(e.done_at) <= d
                        and (not e.removed_at or local(e.removed_at) > d))
        ideal = float(start_scope) * (1 - (i + 1) / total_days) if total_days else 0
        point = d <= today
        burndown.append({"date": d.isoformat(), "remaining": float(scope - completed) if point else None, "ideal": round(ideal, 2)})
        burnup.append({"date": d.isoformat(), "done": float(completed) if point else None, "scope": float(scope) if point else None})
    devs = [u.pk for u in _team(project)]
    consumed = TimeEntry.objects.filter(project=project, work_date__range=(sprint.start, min(sprint.end, today)),
                                        person_id__in=devs).aggregate(h=Sum("hours"))["h"] or 0
    remaining_h = sum((e.remaining_hours if e.remaining_hours is not None else (e.item.estimate_hours or 0))
                      for e in active if not e.done_at)
    by_member = defaultdict(lambda: {"points": 0.0, "done": 0.0, "items": 0})
    for e in active:
        key = e.assignee.display_name if e.assignee_id else "Non affecté"
        by_member[key]["points"] += float(e.points or 0)
        by_member[key]["done"] += float(e.points or 0) if e.done_at else 0
        by_member[key]["items"] += 1
    capacity = float(sprint.capacity_hours) if sprint.capacity_hours is not None else sprint_capacity(sprint)["totals"]["productive"]
    goal = getattr(sprint, "goal", None)
    return {
        "sprint": sprint_row(sprint), "goal": goal_sprint_row(goal),
        "daysElapsed": elapsed, "daysRemaining": max(total_days - elapsed, 0), "workingDays": total_days,
        "pointsPlanned": float(committed), "pointsDone": float(done), "pointsRemaining": float(committed - done),
        "tasksDoneRate": round(sum(1 for e in active if e.done_at) / len(active) * 100) if active else 0,
        "capacityInitial": capacity, "capacityConsumed": float(consumed), "remainingHours": float(remaining_h),
        "velocity": velocity_history(project, sprint),
        "blocked": [{"id": e.pk, "title": e.item.title, "reason": e.block_reason} for e in active if e.blocked],
        "burndown": burndown, "burnup": burnup,
        "byMember": [{"name": k, **v} for k, v in sorted(by_member.items())],
    }


def item_row(i):
    return {"id": i.pk, "key": i.key, "kind": i.kind, "title": i.title, "description": i.description,
            "userStory": i.user_story, "acceptance": i.acceptance, "rank": i.rank, "priority": i.priority,
            "storyPoints": float(i.story_points) if i.story_points is not None else None,
            "estimateHours": float(i.estimate_hours) if i.estimate_hours is not None else None,
            "assignee": {"id": i.assignee_id, "name": i.assignee.display_name} if i.assignee_id else None,
            "team": i.team, "status": i.status, "statusLabel": i.get_status_display(),
            "parent": {"id": i.parent_id, "title": i.parent.title} if i.parent_id else None,
            "dependencies": [{"id": d.pk, "title": d.title, "status": d.status} for d in i.dependencies.all()],
            "attachments": [{"id": d.pk, "name": d.name} for d in i.attachments.all()],
            "historyCount": len(i.history or [])}


def goal_sprint_row(g):
    if not g:
        return None
    return {"objective": g.objective, "value": g.value, "expectedResults": g.expected_results,
            "successCriteria": g.success_criteria, "risks": g.risks,
            "owner": {"id": g.owner_id, "name": g.owner.display_name} if g.owner_id else None,
            "status": g.status, "statusLabel": g.get_status_display(), "progress": g.progress,
            "items": [{"id": i.pk, "title": i.title} for i in g.items.all()]}


def sprint_row(s, user=None):
    return {"id": s.pk, "number": s.number, "label": s.label, "start": s.start.isoformat(), "end": s.end.isoformat(),
            "team": s.team, "status": s.status, "statusLabel": s.get_status_display(),
            "capacityHours": float(s.capacity_hours) if s.capacity_hours is not None else None,
            "committedPoints": float(s.committed_points) if s.committed_points is not None else None,
            "completedPoints": float(s.completed_points) if s.completed_points is not None else None,
            "goal": goal_sprint_row(getattr(s, "goal", None)),
            "poValidated": {"by": s.po_validated_by.display_name, "at": s.po_validated_at} if s.po_validated_at else None,
            "teamValidated": {"by": s.team_validated_by.display_name, "at": s.team_validated_at} if s.team_validated_at else None,
            "events": s.events}


def entry_row(e):
    return {"id": e.pk, "item": item_row(e.item), "column": e.column, "order": e.order,
            "points": float(e.points) if e.points is not None else None,
            "assignee": {"id": e.assignee_id, "name": e.assignee.display_name} if e.assignee_id else None,
            "blocked": e.blocked, "blockReason": e.block_reason,
            "remainingHours": float(e.remaining_hours) if e.remaining_hours is not None else None,
            "doneAt": e.done_at, "removed": e.removed_at is not None, "history": e.history[-20:]}


# --------------------------------------------------------------------------- rétrospectives
def retro_for(user, pk):
    r = Retrospective.objects.select_related("project", "sprint").filter(pk=pk).first()
    if r is None or r.project_id not in set(visible_projects(user).values_list("pk", flat=True)):
        raise MethodError("NOT_FOUND", "Rétrospective introuvable.", 404)
    return r


def _parse_dt(project, value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise MethodError("VALIDATION_ERROR", "Date et heure invalides.") from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=_tz(project))


@transaction.atomic
def create_retro(user, project, data, dedupe=""):
    require(user, project, "create", member_ok=True)
    require_feature(project, "retro")
    if dedupe:
        existing = Retrospective.objects.filter(project=project, dedupe_key=dedupe).first()
        if existing:
            return existing
    when = _parse_dt(project, data["scheduledAt"]) if data.get("scheduledAt") else _at(project, timezone.localdate() + timedelta(days=2), "16:00")
    fmt = data.get("format", "ssc")
    if fmt not in RETRO_CATEGORIES:
        raise MethodError("VALIDATION_ERROR", "Format de rétrospective inconnu.")
    sprint = Sprint.objects.filter(project=project, pk=data["sprint"]).first() if data.get("sprint") else None
    phase = VPhase.objects.filter(project=project, pk=data["phase"]).first() if data.get("phase") else None
    sm = _team(project, ["sm"])
    facilitator = _member(project, data.get("facilitator")) if data.get("facilitator") else (sm[0] if sm else (project.pm or user))
    policy = tenant_conf(project.tenant)
    r = Retrospective.objects.create(
        tenant=project.tenant, project=project, sprint=sprint, phase=phase, trigger=data.get("trigger", "adhoc"),
        period_label=str(data.get("periodLabel") or "")[:120], title=str(data.get("title") or "Rétrospective")[:200],
        format=fmt, scheduled_at=when, duration_minutes=int(data.get("durationMinutes") or 60), facilitator=facilitator,
        anonymous_allowed=bool(data.get("anonymous")) and policy["allowAnonymous"], status="collecting",
        dedupe_key=dedupe, created_by=user)
    users = list(User.objects.filter(pk__in=data["participants"], tenant=project.tenant)) if data.get("participants") else _team(project)
    if facilitator and facilitator not in users:
        users.append(facilitator)
    for u in users:
        RetrospectiveParticipant.objects.get_or_create(retro=r, user=u, defaults={"tenant": project.tenant})
    ev = _event(project, user, f"{r.title} ({project.code})", when, when + timedelta(minutes=r.duration_minutes),
                users=users, owner=facilitator)
    r.calendar_event = ev
    r.save(update_fields=["calendar_event"])
    for h in settings_of(project)["reminderHours"]:
        label = "aujourd'hui" if h == 0 else f"dans {h} h"
        _remind(project, "retro", when - timedelta(hours=h) if h else _at(project, when.astimezone(_tz(project)).date(), "08:30"),
                users, f"Rétrospective {label} — {project.code}", f"{r.title} : préparez vos retours.",
                key=f"retro:{r.pk}:{h}", retro=r)
    _remind(project, "retro_report", when + timedelta(hours=24), [facilitator], f"Compte rendu à finaliser — {r.title}",
            project.code, key=f"retro_report:{r.pk}", retro=r)
    notify("retro_reminder", [u for u in users if u.pk != user.pk], f"Rétrospective programmée — {project.code}",
           f"{r.title}, le {when.astimezone(_tz(project)):%d/%m à %H:%M}. Vous pouvez déjà saisir vos retours.")
    audit.record(user, f"Projet {project.code}", "Rétrospective programmée", "", r.title)
    return r


def add_feedback(user, retro, data):
    project = retro.project
    require(user, project, "read")
    participant = retro.participants.filter(user=user).first()
    if participant is None and not allowed(user, project, "update", member_ok=False):
        raise forbid("Seuls les participants contribuent à cette rétrospective.")
    if retro.status == "closed":
        raise MethodError("CONFLICT", "Rétrospective clôturée.", 409)
    if data.get("category") not in RETRO_CATEGORIES[retro.format]:
        raise MethodError("VALIDATION_ERROR", "Catégorie inconnue pour ce format.")
    text = str(data.get("text") or "").strip()
    if not text:
        raise MethodError("VALIDATION_ERROR", "Retour vide.")
    anonymous = bool(data.get("anonymous"))
    if anonymous and not (retro.anonymous_allowed and tenant_conf(project.tenant)["allowAnonymous"]):
        raise MethodError("VALIDATION_ERROR", "Les retours anonymes ne sont pas autorisés pour cette rétrospective.")
    f = RetrospectiveFeedback.objects.create(tenant=project.tenant, retro=retro, author=None if anonymous else user,
                                             anonymous=anonymous, category=data["category"], text=text[:2000])
    if participant:
        participant.contributed_at = timezone.now()
        participant.save(update_fields=["contributed_at"])
    return f


def vote(user, feedback):
    require(user, feedback.retro.project, "read")
    if not feedback.retro.participants.filter(user=user).exists():
        raise forbid("Vote réservé aux participants.")
    RetrospectiveFeedback.objects.filter(pk=feedback.pk).update(votes=feedback.votes + 1)


def save_improvement(user, retro, data, imp=None):
    project = retro.project
    require(user, project, "update" if imp else "create")
    creating = imp is None
    imp = imp or ImprovementAction(tenant=project.tenant, retro=retro)
    for key, field in (("title", "title"), ("description", "description"), ("resultIndicator", "result_indicator"),
                       ("targetPeriod", "target_period")):
        if key in data:
            setattr(imp, field, str(data[key] or "")[:300 if field != "description" else 4000])
    if "owner" in data:
        imp.owner = _member(project, data["owner"])
    if "due" in data:
        imp.due = _date(data["due"])
    if "priority" in data and data["priority"] in ACTION_PRIO:
        imp.priority = data["priority"]
    if "status" in data and data["status"] in ("todo", "doing", "done", "dropped"):
        imp.status = data["status"]
        imp.done_at = timezone.now() if imp.status == "done" else None
    if "targetSprint" in data:
        imp.target_sprint = Sprint.objects.filter(project=project, pk=data["targetSprint"]).first() if data["targetSprint"] else None
    if not imp.title.strip():
        raise MethodError("VALIDATION_ERROR", "Décrivez l'action d'amélioration.")
    with transaction.atomic():
        if creating:
            imp.action = _new_action(project, user, imp.title, imp.owner, imp.due, "Amélioration", imp.priority)
        imp.save()
        a = imp.action
        if a:
            a.title, a.owner, a.due, a.prio = imp.title[:300], imp.owner, imp.due, ACTION_PRIO[imp.priority]
            a.status = {"todo": "todo", "doing": "doing", "done": "done", "dropped": "done"}[imp.status]
            a.done_at = timezone.localdate() if imp.status == "done" else None
            a.save()
    return imp


def sync_improvements(project):
    """L'action PCT liée fait foi : terminée dans PCT → action d'amélioration réalisée."""
    for imp in ImprovementAction.objects.filter(retro__project=project, status__in=("todo", "doing"), action__status="done"):
        imp.status, imp.done_at = "done", timezone.now()
        imp.save(update_fields=["status", "done_at"])


def close_retro(user, retro, data):
    project = retro.project
    if retro.status == "closed":
        return retro
    require(user, project, "update")
    if "report" in data:
        retro.report = str(data["report"] or "")[:20000]
    problems = []
    if not retro.report.strip():
        problems.append("compte rendu vide")
    for imp in retro.improvements.all():
        if not imp.owner_id or not imp.due:
            problems.append(f"« {imp.title} » sans responsable ou échéance")
    force = bool(data.get("force"))
    if problems and not force:
        raise MethodError("RETRO_INCOMPLETE", "Rétrospective incomplète : " + " ; ".join(problems) + ".", 409, problems)
    if problems:
        require(user, project, "approve")
        retro.forced_close = True
    retro.status, retro.closed_at = "closed", timezone.now()
    retro.save()
    retro.reminders.filter(status="pending").update(status="cancelled")
    audit.record(user, f"Projet {project.code}", "Rétrospective clôturée" + (" (forcée)" if force and problems else ""), "", retro.title)
    return retro


def retro_detail(user, retro):
    sync_improvements(retro.project)
    previous = ImprovementAction.objects.filter(retro__project=retro.project, created_at__lt=retro.created_at) \
        .exclude(status__in=("done", "dropped")).exclude(retro=retro).select_related("owner", "retro")
    all_imps = ImprovementAction.objects.filter(retro__project=retro.project)
    done = all_imps.filter(status="done").count()
    return {
        **retro_row(retro), "categories": RETRO_CATEGORIES[retro.format],
        "participants": [{"id": p.user_id, "name": p.user.display_name, "contributed": bool(p.contributed_at)}
                         for p in retro.participants.select_related("user")],
        "feedback": [{"id": f.pk, "category": f.category, "text": f.text, "votes": f.votes, "anonymous": f.anonymous,
                      "author": None if f.anonymous or not f.author_id else {"id": f.author_id, "name": f.author.display_name},
                      "mine": f.author_id == user.pk} for f in retro.feedback.select_related("author")],
        "improvements": [improvement_row(i) for i in retro.improvements.select_related("owner", "action", "target_sprint")],
        "previousOpen": [improvement_row(i) for i in previous],
        "improvementRate": round(done / all_imps.count() * 100) if all_imps.count() else None,
        "isParticipant": retro.participants.filter(user=user).exists(),
        "allowAnonymous": retro.anonymous_allowed and tenant_conf(retro.project.tenant)["allowAnonymous"],
    }


def retro_row(r):
    return {"id": r.pk, "title": r.title, "trigger": r.trigger, "triggerLabel": r.get_trigger_display(), "format": r.format,
            "formatLabel": r.get_format_display(), "scheduledAt": r.scheduled_at, "durationMinutes": r.duration_minutes,
            "status": r.status, "statusLabel": r.get_status_display(), "report": r.report, "periodLabel": r.period_label,
            "sprint": {"id": r.sprint_id, "label": r.sprint.label} if r.sprint_id else None,
            "phase": {"id": r.phase_id, "name": r.phase.name} if r.phase_id else None,
            "facilitator": {"id": r.facilitator_id, "name": r.facilitator.display_name} if r.facilitator_id else None,
            "calendarEvent": r.calendar_event_id, "forcedClose": r.forced_close, "closedAt": r.closed_at,
            "feedbackCount": r.feedback.count(), "improvementCount": r.improvements.count()}


def improvement_row(i):
    return {"id": i.pk, "title": i.title, "description": i.description, "status": i.status, "priority": i.priority,
            "owner": {"id": i.owner_id, "name": i.owner.display_name} if i.owner_id else None,
            "due": i.due.isoformat() if i.due else None, "resultIndicator": i.result_indicator,
            "targetSprint": {"id": i.target_sprint_id, "label": i.target_sprint.label} if i.target_sprint_id else None,
            "targetPeriod": i.target_period, "action": i.action_id, "retro": {"id": i.retro_id, "title": i.retro.title},
            "late": bool(i.due and i.due < timezone.localdate() and i.status not in ("done", "dropped"))}


# --------------------------------------------------------------------------- rappels et automatismes
def process(now=None):
    """Tâche planifiée idempotente : rétrospectives automatiques Cycle en V, rappels générés, rappels échus."""
    now = now or timezone.now()
    report = {"retros": 0, "scheduled": 0, "sent": 0, "failed": 0, "cancelled": 0}
    today = timezone.localdate(now)
    for m in ProjectMethodology.objects.select_related("project__pm", "project__tenant"):
        project = m.project
        if project.tenant.status != "active":
            continue
        try:
            report["retros"] += _auto_retros(m, project, today)
            report["scheduled"] += _auto_reminders(m, project, today)
        except Exception:  # un projet en erreur n'arrête pas les autres
            logger.exception("Automatismes méthodologiques en échec (projet %s)", project.pk)
    for r in MethodologyReminder.objects.filter(status="pending", remind_at__lte=now).select_related("retro", "sprint")[:500]:
        result = _deliver(r, now)
        report[result] += 1
    return report


def _system_user(project):
    return project.pm or User.objects.filter(tenant=project.tenant, role_id="admin", is_active=True).first()


def _auto_retros(m, project, today):
    freq = m.conf("retroFrequency")
    if "retro" not in m.enabled() or freq in ("sprint", "none") or "phases" not in m.enabled() and freq == "phase":
        return 0
    by = _system_user(project)
    if by is None:
        return 0
    todo = []
    if freq == "weekly":
        friday = week_of(today) + timedelta(days=4)
        todo.append((f"weekly:{week_of(today)}", friday, f"Rétrospective de la semaine du {week_of(today):%d/%m}", "weekly", None))
    elif freq == "monthly":
        nxt = date(today.year + (today.month == 12), today.month % 12 + 1, 1)
        last = nxt - timedelta(days=1)
        while last.weekday() >= 5:
            last -= timedelta(days=1)
        if (last - today).days <= 7:
            todo.append((f"monthly:{today:%Y-%m}", last, f"Rétrospective de {today:%m/%Y}", "monthly", None))
    elif freq == "phase":
        for ph in VPhase.objects.filter(project=project, end__range=(today, today + timedelta(days=7))).exclude(status="skipped"):
            todo.append((f"phase:{ph.pk}", ph.end, f"Rétrospective — fin de phase {ph.name}", "phase", ph.pk))
    elif freq == "milestone":
        for ev in CalendarEvent.objects.filter(project=project, kind="milestone"):
            d = ev.start.astimezone(_tz(project)).date()
            if today <= d <= today + timedelta(days=7):
                todo.append((f"milestone:{ev.pk}", d, f"Rétrospective — jalon {ev.title}", "milestone", None))
    elif freq == "project" and project.end_date and today <= project.end_date <= today + timedelta(days=14):
        todo.append(("project", project.end_date, f"Rétrospective de fin de projet {project.code}", "project", None))
    created = 0
    for key, day, title, trigger, phase in todo:
        if Retrospective.objects.filter(project=project, dedupe_key=key).exists():
            continue
        create_retro(by, project, {"title": title, "trigger": trigger, "phase": phase,
                                   "scheduledAt": _at(project, day, "16:00").isoformat()}, dedupe=key)
        created += 1
    return created


def _auto_reminders(m, project, today):
    n = 0
    members = _team(project)
    monday = week_of(today)
    if "weekly" in m.enabled():
        if members and _remind(project, "week_start", _at(project, monday, "08:00"), members,
                               f"Nouvelle semaine — {project.code}", "Consultez les objectifs de la semaine.",
                               key=f"week_start:{project.pk}:{monday}"):
            n += 1
        plan = plan_for(project, monday, create=False)
        if project.pm_id and not (plan and plan.state != "draft"):
            day = monday + timedelta(days=int(m.conf("weeklyPlanningDay")))
            if _remind(project, "weekly_planning", _at(project, day, m.conf("weeklyPlanningTime")) - timedelta(hours=1),
                       [project.pm], f"Préparez et validez la semaine — {project.code}", "",
                       key=f"weekly_planning:{project.pk}:{monday}"):
                n += 1
    for imp in ImprovementAction.objects.filter(retro__project=project, due__lt=today, status__in=("todo", "doing")).select_related("owner"):
        if _remind(project, "improvement_overdue", timezone.now(), [imp.owner] + ([project.pm] if project.pm_id else []),
                   f"Action d'amélioration en retard — {imp.title}", project.code, key=f"improvement:{imp.pk}", retro=imp.retro):
            n += 1
    return n


def _deliver(r, now):
    obsolete = (r.retro_id and r.retro.status == "closed") or \
        (r.sprint_id and r.kind in ("daily", "sprint_close", "sprint_review") and r.sprint.status in ("done", "cancelled")) or \
        (r.kind == "retro_report" and r.retro_id and r.retro.report.strip())
    if obsolete:
        r.status = "cancelled"
        r.save(update_fields=["status"])
        return "cancelled"
    try:
        notify(REMINDER_EVENT[r.kind], list(r.users.all()), r.title, r.body)
    except Exception as exc:
        r.attempts += 1
        r.last_error = f"{type(exc).__name__}: {exc}"[:300]
        if r.attempts >= MAX_ATTEMPTS:
            r.status = "failed"
        else:
            r.remind_at = now + timedelta(minutes=10 * r.attempts)  # nouvel essai différé
        r.save(update_fields=["attempts", "last_error", "status", "remind_at"])
        logger.warning("Rappel %s en échec (essai %s) : %s", r.dedupe_key, r.attempts, r.last_error)
        return "failed"
    r.status, r.sent_at, r.attempts = "sent", now, r.attempts + 1
    r.save(update_fields=["status", "sent_at", "attempts"])
    return "sent"


# --------------------------------------------------------------------------- assistance (propositions uniquement)
WORD = re.compile(r"[a-zà-ÿ]{4,}")
STOP = {"pour", "avec", "dans", "plus", "moins", "sans", "mais", "nous", "vous", "elle", "sont", "être", "avoir", "faire",
        "cette", "très", "trop", "pas", "bien", "tout", "tous", "équipe", "sprint"}


def assist(user, project, topic):
    """Propositions calculées par des règles transparentes (aucune IA générative n'est configurée sur la plateforme).

    Rien n'est appliqué : l'utilisateur reprend, modifie ou ignore chaque proposition.
    """
    require(user, project, "read")
    today = timezone.localdate()
    out = {"topic": topic, "engine": "rules", "note": "Propositions automatiques fondées sur les données du projet ; "
           "aucune n'est appliquée sans votre validation.", "items": []}
    opened = list(_open_actions(project))
    if topic == "weekly_goals":
        by_phase = defaultdict(list)
        for a in sorted(opened, key=lambda a: (PRIO_RANK.get(a.prio, 2), a.due or date.max)):
            by_phase[a.phase or "Sans phase"].append(a)
        for phase, acts in list(by_phase.items())[:3]:
            out["items"].append({"title": f"Faire avancer « {phase} » : {acts[0].title}", "actions": [a.pk for a in acts[:5]],
                                 "reason": f"{len(acts)} action(s) ouvertes, dont {sum(1 for a in acts if a.due and a.due < today)} en retard."})
    elif topic == "delays":
        for a in [a for a in opened if a.due and a.due < today][:15]:
            out["items"].append({"title": a.title, "reason": f"Échéance dépassée de {(today - a.due).days} j"
                                 + (f" — blocage : {a.block}" if a.block else ""), "action": a.pk})
    elif topic == "capacity":
        c = cap.team_capacity(project, week_of(today), week_of(today) + timedelta(days=4))
        for mbr in c["members"]:
            if mbr["state"] != "ok":
                out["items"].append({"title": mbr["user"]["name"], "reason": (
                    f"Surchargé : {mbr['planned']} h planifiées pour {mbr['productive']} h disponibles."
                    if mbr["state"] == "over" else f"Sous-utilisé : {mbr['utilization']} % de sa capacité.")})
    elif topic == "risks":
        for a in [a for a in opened if a.status == "blocked"][:10]:
            out["items"].append({"title": f"Blocage : {a.title}", "reason": a.block or "Cause non renseignée", "action": a.pk})
        for ph in VPhase.objects.filter(project=project, status="late"):
            out["items"].append({"title": f"Phase en retard : {ph.name}", "reason": f"Fin prévue {ph.forecast_end} au lieu de {ph.end}"})
    elif topic == "priorities":
        for a in sorted(opened, key=lambda a: (a.status != "blocked", PRIO_RANK.get(a.prio, 2), a.due or date.max))[:10]:
            out["items"].append({"title": a.title, "reason": f"Priorité {a.prio or '—'}, échéance {a.due or '—'}", "action": a.pk})
    elif topic == "sprint_goal":
        top = list(ProductBacklogItem.objects.filter(project=project, status__in=("ready", "new")).exclude(kind="epic")
                   .select_related("parent").order_by("rank")[:5])
        if top:
            theme = top[0].parent.title if top[0].parent_id else top[0].title
            out["items"].append({"title": f"Livrer « {theme} » utilisable par les utilisateurs",
                                 "reason": "Formulé à partir des éléments les plus prioritaires : " + ", ".join(i.title for i in top[:3]),
                                 "items": [i.pk for i in top]})
    elif topic == "blockers":
        sprint = Sprint.objects.filter(project=project, status="active").first()
        if sprint:
            for e in sprint.items.filter(blocked=True).select_related("item"):
                out["items"].append({"title": e.item.title, "reason": e.block_reason or "Blocage sans cause"})
            for d in ScrumDailyEntry.objects.filter(daily__sprint=sprint, impediment_status__in=("open", "in_progress")).exclude(impediment=""):
                out["items"].append({"title": d.impediment[:120], "reason": f"Obstacle signalé par {d.user.display_name} le {d.daily.date:%d/%m}"})
    elif topic == "sprint_summary":
        sprint = Sprint.objects.filter(project=project).exclude(status__in=("preparing", "cancelled")).order_by("-number").first()
        if sprint:
            mtr = sprint_metrics(sprint)
            out["items"].append({"title": sprint.label, "reason": (
                f"{mtr['pointsDone']} / {mtr['pointsPlanned']} points, {len(mtr['blocked'])} blocage(s), "
                f"objectif : {mtr['goal']['statusLabel'] if mtr['goal'] else 'non défini'} (apprécié par l'équipe).")})
    elif topic in ("retro_synthesis", "recurring_improvements"):
        texts = RetrospectiveFeedback.objects.filter(retro__project=project).values_list("category", "text")
        imps = ImprovementAction.objects.filter(retro__project=project).values_list("title", flat=True)
        words = Counter(w for _, t in texts for w in WORD.findall(t.lower()) if w not in STOP)
        if topic == "retro_synthesis":
            by_cat = Counter(c for c, _ in texts)
            out["items"] = [{"title": f"{c} : {n} retour(s)", "reason": ""} for c, n in by_cat.most_common()]
            out["items"] += [{"title": f"Thème récurrent : {w}", "reason": f"cité {n} fois"} for w, n in words.most_common(5) if n > 1]
        else:
            norm = Counter(" ".join(sorted(set(WORD.findall(t.lower())) - STOP)) for t in imps)
            out["items"] = [{"title": k, "reason": f"décidé {n} fois"} for k, n in norm.most_common(10) if n > 1 and k]
    else:
        raise MethodError("VALIDATION_ERROR", "Sujet d'assistance inconnu.")
    return out

