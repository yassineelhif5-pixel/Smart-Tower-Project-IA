"""Feuille de temps par période (jour, semaine, mois) : saisie en brouillon par projet et par ligne,
absences, contrôle de complétude et envoi en validation de la période.

Lignes de saisie : chaque projet peut avoir des lignes (activités) définies par le client ou l'administrateur,
ajoutées au fil de l'eau dans le paramétrage du projet. L'administrateur (ou le Pilote) choisit les profils
qui saisissent par ligne ; pour ces profils, une ligne est obligatoire dès que le projet en a.
"""
import secrets
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import has_perm
from config.errors import ApiError
from configuration import audit
from configuration.models import AppSetting
from planning.services import hours_per_day
from .access import in_active_tenant, visible_projects
from .models import ABSENCE_KINDS, Project, ProjectAccess, TimeAbsence, TimeEntry
from . import time_approval

LINES_KEY, LINES_PROFILES_KEY = "timesheet_lines", "timesheet_lines_profiles"
DEFAULT_LINE_PROFILES = ["consultant", "dev", "testeur", "techlead", "cdp", "support_n1", "support_n2", "support_n3"]


# --------------------------------------------------------------------------- jours fériés (France)
def _easter(y):
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    return date(y, month, ((h + l_ - 7 * m + 114) % 31) + 1)


def holidays(year):
    e = _easter(year)
    return {date(year, 1, 1): "Jour de l'an", e + timedelta(days=1): "Lundi de Pâques", date(year, 5, 1): "Fête du travail",
            date(year, 5, 8): "Victoire 1945", e + timedelta(days=39): "Ascension", e + timedelta(days=50): "Lundi de Pentecôte",
            date(year, 7, 14): "Fête nationale", date(year, 8, 15): "Assomption", date(year, 11, 1): "Toussaint",
            date(year, 11, 11): "Armistice", date(year, 12, 25): "Noël"}


# --------------------------------------------------------------------------- lignes de saisie
def _map(tenant, key):
    row = AppSetting.objects.filter(tenant=tenant, key=key).first()
    return row.value if row and row.value is not None else None


def lines_of(project, active_only=False):
    items = list(((_map(project.tenant, LINES_KEY) or {}).get(project.id)) or [])
    return [x for x in items if x.get("active", True)] if active_only else items


def _save_lines(project, items):
    row, _ = AppSetting.objects.select_for_update().get_or_create(tenant=project.tenant, key=LINES_KEY, defaults={"value": {}})
    data = dict(row.value or {})
    data[project.id] = items
    row.value = data
    row.save(update_fields=["value"])


def line_profiles(tenant):
    v = _map(tenant, LINES_PROFILES_KEY)
    return list(v) if isinstance(v, list) else list(DEFAULT_LINE_PROFILES)


def lines_enabled_for(user):
    return bool(user.role_id and user.role_id in line_profiles(user.tenant))


def can_manage_lines(user, project):
    from .budget_report import is_client_of
    return bool(user.is_app_admin or user.is_platform_admin or is_client_of(user, project))


class ProjectLinesView(APIView):
    """GET : lignes de saisie du projet. POST {label, code?} : ajoute une ligne. PATCH {id, label?, active?} : modifie."""

    def _project(self, request, pk):
        project = Project.objects.filter(pk=pk, tenant=request.user.tenant).first()
        if project is None or not (request.user.is_app_admin or visible_projects(request.user).filter(pk=pk).exists()):
            raise ApiError("NOT_FOUND", "Projet introuvable.", status.HTTP_404_NOT_FOUND)
        return project

    def _out(self, request, project):
        used = {}
        for line, n in TimeEntry.objects.filter(project=project).exclude(line="").values_list("line").order_by().annotate(
                n=__import__("django.db.models", fromlist=["Count"]).Count("id")):
            used[line] = n
        return Response({"lines": [{**x, "entries": used.get(x["id"], 0)} for x in lines_of(project)],
                         "canManage": can_manage_lines(request.user, project), "profiles": line_profiles(project.tenant)})

    def get(self, request, pk):
        return self._out(request, self._project(request, pk))

    def post(self, request, pk):
        project = self._project(request, pk)
        if not can_manage_lines(request.user, project):
            raise ApiError("FORBIDDEN_PERMISSION", "Les lignes de saisie sont définies par le client ou l'administrateur.", status.HTTP_403_FORBIDDEN)
        label = str(request.data.get("label") or "").strip()[:80]
        if not label:
            raise ApiError("VALIDATION_ERROR", "Donnez un libellé à la ligne.")
        with transaction.atomic():
            items = lines_of(project)
            if any(x["label"].lower() == label.lower() for x in items):
                raise ApiError("CONFLICT", "Cette ligne existe déjà.", status.HTTP_409_CONFLICT)
            items.append({"id": secrets.token_hex(4), "label": label, "code": str(request.data.get("code") or "").strip()[:20],
                          "active": True, "by": request.user.display_name, "at": timezone.now().isoformat()})
            _save_lines(project, items)
        audit.record(request.user, f"Projet {project.code}", "Ligne de saisie ajoutée", "", label, tenant=project.tenant)
        return self._out(request, project)

    def patch(self, request, pk):
        project = self._project(request, pk)
        if not can_manage_lines(request.user, project):
            raise ApiError("FORBIDDEN_PERMISSION", "Les lignes de saisie sont définies par le client ou l'administrateur.", status.HTTP_403_FORBIDDEN)
        with transaction.atomic():
            items = lines_of(project)
            line = next((x for x in items if x["id"] == request.data.get("id")), None)
            if line is None:
                raise ApiError("NOT_FOUND", "Ligne introuvable.", status.HTTP_404_NOT_FOUND)
            if "label" in request.data and str(request.data["label"]).strip():
                line["label"] = str(request.data["label"]).strip()[:80]
            if "code" in request.data:
                line["code"] = str(request.data.get("code") or "").strip()[:20]
            if "active" in request.data:
                line["active"] = bool(request.data["active"])
            _save_lines(project, items)
        audit.record(request.user, f"Projet {project.code}", "Ligne de saisie modifiée", "", str(line), tenant=project.tenant)
        return self._out(request, project)


class LineProfilesView(APIView):
    """Administrateur : profils qui saisissent par ligne. GET / PUT {profiles: [...]}."""

    def get(self, request):
        if not request.user.is_app_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé à l'administrateur.", status.HTTP_403_FORBIDDEN)
        return Response(_profiles_out(request.user.tenant))

    def put(self, request):
        if not request.user.is_app_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé à l'administrateur.", status.HTTP_403_FORBIDDEN)
        return Response(_save_profiles(request.user.tenant, request.data.get("profiles"), request.user))


class PilotLineProfilesView(APIView):
    def get(self, request, tenant_id):
        from tenants.models import Tenant
        if not request.user.is_platform_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé au Pilote.", status.HTTP_403_FORBIDDEN)
        return Response(_profiles_out(Tenant.objects.get(pk=tenant_id)))

    def put(self, request, tenant_id):
        from tenants.models import Tenant
        if not request.user.is_platform_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé au Pilote.", status.HTTP_403_FORBIDDEN)
        return Response(_save_profiles(Tenant.objects.get(pk=tenant_id), request.data.get("profiles"), request.user))


def _profiles_out(tenant):
    from accounts.models import Role
    from django.db.models import Q
    return {"profiles": line_profiles(tenant),
            "roles": [{"code": r.code, "label": r.label} for r in Role.objects.filter(internal=True).filter(Q(tenant__isnull=True) | Q(tenant=tenant)).order_by("label")]}


def _save_profiles(tenant, profiles, by):
    if not isinstance(profiles, list):
        raise ApiError("VALIDATION_ERROR", "Liste de profils attendue.")
    AppSetting.objects.update_or_create(tenant=tenant, key=LINES_PROFILES_KEY, defaults={"value": [str(p) for p in profiles]})
    audit.record(by, "Feuille de temps", "Profils saisissant par ligne", "", ", ".join(map(str, profiles)), tenant=tenant)
    return _profiles_out(tenant)


# --------------------------------------------------------------------------- feuille de temps
def _settings(tenant):
    row = AppSetting.objects.filter(tenant=tenant, key="time").first()
    v = row.value if row and isinstance(row.value, dict) else {}
    hpd = Decimal(str(hours_per_day(tenant) or 8))
    return v.get("entryUnit", "hour"), hpd


def _range(request):
    try:
        start = date.fromisoformat(request.query_params.get("from") or request.data.get("from"))
        end = date.fromisoformat(request.query_params.get("to") or request.data.get("to"))
    except (TypeError, ValueError):
        raise ApiError("VALIDATION_ERROR", "Période invalide.")
    if end < start or (end - start).days > 62:
        raise ApiError("VALIDATION_ERROR", "Période trop longue (2 mois maximum).")
    return start, end


def _amount_out(hours, unit, hpd):
    v = Decimal(hours) / hpd if unit == "day" else Decimal(hours)
    return float(v.quantize(Decimal("0.01")))


def _sheet(user, start, end):
    unit, hpd = _settings(user.tenant)
    full = hpd
    hol = {**holidays(start.year), **holidays(end.year)}
    projects = list(visible_projects(user).filter(status="active").select_related("client").order_by("name")) \
        if hasattr(Project, "status") else list(visible_projects(user).select_related("client"))
    by_line = lines_enabled_for(user)
    entries = list(TimeEntry.objects.filter(person=user, work_date__range=(start, end)).select_related("project"))
    absences = list(TimeAbsence.objects.filter(person=user, work_date__range=(start, end)))
    days, per_day = [], {}
    for e in entries:
        if e.approval_status != "rejected":
            per_day[e.work_date] = per_day.get(e.work_date, Decimal("0")) + e.hours
    for a in absences:
        per_day[a.work_date] = per_day.get(a.work_date, Decimal("0")) + a.hours
    d = start
    incomplete = []
    while d <= end:
        working = d.weekday() < 5 and d not in hol
        total = per_day.get(d, Decimal("0"))
        complete = (not working) or total >= full
        if working and not complete:
            incomplete.append(d.isoformat())
        days.append({"date": d.isoformat(), "working": working, "holiday": hol.get(d), "total": _amount_out(total, unit, hpd),
                     "complete": complete, "over": total > Decimal("24")})
        d += timedelta(days=1)
    drafts = sum(1 for e in entries if e.approval_status in ("draft", "rejected")) + sum(1 for a in absences if a.status == "draft")
    proj_out = []
    for p in projects:
        lines = lines_of(p, active_only=True) if by_line else []
        proj_out.append({"id": p.id, "code": p.code, "name": p.name, "client": p.client.name if p.client_id else "",
                         "lines": [{"id": x["id"], "label": x["label"], "code": x.get("code", "")} for x in lines],
                         "lineRequired": bool(lines)})
    return {
        "unit": unit, "hoursPerDay": float(hpd), "full": 1 if unit == "day" else float(hpd), "from": start, "to": end,
        "approval": time_approval.approval_mode(user.tenant),
        "projects": proj_out,
        "entries": [{"id": e.id, "project": e.project_id, "line": e.line, "date": e.work_date, "amount": _amount_out(e.hours, unit, hpd),
                     "status": e.approval_status} for e in entries],
        "absences": [{"id": a.id, "kind": a.kind, "date": a.work_date, "amount": _amount_out(a.hours, unit, hpd), "status": a.status}
                     for a in absences],
        "absenceKinds": [{"code": c, "label": l} for c, l in ABSENCE_KINDS],
        "days": days, "incomplete": incomplete, "drafts": drafts,
        "canSubmit": not incomplete and drafts > 0,
    }


def _guard(user):
    if not in_active_tenant(user) or not has_perm(user, "timesheet", "create") or not user.role or not user.role.internal:
        raise ApiError("FORBIDDEN_PERMISSION", "La saisie est réservée aux collaborateurs autorisés.", status.HTTP_403_FORBIDDEN)


class TimeSheetView(APIView):
    """GET ?from&to : ma feuille. PUT {cells:[{project, line, date, amount}], absences:[{date, kind, amount}]} : enregistre en brouillon."""

    def get(self, request):
        _guard(request.user)
        start, end = _range(request)
        return Response(_sheet(request.user, start, end))

    def put(self, request):
        user = request.user
        _guard(user)
        unit, hpd = _settings(user.tenant)
        visible = {p.id: p for p in visible_projects(user)}
        by_line = lines_enabled_for(user)

        def hours_of(raw):
            try:
                v = Decimal(str(raw if raw not in (None, "") else 0))
            except InvalidOperation:
                raise ApiError("VALIDATION_ERROR", "Durée invalide.")
            if not v.is_finite() or v < 0:
                raise ApiError("VALIDATION_ERROR", "Durée invalide.")
            h = v * hpd if unit == "day" else v
            if h > 24:
                raise ApiError("VALIDATION_ERROR", "Une saisie ne peut dépasser 24 heures.")
            return h.quantize(Decimal("0.01"))

        from .budget_report import check_entry_allowed
        with transaction.atomic():
            for c in request.data.get("cells") or []:
                project = visible.get(c.get("project"))
                if project is None:
                    raise ApiError("NOT_FOUND", "Projet introuvable.", status.HTTP_404_NOT_FOUND)
                day = date.fromisoformat(str(c.get("date")))
                line = str(c.get("line") or "")
                active = {x["id"] for x in lines_of(project, active_only=True)} if by_line else set()
                if active and line not in active:
                    raise ApiError("VALIDATION_ERROR", f"Choisissez une ligne de saisie pour {project.name}.")
                if not by_line:
                    line = ""
                h = hours_of(c.get("amount"))
                rows = list(TimeEntry.objects.select_for_update().filter(person=user, project=project, work_date=day, line=line))
                locked = [r for r in rows if r.approval_status in ("pending", "client", "approved")]
                editable = [r for r in rows if r.approval_status in ("draft", "rejected")]
                if locked and not editable and h > 0:
                    raise ApiError("CONFLICT", f"{project.name} le {day:%d/%m} est déjà envoyé en validation.", status.HTTP_409_CONFLICT)
                for r in editable[1:]:
                    r.delete()
                if h == 0:
                    if editable:
                        editable[0].delete()
                    continue
                blocked = check_entry_allowed(project, user)
                if blocked:
                    raise ApiError("FORBIDDEN_PERMISSION", blocked, status.HTTP_403_FORBIDDEN)
                if editable:
                    e = editable[0]
                    e.hours, e.approval_status, e.approved_by, e.approved_at = h, "draft", None, None
                    e.save(update_fields=["hours", "approval_status", "approved_by", "approved_at"])
                else:
                    TimeEntry.objects.create(tenant=user.tenant, person=user, project=project, work_date=day, hours=h,
                                             line=line, approval_status="draft")
            kinds = dict(ABSENCE_KINDS)
            for a in request.data.get("absences") or []:
                if a.get("kind") not in kinds:
                    raise ApiError("VALIDATION_ERROR", "Type d'absence inconnu.")
                day = date.fromisoformat(str(a.get("date")))
                h = hours_of(a.get("amount"))
                row = TimeAbsence.objects.select_for_update().filter(person=user, work_date=day, kind=a["kind"]).first()
                if row and row.status == "submitted":
                    raise ApiError("CONFLICT", f"L'absence du {day:%d/%m} est déjà envoyée.", status.HTTP_409_CONFLICT)
                if h == 0:
                    if row:
                        row.delete()
                    continue
                if row:
                    row.hours = h
                    row.save(update_fields=["hours"])
                else:
                    TimeAbsence.objects.create(tenant=user.tenant, person=user, work_date=day, kind=a["kind"], hours=h)
        start, end = _range(request)
        return Response(_sheet(user, start, end))


class TimeSheetSubmitView(APIView):
    """POST {from, to} : envoie en validation les brouillons de la période si chaque jour ouvré est complet."""

    def post(self, request):
        user = request.user
        _guard(user)
        start, end = _range(request)
        sheet = _sheet(user, start, end)
        if sheet["incomplete"]:
            raise ApiError("VALIDATION_ERROR", f"{len(sheet['incomplete'])} jour(s) ouvré(s) incomplet(s) : complétez présence et absences avant l'envoi.")
        auto = time_approval.approval_mode(user.tenant) == "auto"
        now = timezone.now()
        with transaction.atomic():
            qs = TimeEntry.objects.select_for_update().filter(person=user, work_date__range=(start, end), approval_status__in=("draft", "rejected"))
            n = 0
            for e in qs:
                e.approval_status = time_approval.after_internal_approval(user.tenant) if auto else "pending"
                e.approved_at = now if auto else None
                e.approval_step = 0
                e.save(update_fields=["approval_status", "approved_at", "approval_step"])  # déclenche budget et CRA
                n += 1
            a = TimeAbsence.objects.filter(person=user, work_date__range=(start, end), status="draft").update(status="submitted")
        audit.record(user, "Feuille de temps", "Période envoyée en validation", "", f"{start} → {end} : {n} saisie(s), {a} absence(s)", tenant=user.tenant)
        if not auto and n:
            _notify_validators(user, start, end)
        out = _sheet(user, start, end)
        out["sent"] = {"entries": n, "absences": a, "auto": auto}
        return Response(out)


def _notify_validators(user, start, end):
    try:
        from .timesheet_reminders import _send
        projects = Project.objects.filter(time_entries__person=user, time_entries__work_date__range=(start, end),
                                          time_entries__approval_status="pending").distinct()
        seen = set()
        for p in projects:
            for v in time_approval.base_approvers(p, time_approval.approval_mode(user.tenant)):
                if v in seen or v == user.id:
                    continue
                seen.add(v)
                from django.contrib.auth import get_user_model
                u = get_user_model().objects.filter(pk=v).first()
                if u:
                    _send(u, f"Feuille de temps à valider : {user.display_name}",
                          f"{user.display_name} a envoyé sa feuille de temps du {start:%d/%m} au {end:%d/%m/%Y} en validation.", email=False)
    except Exception:  # pragma: no cover - la notification ne doit pas bloquer l'envoi
        pass
