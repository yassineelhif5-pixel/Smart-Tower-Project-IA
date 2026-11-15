"""Historique des feuilles de temps : par personne et par mois, état actuel, en attente chez qui, lien vers le CRA.

Visibilité paramétrable par l'administrateur (ou le Pilote) pour chaque profil :
  own   : ses propres feuilles ;
  team  : ses feuilles + celles des projets qu'il pilote ou valide (chef de projet, tech lead, valideur) ;
  all   : toute l'entreprise.
"""
from collections import defaultdict
from decimal import Decimal
from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.errors import ApiError
from configuration import audit
from configuration.models import AppSetting
from .access import in_active_tenant
from .models import Project, TimeAbsence, TimeEntry
from . import time_approval

KEY = "timesheet_history"
SCOPES = ("own", "team", "all")
DEFAULTS = {"cdp": "team", "techlead": "team", "manager": "team", "direction": "all"}
STATE_LABEL = {"draft": "Brouillon", "rejected": "Refusé (à corriger)", "pending": "En validation", "client": "Chez le client",
               "approved": "Validé", "empty": "Vide"}


def scopes_of(tenant):
    row = AppSetting.objects.filter(tenant=tenant, key=KEY).first()
    v = row.value if row and isinstance(row.value, dict) else {}
    return {**DEFAULTS, **{k: s for k, s in (v.get("roles") or {}).items() if s in SCOPES}}


def scope_for(user):
    if user.is_app_admin:
        return "all"
    return scopes_of(user.tenant).get(user.role_id or "", "own")


def visible_people(user):
    """(scope, ids des personnes visibles ou None pour tous, ids des projets visibles pour l'équipe)."""
    sc = scope_for(user)
    if sc == "all":
        return sc, None, None
    if sc == "team":
        pids = set(Project.objects.filter(tenant=user.tenant).filter(Q(pm=user) | Q(tl=user)).values_list("id", flat=True))
        pids |= time_approval.decidable_project_ids(user)
        people = set(TimeEntry.objects.filter(project_id__in=pids).values_list("person_id", flat=True)) | {user.id}
        return sc, people, pids
    return sc, {user.id}, None


def _hours(unit, hpd, h):
    v = Decimal(h) / hpd if unit == "day" else Decimal(h)
    return float(v.quantize(Decimal("0.01")))


class TimesheetHistoryView(APIView):
    """GET ?person=&months=12 : feuilles par personne et par mois avec état, attente et CRA."""

    def get(self, request):
        from .timesheet_sheet import _settings
        user = request.user
        if not in_active_tenant(user) or not user.role or not user.role.internal and not user.is_app_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Historique réservé aux collaborateurs.", status.HTTP_403_FORBIDDEN)
        sc, people, team_pids = visible_people(user)
        unit, hpd = _settings(user.tenant)
        months = max(1, min(24, int(request.query_params.get("months") or 12)))
        from django.utils import timezone
        today = timezone.localdate()
        y, m = today.year, today.month - months + 1
        while m <= 0:
            y, m = y - 1, m + 12
        start = today.replace(year=y, month=m, day=1)
        qs = TimeEntry.objects.filter(tenant=user.tenant, work_date__gte=start).select_related("project", "project__client", "person", "approved_by", "project__tenant")
        if people is not None:
            qs = qs.filter(person_id__in=people)
            if sc == "team":  # les autres membres : uniquement leurs saisies sur les projets de l'équipe
                qs = qs.filter(Q(person=user) | Q(project_id__in=team_pids))
        wanted = request.query_params.get("person")
        if wanted and str(wanted).isdigit():
            qs = qs.filter(person_id=int(wanted))
        by_week = request.query_params.get("group") == "week"
        groups = defaultdict(lambda: {"entries": [], "projects": {}})
        for e in qs:
            key = (e.person_id, _week_key(e.work_date) if by_week else f"{e.work_date:%Y-%m}")
            g = groups[key]
            g["person"] = e.person
            g["entries"].append(e)
            g["projects"][e.project_id] = e.project
        abs_rows = defaultdict(lambda: Decimal("0"))
        for a in TimeAbsence.objects.filter(tenant=user.tenant, work_date__gte=start, person_id__in=[k[0] for k in groups] or [user.id]):
            abs_rows[(a.person_id, _week_key(a.work_date) if by_week else f"{a.work_date:%Y-%m}")] += a.hours
        from clientspace.models import ClientDocument
        docs = defaultdict(list)
        for d in ClientDocument.objects.filter(tenant=user.tenant, kind="cra", person_id__in=[k[0] for k in groups] or [0],
                                               period__gte=f"{start:%Y-%m}").select_related("client"):
            docs[(d.person_id, d.period)].append({"id": d.id, "name": d.name, "client": d.client.name, "version": d.version,
                                                 "days": d.days, "createdAt": d.created_at, "number": d.number,
                                                 "generatedBy": (d.meta or {}).get("generatedBy", "automatique"),
                                                 "approvers": (d.meta or {}).get("approvers", [])})
        User = get_user_model()
        mode = time_approval.approval_mode(user.tenant)
        out = []
        for (pid, period), g in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[1]["person"].display_name), reverse=True):
            counts = defaultdict(lambda: Decimal("0"))
            for e in g["entries"]:
                counts[e.approval_status] += e.hours
            state = next((s for s in ("rejected", "draft", "pending", "client", "approved") if counts.get(s)), "empty")
            waiting = []
            pend = {(e.project_id, e.approval_step): e.project for e in g["entries"] if e.approval_status == "pending"}
            if pend:
                ids = set()
                for (_, step), p in pend.items():
                    ids |= time_approval.approvers(p, mode, step=step)
                ids.discard(pid)
                waiting += [{"who": u.display_name, "role": u.role.label if u.role else "", "step": "Validation interne"}
                            for u in User.objects.filter(pk__in=ids).select_related("role")]
                if not ids:
                    waiting.append({"who": "Administrateur", "role": "", "step": "Validation interne"})
            cli_projects = {e.project_id: e.project for e in g["entries"] if e.approval_status == "client"}
            if cli_projects:
                from clientspace.billing import client_users
                seen = set()
                for p in cli_projects.values():
                    for u in client_users(user.tenant, p.client, [p]):
                        if u.pk not in seen:
                            seen.add(u.pk)
                            waiting.append({"who": u.display_name, "role": f"Client {p.client.name}", "step": "Validation client"})
            if counts.get("draft") or counts.get("rejected"):
                waiting.insert(0, {"who": g["person"].display_name, "role": "Collaborateur",
                                   "step": "Correction à faire" if counts.get("rejected") else "Envoi en validation à faire"})
            out.append({
                "person": {"id": pid, "name": g["person"].display_name}, "period": period,
                "state": state, "stateLabel": STATE_LABEL[state],
                "totals": {k: _hours(unit, hpd, v) for k, v in counts.items()},
                "total": _hours(unit, hpd, sum(counts.values(), Decimal("0"))),
                "absences": _hours(unit, hpd, abs_rows.get((pid, period), Decimal("0"))),
                "projects": [{"id": p.id, "name": p.name, "client": p.client.name} for p in g["projects"].values()],
                "waiting": waiting, "cra": docs.get((pid, period[:7] if not by_week else _week_month(period)), []),
                "periodLabel": _week_label(period) if by_week else None,
                "pipelines": _pipelines(g["entries"], user.tenant),
                "lastValidation": _last_validation(g["entries"]),
                "timeline": _timeline(g["entries"], docs.get((pid, period[:7] if not by_week else _week_month(period)), []),
                                      pid, period, by_week),
                "mine": pid == user.id,
            })
        return Response({"scope": sc, "unit": unit, "rows": out, "group": "week" if by_week else "month",
                         "people": sorted({(r["person"]["id"], r["person"]["name"]) for r in out}, key=lambda x: x[1]),
                         "canConfigure": bool(user.is_app_admin)})


class TimesheetCraView(APIView):
    """Téléchargement du CRA depuis l'historique (même règles de visibilité que l'historique)."""

    def get(self, request, doc_id):
        from clientspace.models import ClientDocument
        user = request.user
        d = get_object_or_404(ClientDocument.objects.filter(tenant=user.tenant, kind="cra"), pk=doc_id)
        sc, people, _ = visible_people(user)
        if not (people is None or d.person_id in people or d.readers.filter(pk=user.pk).exists()):
            raise ApiError("FORBIDDEN_PERMISSION", "Ce CRA n'est pas dans votre périmètre.", status.HTTP_403_FORBIDDEN)
        audit.record(user, f"Client {d.client.name}", "CRA consulté (historique des temps)", "", d.name)
        if request.query_params.get("preview"):
            from clientspace.preview import preview_response
            return preview_response(d.content, d.mime, d.name)
        resp = HttpResponse(bytes(d.content), content_type=d.mime)
        resp["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(d.name)}"
        return resp


def _settings_out(tenant):
    from accounts.models import Role
    return {"roles": scopes_of(tenant),
            "profiles": [{"code": r.code, "label": r.label} for r in
                         Role.objects.filter(internal=True).filter(Q(tenant__isnull=True) | Q(tenant=tenant)).exclude(code="superadmin").order_by("label")],
            "scopes": [{"code": "own", "label": "Ses feuilles"}, {"code": "team", "label": "Son équipe (projets pilotés ou validés)"},
                       {"code": "all", "label": "Toute l'entreprise"}]}


def _save(tenant, roles, by):
    if not isinstance(roles, dict):
        raise ApiError("VALIDATION_ERROR", "Paramètre attendu : {profil: own|team|all}.")
    clean = {str(k)[:20]: v for k, v in roles.items() if v in SCOPES}
    AppSetting.objects.update_or_create(tenant=tenant, key=KEY, defaults={"value": {"roles": clean}})
    audit.record(by, "Feuille de temps", "Visibilité de l'historique", "", str(clean), tenant=tenant)
    return _settings_out(tenant)


class HistorySettingsView(APIView):
    def get(self, request):
        if not request.user.is_app_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé à l'administrateur.", status.HTTP_403_FORBIDDEN)
        return Response(_settings_out(request.user.tenant))

    def put(self, request):
        if not request.user.is_app_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé à l'administrateur.", status.HTTP_403_FORBIDDEN)
        return Response(_save(request.user.tenant, request.data.get("roles"), request.user))


class PilotHistorySettingsView(APIView):
    def get(self, request, tenant_id):
        from tenants.models import Tenant
        if not request.user.is_platform_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé au Pilote.", status.HTTP_403_FORBIDDEN)
        return Response(_settings_out(Tenant.objects.get(pk=tenant_id)))

    def put(self, request, tenant_id):
        from tenants.models import Tenant
        if not request.user.is_platform_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé au Pilote.", status.HTTP_403_FORBIDDEN)
        return Response(_save(Tenant.objects.get(pk=tenant_id), request.data.get("roles"), request.user))



# --------------------------------------------------------------------------- semaines et circuit de validation
def _week_key(d):
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _week_bounds(key):
    from datetime import date
    y, w = key.split("-W")
    monday = date.fromisocalendar(int(y), int(w), 1)
    from datetime import timedelta
    return monday, monday + timedelta(days=6)


def _week_label(key):
    a, b = _week_bounds(key)
    return f"Semaine {int(key.split('-W')[1])} · du {a:%d/%m} au {b:%d/%m/%Y}"


def _week_month(key):
    return f"{_week_bounds(key)[0]:%Y-%m}"


def _steps(project):
    """Étapes du circuit de validation du projet : libellés lisibles (avec les noms des valideurs)."""
    from .time_workflow_view import _describe
    users = {u.id: u.display_name for u in get_user_model().objects.filter(tenant=project.tenant, is_active=True)}
    wf = time_approval.workflow_of(project)
    if wf:
        chain = _describe(project, wf, users)
        internal = chain[:-1] if wf.get("client") else chain
        return internal, bool(wf.get("client"))
    mode = time_approval.approval_mode(project.tenant)
    if mode == "auto":
        return [], time_approval.client_step(project.tenant)
    label = {"pm": f"Chef de projet ({users.get(project.pm_id, '—')})", "pm_tl": "Chef de projet ou Tech Lead",
             "role": "Responsable habilité", "admin": "Administrateurs"}.get(mode, time_approval.MODES[mode])
    return [label], time_approval.client_step(project.tenant)


def _progress(entry, n_internal, client):
    """Position de la saisie dans le circuit : 0 = envoi à faire, 1..n = valideur interne, n+1 = client, fin = validé."""
    if entry.approval_status in ("draft", "rejected"):
        return 0
    if entry.approval_status == "pending":
        return 1 + min(entry.approval_step, max(0, n_internal - 1))
    if entry.approval_status == "client":
        return 1 + n_internal
    return 1 + n_internal + (1 if client else 0)


def _pipelines(entries, tenant):
    """Par projet : étapes faites, en cours, à venir, avec le nombre de saisies à chaque étape."""
    out = []
    by_project = defaultdict(list)
    for e in entries:
        by_project[e.project_id].append(e)
    for pid, items in by_project.items():
        project = items[0].project
        internal, client = _steps(project)
        labels = ["Envoi en validation"] + [f"Validation {lbl}" for lbl in internal] + (["Validation client"] if client else [])
        final = len(labels)
        pos = [_progress(e, len(internal), client) for e in items]
        current = min(pos)
        counts = defaultdict(int)
        for x in pos:
            counts[x] += 1
        steps = []
        for i, lbl in enumerate(labels):
            state = "done" if i < current else ("current" if i == current else "todo")
            steps.append({"label": lbl, "state": state, "count": counts.get(i, 0)})
        steps.append({"label": "Validé", "state": "done" if current >= final else "todo", "count": counts.get(final, 0)})
        out.append({"project": project.name, "steps": steps, "complete": current >= final,
                    "next": labels[current] if current < final else None})
    return out


def _last_validation(entries):
    done = [e for e in entries if e.approved_at and e.approved_by_id and e.approval_status in ("pending", "client", "approved")]
    if not done:
        return None
    last = max(done, key=lambda e: e.approved_at)
    return {"by": last.approved_by.display_name if last.approved_by else "", "at": last.approved_at,
            "status": last.approval_status}



def _timeline(entries, cras, person_id, period, by_week):
    """Historique complet de la période : envois, validations (qui, quelle étape, quand), refus, génération des CRA."""
    from datetime import date
    from configuration.models import AuditEvent
    from clientspace.billing import bounds
    events = defaultdict(lambda: {"count": 0, "hours": Decimal("0")})
    for e in entries:
        for a in (e.approvals or []):
            at = str(a.get("at", ""))
            key = (at[:16], a.get("decision"), a.get("by", ""), a.get("step", ""))
            events[key]["count"] += 1
            events[key]["hours"] += e.hours
        if e.approval_status == "rejected" and e.reject_reason and not any(a.get("decision") == "rejected" for a in (e.approvals or [])):
            key = (e.approved_at.isoformat()[:16] if e.approved_at else "", "rejected", e.approved_by.display_name if e.approved_by_id else "", "")
            events[key]["count"] += 1
            events[key]["hours"] += e.hours
            events[key]["reason"] = e.reject_reason
        if e.approval_status == "rejected" and e.reject_reason:
            for key in list(events):
                if key[1] == "rejected" and key[2] == (e.approved_by.display_name if e.approved_by_id else key[2]):
                    events[key]["reason"] = e.reject_reason
    out = []
    for (at, decision, by, step), v in events.items():
        out.append({"at": at, "kind": "validation" if decision == "approved" else "refus", "by": by, "step": step,
                    "count": v["count"], "hours": v["hours"], "reason": v.get("reason", "")})
    # Envois en validation (journal)
    first, last = (_week_bounds(period) if by_week else bounds(period))
    for ev in AuditEvent.objects.filter(actor_id=person_id, event="Période envoyée en validation").order_by("-at")[:200]:
        try:
            a, b = ev.new_value.split(" : ")[0].split(" → ")
            a, b = date.fromisoformat(a.strip()), date.fromisoformat(b.strip())
        except (ValueError, IndexError):
            continue
        if a <= last and b >= first:
            out.append({"at": ev.at.isoformat()[:16], "kind": "envoi", "by": "", "step": f"du {a:%d/%m} au {b:%d/%m}",
                        "count": 0, "hours": 0, "reason": ev.new_value.split(" : ", 1)[1] if " : " in ev.new_value else ""})
    for c in cras:
        out.append({"at": c["createdAt"].isoformat()[:16] if hasattr(c["createdAt"], "isoformat") else str(c["createdAt"])[:16],
                    "kind": "cra", "by": c.get("generatedBy", ""), "step": f"CRA v{c['version']} · {c['client']}" + (f" · facture {c['number']}" if c.get("number") else ""),
                    "count": 0, "hours": 0, "reason": ("Validé par " + ", ".join(c["approvers"])) if c.get("approvers") else ""})
    return sorted(out, key=lambda x: x["at"], reverse=True)
