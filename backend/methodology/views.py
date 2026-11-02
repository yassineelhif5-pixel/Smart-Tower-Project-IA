"""API du pilotage méthodologique : /api/v1/methodology/…"""
from datetime import date

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import has_perm
from config.errors import ApiError
from projects.access import in_active_tenant, visible_projects

from . import capacity as cap
from . import services as S
from .models import (AVAILABILITY_KINDS, ImprovementAction, ProductBacklogItem, Retrospective, RetrospectiveFeedback,
                     ScrumDaily, ScrumDailyEntry, Sprint, SprintBacklogItem, TeamAvailability, TeamMemberAllocation,
                     VPhase, WeeklyGoal)


def fail(exc):
    return ApiError(exc.code, exc.message, exc.http_status, exc.details)


def day(value, default=None):
    if not value:
        return default
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ApiError("VALIDATION_ERROR", f"Date invalide : {value}.") from exc


class MView(APIView):
    """Traduit les erreurs métier en réponses d'API homogènes."""

    def handle_exception(self, exc):
        if isinstance(exc, S.MethodError):
            exc = fail(exc)
        return super().handle_exception(exc)

    def project(self, pk):
        return S.project_for(self.request.user, pk)


# --------------------------------------------------------------------------- projets et méthodologie
class ProjectListView(MView):
    def get(self, request):
        if not in_active_tenant(request.user) or not has_perm(request.user, "methodology", "read"):
            raise ApiError("FORBIDDEN_PERMISSION", "Module non accessible avec vos droits.", 403)
        rows = []
        for p in visible_projects(request.user).select_related("client"):
            m = S.methodology(p)
            active = Sprint.objects.filter(project=p, status="active").select_related("goal").first()
            rows.append({"id": p.pk, "code": p.code, "name": p.name, "client": p.client.name, "kind": m.kind,
                         "kindLabel": m.get_kind_display(), "features": m.enabled(),
                         "activeSprint": S.sprint_row(active) if active else None})
        return Response(rows)


class MethodologyView(MView):
    def get(self, request, pk):
        p = self.project(pk)
        S.require(request.user, p, "read")
        m = S.methodology(p)
        u = request.user
        return Response({
            "project": {"id": p.pk, "code": p.code, "name": p.name, "start": p.start_date, "end": p.end_date,
                        "pm": p.pm.display_name if p.pm_id else None},
            "kind": m.kind, "kindLabel": m.get_kind_display(), "features": m.enabled(), "customFeatures": m.features,
            "settings": S.settings_of(p), "history": m.history, "myScrumRole": S.scrum_role(u, p),
            "can": {"edit": S.allowed(u, p, "update", member_ok=False), "plan": S.allowed(u, p, "create"),
                    "approve": S.allowed(u, p, "approve"), "capacity": S.allowed(u, p, "update", "capacity", member_ok=False),
                    "prioritize": S.can_prioritize(u, p)},
            "tenantPolicy": S.tenant_conf(p.tenant),
        })

    def put(self, request, pk):
        p = self.project(pk)
        data = request.data
        if "kind" in data:
            S.change_methodology(request.user, p, data["kind"], data.get("features"), bool(data.get("confirm")))
        if "settings" in data:
            S.save_settings(request.user, p, data["settings"])
        return self.get(request, pk)


class ImpactView(MView):
    def post(self, request, pk):
        p = self.project(pk)
        S.require(request.user, p, "read")
        return Response(S.impact(p, request.data.get("kind"), request.data.get("features")))


class TenantPolicyView(MView):
    def get(self, request):
        if not in_active_tenant(request.user):
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé aux entreprises.", 403)
        return Response(S.tenant_conf(request.user.tenant))

    def put(self, request):
        return Response(S.save_tenant_conf(request.user, request.data))


class AssistView(MView):
    def get(self, request, pk):
        return Response(S.assist(request.user, self.project(pk), request.query_params.get("topic", "")))


# --------------------------------------------------------------------------- capacité
def allocation_row(a):
    return {"id": a.pk, "user": {"id": a.user_id, "name": a.user.display_name, "team": a.user.team}, "projectRole": a.project_role,
            "scrumRole": a.scrum_role, "allocationPct": a.allocation_pct, "hoursPerDay": float(a.hours_per_day),
            "daysPerWeek": a.days_per_week, "meetingHoursPerWeek": float(a.meeting_hours_per_week), "skills": a.skills,
            "start": a.start, "end": a.end, "active": a.active}


class CapacityView(MView):
    def get(self, request, pk):
        p = self.project(pk)
        S.require(request.user, p, "read", "capacity")
        today = timezone.localdate()
        start = day(request.query_params.get("start"), S.week_of(today))
        end = day(request.query_params.get("end"), start + timedelta_days(4))
        if (end - start).days > 120 or end < start:
            raise ApiError("VALIDATION_ERROR", "Période de 1 à 120 jours.")
        data = cap.team_capacity(p, start, end)
        # Vue par semaine sur la période (graphiques).
        weeks = []
        w = S.week_of(start)
        while w <= end:
            c = cap.team_capacity(p, max(w, start), min(w + timedelta_days(6), end))
            weeks.append({"week": w.isoformat(), **{k: c["totals"][k] for k in ("productive", "planned", "consumed")}})
            w += timedelta_days(7)
        data["weeks"] = weeks
        return Response(data)


def timedelta_days(n):
    from datetime import timedelta
    return timedelta(days=n)


class AllocationListView(MView):
    def get(self, request, pk):
        p = self.project(pk)
        S.require(request.user, p, "read", "capacity")
        return Response([allocation_row(a) for a in TeamMemberAllocation.objects.filter(project=p).select_related("user")])

    def post(self, request, pk):
        p = self.project(pk)
        S.require(request.user, p, "update", "capacity", member_ok=False)
        u = S._member(p, request.data.get("user"))
        if u is None:
            raise ApiError("VALIDATION_ERROR", "Choisissez un collaborateur.")
        if not visible_projects(u).filter(pk=p.pk).exists():
            raise ApiError("VALIDATION_ERROR", "Ce collaborateur n'a pas accès au projet : donnez-lui d'abord l'accès.")
        a, _ = TeamMemberAllocation.objects.get_or_create(project=p, user=u, defaults={"tenant": p.tenant})
        return Response(allocation_row(save_allocation(a, request.data)), status=status.HTTP_201_CREATED)


def save_allocation(a, data):
    for key, field, cast, low, high in (("allocationPct", "allocation_pct", int, 0, 100), ("hoursPerDay", "hours_per_day", float, 0, 24),
                                        ("daysPerWeek", "days_per_week", int, 1, 7),
                                        ("meetingHoursPerWeek", "meeting_hours_per_week", float, 0, 60)):
        if key in data:
            v = cast(data[key])
            if not low <= v <= high:
                raise ApiError("VALIDATION_ERROR", f"Valeur hors limites : {key}.")
            setattr(a, field, v)
    if "projectRole" in data:
        a.project_role = str(data["projectRole"] or "")[:80]
    if "scrumRole" in data:
        if data["scrumRole"] not in ("", "po", "sm", "dev"):
            raise ApiError("VALIDATION_ERROR", "Rôle Scrum inconnu.")
        a.scrum_role = data["scrumRole"]
    if "skills" in data:
        a.skills = [str(s)[:60] for s in data["skills"] or []][:30]
    for key in ("start", "end"):
        if key in data:
            setattr(a, key, day(data[key]))
    if "active" in data:
        a.active = bool(data["active"])
    a.save()
    return a


class AllocationDetailView(MView):
    def get_object(self, request, aid):
        a = get_object_or_404(TeamMemberAllocation.objects.select_related("project", "user"), pk=aid,
                              project__in=visible_projects(request.user))
        S.require(request.user, a.project, "update", "capacity", member_ok=False)
        return a

    def patch(self, request, aid):
        return Response(allocation_row(save_allocation(self.get_object(request, aid), request.data)))

    def delete(self, request, aid):
        a = self.get_object(request, aid)
        a.active = False
        a.save(update_fields=["active"])
        return Response(status=status.HTTP_204_NO_CONTENT)


def availability_row(a, user):
    return {"id": a.pk, "user": {"id": a.user_id, "name": a.user.display_name} if a.user_id else None, "kind": a.kind,
            "kindLabel": a.get_kind_display(), "start": a.start, "end": a.end,
            "hours": float(a.hours) if a.hours is not None else None, "note": a.note if (a.user_id == user.pk or has_perm(user, "capacity", "update")) else "",
            "mine": a.user_id == user.pk}


def can_edit_availability(user, target_user):
    """Ses propres disponibilités : toujours. Celles d'un autre : droit « Capacité · Modifier » sur un projet commun.
    Jours fériés de l'entreprise : « Capacité · Valider »."""
    if target_user is None:
        return has_perm(user, "capacity", "approve")
    if target_user.pk == user.pk:
        return True
    if not has_perm(user, "capacity", "update"):
        return False
    projects = TeamMemberAllocation.objects.filter(user=target_user).values_list("project", flat=True)
    return any(S.can_edit_project(user, p) for p in visible_projects(user).filter(pk__in=projects))


class AvailabilityListView(MView):
    def get(self, request):
        user = request.user
        if not in_active_tenant(user):
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé aux entreprises.", 403)
        start = day(request.query_params.get("start"), timezone.localdate())
        end = day(request.query_params.get("end"), start + timedelta_days(90))
        qs = TeamAvailability.objects.filter(tenant=user.tenant, start__lte=end, end__gte=start).select_related("user")
        if request.query_params.get("project"):
            p = S.project_for(user, request.query_params["project"])
            S.require(user, p, "read", "capacity")
            members = TeamMemberAllocation.objects.filter(project=p, active=True).values_list("user_id", flat=True)
            qs = qs.filter(Q(user__isnull=True) | Q(user_id__in=members))
        elif not has_perm(user, "capacity", "read"):
            qs = qs.filter(Q(user=user) | Q(user__isnull=True))
        return Response({"kinds": [{"code": k, "label": v} for k, v in AVAILABILITY_KINDS],
                         "rows": [availability_row(a, user) for a in qs]})

    def post(self, request):
        user = request.user
        if not in_active_tenant(user):
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé aux entreprises.", 403)
        data = request.data
        target = None
        if data.get("kind") != "holiday":
            target = user if not data.get("user") else S._member_tenant(user.tenant, data["user"])
        if not can_edit_availability(user, target):
            raise ApiError("FORBIDDEN_PERMISSION", "Vous ne pouvez pas modifier ces disponibilités.", 403)
        a = TeamAvailability(tenant=user.tenant, user=target, created_by=user)
        return Response(availability_row(save_availability(a, data), user), status=status.HTTP_201_CREATED)


def save_availability(a, data):
    if data.get("kind") not in dict(AVAILABILITY_KINDS):
        raise ApiError("VALIDATION_ERROR", "Type d'indisponibilité inconnu.")
    a.kind = data["kind"]
    a.start = day(data.get("start"))
    a.end = day(data.get("end"), a.start)
    if not a.start or a.end < a.start:
        raise ApiError("VALIDATION_ERROR", "Période invalide.")
    h = data.get("hours")
    a.hours = None if h in (None, "") else float(h)
    if a.hours is not None and not 0 < a.hours <= 24:
        raise ApiError("VALIDATION_ERROR", "Heures entre 0 et 24 (vide : journée entière).")
    a.note = str(data.get("note") or "")[:200]
    a.save()
    return a


class AvailabilityDetailView(MView):
    def delete(self, request, aid):
        a = get_object_or_404(TeamAvailability, pk=aid, tenant=request.user.tenant)
        if not can_edit_availability(request.user, a.user):
            raise ApiError("FORBIDDEN_PERMISSION", "Vous ne pouvez pas modifier ces disponibilités.", 403)
        a.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- phases Cycle en V
def phase_row(ph):
    return {"id": ph.pk, "order": ph.order, "name": ph.name, "start": ph.start, "end": ph.end, "forecastEnd": ph.forecast_end,
            "owner": {"id": ph.owner_id, "name": ph.owner.display_name} if ph.owner_id else None, "status": ph.status,
            "statusLabel": ph.get_status_display(), "progress": ph.progress, "deliverables": ph.deliverables,
            "validationCriteria": ph.validation_criteria, "risks": ph.risks,
            "dependsOn": list(ph.depends_on.values_list("pk", flat=True))}


class PhaseListView(MView):
    def get(self, request, pk):
        p = self.project(pk)
        S.require(request.user, p, "read")
        from planning.models import CalendarEvent
        milestones = CalendarEvent.objects.filter(project=p, kind="milestone").order_by("start")
        return Response({"phases": [phase_row(ph) for ph in VPhase.objects.filter(project=p).select_related("owner")],
                         "milestones": [{"id": e.pk, "title": e.title, "date": e.start.date(), "status": e.status,
                                         "phase": e.phase} for e in milestones]})

    def post(self, request, pk):
        return Response(phase_row(S.save_phase(request.user, self.project(pk), request.data)), status=status.HTTP_201_CREATED)


class PhaseDetailView(MView):
    def patch(self, request, pid):
        ph = get_object_or_404(VPhase, pk=pid, project__in=visible_projects(request.user))
        return Response(phase_row(S.save_phase(request.user, ph.project, request.data, ph)))

    def delete(self, request, pid):
        ph = get_object_or_404(VPhase, pk=pid, project__in=visible_projects(request.user))
        S.require(request.user, ph.project, "delete", member_ok=False)
        ph.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- semaine (Cycle en V)
class WeekView(MView):
    def get(self, request, pk, week):
        p = self.project(pk)
        data = S.prepare_week(request.user, p, day(week))
        plan = S.plan_for(p, day(week))
        data["tracking"] = S.track_week(plan)
        data["history"] = [{"weekStart": w.week_start, "status": w.status, "statusLabel": w.get_status_display(), "state": w.state}
                           for w in p.weekly_plans.order_by("-week_start")[:12]]
        return Response(data)


class WeekActionView(MView):
    """POST …/weeks/<lundi>/<action> : goals, assign, validate, close, meeting."""

    def post(self, request, pk, week, action):
        p = self.project(pk)
        plan = S.plan_for(p, day(week))
        d = request.data
        if action == "goals":
            S.save_goal(request.user, plan, d)
        elif action == "assign":
            S.assign_actions(request.user, plan, d.get("items") or [], bool(d.get("confirm")))
        elif action == "validate":
            S.validate_week(request.user, plan, bool(d.get("confirm")))
        elif action == "close":
            S.close_week(request.user, plan, d)
        elif action == "meeting":
            S.save_meeting(request.user, plan, d)
        else:
            raise ApiError("NOT_FOUND", "Opération inconnue.", 404)
        plan.refresh_from_db()
        return Response({"plan": S.plan_row(plan, request.user), "tracking": S.track_week(plan)})


class GoalDetailView(MView):
    def get_goal(self, request, gid):
        return get_object_or_404(WeeklyGoal.objects.select_related("plan__project"), pk=gid,
                                 plan__project__in=visible_projects(request.user))

    def patch(self, request, gid):
        g = self.get_goal(request, gid)
        return Response(S.goal_row(S.save_goal(request.user, g.plan, request.data, g)))

    def delete(self, request, gid):
        S.delete_goal(request.user, self.get_goal(request, gid))
        return Response(status=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- Scrum
class BacklogView(MView):
    def get(self, request, pk):
        p = self.project(pk)
        S.require(request.user, p, "read")
        qs = ProductBacklogItem.objects.filter(project=p).select_related("parent", "assignee").prefetch_related("dependencies", "attachments")
        q = request.query_params
        if q.get("status"):
            qs = qs.filter(status__in=q["status"].split(","))
        else:
            qs = qs.exclude(status="removed")
        if q.get("kind"):
            qs = qs.filter(kind__in=q["kind"].split(","))
        if q.get("epic"):
            qs = qs.filter(Q(parent_id=q["epic"]) | Q(pk=q["epic"]))
        if q.get("q"):
            qs = qs.filter(Q(title__icontains=q["q"]) | Q(key__icontains=q["q"]) | Q(description__icontains=q["q"]))
        return Response([S.item_row(i) for i in qs])

    def post(self, request, pk):
        return Response(S.item_row(S.save_item(request.user, self.project(pk), request.data)), status=status.HTTP_201_CREATED)


class BacklogReorderView(MView):
    def post(self, request, pk):
        p = self.project(pk)
        S.reorder(request.user, p, [int(i) for i in request.data.get("ids") or []])
        return Response({"ok": True})


class BacklogItemView(MView):
    def get_item(self, request, iid):
        return get_object_or_404(ProductBacklogItem.objects.select_related("project"), pk=iid,
                                 project__in=visible_projects(request.user))

    def get(self, request, iid):
        i = self.get_item(request, iid)
        S.require(request.user, i.project, "read")
        return Response({**S.item_row(i), "history": i.history})

    def patch(self, request, iid):
        i = self.get_item(request, iid)
        return Response(S.item_row(S.save_item(request.user, i.project, request.data, i)))


class SprintListView(MView):
    def get(self, request, pk):
        p = self.project(pk)
        S.require(request.user, p, "read")
        return Response({"sprints": [S.sprint_row(s) for s in Sprint.objects.filter(project=p).select_related("goal")],
                         "velocity": S.velocity_history(p), "columns": S.board_columns(p)})

    def post(self, request, pk):
        return Response(S.sprint_row(S.create_sprint(request.user, self.project(pk), request.data)), status=status.HTTP_201_CREATED)


class SprintView(MView):
    def get(self, request, sid):
        s = S.sprint_for(request.user, sid)
        S.require(request.user, s.project, "read")
        entries = s.items.select_related("item__parent", "item__assignee", "assignee").prefetch_related("item__dependencies", "item__attachments")
        return Response({"sprint": S.sprint_row(s, request.user), "columns": S.board_columns(s.project),
                         "items": [S.entry_row(e) for e in entries if not e.removed_at],
                         "removed": [S.entry_row(e) for e in entries if e.removed_at],
                         "metrics": S.sprint_metrics(s), "myScrumRole": S.scrum_role(request.user, s.project)})


class SprintActionView(MView):
    """POST /sprints/<id>/<action> : planning (GET), select, goal, validate, start, close, review, daily."""

    def get(self, request, sid, action):
        s = S.sprint_for(request.user, sid)
        if action == "planning":
            return Response(S.planning_view(request.user, s))
        if action == "daily":
            S.require(request.user, s.project, "read")
            d = day(request.query_params.get("date"), timezone.localdate())
            daily = ScrumDaily.objects.filter(sprint=s, date=d).first()
            imps = ScrumDailyEntry.objects.filter(daily__sprint=s).exclude(impediment="").select_related("user", "resolution_owner", "daily")
            return Response({
                "date": d, "notes": daily.notes if daily else "",
                "entries": [daily_entry(e, request.user) for e in (daily.entries.select_related("user", "resolution_owner") if daily else [])],
                "impediments": [daily_entry(e, request.user) for e in imps.order_by("-daily__date")],
                "team": [{"id": u.pk, "name": u.display_name} for u in S._team(s.project)],
            })
        if action == "review":
            S.require(request.user, s.project, "read")
            r = getattr(s, "review", None)
            return Response(review_row(s, r))
        raise ApiError("NOT_FOUND", "Opération inconnue.", 404)

    def post(self, request, sid, action):
        s = S.sprint_for(request.user, sid)
        d = request.data
        u = request.user
        if action == "select":
            S.select_items(u, s, [int(i) for i in d.get("items") or []], bool(d.get("confirm")))
        elif action == "goal":
            S.save_goal_sprint(u, s, d)
        elif action == "validate":
            S.validate_sprint(u, s, d.get("as"))
        elif action == "start":
            S.start_sprint(u, s)
        elif action == "close":
            _, retro = S.close_sprint(u, s, d)
            return Response({"sprint": S.sprint_row(Sprint.objects.get(pk=s.pk)), "retro": S.retro_row(retro) if retro else None})
        elif action == "review":
            r = S.save_review(u, s, d)
            return Response(review_row(s, r))
        elif action == "daily":
            S.save_daily(u, s, day(d.get("date"), timezone.localdate()), d)
            return self.get(request, sid, "daily")
        else:
            raise ApiError("NOT_FOUND", "Opération inconnue.", 404)
        return Response(S.sprint_row(Sprint.objects.get(pk=s.pk), u))


def daily_entry(e, user):
    return {"id": e.pk, "date": e.daily.date, "user": {"id": e.user_id, "name": e.user.display_name}, "progress": e.progress,
            "plan": e.plan, "impediment": e.impediment, "impedimentStatus": e.impediment_status, "resolution": e.resolution,
            "resolutionOwner": {"id": e.resolution_owner_id, "name": e.resolution_owner.display_name} if e.resolution_owner_id else None,
            "resolutionDue": e.resolution_due, "mine": e.user_id == user.pk}


def review_row(s, r):
    entries = s.items.filter(removed_at__isnull=True).select_related("item")
    return {"sprint": S.sprint_row(s), "increment": r.increment if r else "", "demos": r.demos if r else "",
            "feedback": r.feedback if r else "", "decisions": r.decisions if r else "",
            "backlogChanges": r.backlog_changes if r else "", "heldAt": r.held_at if r else None, "report": r.report if r else "",
            "done": [S.item_row(e.item) for e in entries if e.done_at], "notDone": [S.item_row(e.item) for e in entries if not e.done_at]}


class EntryView(MView):
    def patch(self, request, eid):
        e = get_object_or_404(SprintBacklogItem.objects.select_related("sprint__project", "item"), pk=eid,
                              sprint__project__in=visible_projects(request.user))
        return Response(S.entry_row(S.move_item(request.user, e, request.data)))


class ImpedimentView(MView):
    def patch(self, request, eid):
        e = get_object_or_404(ScrumDailyEntry.objects.select_related("daily__sprint__project"), pk=eid,
                              daily__sprint__project__in=visible_projects(request.user))
        return Response(daily_entry(S.update_impediment(request.user, e, request.data), request.user))


class ScrumDashboardView(MView):
    def get(self, request, pk):
        p = self.project(pk)
        S.require(request.user, p, "read")
        S.require_feature(p, "scrum")
        sprint = Sprint.objects.filter(project=p, status="active").first() or \
            Sprint.objects.filter(project=p).exclude(status__in=("cancelled",)).order_by("-number").first()
        S.sync_improvements(p)
        imps = ImprovementAction.objects.filter(retro__project=p)
        from planning.models import CalendarEvent
        now = timezone.now()
        upcoming = CalendarEvent.objects.filter(project=p, kind="meeting", start__gte=now).order_by("start")[:8]
        return Response({
            "sprint": S.sprint_row(sprint) if sprint else None, "metrics": S.sprint_metrics(sprint) if sprint else None,
            "velocity": S.velocity_history(p, limit=8),
            "backlog": {"ready": ProductBacklogItem.objects.filter(project=p, status="ready").count(),
                        "new": ProductBacklogItem.objects.filter(project=p, status="new").count(),
                        "readyPoints": float(sum((i.story_points or 0) for i in ProductBacklogItem.objects.filter(project=p, status="ready")))},
            "ceremonies": [{"id": e.pk, "title": e.title, "start": e.start} for e in upcoming],
            "retros": [S.retro_row(r) for r in Retrospective.objects.filter(project=p).exclude(status="closed")[:5]],
            "improvementRate": round(imps.filter(status="done").count() / imps.count() * 100) if imps.count() else None,
        })


# --------------------------------------------------------------------------- rétrospectives
class RetroListView(MView):
    def get(self, request, pk):
        p = self.project(pk)
        S.require(request.user, p, "read")
        S.sync_improvements(p)
        imps = ImprovementAction.objects.filter(retro__project=p).select_related("owner", "retro", "target_sprint")
        return Response({"retros": [S.retro_row(r) for r in Retrospective.objects.filter(project=p).select_related("sprint", "phase", "facilitator")],
                         "improvements": [S.improvement_row(i) for i in imps],
                         "rate": round(imps.filter(status="done").count() / imps.count() * 100) if imps.count() else None})

    def post(self, request, pk):
        return Response(S.retro_row(S.create_retro(request.user, self.project(pk), request.data)), status=status.HTTP_201_CREATED)


class RetroView(MView):
    def get(self, request, rid):
        r = S.retro_for(request.user, rid)
        S.require(request.user, r.project, "read")
        return Response(S.retro_detail(request.user, r))

    def patch(self, request, rid):
        r = S.retro_for(request.user, rid)
        S.require(request.user, r.project, "update")
        if r.status == "closed":
            raise ApiError("CONFLICT", "Rétrospective clôturée.", 409)
        if "report" in request.data:
            r.report = str(request.data["report"] or "")[:20000]
        if request.data.get("status") in ("collecting", "held"):
            r.status = request.data["status"]
        if "format" in request.data and request.data["format"] in S.RETRO_CATEGORIES and not r.feedback.exists():
            r.format = request.data["format"]
        r.save()
        return Response(S.retro_detail(request.user, r))


class RetroActionView(MView):
    def post(self, request, rid, action):
        r = S.retro_for(request.user, rid)
        if action == "feedback":
            S.add_feedback(request.user, r, request.data)
        elif action == "improvements":
            S.save_improvement(request.user, r, request.data)
        elif action == "close":
            S.close_retro(request.user, r, request.data)
        else:
            raise ApiError("NOT_FOUND", "Opération inconnue.", 404)
        return Response(S.retro_detail(request.user, Retrospective.objects.get(pk=r.pk)))


class FeedbackVoteView(MView):
    def post(self, request, fid):
        f = get_object_or_404(RetrospectiveFeedback.objects.select_related("retro__project"), pk=fid,
                              retro__project__in=visible_projects(request.user))
        S.vote(request.user, f)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ImprovementView(MView):
    def patch(self, request, iid):
        i = get_object_or_404(ImprovementAction.objects.select_related("retro__project"), pk=iid,
                              retro__project__in=visible_projects(request.user))
        return Response(S.improvement_row(S.save_improvement(request.user, i.retro, request.data, i)))


# --------------------------------------------------------------------------- rapports
class ReportsView(MView):
    def get(self, request, pk):
        p = self.project(pk)
        S.require(request.user, p, "read")
        m = S.methodology(p)
        out = {"kind": m.kind, "features": m.enabled()}
        if "weekly" in m.enabled():
            plans = list(p.weekly_plans.order_by("-week_start")[:12])
            out["weeks"] = [{"weekStart": w.week_start, "status": w.status, "statusLabel": w.get_status_display(), "state": w.state,
                             **{k: S.track_week(w)[k] for k in ("rate", "plannedHours", "consumedHours")}} for w in plans][::-1]
        if "phases" in m.enabled():
            out["phases"] = [phase_row(ph) for ph in VPhase.objects.filter(project=p).select_related("owner")]
        if "scrum" in m.enabled():
            out["velocity"] = S.velocity_history(p, limit=12)
            out["sprints"] = [{**S.sprint_row(s), "goalStatus": s.goal.status if hasattr(s, "goal") else None}
                              for s in Sprint.objects.filter(project=p).select_related("goal").order_by("number")]
        imps = ImprovementAction.objects.filter(retro__project=p)
        out["retros"] = {"count": Retrospective.objects.filter(project=p).count(),
                         "closed": Retrospective.objects.filter(project=p, status="closed").count(),
                         "improvements": imps.count(), "improvementsDone": imps.filter(status="done").count(),
                         "late": sum(1 for i in imps if i.due and i.due < timezone.localdate() and i.status not in ("done", "dropped"))}
        out["capacity"] = [{"start": c.start, "end": c.end, "available": float(c.available), "planned": float(c.planned),
                            "sprint": c.sprint_id, "week": c.weekly_plan_id} for c in p.capacity_snapshots.order_by("start")[:30]]
        return Response(out)
