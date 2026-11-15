"""Espace projet : détail d'un projet, équipe (ressources) et tâches, pour le chef de projet et son équipe.

Droits (matrice des droits + rôle sur le projet) :
- voir : le projet doit être dans le périmètre de l'utilisateur (visible_projects) ;
- gérer l'équipe : administrateur, chef de projet du projet, ou droit « Ressources › Modifier » avec accès en écriture ;
- gérer les tâches : administrateur, chef de projet / Tech Lead du projet, ou droit « Tâches › Créer / Modifier »
  avec accès en écriture au projet ;
- modifier les informations : administrateur ou chef de projet du projet (droit « Projet › Modifier »).
"""
import re
from decimal import Decimal
from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import has_perm
from config.errors import ApiError
from configuration import audit

from .access import can_edit_project, in_active_tenant, visible_actions, visible_projects
import secrets

from django.db.models import Sum
from django.http import HttpResponse
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from planning.services import hours_per_day

from .models import ACTION_STATUSES, PROJECT_TYPES, Action, Document, Project, ProjectAccess, ProjectFinance, TimeEntry

DOC_TYPES = [
    ("proposal", "Proposition commerciale"), ("contract", "Contrat / bon de commande"),
    ("specs", "Cahier des charges / expression de besoin"), ("sfd", "Spécifications fonctionnelles"),
    ("std", "Spécifications techniques / architecture"), ("planning", "Planning"),
    ("minutes", "Compte rendu de réunion"), ("test", "Cahier de recette / PV"),
    ("delivery", "Livrable / documentation"), ("invoice", "Facture"), ("other", "Autre"),
]
MAX_DOC_BYTES = 10 * 1024 * 1024

STATUS_LABELS = dict(ACTION_STATUSES)


def _person(u):
    return {"id": u.id, "name": u.display_name, "role": u.role.label if u.role else ""} if u else None


def _rights(user, project):
    is_pm = project.pm_id == user.id
    is_tl = project.tl_id == user.id
    admin = user.is_app_admin
    edit = can_edit_project(user, project)
    return {
        "isPm": is_pm,
        "isTl": is_tl,
        "canManageTeam": admin or is_pm or (has_perm(user, "resource", "update") and edit),
        "canManageTasks": admin or is_pm or is_tl or (
            (has_perm(user, "action", "create") or has_perm(user, "action", "update")) and edit),
        "canEditInfo": admin or (is_pm and has_perm(user, "project", "update")),
        # Type de projet : client du projet, administrateur ou chef de projet.
        "canEditType": admin or is_pm or bool(user.role and not user.role.internal),
        # Budget et TJM : administrateur, chef de projet, ou profil financier (« money »).
        "canSeeMoney": admin or is_pm or bool(user.role and user.role.money),
        "canManageDocs": admin or is_pm or is_tl or edit,
        # Création d'action : tout membre interne de l'équipe du projet.
        "canCreateTasks": admin or is_pm or is_tl or bool(user.role and user.role.internal
                                                          and ProjectAccess.objects.filter(project=project, user=user).exists()),
    }


def _project(user, pk):
    if not in_active_tenant(user):
        raise ApiError("FORBIDDEN_PERMISSION", "Accès réservé aux utilisateurs d'une entreprise.", status.HTTP_403_FORBIDDEN)
    qs = Project.objects.filter(tenant_id=user.tenant_id) if user.is_app_admin else visible_projects(user)
    return get_object_or_404(qs.select_related("client", "pm", "tl", "pm__role", "tl__role"), pk=pk)


def _dep_row(a, project_id=None):
    return {"id": a.id, "title": a.title, "status": a.status, "statusLabel": STATUS_LABELS.get(a.status, a.status), "due": a.due,
            "startDate": a.start_date, "project": a.project_id, "projectName": a.project.name if a.project_id != project_id else None}


def _task_row(a, deps=None, succ=None):
    row = {"id": a.id, "title": a.title, "status": a.status, "statusLabel": STATUS_LABELS.get(a.status, a.status),
           "owner": _person(a.owner), "due": a.due, "startDate": a.start_date, "prio": a.prio, "phase": a.phase,
           "est": a.est, "done": a.done, "spent": a.done, "raf": a.raf,
           "instance": {"id": a.instance_id, "name": a.instance.name} if a.instance_id else None,
           "doneAt": a.done_at, "type": a.type, "ticket": a.ticket, "extOwner": a.ext_owner, "incidentDate": a.incident_date,
           "us": {"id": a.us_id, "title": a.us.title, "sprint": a.us.sprint} if a.us_id else None,
           "extension": next((h for h in reversed(a.history or []) if isinstance(h, dict) and h.get("type") == "extension"
                              and h.get("status") == "pending"), None)}
    if deps is not None:
        preds = [_dep_row(d, a.project_id) for d in deps.get(a.id, [])]
        row["dependsOn"] = preds
        row["successors"] = [_dep_row(d, a.project_id) for d in (succ or {}).get(a.id, [])]
        row["blockedBy"] = sum(1 for d in preds if d["status"] != "done")
        start = a.start_date or a.due
        row["depConflict"] = bool(start and any(d["due"] and d["status"] != "done" and d["due"] > start for d in preds))
    return row


def _deps_maps(tasks):
    """Prédécesseurs / successeurs des actions (y compris sur d'autres projets), en 2 requêtes."""
    ids = [t.id for t in tasks]
    through = Action.depends_on.through
    deps, succ = {}, {}
    pairs = list(through.objects.filter(from_action_id__in=ids).values_list("from_action_id", "to_action_id")) + \
        list(through.objects.filter(to_action_id__in=ids).values_list("from_action_id", "to_action_id"))
    others = {a.id: a for a in Action.objects.filter(id__in={x for p in pairs for x in p}).select_related("project")}
    for f, t in set(pairs):
        if f in others and t in others:
            deps.setdefault(f, []).append(others[t])
            succ.setdefault(t, []).append(others[f])
    return deps, succ


def _project_ref(p):
    return {"id": p.id, "code": p.code, "name": p.name, "progress": p.progress, "endDate": p.end_date, "startDate": p.start_date}


def _detail(user, project):
    rights = _rights(user, project)
    team = (ProjectAccess.objects.filter(project=project).select_related("user", "user__role")
            .filter(user__is_active=True).order_by("user__first_name", "user__username"))
    tasks_qs = Action.objects.filter(project=project) if (user.is_app_admin or rights["isPm"]) else visible_actions(user).filter(project=project)
    tasks = list(tasks_qs.select_related("owner", "owner__role", "instance", "us").order_by("status", "due", "id"))
    load = dict(Action.objects.filter(project=project).exclude(status="done").values("owner_id")
                .annotate(n=Count("id")).values_list("owner_id", "n"))
    members = [{**_person(a.user), "canEdit": a.can_edit, "isPm": a.user_id == project.pm_id,
                "isTl": a.user_id == project.tl_id, "openTasks": load.get(a.user_id, 0),
                **({"dailyRate": a.daily_rate} if rights["canSeeMoney"] else {})} for a in team]
    data = {
        "id": project.id, "code": project.code, "name": project.name,
        "client": {"code": project.client_id, "name": project.client.name},
        "method": project.method, "description": project.descr, "startDate": project.start_date,
        "endDate": project.end_date, "progress": project.progress,
        "pm": _person(project.pm), "tl": _person(project.tl),
        "rights": rights, "team": members, "tasks": None,
        "statuses": [{"code": c, "label": l} for c, l in ACTION_STATUSES],
        "counts": {c: sum(1 for t in tasks if t.status == c) for c, _ in ACTION_STATUSES},
        "projectType": project.project_type, "projectTypeLabel": project.get_project_type_display(),
        "baseProject": ({"id": project.base_project_id, "name": project.base_project.name, "code": project.base_project.code}
                        if project.base_project_id else None),
        "baseVersion": project.base_version, "targetVersion": project.target_version,
        "projectTypes": [{"code": c, "label": l} for c, l in PROJECT_TYPES],
        "natures": list(project.natures or []), "natureChoices": [{"code": c, "label": l} for c, l in NATURES],
        "methodology": _methodology(project),
        "docTypes": [{"code": c, "label": l} for c, l in DOC_TYPES],
        "phases": _phase_names(project),
        "instances": [{"id": i.pk, "name": i.name, "isPilot": i.is_pilot} for i in project.instances.all()],
        "status": project.status, "statusLabel": project.get_status_display(), "closedAt": project.closed_at,
        "parent": _project_ref(project.parent) if project.parent_id else None,
        "children": [_project_ref(c) for c in project.children.all().order_by("name")],
        "dependsOn": [_project_ref(c) for c in project.depends_on.all().order_by("name")],
        "dependents": [_project_ref(c) for c in project.dependents.all().order_by("name")],
    }
    deps, succ = _deps_maps(tasks)
    data["tasks"] = [_task_row(t, deps, succ) for t in tasks]
    data["linkProjects"] = [{"id": p.id, "code": p.code, "name": p.name}
                            for p in (Project.objects.filter(tenant=project.tenant) if user.is_app_admin else visible_projects(user))
                            .exclude(pk=project.pk).order_by("name")]
    if rights["canEditType"]:
        data["otherProjects"] = [{"id": p.id, "code": p.code, "name": p.name}
                                 for p in Project.objects.filter(tenant=project.tenant).exclude(pk=project.pk).order_by("name")]
    if rights["canSeeMoney"]:
        data["budget"] = budget_of(project)
    if rights["canManageTeam"]:
        in_team = {m["id"] for m in members}
        candidates = (get_user_model().objects.filter(tenant_id=user.tenant_id, is_active=True, role__internal=True)
                      .exclude(id__in=in_team).select_related("role").order_by("first_name", "username"))
        data["candidates"] = [_person(u) for u in candidates]
    return data


class ProjectWorkspaceView(APIView):
    def get(self, request, pk):
        return Response(_detail(request.user, _project(request.user, pk)))

    def delete(self, request, pk):
        project = _project(request.user, pk)
        if not (request.user.is_app_admin or project.pm_id == request.user.pk):
            raise ApiError("FORBIDDEN_PERMISSION", "Seul le chef de projet ou un administrateur peut supprimer le projet.", status.HTTP_403_FORBIDDEN)
        if str(request.data.get("confirm") or request.query_params.get("confirm") or "").strip().upper() != project.code.upper():
            raise ApiError("VALIDATION_ERROR", f"Pour confirmer, saisissez le code du projet ({project.code}).")
        n = delete_project(request.user, project)
        return Response({"deleted": project.code, "actions": n})

    def patch(self, request, pk):
        project = _project(request.user, pk)
        rights = _rights(request.user, project)
        if any(k in request.data for k in ("projectType", "baseProject", "baseVersion", "targetVersion", "natures")):
            if not rights["canEditType"]:
                raise ApiError("FORBIDDEN_PERMISSION", "Seuls le client, le chef de projet ou un administrateur modifient le type de projet.", status.HTTP_403_FORBIDDEN)
            set_project_type(project, request.data)
            project.save()
            audit.record(request.user, f"Projet {project.code}", "Type de projet modifié", "",
                         f"{project.get_project_type_display()} {project.base_version} → {project.target_version}".strip(), tenant=request.user.tenant)
            if not any(k in request.data for k in ("startDate", "endDate", "description", "method", "budget", "name", "parent", "dependsOn", "status")):
                return Response(_detail(request.user, project))
        if "budget" in request.data:
            if not (rights["canSeeMoney"] and (rights["isPm"] or request.user.is_app_admin)):
                raise ApiError("FORBIDDEN_PERMISSION", "Seul le chef de projet ou un administrateur fixe le budget.", status.HTTP_403_FORBIDDEN)
            raw = request.data.get("budget")
            try:
                value = Decimal(str(raw)).quantize(Decimal("0.01")) if raw not in (None, "") else None
            except Exception:
                raise ApiError("VALIDATION_ERROR", "Budget invalide.")
            if value is not None and value < 0:
                raise ApiError("VALIDATION_ERROR", "Le budget doit être positif.")
            fin, _ = ProjectFinance.objects.get_or_create(project=project, defaults={"tenant": project.tenant})
            fin.approved = value
            fin.save(update_fields=["approved"])
            audit.record(request.user, f"Projet {project.code}", "Budget modifié", "", str(value or ""), tenant=request.user.tenant)
            if not any(k in request.data for k in ("startDate", "endDate", "description", "method", "name", "parent", "dependsOn", "status")):
                return Response(_detail(request.user, project))
        if not rights["canEditInfo"]:
            raise ApiError("FORBIDDEN_PERMISSION", "Seul le chef de projet ou un administrateur peut modifier le projet.", status.HTTP_403_FORBIDDEN)
        for key, field in (("startDate", "start_date"), ("endDate", "end_date")):
            if key in request.data:
                raw = request.data.get(key) or ""
                parsed = parse_date(str(raw)) if raw else None
                if raw and parsed is None:
                    raise ApiError("VALIDATION_ERROR", "Date invalide.")
                setattr(project, field, parsed)
        if project.start_date and project.end_date and project.end_date < project.start_date:
            raise ApiError("VALIDATION_ERROR", "La date de fin doit être postérieure à la date de début.")
        if "status" in request.data:
            st = request.data.get("status")
            if st not in ("active", "paused", "closed"):
                raise ApiError("VALIDATION_ERROR", "Statut de projet inconnu.")
            if st != project.status:
                old = project.get_status_display()
                project.status = st
                project.closed_at = timezone.localdate() if st == "closed" else None
                audit.record(request.user, f"Projet {project.code}", "Statut du projet modifié", old, project.get_status_display(),
                             tenant=request.user.tenant)
        if "parent" in request.data:
            pid = request.data.get("parent") or None
            if pid:
                parent = get_object_or_404(Project.objects.filter(tenant=project.tenant), pk=pid)
                node = parent
                while node is not None:  # pas de boucle programme ↔ sous-projet
                    if node.pk == project.pk:
                        raise ApiError("VALIDATION_ERROR", "Ce rattachement créerait une boucle (un projet ne peut pas être parent de son parent).")
                    node = node.parent
                project.parent = parent
            else:
                project.parent = None
        if "dependsOn" in request.data:
            ids = [i for i in (request.data.get("dependsOn") or []) if i and i != project.pk]
            targets = list(Project.objects.filter(tenant=project.tenant, pk__in=ids))
            for t in targets:  # pas de dépendance circulaire directe ou indirecte
                stack, seen = [t], set()
                while stack:
                    n = stack.pop()
                    if n.pk == project.pk:
                        raise ApiError("VALIDATION_ERROR", f"Dépendance circulaire : « {t.name} » dépend déjà (directement ou non) de ce projet.")
                    if n.pk in seen:
                        continue
                    seen.add(n.pk)
                    stack += list(n.depends_on.all())
            project.depends_on.set(targets)
        if "name" in request.data:
            name = str(request.data.get("name") or "").strip()
            if not name or len(name) > 200:
                raise ApiError("VALIDATION_ERROR", "Le nom du projet est obligatoire (200 caractères maximum).")
            project.name = name
        if "description" in request.data:
            project.descr = str(request.data.get("description") or "")
        if "method" in request.data:
            project.method = str(request.data.get("method") or "")[:20]
        project.save()
        audit.record(request.user, f"Projet {project.code}", "Informations du projet modifiées", tenant=request.user.tenant)
        return Response(_detail(request.user, project))


def delete_project(user, project):
    """Suppression définitive d'un projet et de tout son contenu (actions, accès, documents, planning…)."""
    from django.db import transaction
    from django.db.models.deletion import ProtectedError
    from .models import TimeEntry
    label = f"{project.name} ({project.code})"
    n_actions = Action.objects.filter(project=project).count()
    with transaction.atomic():
        TimeEntry.objects.filter(project=project).delete()
        Project.objects.filter(base_project=project).update(base_project=None)
        try:
            project.delete()
        except ProtectedError as exc:
            raise ApiError("VALIDATION_ERROR", "Ce projet est encore référencé par d'autres données : suppression impossible.") from exc
    audit.record(user, f"Projet {project.code}", "Projet supprimé", label, f"{n_actions} action(s) supprimée(s)", tenant=user.tenant)
    return n_actions


class ProjectTeamView(APIView):
    """Affecter (POST) ou retirer (DELETE) une ressource du projet."""

    def _check(self, request, pk):
        project = _project(request.user, pk)
        if not _rights(request.user, project)["canManageTeam"]:
            raise ApiError("FORBIDDEN_PERMISSION", "Vous ne pouvez pas modifier l'équipe de ce projet.", status.HTTP_403_FORBIDDEN)
        return project

    def post(self, request, pk):
        project = self._check(request, pk)
        user = get_object_or_404(get_user_model().objects.filter(tenant_id=request.user.tenant_id, is_active=True,
                                                                 role__internal=True), pk=request.data.get("user"))
        access, created = ProjectAccess.objects.get_or_create(tenant=project.tenant, project=project, user=user,
                                                              defaults={"can_edit": bool(request.data.get("canEdit", False)),
                                                                        "granted_by": request.user})
        if "canEdit" in request.data and access.can_edit != bool(request.data["canEdit"]):
            access.can_edit = bool(request.data["canEdit"])
            access.save(update_fields=["can_edit"])
        if "dailyRate" in request.data:
            if not _rights(request.user, project)["canSeeMoney"]:
                raise ApiError("FORBIDDEN_PERMISSION", "Vous ne pouvez pas saisir de TJM.", status.HTTP_403_FORBIDDEN)
            raw = request.data.get("dailyRate")
            try:
                rate = Decimal(str(raw)).quantize(Decimal("0.01")) if raw not in (None, "") else None
            except Exception:
                raise ApiError("VALIDATION_ERROR", "TJM invalide.")
            if rate is not None and not (0 <= rate <= 100000):
                raise ApiError("VALIDATION_ERROR", "TJM hors limites.")
            access.daily_rate = rate
            access.save(update_fields=["daily_rate"])
            audit.record(request.user, f"Projet {project.code}", "TJM modifié", "", user.display_name, tenant=request.user.tenant)
            return Response(_detail(request.user, project))
        can_edit = access.can_edit
        audit.record(request.user, f"Projet {project.code}", "Ressource affectée" if created else "Accès modifié", "",
                     f"{user.display_name} ({'écriture' if can_edit else 'lecture'})", tenant=request.user.tenant)
        return Response(_detail(request.user, project), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def delete(self, request, pk, user_id):
        project = self._check(request, pk)
        if user_id in (project.pm_id, project.tl_id):
            raise ApiError("VALIDATION_ERROR", "Le chef de projet et le Tech Lead restent dans l'équipe ; changez-les d'abord dans Paramétrage › Projets.")
        access = get_object_or_404(ProjectAccess.objects.select_related("user"), project=project, user_id=user_id)
        Action.objects.filter(project=project, owner_id=user_id).exclude(status="done").update(owner=None)
        audit.record(request.user, f"Projet {project.code}", "Ressource retirée", access.user.display_name, "", tenant=request.user.tenant)
        access.delete()
        return Response(_detail(request.user, project))


def _next_action_id(project):
    stem = re.sub(r"[^A-Z0-9]", "", project.code.upper())[:12] or "T"
    n = Action.objects.filter(project=project).count() + 1
    while Action.objects.filter(pk=f"{stem}-{n}").exists():
        n += 1
    return f"{stem}-{n}"


def set_action_deps(user, action, ids):
    """Prédécesseurs d'une action (même projet ou autre projet visible), sans dépendance circulaire."""
    ids = [i for i in ids if i and i != action.pk][:30]
    allowed = Action.objects.filter(pk__in=ids)
    if not user.is_app_admin:
        allowed = allowed.filter(project__in=visible_projects(user))
    targets = list(allowed.filter(tenant=action.tenant))
    for t in targets:
        stack, seen = [t], set()
        while stack:
            n = stack.pop()
            if n.pk == action.pk:
                raise ApiError("VALIDATION_ERROR", f"Dépendance circulaire : « {t.title} » dépend déjà (directement ou non) de cette action.")
            if n.pk in seen:
                continue
            seen.add(n.pk)
            stack += list(n.depends_on.all())
    action.depends_on.set(targets)
    audit.record(user, f"Tâche {action.id}", "Dépendances modifiées", "", ", ".join(t.id for t in targets) or "aucune", tenant=action.tenant)


class ActionSearchView(APIView):
    """Recherche d'actions (tous les projets visibles) pour créer une dépendance."""

    def get(self, request):
        q = str(request.query_params.get("q") or "").strip()
        qs = Action.objects.filter(tenant_id=request.user.tenant_id) if request.user.is_app_admin else \
            Action.objects.filter(project__in=visible_projects(request.user))
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(id__icontains=q) | Q(project__name__icontains=q))
        return Response([_dep_row(a) | {"projectName": a.project.name}
                         for a in qs.select_related("project").order_by("project__name", "due", "id")[:30]])


def _apply_task(project, action, data):
    if "title" in data:
        title = str(data.get("title") or "").strip()
        if not title or len(title) > 300:
            raise ApiError("VALIDATION_ERROR", "Le titre de la tâche est obligatoire (300 caractères maximum).")
        action.title = title
    if "status" in data:
        if data["status"] not in STATUS_LABELS:
            raise ApiError("VALIDATION_ERROR", "Statut inconnu.")
        action.status = data["status"]
        # Date de clôture : alimente « actions clôturées de la semaine » et le reporting.
        if action.status == "done" and not action.done_at:
            action.done_at = timezone.localdate()
        elif action.status != "done":
            action.done_at = None
    if "owner" in data:
        owner_id = data.get("owner")
        if owner_id:
            if not ProjectAccess.objects.filter(project=project, user_id=owner_id, user__is_active=True).exists():
                raise ApiError("VALIDATION_ERROR", "Affectez d'abord cette personne à l'équipe du projet.")
            action.owner_id = owner_id
        else:
            action.owner = None
    for key, field in (("due", "due"), ("startDate", "start_date")):
        if key in data:
            raw = data.get(key) or ""
            parsed = parse_date(str(raw)) if raw else None
            if raw and parsed is None:
                raise ApiError("VALIDATION_ERROR", "Date invalide.")
            setattr(action, field, parsed)
    if "prio" in data:
        action.prio = str(data.get("prio") or "")[:20]
    if "type" in data:
        action.type = str(data.get("type") or "")[:40]
    if "ticket" in data:
        action.ticket = str(data.get("ticket") or "").strip()[:60]
    if "extOwner" in data:
        action.ext_owner = str(data.get("extOwner") or "").strip()[:120]
    if "incidentDate" in data:
        raw = data.get("incidentDate")
        try:
            action.incident_date = timezone.datetime.strptime(raw, "%Y-%m-%d").date() if raw else None
        except (TypeError, ValueError):
            raise ApiError("VALIDATION_ERROR", "Date de l'incident ou de la demande invalide.")
    if action.type == "infra" and not (action.ext_owner or action.owner_id):
        raise ApiError("VALIDATION_ERROR", "Tâche infra : indiquez la personne ou le groupe en charge.")
    if "instance" in data:
        iid = data.get("instance")
        if iid:
            from .models import MigrationInstance
            action.instance = get_object_or_404(MigrationInstance, project=project, pk=iid)
        else:
            action.instance = None
    if "phase" in data:
        action.phase = str(data.get("phase") or "")[:60]
    for key, field in (("spent", "done"), ("raf", "raf")):
        if key in data:
            try:
                setattr(action, field, Decimal(str(max(0.0, float(data.get(key) or 0)))).quantize(Decimal("0.01")))
            except (TypeError, ValueError):
                raise ApiError("VALIDATION_ERROR", "Temps invalide.")
    if "doneAt" in data and action.status == "done":
        try:
            action.done_at = timezone.datetime.strptime(str(data["doneAt"]), "%Y-%m-%d").date() if data.get("doneAt") else timezone.localdate()
        except ValueError:
            raise ApiError("VALIDATION_ERROR", "Date de réalisation invalide.")
    if "est" in data:
        try:
            action.est = Decimal(str(max(0.0, float(data.get("est") or 0)))).quantize(Decimal("0.01"))
        except (TypeError, ValueError):
            raise ApiError("VALIDATION_ERROR", "Charge estimée invalide.")


def require_done_info(action, data):
    """Passage au statut « Terminé » : temps réellement passé (> 0) et date de réalisation obligatoires."""
    if data.get("status") != "done" or action.status == "done":
        return
    try:
        spent = float(data.get("spent") if data.get("spent") not in (None, "") else (action.done or 0))
    except (TypeError, ValueError):
        spent = 0
    if spent <= 0 or not data.get("doneAt"):
        raise ApiError("VALIDATION_ERROR", "Pour terminer l'action, saisissez le temps réellement passé et la date de réalisation.")


class ProjectTasksView(APIView):
    """Créer (POST) ou modifier (PATCH) une tâche du projet, notamment son affectation."""

    def _check(self, request, pk):
        project = _project(request.user, pk)
        if not _rights(request.user, project)["canManageTasks"]:
            raise ApiError("FORBIDDEN_PERMISSION", "Vous ne pouvez pas gérer les tâches de ce projet.", status.HTTP_403_FORBIDDEN)
        return project

    def post(self, request, pk):
        project = _project(request.user, pk)
        rights = _rights(request.user, project)
        member = ProjectAccess.objects.filter(project=project, user=request.user).exists()
        if not (rights["canManageTasks"] or (member and request.user.role and request.user.role.internal)):
            raise ApiError("FORBIDDEN_PERMISSION", "Seuls les membres de l'équipe du projet créent des actions.", status.HTTP_403_FORBIDDEN)
        action = Action(tenant=project.tenant, project=project, id=_next_action_id(project), status="todo", title="")
        _apply_task(project, action, {"title": "", **request.data})
        action.save()
        if request.data.get("dependsOn"):
            set_action_deps(request.user, action, request.data.get("dependsOn") or [])
        audit.record(request.user, f"Tâche {action.id}", "Tâche créée", "", action.title, tenant=request.user.tenant)
        return Response(_detail(request.user, project), status=status.HTTP_201_CREATED)

    def patch(self, request, pk, task_id):
        project = self._check(request, pk)
        action = get_object_or_404(Action.objects.select_related("owner"), project=project, pk=task_id)
        before = (action.owner.display_name if action.owner else "—", STATUS_LABELS.get(action.status, action.status))
        require_done_info(action, request.data)
        _apply_task(project, action, request.data)
        action.save()
        if "dependsOn" in request.data:
            set_action_deps(request.user, action, request.data.get("dependsOn") or [])
        after = (action.owner.display_name if action.owner else "—", STATUS_LABELS.get(action.status, action.status))
        if before != after:
            audit.record(request.user, f"Tâche {action.id}", "Tâche modifiée", " · ".join(before), " · ".join(after),
                         tenant=request.user.tenant)
        return Response(_detail(request.user, project))

    def delete(self, request, pk, task_id):
        project = self._check(request, pk)
        action = get_object_or_404(Action, project=project, pk=task_id)
        title = action.title
        from .models import TimeEntry
        logged = TimeEntry.objects.filter(action=action).count()
        action.delete()  # les temps saisis sont conservés sur le projet (action vidée)
        audit.record(request.user, f"Tâche {task_id}", "Tâche supprimée", title, f"{logged} saisie(s) de temps conservée(s)" if logged else "",
                     tenant=request.user.tenant)
        return Response(_detail(request.user, project))



def _methodology(project):
    try:
        from methodology.services import methodology
        m = methodology(project)
        return {"kind": m.kind, "label": m.get_kind_display(), "features": m.enabled()}
    except Exception:  # pragma: no cover - méthodologie indisponible
        return {"kind": "", "label": project.method, "features": []}


NATURES = [("build", "Build"), ("run", "Run"), ("support", "Support"), ("migration", "Migration"), ("other", "Autre")]


def set_project_type(project, data):
    if "natures" in data:
        vals = data.get("natures") or []
        if not isinstance(vals, list) or any(v not in dict(NATURES) for v in vals):
            raise ApiError("VALIDATION_ERROR", "Nature de projet inconnue.")
        project.natures = [c for c, _ in NATURES if c in vals]
    if "projectType" in data:
        if data["projectType"] not in dict(PROJECT_TYPES):
            raise ApiError("VALIDATION_ERROR", "Type de projet inconnu.")
        project.project_type = data["projectType"]
    if "baseProject" in data:
        bid = data.get("baseProject")
        project.base_project = (get_object_or_404(Project.objects.filter(tenant=project.tenant).exclude(pk=project.pk), pk=bid)
                                if bid else None)
    if "baseVersion" in data:
        project.base_version = str(data.get("baseVersion") or "").strip()[:40]
    if "targetVersion" in data:
        project.target_version = str(data.get("targetVersion") or "").strip()[:40]
    if project.project_type == "new":
        project.base_project, project.base_version = None, ""


def budget_of(project):
    """Consommation du budget = temps passé × TJM du membre. Validé = consommé ; à valider = engagé."""
    hpd = hours_per_day(project.tenant) or Decimal("8")
    rates = dict(ProjectAccess.objects.filter(project=project).values_list("user_id", "daily_rate"))
    per = {}
    for person_id, status_, hours in (TimeEntry.objects.filter(project=project).exclude(approval_status__in=("rejected", "draft"))
                                      .values_list("person_id", "approval_status").annotate(h=Sum("hours"))):
        row = per.setdefault(person_id, {"approved": Decimal("0"), "pending": Decimal("0")})
        row["approved" if status_ == "approved" else "pending"] += hours or Decimal("0")
    users = {u.id: u.display_name for u in get_user_model().objects.filter(id__in=per.keys())}
    consumed = pending = Decimal("0")
    rows, missing = [], []
    for uid, h in per.items():
        rate = rates.get(uid)
        if rate is None:
            missing.append(users.get(uid, str(uid)))
        cost = (h["approved"] / hpd * rate) if rate is not None else Decimal("0")
        engaged = (h["pending"] / hpd * rate) if rate is not None else Decimal("0")
        consumed += cost
        pending += engaged
        rows.append({"user": users.get(uid, str(uid)), "dailyRate": rate, "hoursApproved": h["approved"],
                     "hoursPending": h["pending"], "daysApproved": (h["approved"] / hpd).quantize(Decimal("0.01")),
                     "cost": cost.quantize(Decimal("0.01")), "engaged": engaged.quantize(Decimal("0.01"))})
    fin = ProjectFinance.objects.filter(project=project).first()
    budget = fin.approved if fin else None
    return {
        "budget": budget, "consumed": consumed.quantize(Decimal("0.01")), "pending": pending.quantize(Decimal("0.01")),
        "remaining": (budget - consumed - pending).quantize(Decimal("0.01")) if budget is not None else None,
        "rate": round(float((consumed + pending) / budget * 100), 1) if budget else None,
        "hoursPerDay": hpd, "rows": sorted(rows, key=lambda r: -r["cost"]), "missingRates": missing,
    }


def _doc_row(d):
    return {"id": d.pk, "name": d.name, "ext": d.ext, "type": d.type, "typeLabel": dict(DOC_TYPES).get(d.type, d.type or "Autre"),
            "description": d.description, "size": d.size_bytes, "mime": d.mime, "version": d.version,
            "uploadedBy": d.uploaded_by.display_name if d.uploaded_by_id else None, "uploadedAt": d.uploaded_at,
            "clientVisible": d.client_visible, "hasFile": d.size_bytes is not None,
            "extraction": {**(d.extraction or {}), "suggestedTypeLabel": dict(DOC_TYPES).get((d.extraction or {}).get("suggestedType"), "")}}


class ProjectDocumentsView(APIView):
    """Documents du projet, classés par type. Les clients ne voient que les documents marqués « visibles client »."""

    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _docs(self, user, project):
        qs = Document.objects.filter(project=project).select_related("uploaded_by").defer("content", "extracted_text")
        if not (user.role and user.role.internal):
            qs = qs.filter(client_visible=True)
        return qs.order_by("type", "-uploaded_at", "name")

    def get(self, request, pk):
        project = _project(request.user, pk)
        docs = self._docs(request.user, project)
        q = str(request.query_params.get("q") or "").strip()
        if q:
            docs = docs.filter(Q(name__icontains=q) | Q(extracted_text__icontains=q) | Q(description__icontains=q))
        return Response({"types": [{"code": c, "label": l} for c, l in DOC_TYPES],
                         "canManage": _rights(request.user, project)["canManageDocs"],
                         "canUploadMinutes": True,
                         "internal": bool(request.user.role and request.user.role.internal),
                         "documents": [_doc_row(d) for d in docs]})

    def post(self, request, pk):
        project = _project(request.user, pk)
        doc_type = request.data.get("type") or "auto"
        # Tous les profils du projet peuvent déposer un compte rendu de réunion ou une pièce jointe de discussion ;
        # les autres documents restent réservés aux profils qui gèrent les documents.
        free = doc_type == "minutes" or str(request.data.get("attachment", "")).lower() in ("1", "true")
        if not free and not _rights(request.user, project)["canManageDocs"]:
            raise ApiError("FORBIDDEN_PERMISSION", "Vous ne pouvez pas déposer de document sur ce projet.", status.HTTP_403_FORBIDDEN)
        d = store_document(request, project, request.FILES.get("file"), doc_type)
        from .project_alerts import notify_new_document
        notified, mailed = notify_new_document(project, request.user, d, dict(DOC_TYPES)[d.type], request)
        return Response({**_doc_row(d), "notified": notified, "mailed": mailed}, status=status.HTTP_201_CREATED)


def store_document(request, project, f, doc_type="auto"):
    """Enregistre un fichier déposé (lecture du texte, OCR navigateur, classification, versions)."""
    if f is None:
        raise ApiError("VALIDATION_ERROR", "Choisissez un fichier.")
    if f.size > MAX_DOC_BYTES:
        raise ApiError("VALIDATION_ERROR", "Fichier trop volumineux (10 Mo maximum).")
    if doc_type != "auto" and doc_type not in dict(DOC_TYPES):
        raise ApiError("VALIDATION_ERROR", "Type de document inconnu.")
    name = (str(request.data.get("title") or "").strip() or f.name)[:255]
    ext = f.name.rsplit(".", 1)[-1].lower()[:10] if "." in f.name else ""
    content = f.read()
    from .doc_intel import analyse
    text, extraction = analyse(content, ext, f.content_type or "", f"{name} {f.name}", project.tenant,
                               str(request.data.get("ocrText") or ""))
    if doc_type == "auto":
        doc_type = extraction.get("suggestedType") or "other"
        extraction["autoClassified"] = True
    internal = bool(request.user.role and request.user.role.internal)
    same = Document.objects.filter(project=project, name=name, type=doc_type).order_by("-version").first()
    d = Document.objects.create(
        tenant=project.tenant, project=project, id=f"D{secrets.token_hex(6).upper()}", name=name, ext=ext,
        type=doc_type, description=str(request.data.get("description") or "")[:5000], uploaded_by=request.user,
        uploaded_at=timezone.localdate(), version=(same.version + 1) if same else 1, dstat="Déposé",
        # Un document déposé par le client reste visible du client.
        client_visible=(not internal) or str(request.data.get("clientVisible", "")).lower() in ("1", "true", "on"),
        content=content, mime=(f.content_type or "application/octet-stream")[:100], size_bytes=f.size,
        size_mb=Decimal(f.size) / Decimal(1024 * 1024), extracted_text=text, extraction=extraction)
    audit.record(request.user, f"Projet {project.code}", "Document déposé", "", f"{d.name} ({dict(DOC_TYPES)[doc_type]})",
                 tenant=request.user.tenant)
    return d


INLINE_MIMES = {"application/pdf", "text/plain", "text/csv", "text/markdown"}


class ProjectDocumentDetailView(APIView):
    def _get(self, request, pk, doc_id):
        project = _project(request.user, pk)
        d = get_object_or_404(Document.objects.select_related("uploaded_by"), project=project, pk=doc_id)
        if not (request.user.role and request.user.role.internal) and not d.client_visible:
            raise ApiError("NOT_FOUND", "Document introuvable.", status.HTTP_404_NOT_FOUND)
        return project, d

    def get(self, request, pk, doc_id):
        _, d = self._get(request, pk, doc_id)
        if request.query_params.get("text"):
            # Consultation : texte extrait (Word, Excel, PowerPoint… que le navigateur ne sait pas afficher).
            return Response({"id": d.id, "name": d.name, "ext": d.ext, "mime": d.mime, "text": d.extracted_text or "",
                             "extraction": d.extraction or {}, "description": d.description})
        if d.content is None:
            raise ApiError("NOT_FOUND", "Ce document n'a pas de fichier.", status.HTTP_404_NOT_FOUND)
        filename = d.name if d.name.lower().endswith(f".{d.ext}") or not d.ext else f"{d.name}.{d.ext}"
        mime = d.mime or "application/octet-stream"
        inline = bool(request.query_params.get("inline")) and (mime in INLINE_MIMES or mime.startswith("image/") and mime != "image/svg+xml")
        if inline and mime.startswith("text/"):
            mime = "text/plain; charset=utf-8"
        resp = HttpResponse(bytes(d.content), content_type=mime)
        resp["Content-Disposition"] = f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{quote(filename)}"
        resp["X-Content-Type-Options"] = "nosniff"
        if inline:
            # Affichage dans la fenêtre « Consulter » de l'application (même origine) ; aucun script exécuté.
            resp["X-Frame-Options"] = "SAMEORIGIN"
            resp["Cache-Control"] = "private, max-age=300"
        return resp

    def patch(self, request, pk, doc_id):
        project, d = self._get(request, pk, doc_id)
        if not _rights(request.user, project)["canManageDocs"]:
            raise ApiError("FORBIDDEN_PERMISSION", "Vous ne pouvez pas modifier ce document.", status.HTTP_403_FORBIDDEN)
        if "type" in request.data:
            if request.data["type"] not in dict(DOC_TYPES):
                raise ApiError("VALIDATION_ERROR", "Type de document inconnu.")
            d.type = request.data["type"]
        if "clientVisible" in request.data:
            d.client_visible = bool(request.data["clientVisible"])
        if "description" in request.data:
            d.description = str(request.data.get("description") or "")[:5000]
        d.save(update_fields=["type", "client_visible", "description"])
        return Response(_doc_row(d))

    def delete(self, request, pk, doc_id):
        project, d = self._get(request, pk, doc_id)
        if not _rights(request.user, project)["canManageDocs"]:
            raise ApiError("FORBIDDEN_PERMISSION", "Vous ne pouvez pas supprimer ce document.", status.HTTP_403_FORBIDDEN)
        audit.record(request.user, f"Projet {project.code}", "Document supprimé", d.name, "", tenant=request.user.tenant)
        d.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _planned_pct(start, end, today):
    if not start or not end:
        return None
    if today <= start:
        return 0
    if today >= end:
        return 100
    return round((today - start).days / max(1, (end - start).days) * 100)


class ProjectReportView(APIView):
    """Reporting d'avancement : Gantt planifié / réel des phases, tâches, temps passés, jalons et budget."""

    def get(self, request, pk):
        project = _project(request.user, pk)
        rights = _rights(request.user, project)
        today = timezone.localdate()
        from methodology.models import VPhase
        from planning.models import CalendarEvent
        phases = []
        weight_total = planned_sum = real_sum = 0
        all_phases = list(VPhase.objects.filter(project=project).select_related("owner").order_by("order", "id"))
        live = live_phases(project, all_phases, today)
        status_labels = dict(VPhase._meta.get_field("status").choices)
        for ph in all_phases:
            ph.progress, ph.status = live[ph.pk]["progress"], live[ph.pk]["status"]
            planned = _planned_pct(ph.start, ph.end, today)
            real_end = ph.forecast_end or ph.end
            weight = max(1, (ph.end - ph.start).days) if ph.start and ph.end else 0
            if weight and ph.status != "skipped":
                weight_total += weight
                planned_sum += weight * (planned or 0)
                real_sum += weight * ph.progress
            phases.append({"id": ph.pk, "name": ph.name, "start": ph.start, "end": ph.end, "forecastEnd": ph.forecast_end,
                           "realEnd": real_end, "status": ph.status, "statusLabel": status_labels.get(ph.status, ph.status),
                           "tasks": live[ph.pk]["tasks"], "tasksDone": live[ph.pk]["done"], "live": live[ph.pk]["live"],
                           "progress": ph.progress, "plannedProgress": planned,
                           "gap": (ph.progress - planned) if planned is not None else None,
                           "owner": ph.owner.display_name if ph.owner_id else None,
                           "slipDays": (ph.forecast_end - ph.end).days if ph.forecast_end and ph.end else 0})
        tasks = list(Action.objects.filter(project=project).select_related("owner"))
        done = sum(1 for t in tasks if t.status == "done")
        late = [t for t in tasks if t.due and t.due < today and t.status != "done"]
        task_pct = round(done / len(tasks) * 100) if tasks else None
        hours = TimeEntry.objects.filter(project=project).exclude(approval_status__in=("rejected", "draft")).aggregate(h=Sum("hours"))["h"] or 0
        milestones = [{"title": e.title, "date": e.start.date(), "status": e.status}
                      for e in CalendarEvent.objects.filter(project=project, kind="milestone").order_by("start")]
        real_pct = round(real_sum / weight_total) if weight_total else task_pct
        planned_pct = round(planned_sum / weight_total) if weight_total else _planned_pct(project.start_date, project.end_date, today)
        data = {
            "generatedAt": timezone.now(), "today": today,
            "project": {"id": project.id, "code": project.code, "name": project.name, "client": project.client.name,
                        "pm": project.pm.display_name if project.pm_id else None, "start": project.start_date,
                        "end": project.end_date, "typeLabel": project.get_project_type_display(),
                        "baseVersion": project.base_version, "targetVersion": project.target_version,
                        "methodology": _methodology(project)},
            "progress": {"planned": planned_pct, "real": real_pct,
                         "gap": (real_pct - planned_pct) if real_pct is not None and planned_pct is not None else None},
            "phases": phases, "milestones": milestones,
            "tasks": {"total": len(tasks), "done": done, "rate": task_pct, "late": len(late),
                      "byStatus": {c: sum(1 for t in tasks if t.status == c) for c, _ in ACTION_STATUSES},
                      "statusLabels": dict(ACTION_STATUSES),
                      "lateList": [{"id": t.id, "title": t.title, "due": t.due, "owner": t.owner.display_name if t.owner_id else None}
                                   for t in sorted(late, key=lambda t: t.due)[:10]]},
            "hours": hours,
        }
        data["evolution"] = _evolution(project, all_phases, tasks, today)
        if rights["canSeeMoney"]:
            data["budget"] = budget_of(project)
        return Response(data)



class DocKeywordsView(APIView):
    """Mots-clés de classification par type de document (administrateur de l'entreprise)."""

    def get(self, request):
        if not request.user.is_app_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé aux administrateurs.", status.HTTP_403_FORBIDDEN)
        from .doc_intel import keywords_for
        kw = keywords_for(request.user.tenant)
        return Response({"types": [{"code": c, "label": l, "keywords": kw.get(c, [])} for c, l in DOC_TYPES if c != "other"]})

    def put(self, request):
        if not request.user.is_app_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé aux administrateurs.", status.HTTP_403_FORBIDDEN)
        from configuration.models import AppSetting
        data = request.data.get("keywords") or {}
        clean = {}
        for code, words in data.items():
            if code in dict(DOC_TYPES) and isinstance(words, list):
                clean[code] = [str(w).strip()[:60] for w in words if str(w).strip()][:60]
        AppSetting.objects.update_or_create(tenant=request.user.tenant, key="doc_keywords", defaults={"value": clean})
        audit.record(request.user, "Documents", "Mots-clés de classification modifiés", tenant=request.user.tenant)
        return self.get(request)



def live_phases(project, phases=None, today=None):
    """État actuel des phases d'après les tâches rattachées (Action.phase = nom de la phase).

    Avancement = charge terminée / charge totale (1 par tâche sans charge). Statut : « Sans objet » est conservé ;
    toutes les tâches terminées → Terminé ; fin dépassée → En retard ; une tâche démarrée → En cours.
    Sans tâche rattachée, la saisie manuelle de la phase est conservée.
    """
    from methodology.models import VPhase
    today = today or timezone.localdate()
    phases = list(phases if phases is not None else VPhase.objects.filter(project=project).select_related("owner"))
    tasks = list(Action.objects.filter(project=project).exclude(phase="").values("phase", "status", "est"))
    out = {}
    for ph in phases:
        mine = [t for t in tasks if t["phase"].strip().lower() == ph.name.strip().lower()]
        if not mine or ph.status == "skipped":
            out[ph.pk] = {"progress": ph.progress, "status": ph.status, "tasks": len(mine), "done": 0, "live": False}
            continue
        weight = lambda t: float(t["est"] or 0) or 1.0  # noqa: E731
        total = sum(weight(t) for t in mine)
        done_w = sum(weight(t) for t in mine if t["status"] == "done")
        done = sum(1 for t in mine if t["status"] == "done")
        progress = round(done_w / total * 100) if total else 0
        end = ph.forecast_end or ph.end
        if done == len(mine):
            status_ = "done"
        elif end and end < today:
            status_ = "late"
        elif any(t["status"] in ("doing", "review", "blocked", "done") for t in mine):
            status_ = "doing"
        else:
            status_ = "todo"
        out[ph.pk] = {"progress": progress, "status": status_, "tasks": len(mine), "done": done, "live": True,
                      "blocked": sum(1 for t in mine if t["status"] == "blocked")}
    return out



def _phase_names(project):
    from methodology.models import VPhase
    return list(VPhase.objects.filter(project=project).order_by("order", "id").values_list("name", flat=True))



def _evolution(project, phases, tasks, today):
    """Courbes hebdomadaires : avancement prévu (dates des phases, sinon du projet) et réel (tâches clôturées)."""
    from datetime import timedelta
    starts = [d for d in [project.start_date, *[p.start for p in phases]] if d]
    ends = [d for d in [project.end_date, *[(p.forecast_end or p.end) for p in phases]] if d]
    dues = [t.due for t in tasks if t.due] + [t.done_at for t in tasks if t.done_at]
    if not starts and not dues:
        return []
    first = min(starts or dues)
    last = max(ends + dues + [today]) if (ends or dues) else today
    first = first - timedelta(days=first.weekday())
    weeks = []
    d = first
    while d <= last + timedelta(days=6) and len(weeks) < 80:
        weeks.append(d)
        d += timedelta(days=7)
    weighted = [(p, max(1, (p.end - p.start).days)) for p in phases if p.start and p.end and p.status != "skipped"]
    total_w = sum(w for _, w in weighted)
    weight = lambda t: float(t.est or 0) or 1.0  # noqa: E731
    total_t = sum(weight(t) for t in tasks)
    points = []
    for w in weeks:
        end_w = w + timedelta(days=6)
        if total_w:
            planned = sum(wt * (_planned_pct(p.start, p.end, end_w) or 0) for p, wt in weighted) / total_w
        else:
            planned = _planned_pct(project.start_date, project.end_date, end_w)
        real = None
        if w <= today:
            ref = min(end_w, today)
            real = (sum(weight(t) for t in tasks if t.status == "done" and (t.done_at or t.due or today) <= ref) / total_t * 100) if total_t else None
        points.append({"week": w, "planned": round(planned) if planned is not None else None,
                       "real": round(real) if real is not None else None})
    return points


class PortfolioReportView(APIView):
    """Reporting multi-projets : planning macro, actions en retard / en cours et phases clés de plusieurs projets."""

    def get(self, request):
        ids = [i for i in str(request.query_params.get("ids") or "").split(",") if i][:12]
        if not ids:
            raise ApiError("VALIDATION_ERROR", "Sélectionnez au moins un projet.")
        today = timezone.localdate()
        out = []
        for pk in ids:
            try:
                project = _project(request.user, pk)
            except Exception:  # projet inaccessible : ignoré
                continue
            data = ProjectReportView().get(request, pk).data
            tasks = list(Action.objects.filter(project=project).select_related("owner"))
            starts = [t.start_date for t in tasks if t.start_date] + [t.due for t in tasks if t.due]
            doing = sorted([t for t in tasks if t.status in ("doing", "review")], key=lambda t: (t.due or today.replace(year=today.year + 5)))
            late = sorted([t for t in tasks if t.due and t.due < today and t.status != "done"], key=lambda t: t.due)
            row = lambda t: {"id": t.id, "title": t.title, "due": t.due, "start": t.start_date, "status": t.status,  # noqa: E731
                             "owner": t.owner.display_name if t.owner_id else None, "phase": t.phase,
                             "lateDays": (today - t.due).days if t.due and t.due < today else 0}
            # Sans planning macro : lots déduits des actions (colonne Phase / lot), sinon un lot unique.
            lots = []
            if not data["phases"] and tasks:
                groups = {}
                for t in tasks:
                    groups.setdefault((t.phase or "").strip() or "Actions du projet", []).append(t)
                for name, items in sorted(groups.items(), key=lambda kv: min([x.start_date or x.due or today for x in kv[1]])):
                    ds = [x.start_date for x in items if x.start_date] + [x.due for x in items if x.due]
                    end = max([x.due for x in items if x.due], default=None)
                    n_done = sum(1 for x in items if x.status == "done")
                    n_late = sum(1 for x in items if x.due and x.due < today and x.status != "done")
                    st = ("done" if n_done == len(items) else "late" if (n_late or (end and end < today)) else
                          "doing" if any(x.status in ("doing", "review", "done", "blocked") for x in items) else "todo")
                    lots.append({"id": f"lot-{len(lots)}", "name": f"{name} ({len(items)})", "start": min(ds) if ds else None, "end": end or (max(ds) if ds else None),
                                 "realEnd": None, "status": st, "statusLabel": {"done": "Terminé", "late": "En retard", "doing": "En cours", "todo": "À venir"}[st],
                                 "progress": round(n_done / len(items) * 100), "plannedProgress": None, "owner": None, "slipDays": 0,
                                 "lot": True, "late": n_late})
                lots = lots[:15]
            out.append({
                "project": data["project"], "progress": data["progress"], "phases": data["phases"], "lots": lots, "milestones": data["milestones"], "evolution": data.get("evolution", []),
                "tasks": {k: v for k, v in data["tasks"].items() if k != "lateList"},
                "late": [row(t) for t in late[:20]], "lateCount": len(late),
                "doing": [row(t) for t in doing[:20]], "doingCount": len(doing),
                "span": {"start": project.start_date or (min(starts) if starts else None),
                         "end": project.end_date or (max(starts) if starts else None)},
            })
        return Response({"today": today, "generatedAt": timezone.now(), "projects": out})


class ActionCommentsView(APIView):
    """Commentaires d'une action (fil), avec mention @ de membres de l'équipe → notification (et e-mail)."""

    def _get(self, request, pk, task_id):
        project = _project(request.user, pk)
        action = get_object_or_404(Action.objects.select_related("owner"), project=project, pk=task_id)
        return project, action

    @staticmethod
    def _row(c):
        return {"id": c.pk, "author": c.author.display_name if c.author_id else "Système", "authorId": c.author_id,
                "at": c.at, "body": c.body, "internal": c.internal}

    def get(self, request, pk, task_id):
        project, action = self._get(request, pk, task_id)
        from .models import ActionComment
        qs = ActionComment.objects.filter(action=action).select_related("author").order_by("-id")
        if not (request.user.role and request.user.role.internal):
            qs = qs.filter(internal=False)
        hist = [{"at": h.get("at") or h.get("date"), "text": h.get("text") or h.get("event") or str(h)} for h in (action.history or [])][-20:]
        return Response({"comments": [self._row(c) for c in qs[:100]], "history": hist})

    def post(self, request, pk, task_id):
        project, action = self._get(request, pk, task_id)
        from configuration.models import Notification
        from .models import ActionComment
        body = str(request.data.get("body") or "").strip()[:5000]
        if not body:
            raise ApiError("VALIDATION_ERROR", "Le commentaire est vide.")
        internal = bool(request.data.get("internal")) and bool(request.user.role and request.user.role.internal)
        c = ActionComment.objects.create(tenant=project.tenant, action=action, author=request.user, body=body, internal=internal,
                                         at=timezone.now().strftime("%Y-%m-%d %H:%M"))
        members = {a.user_id: a.user for a in ProjectAccess.objects.filter(project=project, user__is_active=True).select_related("user")}
        mentioned = [members[int(u)] for u in (request.data.get("mentions") or []) if str(u).isdigit() and int(u) in members]
        notified = []
        for u in {u.pk: u for u in mentioned}.values():
            if u.pk == request.user.pk:
                continue
            Notification.objects.create(user=u, event="project_alert",
                                        title=f"[{project.code}] 💬 {request.user.display_name} vous mentionne : {action.title}"[:200],
                                        body=f"{body[:400]} · {project.id}")
            notified.append(u.display_name)
        # Le responsable de l'action est informé des nouveaux commentaires.
        if action.owner_id and action.owner_id != request.user.pk and action.owner_id not in {u.pk for u in mentioned}:
            Notification.objects.create(user=action.owner, event="project_alert",
                                        title=f"[{project.code}] 💬 Nouveau commentaire sur « {action.title} »"[:200],
                                        body=f"{request.user.display_name} : {body[:400]} · {project.id}")
        audit.record(request.user, f"Tâche {action.id}", "Commentaire ajouté", "", body[:200], tenant=request.user.tenant)
        return Response({**self._row(c), "notified": notified}, status=status.HTTP_201_CREATED)



class MyTaskView(APIView):
    """Actions du collaborateur sur une tâche du projet (sans droit de gestion des tâches) :
    POST {op: claim | status | extend | extension_decision, ...}
    - claim : s'affecter une action non affectée ;
    - status {status, doneAt?} : changer le statut de SON action (date de réalisation si « Terminé ») ;
    - extend {due, reason} : demander un délai supplémentaire au chef de projet ;
    - extension_decision {decision: approved|rejected, comment} : réponse du chef de projet (gestion des tâches)."""

    def post(self, request, pk, task_id):
        from configuration.models import Notification
        from .models import ActionComment
        user = request.user
        project = _project(user, pk)
        rights = _rights(user, project)
        action = get_object_or_404(Action.objects.select_related("owner"), project=project, pk=task_id)
        member = rights["canManageTasks"] or ProjectAccess.objects.filter(project=project, user=user).exists()
        if not (member and user.role and user.role.internal):
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé aux membres de l'équipe du projet.", status.HTTP_403_FORBIDDEN)
        op = request.data.get("op")
        now = timezone.now()
        hist = list(action.history or [])

        def note(text):
            ActionComment.objects.create(tenant=project.tenant, action=action, author=user, body=text, internal=True,
                                         at=now.strftime("%Y-%m-%d %H:%M"))

        def tell(u, title, body):
            if u and u.pk != user.pk:
                Notification.objects.create(user=u, event="project_alert", title=f"[{project.code}] {title}"[:200], body=f"{body[:400]} · {project.id}")

        if op == "claim":
            if action.status == "done":
                raise ApiError("CONFLICT", "Cette action est déjà terminée.", status.HTTP_409_CONFLICT)
            previous = action.owner if action.owner_id and action.owner_id != user.pk else None
            action.owner = user
            hist.append({"at": now.isoformat(), "text": f"{user.display_name} s'est affecté l'action"
                         + (f" (auparavant : {previous.display_name})" if previous else "")})
            action.history = hist
            action.save(update_fields=["owner", "history"])
            tell(project.pm, f"🙋 {user.display_name} prend l'action « {action.title} »",
                 "Affectation par le collaborateur" + (f" (auparavant {previous.display_name})." if previous else "."))
            if previous and previous.pk != project.pm_id:
                tell(previous, f"🙋 {user.display_name} a repris votre action « {action.title} »", "Vous n'êtes plus responsable de cette action.")
            audit.record(user, f"Tâche {action.id}", "S'est affecté l'action", "—", user.display_name, tenant=project.tenant)
        elif op == "status":
            if action.owner_id != user.pk and not rights["canManageTasks"]:
                raise ApiError("FORBIDDEN_PERMISSION", "Vous ne pouvez changer le statut que de vos actions.", status.HTTP_403_FORBIDDEN)
            new = request.data.get("status")
            if new not in dict(ACTION_STATUSES):
                raise ApiError("VALIDATION_ERROR", "Statut inconnu.")
            require_done_info(action, request.data)
            if new == "done" and request.data.get("spent") not in (None, ""):
                action.done = Decimal(str(max(0.0, float(request.data["spent"])))).quantize(Decimal("0.01"))
            before = STATUS_LABELS.get(action.status, action.status)
            action.status = new
            if new == "done":
                raw = request.data.get("doneAt")
                try:
                    action.done_at = timezone.datetime.strptime(raw, "%Y-%m-%d").date() if raw else timezone.localdate()
                except ValueError:
                    raise ApiError("VALIDATION_ERROR", "Date de réalisation invalide.")
                if action.done_at > timezone.localdate():
                    raise ApiError("VALIDATION_ERROR", "La date de réalisation ne peut pas être dans le futur.")
            else:
                action.done_at = None
            hist.append({"at": now.isoformat(), "text": f"Statut : {before} → {STATUS_LABELS.get(new, new)}"
                         + (f" (réalisée le {action.done_at:%d/%m/%Y})" if action.done_at else "")})
            action.history = hist
            action.save(update_fields=["status", "done_at", "history", "done"])
            if new == "done":
                tell(project.pm, f"✅ Action terminée : {action.title}", f"{user.display_name} l'a terminée le {action.done_at:%d/%m/%Y}.")
            audit.record(user, f"Tâche {action.id}", "Statut modifié", before, STATUS_LABELS.get(new, new), tenant=project.tenant)
        elif op == "edit":
            if action.owner_id != user.pk and not rights["canManageTasks"]:
                raise ApiError("FORBIDDEN_PERMISSION", "Seul le responsable de l'action (ou le chef de projet) la modifie.", status.HTTP_403_FORBIDDEN)
            allowed = {k: request.data[k] for k in ("startDate", "est", "spent", "raf", "status", "doneAt") if k in request.data}
            require_done_info(action, allowed)
            before = f"{action.start_date or '—'} · {action.est}h · {action.done}h passées · {STATUS_LABELS.get(action.status, action.status)}"
            _apply_task(project, action, allowed)
            if action.done_at and action.done_at > timezone.localdate():
                raise ApiError("VALIDATION_ERROR", "La date de réalisation ne peut pas être dans le futur.")
            after = f"{action.start_date or '—'} · {action.est}h · {action.done}h passées · {STATUS_LABELS.get(action.status, action.status)}"
            hist.append({"at": now.isoformat(), "text": f"Modifiée par {user.display_name} : {after}"})
            action.history = hist
            action.save()
            if action.status == "done" and "status" in allowed:
                tell(project.pm, f"✅ Action terminée : {action.title}", f"{user.display_name} l'a terminée le {action.done_at:%d/%m/%Y}.")
            audit.record(user, f"Tâche {action.id}", "Action mise à jour", before, after, tenant=project.tenant)
        elif op == "extend":
            if action.owner_id != user.pk:
                raise ApiError("FORBIDDEN_PERMISSION", "Seul le responsable de l'action demande un délai.", status.HTTP_403_FORBIDDEN)
            reason = str(request.data.get("reason") or "").strip()[:500]
            try:
                due = timezone.datetime.strptime(str(request.data.get("due") or ""), "%Y-%m-%d").date()
            except ValueError:
                raise ApiError("VALIDATION_ERROR", "Indiquez la nouvelle échéance souhaitée.")
            if not reason:
                raise ApiError("VALIDATION_ERROR", "Expliquez pourquoi le délai est nécessaire.")
            if action.due and due <= action.due:
                raise ApiError("VALIDATION_ERROR", "La nouvelle échéance doit être après l'échéance actuelle.")
            hist.append({"type": "extension", "status": "pending", "at": now.isoformat(), "by": user.display_name, "byId": user.pk,
                         "from": action.due.isoformat() if action.due else None, "due": due.isoformat(), "reason": reason,
                         "text": f"Demande de délai : {action.due or '—'} → {due} ({reason})"})
            action.history = hist
            action.save(update_fields=["history"])
            note(f"⏳ Demande de délai supplémentaire jusqu'au {due:%d/%m/%Y} : {reason}")
            tell(project.pm, f"⏳ Demande de délai : {action.title}", f"{user.display_name} demande jusqu'au {due:%d/%m/%Y} : {reason}")
            audit.record(user, f"Tâche {action.id}", "Demande de délai", str(action.due or ""), f"{due} · {reason}", tenant=project.tenant)
        elif op == "extension_decision":
            if not rights["canManageTasks"]:
                raise ApiError("FORBIDDEN_PERMISSION", "Réservé au chef de projet.", status.HTTP_403_FORBIDDEN)
            req = next((h for h in reversed(hist) if isinstance(h, dict) and h.get("type") == "extension" and h.get("status") == "pending"), None)
            if req is None:
                raise ApiError("CONFLICT", "Aucune demande de délai en attente.", status.HTTP_409_CONFLICT)
            decision = request.data.get("decision")
            if decision not in ("approved", "rejected"):
                raise ApiError("VALIDATION_ERROR", "Décision inconnue.")
            comment = str(request.data.get("comment") or "")[:300]
            req.update(status=decision, decidedBy=user.display_name, decidedAt=now.isoformat(), comment=comment)
            if decision == "approved":
                action.due = timezone.datetime.strptime(req["due"], "%Y-%m-%d").date()
            action.history = hist
            action.save(update_fields=["history", "due"])
            note(f"{'✅ Délai accordé' if decision == 'approved' else '✖ Délai refusé'} ({req['due']})" + (f" : {comment}" if comment else ""))
            from django.contrib.auth import get_user_model
            tell(get_user_model().objects.filter(pk=req.get("byId")).first(),
                 f"{'Délai accordé' if decision == 'approved' else 'Délai refusé'} : {action.title}", comment or req["due"])
            audit.record(user, f"Tâche {action.id}", "Décision sur demande de délai", req["due"], decision, tenant=project.tenant)
        else:
            raise ApiError("VALIDATION_ERROR", "Opération inconnue.")
        return Response(_detail(user, project))



class ReassignTasksView(APIView):
    """POST {from, to, tasks?: [ids]} : le chef de projet, le tech lead ou l'administrateur réaffecte une, plusieurs ou
    toutes les actions ouvertes d'une personne (absente) à un remplaçant de l'équipe."""

    def post(self, request, pk):
        from configuration.models import Notification
        user = request.user
        project = _project(user, pk)
        rights = _rights(user, project)
        if not (user.is_app_admin or rights["isPm"] or rights["isTl"]):
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé au chef de projet, au tech lead et à l'administrateur.", status.HTTP_403_FORBIDDEN)
        team = {a.user_id: a.user for a in ProjectAccess.objects.filter(project=project, user__is_active=True).select_related("user")}
        src = get_object_or_404(get_user_model(), pk=request.data.get("from"), tenant=user.tenant)
        dst = team.get(int(request.data.get("to") or 0))
        if dst is None:
            raise ApiError("VALIDATION_ERROR", "Choisissez un remplaçant membre de l'équipe du projet.")
        if dst.pk == src.pk:
            raise ApiError("VALIDATION_ERROR", "Le remplaçant doit être une autre personne.")
        qs = Action.objects.filter(project=project, owner=src).exclude(status="done")
        ids = request.data.get("tasks")
        if isinstance(ids, list) and ids:
            qs = qs.filter(pk__in=[str(x) for x in ids])
        moved = []
        now = timezone.now()
        for a in qs:
            a.owner = dst
            a.history = list(a.history or []) + [{"at": now.isoformat(), "text": f"Réaffectée par {user.display_name} : {src.display_name} → {dst.display_name}"}]
            a.save(update_fields=["owner", "history"])
            moved.append(a.title)
        if not moved:
            raise ApiError("CONFLICT", "Aucune action ouverte à réaffecter.", status.HTTP_409_CONFLICT)
        Notification.objects.create(user=dst, event="project_alert", title=f"[{project.code}] {len(moved)} action(s) vous sont confiées"[:200],
                                    body=f"{user.display_name} vous confie les actions de {src.display_name} : {', '.join(moved)[:300]} · {project.id}")
        if src.pk != user.pk:
            Notification.objects.create(user=src, event="project_alert", title=f"[{project.code}] {len(moved)} action(s) confiées à {dst.display_name}"[:200],
                                        body=f"Pendant votre absence, {user.display_name} a confié vos actions à {dst.display_name}. · {project.id}")
        audit.record(user, f"Projet {project.code}", "Actions réaffectées (remplacement)", src.display_name, f"{dst.display_name} : {len(moved)} action(s)",
                     tenant=project.tenant)
        out = _detail(user, project)
        out["moved"] = len(moved)
        return Response(out)
