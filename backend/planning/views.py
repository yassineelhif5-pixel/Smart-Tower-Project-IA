"""API du calendrier (/api/v1/calendar/…). Droits : module « planning » de la matrice, périmètre projets, tenant."""
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import has_perm
from config.errors import ApiError
from configuration import audit
from configuration.models import AppSetting
from projects.access import in_active_tenant

from . import models as M
from . import services as S

DEFAULT_COLORS = {
    "status": {"todo": "#8C95A5", "planned": "#2D6CCB", "doing": "#0B7A75", "review": "#9A4E8E", "blocked": "#C8372C",
               "done": "#1D8A57", "cancelled": "#B0B7C3"},
    "priority": {"low": "#8C95A5", "normal": "#2D6CCB", "high": "#B87304", "critical": "#C8372C"},
    "colorBy": "status",
}


def fail(exc):
    return ApiError(exc.code, exc.message, exc.http_status, exc.details)


def require(user, verb="read"):
    if not in_active_tenant(user) or not has_perm(user, "planning", verb):
        raise ApiError("FORBIDDEN_PERMISSION", "Le calendrier n'est pas accessible avec vos droits.", status.HTTP_403_FORBIDDEN)


def user_row(u):
    return {"id": u.pk, "username": u.username, "name": u.display_name, "team": u.team}


def event_row(e, user, now=None):
    now = now or timezone.now()
    assignments = list(e.assignments.all())
    return {
        "id": e.pk, "kind": e.kind, "title": e.title, "description": e.description, "phase": e.phase,
        "project": {"id": e.project_id, "code": e.project.code, "name": e.project.name} if e.project_id else None,
        "action": {"id": e.action_id, "title": e.action.title} if e.action_id else None,
        "start": S._iso(e.start), "end": S._iso(e.end), "allDay": e.all_day, "timezone": e.timezone,
        "startDate": S.first_day(e).isoformat(), "endDate": S.last_day(e).isoformat(),
        "status": e.status, "statusLabel": e.get_status_display(), "priority": e.priority,
        "priorityLabel": e.get_priority_display(), "progress": e.progress,
        "late": e.is_open and e.kind != "milestone" and e.end < now,
        "assignments": [{"id": a.pk, "user": user_row(a.user), "role": a.role, "roleLabel": a.get_role_display(),
                         "estimatedWorkload": float(a.estimated_workload) if a.estimated_workload is not None else None,
                         "actualWorkload": float(a.actual_workload) if a.actual_workload is not None else None,
                         "status": a.assignment_status} for a in assignments],
        "dependencies": [{"id": d.pk, "predecessor": d.predecessor_id, "type": d.dependency_type}
                         for d in e.predecessor_links.all()],
        "canEdit": S.can_edit(user, e), "canUpdateProgress": S.can_quick_update(user, e), "canDelete": S.can_delete(user, e),
        "createdBy": e.created_by.username if e.created_by_id else None, "completedAt": e.completed_at,
    }


def filtered(request, qs):
    p = request.query_params
    if p.get("project"):
        qs = qs.filter(project_id=p["project"])
    if p.get("user"):
        qs = qs.filter(assignments__user_id=p["user"])
    if p.get("team"):
        qs = qs.filter(assignments__user__team=p["team"])
    if p.get("mine") == "1":
        qs = qs.filter(assignments__user=request.user)
    for key in ("status", "priority", "kind"):
        if p.get(key):
            qs = qs.filter(**{f"{key}__in": p[key].split(",")})
    if p.get("q"):
        qs = qs.filter(Q(title__icontains=p["q"]) | Q(description__icontains=p["q"]) | Q(project__code__icontains=p["q"]))
    if p.get("late") == "1":
        qs = qs.filter(status__in=M.OPEN_STATUSES, end__lt=timezone.now()).exclude(kind="milestone")
    return qs.distinct()


def page(request, items, default=500, maximum=2000):
    try:
        limit = min(max(int(request.query_params.get("limit", default)), 1), maximum)
        offset = max(int(request.query_params.get("offset", 0)), 0)
    except ValueError:
        raise ApiError("VALIDATION_ERROR", "Paramètres limit et offset : nombres attendus.")
    return items[offset:offset + limit], {"limit": limit, "offset": offset}


class EventListView(APIView):
    def get(self, request):
        require(request.user)
        try:
            start, end = S.parse_range(request.query_params)
        except S.PlanningError as exc:
            raise fail(exc) from exc
        # Rappels échus : traités aussi à la consultation (filet de sécurité si la tâche planifiée est espacée).
        S.process_due_reminders(request.user.tenant)
        qs = filtered(request, S.events_in(S.visible_events(request.user), start, end))
        count = qs.count()
        rows, meta = page(request, qs)
        now = timezone.now()
        return Response({"count": count, **meta, "results": [event_row(e, request.user, now) for e in rows]})

    def post(self, request):
        require(request.user, "create")
        data = dict(request.data)
        try:
            event = S.save_event(request.user, data, confirm=bool(data.pop("confirm", False)))
        except S.PlanningError as exc:
            raise fail(exc) from exc
        return Response(event_row(event, request.user), status=status.HTTP_201_CREATED)


class EventDetailView(APIView):
    def get_event(self, request, pk):
        require(request.user)
        return get_object_or_404(S.visible_events(request.user).select_related("project", "action", "created_by")
                                 .prefetch_related("assignments__user", "predecessor_links"), pk=pk)

    def get(self, request, pk):
        return Response(event_row(self.get_event(request, pk), request.user))

    def put(self, request, pk):
        event = self.get_event(request, pk)
        data = dict(request.data)
        confirm = bool(data.pop("confirm", False))
        try:
            event = S.save_event(request.user, data, event=event, confirm=confirm)
        except S.PlanningError as exc:
            raise fail(exc) from exc
        return Response(event_row(event, request.user))

    patch = put

    def delete(self, request, pk):
        event = self.get_event(request, pk)
        try:
            S.delete_event(request.user, event)
        except S.PlanningError as exc:
            raise fail(exc) from exc
        return Response(status=status.HTTP_204_NO_CONTENT)


class AssignmentListView(APIView):
    def get(self, request):
        require(request.user)
        try:
            start, end = S.parse_range(request.query_params)
        except S.PlanningError as exc:
            raise fail(exc) from exc
        events = S.events_in(S.visible_events(request.user), start, end)
        uid = request.query_params.get("user") or request.user.pk
        rows = M.CalendarAssignment.objects.filter(event__in=events, user_id=uid).select_related("event__project", "user")
        return Response([{"id": a.pk, "event": {"id": a.event_id, "title": a.event.title, "start": S._iso(a.event.start),
                                                  "end": S._iso(a.event.end), "status": a.event.status,
                                                  "project": a.event.project.code if a.event.project_id else None},
                          "user": user_row(a.user), "role": a.role,
                          "estimatedWorkload": float(a.estimated_workload) if a.estimated_workload is not None else None,
                          "actualWorkload": float(a.actual_workload) if a.actual_workload is not None else None,
                          "status": a.assignment_status} for a in rows])


class WorkloadView(APIView):
    def get(self, request):
        require(request.user)
        try:
            start, end = S.parse_range(request.query_params)
        except S.PlanningError as exc:
            raise fail(exc) from exc
        events = list(filtered(request, S.events_in(S.visible_events(request.user), start, end)))
        data = S.workload(request.user.tenant, events, start, end, request.query_params.get("group", "user"))
        data.pop("_contributions")
        return Response(data)


class ConflictListView(APIView):
    def get(self, request):
        require(request.user)
        try:
            start, end = S.parse_range(request.query_params)
        except S.PlanningError as exc:
            raise fail(exc) from exc
        # Charge réelle calculée sur tout le tenant ; seuls les conflits touchant un événement visible sont renvoyés.
        visible = filtered(request, S.events_in(S.visible_events(request.user), start, end))
        visible_ids = set(visible.values_list("pk", flat=True))
        tenant_events = list(S.events_in(M.CalendarEvent.objects.filter(tenant=request.user.tenant), start, end))
        return Response(S.detect_conflicts(request.user.tenant, tenant_events, start, end, visible_ids=visible_ids))


class DashboardView(APIView):
    def get(self, request):
        require(request.user)
        try:
            start, end = S.parse_range(request.query_params, default_days=30)
        except S.PlanningError as exc:
            raise fail(exc) from exc
        return Response(S.dashboard(request.user, start, end))


class PortfolioView(APIView):
    def get(self, request):
        require(request.user)
        return Response(S.portfolio(request.user))


class SettingsView(APIView):
    """Couleurs du calendrier, propres au tenant. Modification : droit « Paramétrage · Modifier »."""

    def get(self, request):
        require(request.user)
        row = AppSetting.objects.filter(tenant=request.user.tenant, key="calendar").first()
        value = {**DEFAULT_COLORS, **(row.value if row else {})}
        return Response({**value, "canEdit": has_perm(request.user, "settings", "update")})

    def put(self, request):
        require(request.user)
        if not has_perm(request.user, "settings", "update") or request.auth is not None:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé au paramétrage de l'entreprise.", status.HTTP_403_FORBIDDEN)
        value = {}
        for group in ("status", "priority"):
            given = request.data.get(group, {})
            if not isinstance(given, dict):
                raise ApiError("VALIDATION_ERROR", "Format des couleurs invalide.")
            clean = {}
            for k, v in given.items():
                if k not in DEFAULT_COLORS[group] or not (isinstance(v, str) and len(v) == 7 and v.startswith("#")
                                                          and all(c in "0123456789abcdefABCDEF" for c in v[1:])):
                    raise ApiError("VALIDATION_ERROR", f"Couleur invalide pour {group}.{k} (format #RRGGBB).")
                clean[k] = v
            value[group] = {**DEFAULT_COLORS[group], **clean}
        value["colorBy"] = request.data.get("colorBy") if request.data.get("colorBy") in ("status", "priority") else "status"
        AppSetting.objects.update_or_create(tenant=request.user.tenant, key="calendar", defaults={"value": value})
        audit.record(request.user, "Calendrier", "Couleurs modifiées")
        return self.get(request)


class ReminderListView(APIView):
    def get(self, request, pk):
        require(request.user)
        event = get_object_or_404(S.visible_events(request.user), pk=pk)
        rows = event.reminders.filter(user=request.user)
        return Response([{"id": r.pk, "remindAt": r.remind_at, "channel": r.channel, "kind": r.kind, "status": r.status,
                          "error": r.error} for r in rows])

    def post(self, request, pk):
        require(request.user)
        event = get_object_or_404(S.visible_events(request.user), pk=pk)
        channel = request.data.get("channel", "inapp")
        if channel not in dict(M.CHANNEL_CHOICES):
            raise ApiError("VALIDATION_ERROR", "Canal inconnu.")
        try:
            at = S.parse_moment(request.data.get("remindAt"), event.timezone, False, False)
        except S.PlanningError as exc:
            raise fail(exc) from exc
        if at <= timezone.now():
            raise ApiError("VALIDATION_ERROR", "Le rappel doit être dans le futur.")
        r = M.CalendarReminder.objects.create(tenant=event.tenant, event=event, user=request.user, remind_at=at, channel=channel)
        return Response({"id": r.pk, "remindAt": r.remind_at, "channel": r.channel, "kind": r.kind, "status": r.status},
                        status=status.HTTP_201_CREATED)


class ReminderDetailView(APIView):
    def delete(self, request, pk):
        require(request.user)
        r = get_object_or_404(M.CalendarReminder, pk=pk, user=request.user, tenant=request.user.tenant)
        r.status = "cancelled"
        r.save(update_fields=["status"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class FeedTokenView(APIView):
    """Lien d'abonnement ICS personnel (Outlook, Google Agenda…), en lecture seule. Affiché une seule fois."""

    def post(self, request):
        require(request.user)
        if request.auth is not None:
            raise ApiError("FORBIDDEN_PERMISSION", "Session interactive requise.", status.HTTP_403_FORBIDDEN)
        raw = S.issue_feed_token(request.user)
        return Response({"url": request.build_absolute_uri(f"/api/v1/calendar/feed/{raw}.ics")}, status=status.HTTP_201_CREATED)

    def delete(self, request):
        request.user.calendar_feed_tokens.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
        audit.record(request.user, f"Utilisateur {request.user.username}", "Lien d'abonnement au calendrier révoqué")
        return Response(status=status.HTTP_204_NO_CONTENT)


class FeedView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request, token):
        user = S.feed_user(token)
        if user is None or not has_perm(user, "planning", "read"):
            raise ApiError("NOT_FOUND", "Abonnement introuvable ou révoqué.", status.HTTP_404_NOT_FOUND)
        response = HttpResponse(S.ics_feed(user), content_type="text/calendar; charset=utf-8")
        response["Cache-Control"] = "private, max-age=300"
        return response


class PeopleView(APIView):
    """Collaborateurs actifs du tenant, pour les affectations et les filtres. Avec ?project= : ceux qui voient ce projet."""

    def get(self, request):
        require(request.user)
        from django.contrib.auth import get_user_model
        from projects.access import visible_projects
        from projects.models import ProjectAccess
        users = get_user_model().objects.filter(tenant=request.user.tenant, is_active=True, role__isnull=False) \
            .exclude(role_id__in=("superadmin", "license_manager")).order_by("first_name", "last_name", "username")
        project_id = request.query_params.get("project")
        if project_id:
            project = get_object_or_404(visible_projects(request.user), pk=project_id)
            explicit = set(ProjectAccess.objects.filter(project=project).values_list("user_id", flat=True))
            users = [u for u in users if u.pk in explicit or u.role_id in ("admin", "direction")]
        return Response([user_row(u) for u in users])
