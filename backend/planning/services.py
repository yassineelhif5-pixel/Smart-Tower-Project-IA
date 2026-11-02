"""Règles du calendrier : visibilité, droits, enregistrement, conflits, charge, indicateurs, rappels, flux ICS.

Tout est calculé côté serveur à partir des événements réels du tenant de l'utilisateur.
"""
import hashlib
import math
import secrets
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.permissions import has_perm
from configuration import audit, notify
from configuration.models import AppSetting
from projects.access import has_full_scope, in_active_tenant, visible_actions, visible_projects
from projects.models import Action, PersonCapacity, ProjectAccess

from . import models as M

User = get_user_model()
MAX_RANGE_DAYS = 400
DEFAULT_HOURS_PER_DAY = Decimal("8")


class PlanningError(Exception):
    def __init__(self, code, message, http_status=400, details=None):
        super().__init__(message)
        self.code, self.message, self.http_status, self.details = code, message, http_status, details or []


class ConflictsPending(PlanningError):
    """Enregistrement suspendu : des conflits demandent une confirmation explicite (aucune modification faite)."""

    def __init__(self, conflicts):
        super().__init__("CALENDAR_CONFLICTS", "Ce planning crée des conflits : confirmez ou modifiez.", 409, conflicts)
        self.conflicts = conflicts


# --------------------------------------------------------------------------- dates et fuseaux
def zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise PlanningError("VALIDATION_ERROR", f"Fuseau horaire inconnu : {name}.") from exc


def local_date(dt, tzname):
    return dt.astimezone(zone(tzname)).date()


def first_day(event):
    return local_date(event.start, event.timezone)


def last_day(event):
    """Dernier jour couvert (inclus) : la fin est exclusive."""
    end = event.end - timedelta(microseconds=1) if event.end > event.start else event.end
    return local_date(end, event.timezone)


def parse_moment(value, tzname, all_day, is_end):
    """Valeur reçue de l'API -> datetime UTC. Journée entière : date de fin incluse, convertie en fin exclusive."""
    tz = zone(tzname)
    if value in (None, ""):
        raise PlanningError("VALIDATION_ERROR", "Les dates de début et de fin sont obligatoires.")
    try:
        if all_day:
            day = date.fromisoformat(str(value)[:10])
            if is_end:
                day += timedelta(days=1)
            return datetime.combine(day, time.min, tzinfo=tz).astimezone(ZoneInfo("UTC"))
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise PlanningError("VALIDATION_ERROR", f"Date invalide : {value}.") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=tz)
    return moment.astimezone(ZoneInfo("UTC"))


def parse_range(params, default_days=42):
    """Période demandée (?start=&end=, dates ou dates-heures). Par défaut : 6 semaines autour d'aujourd'hui."""
    today = timezone.localdate()
    try:
        start = date.fromisoformat(params.get("start", "")[:10]) if params.get("start") else today - timedelta(days=default_days // 3)
        end = date.fromisoformat(params.get("end", "")[:10]) if params.get("end") else start + timedelta(days=default_days)
    except ValueError as exc:
        raise PlanningError("VALIDATION_ERROR", "Période invalide : dates attendues au format AAAA-MM-JJ.") from exc
    if end < start:
        raise PlanningError("VALIDATION_ERROR", "La fin de la période précède son début.")
    if (end - start).days > MAX_RANGE_DAYS:
        raise PlanningError("VALIDATION_ERROR", f"Période limitée à {MAX_RANGE_DAYS} jours.")
    return start, end


def range_bounds(start, end, tzname="Europe/Paris"):
    tz = zone(tzname)
    return (datetime.combine(start, time.min, tzinfo=tz), datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz))


def working_days(first, last):
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    work = [d for d in days if d.weekday() < 5]
    return work or days


def add_working_days(day, count):
    while count > 0:
        day += timedelta(days=1)
        if day.weekday() < 5:
            count -= 1
    return day


# --------------------------------------------------------------------------- visibilité et droits
def visible_events(user):
    """Événements que l'utilisateur peut voir : son tenant, ses projets visibles, ses propres affectations."""
    if not in_active_tenant(user) or not has_perm(user, "planning", "read"):
        return M.CalendarEvent.objects.none()
    in_projects = Q(project__in=visible_projects(user), action__isnull=True) | Q(action__in=visible_actions(user))
    personal = Q(project__isnull=True) & (Q(created_by=user) | Q(assignments__user=user))
    mine = Q(assignments__user=user, project__isnull=False)  # une affectation explicite donne la lecture
    return M.CalendarEvent.objects.filter(in_projects | personal | mine, tenant_id=user.tenant_id).distinct()


def can_manage_project(user, project, verb="update"):
    if not in_active_tenant(user) or not has_perm(user, "planning", verb):
        return False
    if project is None:
        return True
    if project.tenant_id != user.tenant_id or not visible_projects(user).filter(pk=project.pk).exists():
        return False
    return has_full_scope(user) or ProjectAccess.objects.filter(user=user, project=project, can_edit=True).exists()


def can_edit(user, event):
    if event.tenant_id != user.tenant_id:
        return False
    if event.project_id is None:
        return has_perm(user, "planning", "update") and (event.created_by_id == user.pk or has_full_scope(user))
    return can_manage_project(user, event.project)


def can_quick_update(user, event):
    """Avancement, statut et temps réel : le responsable ou un collaborateur affecté peut les mettre à jour."""
    return can_edit(user, event) or event.assignments.filter(user=user).exists()


def can_delete(user, event):
    if event.project_id is None:
        return event.created_by_id == user.pk or (has_full_scope(user) and has_perm(user, "planning", "delete"))
    return can_manage_project(user, event.project, "delete")


# --------------------------------------------------------------------------- charge
def hours_per_day(tenant):
    row = AppSetting.objects.filter(tenant=tenant, key="time").first()
    try:
        return Decimal(str(row.value.get("hpd"))) if row and row.value.get("hpd") else DEFAULT_HOURS_PER_DAY
    except (AttributeError, ArithmeticError, ValueError):
        return DEFAULT_HOURS_PER_DAY


def daily_capacity(user, default_hpd, capacities):
    cap = capacities.get(user.pk)
    if cap is not None and cap.cap:
        weekly = Decimal(cap.cap) - Decimal(cap.meet or 0)
        return max(weekly / 5, Decimal("0"))
    return default_hpd


def assignment_hours(event, assignment):
    if assignment.estimated_workload is not None:
        return Decimal(assignment.estimated_workload)
    if not event.all_day and event.kind != "milestone":
        return Decimal(str(round((event.end - event.start).total_seconds() / 3600, 2)))
    return Decimal("0")


def workload(tenant, events, start, end, group="user"):
    """Charge par collaborateur (ou par équipe) et par jour, comparée à la capacité."""
    events = [e for e in events if e.status != "cancelled" and e.kind != "milestone"]
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    load = defaultdict(lambda: defaultdict(Decimal))
    users = {}
    contributions = defaultdict(lambda: defaultdict(Decimal))  # (user, jour) -> {événement: heures}
    for e in events:
        span = working_days(first_day(e), last_day(e))
        for a in e.assignments.all():
            hours = assignment_hours(e, a)
            if not hours:
                users.setdefault(a.user_id, a.user)
                continue
            per_day = hours / len(span)
            users.setdefault(a.user_id, a.user)
            for d in span:
                if start <= d <= end:
                    load[a.user_id][d] += per_day
                    contributions[(a.user_id, d)][e.pk] += per_day
    hpd = hours_per_day(tenant)
    capacities = {c.user_id: c for c in PersonCapacity.objects.filter(user_id__in=users)}
    rows = []
    for uid, u in sorted(users.items(), key=lambda kv: kv[1].display_name.lower()):
        cap = daily_capacity(u, hpd, capacities)
        per_day = {d.isoformat(): round(float(load[uid][d]), 2) for d in days if load[uid][d]}
        # Week-end : aucune charge n'y est répartie, sauf élément planifié uniquement ce jour-là (alors compté).
        over = [d.isoformat() for d in days if load[uid][d] > cap + Decimal("0.01")]
        rows.append({"key": str(uid), "user": {"id": uid, "username": u.username, "name": u.display_name, "team": u.team},
                     "label": u.display_name, "team": u.team or "Sans équipe", "capacity": round(float(cap), 2),
                     "total": round(float(sum(load[uid].values())), 2), "load": per_day, "over": over})
    if group == "team":
        teams = {}
        for r in rows:
            t = teams.setdefault(r["team"], {"key": r["team"], "label": r["team"], "team": r["team"], "capacity": 0.0,
                                             "total": 0.0, "load": defaultdict(float), "members": 0})
            t["capacity"] += r["capacity"]
            t["total"] += r["total"]
            t["members"] += 1
            for d, h in r["load"].items():
                t["load"][d] += h
        rows = []
        for t in sorted(teams.values(), key=lambda t: t["label"].lower()):
            t["load"] = {d: round(h, 2) for d, h in t["load"].items()}
            t["over"] = sorted(d for d, h in t["load"].items() if h > t["capacity"] + 0.01)
            t["capacity"], t["total"] = round(t["capacity"], 2), round(t["total"], 2)
            rows.append(t)
    return {"days": [d.isoformat() for d in days], "group": group, "rows": rows, "_contributions": contributions}


# --------------------------------------------------------------------------- conflits
def _iso(dt):
    return dt.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")


def _shift(event, new_start):
    """Proposition : déplacer l'événement en gardant sa durée."""
    duration = event.end - event.start
    return {"event": event.pk, "action": "move", "start": _iso(new_start), "end": _iso(new_start + duration),
            "allDay": event.all_day}


def detect_conflicts(tenant, events, start, end, focus=None, now=None, visible_ids=None, types=None):
    """Conflits du planning.

    La charge et les chevauchements sont calculés sur TOUS les événements du tenant (la charge réelle d'un
    collaborateur), mais un événement que l'utilisateur ne voit pas (`visible_ids`) n'est jamais nommé : il
    apparaît comme « un autre engagement ». `focus` : ne garder que les conflits qui concernent cet événement.
    """
    now = now or timezone.now()
    events = [e for e in events if e.status != "cancelled"]
    by_id = {e.pk: e for e in events}
    found = []

    def _label(e):
        if visible_ids is not None and e.pk not in visible_ids:
            return "un autre engagement (projet non visible)"
        return f"« {e.title} »"

    def add(kind, severity, title, explanation, ids, users=(), suggestion=None):
        if focus is not None and focus not in ids:
            return
        if types is not None and kind not in types:
            return
        shown = [i for i in ids if visible_ids is None or i in visible_ids]
        if not shown:
            return
        if suggestion and visible_ids is not None and suggestion.get("event") not in visible_ids:
            suggestion = None
        found.append({"type": kind, "severity": severity, "title": title, "explanation": explanation,
                      "events": shown, "users": list(users), "suggestion": suggestion})

    # 1. Deux actions simultanées pour un même collaborateur (événements horaires).
    timed = defaultdict(list)
    for e in events:
        if e.is_open and not e.all_day and e.kind != "milestone":
            for a in e.assignments.all():
                timed[a.user_id].append((e, a.user))
    for uid, items in timed.items():
        items.sort(key=lambda x: x[0].start)
        for i, (a, user) in enumerate(items):
            for b, _ in items[i + 1:]:
                if b.start >= a.end:
                    break
                add("double_booking", "warning", f"{user.display_name} est attendu à deux endroits",
                    f"{_label(a)} et {_label(b)} se chevauchent pour {user.display_name}.", [a.pk, b.pk], [uid],
                    _shift(b, a.end))

    # 2. Surcharge d'un collaborateur (charge quotidienne au-delà de sa capacité).
    load = workload(tenant, events, start, end)
    contributions = load.pop("_contributions")
    for row in load["rows"]:
        if not row["over"]:
            continue
        uid = int(row["key"])
        involved = defaultdict(Decimal)
        excess = Decimal("0")
        for d in row["over"]:
            day = date.fromisoformat(d)
            excess += Decimal(str(row["load"][d])) - Decimal(str(row["capacity"]))
            for eid, h in contributions[(uid, day)].items():
                involved[eid] += h
        biggest = by_id[max(involved, key=involved.get)]
        cap = Decimal(str(row["capacity"])) or DEFAULT_HOURS_PER_DAY
        extra_days = max(1, math.ceil(excess / cap))
        new_last = add_working_days(last_day(biggest), extra_days)
        suggestion = {"event": biggest.pk, "action": "extend", "start": _iso(biggest.start),
                      "end": _iso(datetime.combine(new_last + timedelta(days=1), time.min, tzinfo=zone(biggest.timezone))
                                  if biggest.all_day else biggest.end + timedelta(days=extra_days)),
                      "allDay": biggest.all_day}
        add("overload", "warning", f"{row['label']} est surchargé",
            f"{len(row['over'])} jour(s) au-delà de {row['capacity']:g} h par jour (excédent {float(excess):.1f} h). "
            f"Proposition : allonger {_label(biggest)} de {extra_days} jour(s) ouvré(s).",
            sorted(involved), [uid], suggestion)

    # 3. Actions sans responsable.
    for e in events:
        if e.is_open and e.kind in ("action", "task") and not any(a.role == "owner" for a in e.assignments.all()):
            pm = e.project.pm if e.project_id and e.project.pm_id and e.project.pm.is_active else None
            add("unassigned", "info", f"{_label(e)} n'a pas de responsable",
                "Une action sans responsable risque de ne pas être réalisée."
                + (f" Proposition : la confier à {pm.display_name}, chef de projet." if pm else ""),
                [e.pk], [], {"event": e.pk, "action": "assign", "user": pm.pk} if pm else None)

    # 4. Dépendances non respectées.
    for e in events:
        for dep in e.predecessor_links.all():
            p = by_id.get(dep.predecessor_id) or dep.predecessor
            if p.status == "cancelled":
                continue
            t = dep.dependency_type
            needed = {"FS": (e.start, p.end), "SS": (e.start, p.start), "FF": (e.end, p.end), "SF": (e.end, p.start)}[t]
            if needed[0] < needed[1]:
                delta = needed[1] - needed[0]
                add("dependency", "error", f"Dépendance non respectée : {_label(p)} → {_label(e)}",
                    f"{_label(e)} ({dict(M.DEPENDENCY_TYPES)[t]}) commence ou finit avant {_label(p)}.",
                    [p.pk, e.pk], [], _shift(e, e.start + delta))

    # 5. Échéance incompatible avec la fin du projet.
    for e in events:
        if e.is_open and e.project_id and e.project.end_date and last_day(e) > e.project.end_date:
            tz = zone(e.timezone)
            new_end = datetime.combine(e.project.end_date + timedelta(days=1), time.min, tzinfo=tz)
            add("deadline", "warning", f"{_label(e)} dépasse la fin du projet",
                f"Fin prévue le {last_day(e):%d/%m/%Y}, après la fin du projet {e.project.code} ({e.project.end_date:%d/%m/%Y}). "
                "Proposition : avancer l'événement pour qu'il se termine avec le projet.",
                [e.pk], [], _shift(e, e.start - (e.end - new_end)))

    # 6. Actions en retard.
    for e in events:
        if e.is_open and e.kind != "milestone" and e.end < now:
            remaining = (e.end - e.start) * (100 - e.progress) / 100
            new_end = now + max(remaining, timedelta(hours=1))
            if e.all_day:
                new_end = datetime.combine(local_date(new_end, e.timezone) + timedelta(days=1), time.min, tzinfo=zone(e.timezone))
            days_late = (now - e.end).days
            add("late", "error", f"{_label(e)} est en retard",
                f"Échéance dépassée de {days_late} jour(s), avancement {e.progress} %. "
                "Proposition : reporter la fin selon le reste à faire.",
                [e.pk], [a.user_id for a in e.assignments.all()],
                {"event": e.pk, "action": "extend", "start": _iso(e.start), "end": _iso(new_end), "allDay": e.all_day})
    return found


def events_in(qs, start, end, tzname="Europe/Paris"):
    lo, hi = range_bounds(start, end, tzname)
    return (qs.filter(start__lt=hi, end__gte=lo)
            .select_related("project__pm", "action", "created_by")
            .prefetch_related("assignments__user", "predecessor_links__predecessor", "successor_links"))


# --------------------------------------------------------------------------- enregistrement
FIELDS = ("title", "description", "phase", "kind", "status", "priority", "progress", "timezone")
QUICK_FIELDS = {"status", "progress", "actualWorkload"}


def _active_member(tenant, user_id, project):
    user = User.objects.filter(pk=user_id, tenant=tenant, is_active=True).first()
    if user is None:
        raise PlanningError("VALIDATION_ERROR", "Collaborateur introuvable dans votre entreprise.", details=[user_id])
    if project is not None and not visible_projects(user).filter(pk=project.pk).exists():
        raise PlanningError("VALIDATION_ERROR", f"{user.display_name} n'a pas accès au projet {project.code}.", details=[user_id])
    return user


def _snapshot(event):
    owner = next((a.user_id for a in event.assignments.all() if a.role == "owner"), None)
    return {"start": event.start, "end": event.end, "owner": owner, "status": event.status,
            "users": {a.user_id for a in event.assignments.all()}}


def _would_cycle(successor, predecessor):
    """Vrai si `predecessor` dépend déjà (directement ou non) de `successor`."""
    seen, stack = set(), [predecessor.pk]
    while stack:
        current = stack.pop()
        if current == successor.pk:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(M.CalendarDependency.objects.filter(successor_id=current).values_list("predecessor_id", flat=True))
    return False


def save_event(by, data, event=None, confirm=False):
    """Crée ou modifie un événement. Lève ConflictsPending si des conflits apparaissent sans confirmation."""
    try:
        with transaction.atomic():
            return _save(by, data, event, confirm)
    except ConflictsPending:
        raise


def _save(by, data, event, confirm):
    creating = event is None
    tenant = by.tenant
    if creating:
        project = action = None
        if data.get("action"):
            action = visible_actions(by).filter(pk=data["action"]).select_related("project").first()
            if action is None:
                raise PlanningError("NOT_FOUND", "Action introuvable.", 404)
            if M.CalendarEvent.objects.filter(action=action).exists():
                raise PlanningError("VALIDATION_ERROR", "Cette action est déjà planifiée : modifiez son événement.")
            project = action.project
        elif data.get("project"):
            project = visible_projects(by).filter(pk=data["project"]).first()
            if project is None:
                raise PlanningError("NOT_FOUND", "Projet introuvable.", 404)
        if not can_manage_project(by, project, "create"):
            raise PlanningError("FORBIDDEN_PERMISSION", "Vous n'avez pas le droit de planifier sur ce projet.", 403)
        event = M.CalendarEvent(tenant=tenant, project=project, action=action, created_by=by,
                                kind="action" if action else data.get("kind") or "task",
                                title=data.get("title") or (action.title if action else ""))
        before = None
        full = True
    else:
        full = can_edit(by, event)
        if not full:
            if not can_quick_update(by, event):
                raise PlanningError("FORBIDDEN_PERMISSION", "Vous n'avez pas le droit de modifier cet événement.", 403)
            extra = set(data) - QUICK_FIELDS - {"confirm"}
            if extra:
                raise PlanningError("FORBIDDEN_PERMISSION", "Vous pouvez seulement mettre à jour l'avancement, le statut "
                                    "et votre temps réel.", 403, sorted(extra))
        before = _snapshot(event)

    for field in FIELDS:
        if field in data and (full or field in ("status", "progress")):
            setattr(event, field, data[field])
    for field, choices in (("kind", M.KINDS), ("status", M.STATUSES), ("priority", M.PRIORITIES)):
        if getattr(event, field) not in dict(choices):
            raise PlanningError("VALIDATION_ERROR", f"Valeur inconnue pour {field} : {getattr(event, field)}.")
    if event.action_id:
        event.kind = "action"
    elif event.kind == "action":
        event.kind = "task"
    try:
        event.progress = int(event.progress)
    except (TypeError, ValueError) as exc:
        raise PlanningError("VALIDATION_ERROR", "L'avancement doit être un nombre.") from exc
    if not event.title.strip():
        raise PlanningError("VALIDATION_ERROR", "Le titre est obligatoire.")
    zone(event.timezone)
    if full and ("start" in data or "end" in data or "allDay" in data or creating):
        event.all_day = bool(data.get("allDay", event.all_day if not creating else True))
        start_value = data.get("start") if "start" in data else (
            first_day(event).isoformat() if event.all_day and not creating else event.start.isoformat() if not creating else None)
        end_value = data.get("end") if "end" in data else (
            last_day(event).isoformat() if event.all_day and not creating else event.end.isoformat() if not creating else None)
        if creating and event.action_id and not start_value:
            a = event.action
            start_value = (a.start_date or a.due or timezone.localdate()).isoformat()
            end_value = (a.due or a.start_date or timezone.localdate()).isoformat()
        event.start = parse_moment(start_value, event.timezone, event.all_day, False)
        event.end = parse_moment(end_value, event.timezone, event.all_day, True)
        if event.end < event.start:
            raise PlanningError("VALIDATION_ERROR", "La fin précède le début.")
    if not 0 <= int(event.progress) <= 100:
        raise PlanningError("VALIDATION_ERROR", "L'avancement est compris entre 0 et 100 %.")
    if event.status == "done":
        event.progress = 100
        event.completed_at = event.completed_at or timezone.now()
    elif event.completed_at and event.status != "done":
        event.completed_at = None
    if before and (before["start"] != event.start or before["end"] != event.end):
        event.late_notified_at = None
    event.save()

    if full and "assignments" in data:
        _set_assignments(by, event, data["assignments"])
    elif creating and event.action_id and event.action.owner_id and "assignments" not in data:
        _set_assignments(by, event, [{"user": event.action.owner_id, "role": "owner",
                                      "estimatedWorkload": event.action.est}])
    if "actualWorkload" in data:
        mine = event.assignments.filter(user=by).first()
        if mine is None:
            raise PlanningError("VALIDATION_ERROR", "Vous n'êtes pas affecté à cet événement.")
        mine.actual_workload = data["actualWorkload"]
        mine.save(update_fields=["actual_workload"])
    if full and "dependencies" in data:
        _set_dependencies(event, data["dependencies"])

    event = M.CalendarEvent.objects.select_related("project__pm", "action").prefetch_related(
        "assignments__user", "predecessor_links__predecessor").get(pk=event.pk)
    changed = set(_changed(before, event)) if before else {"start", "end", "users"}
    if not confirm and changed & {"start", "end", "users"}:
        # Dates changées : tous les conflits. Seules les affectations changées : chevauchements, surcharge, responsable.
        types = None if changed & {"start", "end"} else {"double_booking", "overload", "unassigned"}
        lo, hi = first_day(event) - timedelta(days=1), last_day(event) + timedelta(days=1)
        window = list(events_in(M.CalendarEvent.objects.filter(tenant=tenant), lo, hi, event.timezone))
        visible_ids = set(visible_events(by).values_list("pk", flat=True)) | {event.pk}
        conflicts = detect_conflicts(tenant, window, lo, hi, focus=event.pk, visible_ids=visible_ids, types=types)
        if conflicts:
            raise ConflictsPending(conflicts)

    sync_action(event)
    schedule_default_reminders(event)
    _notify_changes(by, event, before)
    audit.record(by, f"Événement {event.title}"[:200], "Événement créé" if creating else "Événement modifié",
                 "" if creating else f"{before['start']:%Y-%m-%d %H:%M} → {before['end']:%Y-%m-%d %H:%M} · {before['status']}",
                 f"{event.start:%Y-%m-%d %H:%M} → {event.end:%Y-%m-%d %H:%M} · {event.status}")
    return event


def _changed(before, event):
    after = _snapshot(event)
    return [k for k in ("start", "end", "users", "status") if before[k] != after[k]]


def _set_assignments(by, event, items):
    if not isinstance(items, list):
        raise PlanningError("VALIDATION_ERROR", "Format des affectations invalide.")
    wanted = {}
    owners = 0
    for item in items:
        user = _active_member(event.tenant, item.get("user"), event.project)
        role = item.get("role", "contributor")
        if role not in dict(M.ROLES):
            raise PlanningError("VALIDATION_ERROR", f"Rôle inconnu : {role}.")
        owners += role == "owner"
        wanted[user.pk] = (user, role, item.get("estimatedWorkload"), item.get("actualWorkload"))
    if owners > 1:
        raise PlanningError("VALIDATION_ERROR", "Un seul responsable principal par événement.")
    event.assignments.exclude(user_id__in=wanted).delete()
    # Le responsable change en deux temps pour respecter l'unicité « un responsable par événement ».
    event.assignments.filter(role="owner").exclude(user_id__in=[u for u, w in wanted.items() if w[1] == "owner"]).update(role="contributor")
    for uid, (user, role, est, actual) in sorted(wanted.items(), key=lambda kv: kv[1][1] == "owner"):
        values = {"role": role}
        if est not in (None, ""):
            values["estimated_workload"] = Decimal(str(est))
        if actual not in (None, ""):
            values["actual_workload"] = Decimal(str(actual))
        M.CalendarAssignment.objects.update_or_create(event=event, user=user, defaults={"tenant": event.tenant, **values})


def _set_dependencies(event, items):
    if not isinstance(items, list):
        raise PlanningError("VALIDATION_ERROR", "Format des dépendances invalide.")
    keep = []
    for item in items:
        pred = M.CalendarEvent.objects.filter(pk=item.get("predecessor"), tenant=event.tenant).first()
        if pred is None or pred.pk == event.pk:
            raise PlanningError("VALIDATION_ERROR", "Prédécesseur introuvable.", details=[item.get("predecessor")])
        kind = item.get("type", "FS")
        if kind not in dict(M.DEPENDENCY_TYPES):
            raise PlanningError("VALIDATION_ERROR", f"Type de dépendance inconnu : {kind}.")
        if _would_cycle(event, pred):
            raise PlanningError("VALIDATION_ERROR", f"Dépendance circulaire avec « {pred.title} ».")
        M.CalendarDependency.objects.update_or_create(predecessor=pred, successor=event,
                                                      defaults={"tenant": event.tenant, "dependency_type": kind})
        keep.append(pred.pk)
    event.predecessor_links.exclude(predecessor_id__in=keep).delete()


def sync_action(event):
    """L'action liée reste l'objet métier : dates, statut, priorité, phase et responsable y sont recopiés."""
    if not event.action_id:
        return
    a = Action.objects.get(pk=event.action_id)
    a.title = event.title[:300]
    a.start_date = first_day(event)
    a.due = last_day(event)
    a.phase = event.phase[:60]
    a.prio = M.EVENT_PRIO_TO_ACTION.get(event.priority, a.prio)
    if event.status != "cancelled":
        a.status = event.status
    if event.status == "done" and not a.done_at:
        a.done_at = timezone.localdate()
    owner = event.assignments.filter(role="owner").first()
    if owner is not None:
        a.owner_id = owner.user_id
    a.save()


def delete_event(by, event):
    if not can_delete(by, event):
        raise PlanningError("FORBIDDEN_PERMISSION", "Vous n'avez pas le droit de supprimer cet événement.", 403)
    title = event.title
    event.delete()  # l'action liée n'est pas supprimée : seul son planning disparaît
    audit.record(by, f"Événement {title}"[:200], "Événement supprimé")


def plan_existing_actions(tenant):
    """Crée l'événement de chaque action datée qui n'en a pas encore (les actions apparaissent dans le calendrier)."""
    created = 0
    for a in Action.objects.filter(tenant=tenant, calendar_event__isnull=True).select_related("owner"):
        first, last = a.start_date or a.due, a.due or a.start_date
        if not first:
            continue
        if last < first:
            first, last = last, first
        tz = zone("Europe/Paris")
        event = M.CalendarEvent.objects.create(
            tenant=tenant, project_id=a.project_id, action=a, kind="action", title=a.title, phase=a.phase,
            start=datetime.combine(first, time.min, tzinfo=tz), end=datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz),
            all_day=True, status=a.status, priority=M.ACTION_PRIO_TO_EVENT.get(a.prio, "normal"),
            progress=100 if a.status == "done" else (int(min(100, float(a.done) / float(a.est) * 100)) if a.est and a.done else 0),
            completed_at=datetime.combine(a.done_at, time(12), tzinfo=tz) if a.done_at else None)
        if a.owner_id:
            M.CalendarAssignment.objects.create(tenant=tenant, event=event, user_id=a.owner_id, role="owner",
                                                estimated_workload=a.est, actual_workload=a.done)
        created += 1
    return created


# --------------------------------------------------------------------------- notifications et rappels
def _recipients(event):
    return [a.user for a in event.assignments.select_related("user")]


def _notify_changes(by, event, before):
    after = _snapshot(event)
    users = {a.user_id: a.user for a in event.assignments.select_related("user")}
    others = lambda ids: [users[i] for i in ids if i in users and i != by.pk]  # noqa: E731
    label = f"{event.title}" + (f" · {event.project.code}" if event.project_id else "")
    new_users = after["users"] - (before["users"] if before else set())
    if new_users:
        notify.notify("action_assigned", others(new_users), "Vous êtes affecté à une action", label)
    if before is None:
        return
    if before["owner"] != after["owner"]:
        targets = others([i for i in (before["owner"], after["owner"]) if i])
        old = User.objects.filter(pk=before["owner"]).first() if before["owner"] else None
        if old and old.pk not in users and old.pk != by.pk:
            targets.append(old)
        notify.notify("owner_changed", targets, "Changement de responsable", label)
    if (before["start"], before["end"]) != (after["start"], after["end"]):
        notify.notify("date_changed", others(after["users"] & before["users"]), "Dates modifiées",
                      f"{label} : du {first_day(event):%d/%m} au {last_day(event):%d/%m}")
    if after["status"] == "blocked" and before["status"] != "blocked":
        targets = others(after["users"])
        if event.project_id and event.project.pm_id and event.project.pm_id != by.pk:
            targets.append(event.project.pm)
        notify.notify("action_blocked", targets, "Action bloquée", label)


def schedule_default_reminders(event):
    """Rappels automatiques : la veille de l'échéance pour le responsable, la veille d'un jalon pour les affectés."""
    event.reminders.filter(status="pending", kind__in=["deadline", "milestone"]).delete()
    now = timezone.now()
    if event.kind == "milestone":
        at = event.start - timedelta(days=1)
        if at > now:
            for a in event.assignments.all():
                M.CalendarReminder.objects.create(tenant=event.tenant, event=event, user_id=a.user_id, remind_at=at, kind="milestone")
    elif event.is_open:
        at = event.end - timedelta(days=1)
        owner = event.assignments.filter(role="owner").first()
        if owner and at > now:
            M.CalendarReminder.objects.create(tenant=event.tenant, event=event, user_id=owner.user_id, remind_at=at, kind="deadline")


def process_due_reminders(tenant=None, now=None):
    now = now or timezone.now()
    qs = M.CalendarReminder.objects.filter(status="pending", remind_at__lte=now).select_related("event", "user")
    if tenant is not None:
        qs = qs.filter(tenant=tenant)
    sent = 0
    for r in qs[:500]:
        e = r.event
        if e.kind != "milestone" and not e.is_open:
            r.status = "cancelled"
            r.save(update_fields=["status"])
            continue
        code = "milestone_reminder" if r.kind == "milestone" else "deadline_reminder"
        title = ("Jalon demain : " if r.kind == "milestone" else "Échéance proche : ") + e.title
        error = notify.deliver(r.channel, r.user, code, title, f"Le {last_day(e):%d/%m/%Y}" if r.kind != "milestone" else f"Le {first_day(e):%d/%m/%Y}")
        r.status, r.error, r.sent_at = ("failed", error[:300], None) if error else ("sent", "", now)
        r.save(update_fields=["status", "error", "sent_at"])
        sent += not error
    return sent


def notify_late(tenant=None, now=None):
    now = now or timezone.now()
    qs = M.CalendarEvent.objects.filter(status__in=M.OPEN_STATUSES, end__lt=now, late_notified_at__isnull=True).exclude(kind="milestone")
    if tenant is not None:
        qs = qs.filter(tenant=tenant)
    count = 0
    for e in qs.select_related("project__pm")[:500]:
        targets = _recipients(e)
        if e.project_id and e.project.pm_id:
            targets.append(e.project.pm)
        notify.notify("action_late", targets, "Action en retard", e.title)
        e.late_notified_at = now
        e.save(update_fields=["late_notified_at"])
        count += 1
    return count


# --------------------------------------------------------------------------- indicateurs
def dashboard(user, start, end):
    events = list(events_in(visible_events(user), start, end))
    now = timezone.now()
    active = [e for e in events if e.status != "cancelled"]
    late = [e for e in active if e.is_open and e.kind != "milestone" and e.end < now]
    done = [e for e in active if e.status == "done"]
    on_time = [e for e in done if e.completed_at and e.completed_at <= e.end]
    soon = now + timedelta(days=14)
    work = [e for e in active if e.kind != "milestone"]
    delays = defaultdict(lambda: {"late": 0, "days": 0, "total": 0})
    for e in work:
        if e.project_id:
            d = delays[(e.project_id, e.project.code, e.project.name)]
            d["total"] += 1
            if e in late:
                d["late"] += 1
                d["days"] += (now - e.end).days
    load = workload(user.tenant, active, start, end)
    load.pop("_contributions")
    team_load = workload(user.tenant, active, start, end, group="team")
    team_load.pop("_contributions")
    summarize = lambda rows: [{"key": r["key"], "label": r["label"], "total": r["total"], "overDays": len(r["over"]),  # noqa: E731
                               "capacity": r["capacity"]} for r in rows]
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "planned": len(work),
        "done": len(done),
        "inProgress": sum(e.status in ("doing", "review") for e in active),
        "blocked": sum(e.status == "blocked" for e in active),
        "late": len(late),
        "upcoming": sum(e.is_open and now <= e.start <= soon for e in work),
        "milestones": [{"id": e.pk, "title": e.title, "date": first_day(e).isoformat(), "project": e.project.code if e.project_id else None,
                        "status": e.status} for e in active if e.kind == "milestone" and e.end >= now][:10],
        "progressRate": round(sum(e.progress for e in work) / len(work), 1) if work else 0,
        "onTimeRate": round(len(on_time) / len(done) * 100, 1) if done else None,
        "workloadByUser": summarize(load["rows"]),
        "workloadByTeam": summarize(team_load["rows"]),
        "delaysByProject": [{"project": {"id": pid, "code": code, "name": name}, "late": d["late"], "total": d["total"],
                             "avgDelayDays": round(d["days"] / d["late"], 1) if d["late"] else 0}
                            for (pid, code, name), d in sorted(delays.items(), key=lambda kv: -kv[1]["late"])],
    }


def portfolio(user):
    now = timezone.now()
    rows = []
    projects = visible_projects(user).select_related("client", "pm")
    events = defaultdict(list)
    for e in visible_events(user).filter(project__in=projects).exclude(status="cancelled"):
        events[e.project_id].append(e)
    for p in projects:
        evs = events.get(p.pk, [])
        late = [e for e in evs if e.is_open and e.kind != "milestone" and e.end < now]
        rows.append({
            "id": p.pk, "code": p.code, "name": p.name, "client": p.client.name,
            "pm": p.pm.display_name if p.pm_id else None, "start": p.start_date, "end": p.end_date,
            "forecastEnd": p.forecast_end, "progress": p.progress,
            "events": len(evs), "late": len(late),
            "milestones": [{"title": e.title, "date": first_day(e).isoformat(), "status": e.status} for e in evs if e.kind == "milestone"],
            "health": "late" if late or (p.forecast_end and p.end_date and p.forecast_end > p.end_date) else "ok",
        })
    return rows


# --------------------------------------------------------------------------- flux ICS
def issue_feed_token(user):
    user.calendar_feed_tokens.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
    raw = secrets.token_urlsafe(32)
    M.CalendarFeedToken.objects.create(tenant=user.tenant, user=user, token_hash=hashlib.sha256(raw.encode()).hexdigest())
    audit.record(user, f"Utilisateur {user.username}", "Lien d'abonnement au calendrier créé")
    return raw


def feed_user(raw):
    token = M.CalendarFeedToken.objects.select_related("user__tenant").filter(
        token_hash=hashlib.sha256(raw.encode()).hexdigest(), revoked_at__isnull=True).first()
    if token is None or not token.user.is_active or not in_active_tenant(token.user):
        return None
    M.CalendarFeedToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
    return token.user


def _ics_text(value):
    return str(value).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def _fold(line):
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, current = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(current) + len(b) > (75 if not parts else 74):
            parts.append(current.decode("utf-8"))
            current = b""
        current += b
    parts.append(current.decode("utf-8"))
    return "\r\n ".join(parts)


def ics_feed(user):
    today = timezone.localdate()
    events = events_in(visible_events(user), today - timedelta(days=30), today + timedelta(days=180))
    stamp = timezone.now().strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Project Control Tower//Calendrier//FR", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{_ics_text('PCT · ' + user.display_name)}"]
    for e in events:
        if e.status == "cancelled":
            continue
        lines += ["BEGIN:VEVENT", f"UID:pct-event-{e.pk}@{user.tenant.slug}", f"DTSTAMP:{stamp}"]
        if e.all_day:
            lines += [f"DTSTART;VALUE=DATE:{first_day(e):%Y%m%d}", f"DTEND;VALUE=DATE:{last_day(e) + timedelta(days=1):%Y%m%d}"]
        else:
            lines += [f"DTSTART:{e.start.astimezone(ZoneInfo('UTC')):%Y%m%dT%H%M%SZ}",
                      f"DTEND:{e.end.astimezone(ZoneInfo('UTC')):%Y%m%dT%H%M%SZ}"]
        summary = e.title + (f" ({e.project.code})" if e.project_id else "")
        lines += [f"SUMMARY:{_ics_text(summary)}", f"DESCRIPTION:{_ics_text(e.description or '')}",
                  f"STATUS:{'COMPLETED' if e.status == 'done' else 'CONFIRMED'}" if e.kind != "meeting" else "STATUS:CONFIRMED",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
