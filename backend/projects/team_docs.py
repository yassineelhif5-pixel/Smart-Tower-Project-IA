"""Plan de charge de l'équipe sur tous les projets, et documents obligatoires paramétrables par projet."""
import re
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.errors import ApiError
from configuration import audit
from configuration.models import AppSetting

from .access import in_active_tenant, visible_projects
from .models import Action, Document, Project, ProjectAccess


# --------------------------------------------------------------------------- charge de l'équipe (tous projets)
class TeamWorkloadView(APIView):
    """Charge de chaque membre des projets du chef de projet, cumulée sur TOUS les projets de l'entreprise (8 semaines)."""

    def get(self, request):
        from methodology.models import TeamMemberAllocation
        from planning.services import hours_per_day
        from .planning_view import WEEKS, _monday, _remaining
        user = request.user
        if not in_active_tenant(user):
            raise ApiError("FORBIDDEN_PERMISSION", "Accès réservé aux utilisateurs d'une entreprise.", status.HTTP_403_FORBIDDEN)
        weeks_n = max(4, min(16, int(request.query_params.get("weeks") or WEEKS)))
        today = timezone.localdate()
        start = _monday(today)
        weeks = [start + timedelta(weeks=i) for i in range(weeks_n)]
        mine = list(Project.objects.filter(tenant=user.tenant) if user.is_app_admin else visible_projects(user))
        mine_ids = {p.id for p in mine}
        only = [i for i in str(request.query_params.get("projects") or "").split(",") if i in mine_ids]
        scope = only or list(mine_ids)
        people_ids = set(ProjectAccess.objects.filter(project_id__in=scope, user__is_active=True, user__role__internal=True)
                         .values_list("user_id", flat=True))
        people_ids |= {p.pm_id for p in mine if p.id in scope and p.pm_id} | {p.tl_id for p in mine if p.id in scope and p.tl_id}
        users = {u.pk: u for u in get_user_model().objects.filter(pk__in=people_ids, is_active=True).select_related("role")}
        hpd = float(hours_per_day(user.tenant) or 8)
        caps = {}
        for a in TeamMemberAllocation.objects.filter(user_id__in=users, active=True):
            c = float(a.hours_per_day or hpd) * int(a.days_per_week or 5) * (a.allocation_pct or 100) / 100 - float(a.meeting_hours_per_week or 0)
            caps[a.user_id] = caps.get(a.user_id, 0) + c
        tasks = list(Action.objects.filter(tenant=user.tenant, owner_id__in=users).exclude(status="done").select_related("project"))
        names = {p.id: p.name for p in mine}
        rows = {uid: {"weeks": [dict() for _ in weeks], "open": 0, "late": 0, "projects": {}} for uid in users}
        for t in tasks:
            r = rows[t.owner_id]
            pid = t.project_id if t.project_id in mine_ids else "_other"
            r["open"] += 1
            if t.due and t.due < today:
                r["late"] += 1
            pr = r["projects"].setdefault(pid, {"open": 0, "late": 0, "hours": 0.0})
            pr["open"] += 1
            pr["late"] += 1 if t.due and t.due < today else 0
            rem = _remaining(t)
            pr["hours"] += rem
            begin = max(t.start_date or today, today)
            end = max(t.due or (begin + timedelta(days=4)), begin)
            days = [begin + timedelta(days=i) for i in range((end - begin).days + 1)]
            days = [d for d in days if d.weekday() < 5] or [begin]
            per = rem / len(days)
            for d in days:
                idx = max(0, (_monday(d) - start).days // 7)  # retard : reporté sur la semaine en cours
                if idx < len(weeks):
                    r["weeks"][idx][pid] = r["weeks"][idx].get(pid, 0) + per
        out = []
        for uid, u in users.items():
            r = rows[uid]
            cap = caps.get(uid) or hpd * 5
            wk = [{"week": w, "hours": round(sum(r["weeks"][i].values()), 1), "capacity": round(cap, 1),
                   "byProject": {k: round(v, 1) for k, v in r["weeks"][i].items()}} for i, w in enumerate(weeks)]
            peak = max((x["hours"] / cap * 100 for x in wk), default=0) if cap else 0
            out.append({"id": uid, "name": u.display_name, "role": u.role.label if u.role else "", "capacity": round(cap, 1),
                        "open": r["open"], "late": r["late"], "peak": round(peak), "weeks": wk,
                        "projects": [{"id": k, "name": names.get(k, "Autres projets (hors de votre périmètre)"), **v,
                                      "hours": round(v["hours"], 1)} for k, v in sorted(r["projects"].items(), key=lambda kv: -kv[1]["hours"])]})
        out.sort(key=lambda r: (-r["peak"], r["name"]))
        return Response({"weeks": weeks, "people": out, "hoursPerDay": hpd,
                         "projects": [{"id": p.id, "name": p.name, "code": p.code} for p in sorted(mine, key=lambda p: p.name)],
                         "scope": scope})


# --------------------------------------------------------------------------- documents obligatoires par projet
REQ_KEY = "required_docs"
PRESETS = [
    {"label": "Cahier des charges / expression de besoin", "type": "specs", "keywords": ["cahier des charges", "expression de besoin", "cdc"]},
    {"label": "Spécifications fonctionnelles (SFD)", "type": "sfd", "keywords": ["sfd", "specifications fonctionnelles", "spécifications fonctionnelles"]},
    {"label": "HLD — High Level Design", "type": "std", "keywords": ["hld", "high level design", "conception generale", "conception générale"]},
    {"label": "LLD — Low Level Design", "type": "std", "keywords": ["lld", "low level design", "conception detaillee", "conception détaillée"]},
    {"label": "Document d'architecture", "type": "std", "keywords": ["architecture", "dat"]},
    {"label": "Spécifications techniques (STD)", "type": "std", "keywords": ["std", "specifications techniques", "spécifications techniques"]},
    {"label": "Planning projet", "type": "planning", "keywords": ["planning", "gantt", "retroplanning", "rétroplanning"]},
    {"label": "Plan de test / cahier de recette", "type": "test", "keywords": ["plan de test", "cahier de recette", "strategie de test", "stratégie de test"]},
    {"label": "PV de recette", "type": "test", "keywords": ["pv", "proces verbal", "procès-verbal", "pv de recette"]},
    {"label": "Proposition commerciale", "type": "proposal", "keywords": ["proposition", "offre"]},
    {"label": "Contrat / bon de commande", "type": "contract", "keywords": ["contrat", "bon de commande"]},
    {"label": "Manuel utilisateur", "type": "delivery", "keywords": ["manuel utilisateur", "guide utilisateur"]},
    {"label": "Dossier d'exploitation", "type": "delivery", "keywords": ["dossier d'exploitation", "dex", "exploitation"]},
    {"label": "Compte rendu de lancement (kick-off)", "type": "minutes", "keywords": ["kick-off", "kickoff", "lancement"]},
]


def _norm(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"\s+", " ", s)


def required_of(project):
    row = AppSetting.objects.filter(tenant=project.tenant, key=REQ_KEY).first()
    data = row.value if row and isinstance(row.value, dict) else {}
    return row, data, data.get(project.id, [])


def check_required(project, items, docs=None):
    """Statut de chaque document obligatoire : fourni si un document du projet a le type attendu ET (si précisé) un mot-clé dans son nom."""
    docs = docs if docs is not None else list(Document.objects.filter(project=project).defer("content", "extracted_text"))
    today = timezone.localdate()
    out = []
    for it in items:
        kws = [_norm(k) for k in it.get("keywords") or [] if k]
        match = []
        for d in docs:
            name = _norm(f"{d.name} {d.description}")
            by_kw = any(k and k in name for k in kws)
            if (kws and by_kw) or (not kws and d.type == it.get("type")) or (it.get("strict") is False and d.type == it.get("type")):
                match.append({"id": d.pk, "name": d.name, "version": d.version, "uploadedAt": d.uploaded_at})
        due = parse_date(str(it.get("due") or "")) if it.get("due") else None
        out.append({**it, "ok": bool(match), "docs": match[:5],
                    "late": bool(not match and due and due < today)})
    return out


def _can_edit(user, project):
    return user.is_app_admin or project.pm_id == user.pk or project.tl_id == user.pk


class RequiredDocsView(APIView):
    """GET : documents obligatoires du projet et leur statut. PUT : paramétrage (chef de projet, tech lead, admin)."""

    def get(self, request, pk):
        from .workspace import DOC_TYPES, _project
        project = _project(request.user, pk)
        _, _, items = required_of(project)
        checked = check_required(project, items)
        return Response({"items": checked, "canEdit": _can_edit(request.user, project), "presets": PRESETS,
                         "docTypes": [{"code": c, "label": l} for c, l in DOC_TYPES],
                         "done": sum(1 for x in checked if x["ok"]), "total": len(checked)})

    def put(self, request, pk):
        from .workspace import DOC_TYPES, _project
        project = _project(request.user, pk)
        if not _can_edit(request.user, project):
            raise ApiError("FORBIDDEN_PERMISSION", "Seuls le chef de projet, le tech lead ou l'administrateur définissent les documents obligatoires.",
                           status.HTTP_403_FORBIDDEN)
        types = dict(DOC_TYPES)
        items = []
        for it in (request.data.get("items") or [])[:40]:
            label = str(it.get("label") or "").strip()[:120]
            if not label:
                continue
            due = parse_date(str(it.get("due") or "")) if it.get("due") else None
            items.append({"id": str(it.get("id") or f"R{secrets.token_hex(3).upper()}")[:12], "label": label,
                          "type": it.get("type") if it.get("type") in types else "other",
                          "keywords": [str(k).strip()[:60] for k in (it.get("keywords") or []) if str(k).strip()][:10],
                          "phase": str(it.get("phase") or "")[:60], "due": due.isoformat() if due else None,
                          "note": str(it.get("note") or "")[:300]})
        row, data, old = required_of(project)
        data[project.id] = items
        if row:
            row.value = data
            row.save(update_fields=["value", "updated_at"])
        else:
            AppSetting.objects.create(tenant=project.tenant, key=REQ_KEY, value=data)
        audit.record(request.user, f"Projet {project.code}", "Documents obligatoires paramétrés", f"{len(old)} document(s)",
                     ", ".join(i["label"] for i in items)[:500], tenant=request.user.tenant)
        return self.get(request, pk)
