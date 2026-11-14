"""Projets de migration : outils source / cible, instances (pilote, planning, statut, objets migrés) et actions par instance."""
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.errors import ApiError
from configuration import audit

from .models import MIGRATION_STATUSES, Action, MigrationInstance, ProjectAccess

LABELS = dict(MIGRATION_STATUSES)


def _can_edit(user, project):
    from .workspace import _rights
    r = _rights(user, project)
    return bool(user.is_app_admin or r["isPm"] or r["isTl"] or r["canEditInfo"])


def _date(v, label):
    if v in (None, ""):
        return None
    d = parse_date(str(v))
    if d is None:
        raise ApiError("VALIDATION_ERROR", f"Date invalide : {label}.")
    return d


def _int(v, label):
    try:
        n = int(v or 0)
    except (TypeError, ValueError) as exc:
        raise ApiError("VALIDATION_ERROR", f"Nombre invalide : {label}.") from exc
    if n < 0:
        raise ApiError("VALIDATION_ERROR", f"{label} doit être positif.")
    return n


def instance_row(i, counts=None, today=None):
    c = (counts or {}).get(i.pk, {})
    total = c.get("total", 0)
    pct_obj = round(i.objects_migrated / i.objects_total * 100) if i.objects_total else None
    pct_act = round(c.get("done", 0) / total * 100) if total else None
    late = bool(today and i.end_date and i.end_date < today and i.status not in ("done", "cancelled"))
    return {
        "id": i.pk, "name": i.name, "code": i.code, "description": i.description, "isPilot": i.is_pilot,
        "sourceTool": i.source_tool, "targetTool": i.target_tool, "owner": {"id": i.owner_id, "name": i.owner.display_name} if i.owner_id else None,
        "status": i.status, "statusLabel": LABELS.get(i.status, i.status), "startDate": i.start_date, "endDate": i.end_date,
        "cutoverDate": i.cutover_date, "objectsTotal": i.objects_total, "objectsMigrated": i.objects_migrated,
        "objectsFailed": i.objects_failed, "objectsPct": pct_obj, "notes": i.notes, "order": i.order,
        "actions": {"total": total, "done": c.get("done", 0), "open": total - c.get("done", 0), "late": c.get("late", 0)},
        "progress": pct_obj if pct_obj is not None else (pct_act or 0), "late": late,
    }


def migration_data(user, project):
    today = timezone.localdate()
    insts = list(MigrationInstance.objects.filter(project=project).select_related("owner"))
    agg = (Action.objects.filter(project=project, instance__isnull=False).values("instance_id")
           .annotate(total=Count("id"), done=Count("id", filter=Q(status="done")),
                     late=Count("id", filter=Q(due__lt=today) & ~Q(status="done"))))
    counts = {a["instance_id"]: a for a in agg}
    rows = [instance_row(i, counts, today) for i in insts]
    glob = Action.objects.filter(project=project, instance__isnull=True)
    g_total = glob.count()
    g_done = glob.filter(status="done").count()
    tot = sum(i.objects_total for i in insts)
    mig = sum(i.objects_migrated for i in insts)
    failed = sum(i.objects_failed for i in insts)
    by_status = {}
    for i in insts:
        by_status[i.status] = by_status.get(i.status, 0) + 1
    auto_status = ("done" if insts and all(i.status in ("done", "cancelled") for i in insts) else
                   "blocked" if any(i.status == "blocked" for i in insts) else
                   "migrating" if any(i.status not in ("not_started",) for i in insts) else "not_started")
    st = project.mig_status or auto_status
    pilot = next((r for r in rows if r["isPilot"]), None)
    return {
        "enabled": project.project_type == "migration" or bool(insts),
        "source": project.mig_source, "target": project.mig_target, "status": st, "statusLabel": LABELS.get(st, st),
        "statusAuto": not project.mig_status, "statuses": [{"code": c, "label": l} for c, l in MIGRATION_STATUSES],
        "instances": rows, "pilot": pilot,
        "stats": {"instances": len(insts), "done": by_status.get("done", 0), "inProgress": sum(v for k, v in by_status.items() if k not in ("done", "not_started", "cancelled")),
                  "notStarted": by_status.get("not_started", 0), "blocked": by_status.get("blocked", 0),
                  "objectsTotal": tot, "objectsMigrated": mig, "objectsFailed": failed,
                  "objectsPct": round(mig / tot * 100) if tot else None,
                  "globalActions": {"total": g_total, "done": g_done},
                  "late": sum(1 for r in rows if r["late"])},
        "canEdit": _can_edit(user, project),
        "team": [{"id": a.user_id, "name": a.user.display_name}
                 for a in ProjectAccess.objects.filter(project=project, user__is_active=True).select_related("user")],
    }


def _apply_instance(inst, data, project):
    if "name" in data:
        name = str(data.get("name") or "").strip()[:120]
        if not name:
            raise ApiError("VALIDATION_ERROR", "Le nom de l'instance est obligatoire.")
        inst.name = name
    for key, field, n in (("code", "code", 40), ("sourceTool", "source_tool", 120), ("targetTool", "target_tool", 120)):
        if key in data:
            setattr(inst, field, str(data.get(key) or "").strip()[:n])
    for key, field in (("description", "description"), ("notes", "notes")):
        if key in data:
            setattr(inst, field, str(data.get(key) or "")[:5000])
    if "isPilot" in data:
        inst.is_pilot = bool(data.get("isPilot"))
    if "status" in data:
        if data["status"] not in LABELS:
            raise ApiError("VALIDATION_ERROR", "Statut de migration inconnu.")
        inst.status = data["status"]
    for key, field, label in (("startDate", "start_date", "démarrage"), ("endDate", "end_date", "fin"), ("cutoverDate", "cutover_date", "bascule")):
        if key in data:
            setattr(inst, field, _date(data.get(key), label))
    if inst.start_date and inst.end_date and inst.end_date < inst.start_date:
        raise ApiError("VALIDATION_ERROR", "La fin doit être postérieure au démarrage.")
    for key, field, label in (("objectsTotal", "objects_total", "objets à migrer"), ("objectsMigrated", "objects_migrated", "objets migrés"),
                              ("objectsFailed", "objects_failed", "objets en échec")):
        if key in data:
            setattr(inst, field, _int(data.get(key), label))
    if inst.objects_total and inst.objects_migrated > inst.objects_total:
        raise ApiError("VALIDATION_ERROR", "Le nombre d'objets migrés dépasse le total à migrer.")
    if "owner" in data:
        uid = data.get("owner")
        inst.owner = get_object_or_404(get_user_model().objects.filter(tenant=project.tenant), pk=uid) if uid else None
    if "order" in data:
        inst.order = _int(data.get("order"), "ordre")


class MigrationView(APIView):
    """GET : synthèse de la migration (outils, instances, objets, statut). PATCH : outils source / cible et statut global."""

    def get(self, request, pk):
        from .workspace import _project
        return Response(migration_data(request.user, _project(request.user, pk)))

    def patch(self, request, pk):
        from .workspace import _project
        project = _project(request.user, pk)
        if not _can_edit(request.user, project):
            raise ApiError("FORBIDDEN_PERMISSION", "Seuls le chef de projet, le tech lead ou l'admin modifient la migration.", status.HTTP_403_FORBIDDEN)
        if "source" in request.data:
            project.mig_source = str(request.data.get("source") or "").strip()[:120]
        if "target" in request.data:
            project.mig_target = str(request.data.get("target") or "").strip()[:120]
        if "status" in request.data:
            st = request.data.get("status") or ""
            if st and st not in LABELS:
                raise ApiError("VALIDATION_ERROR", "Statut de migration inconnu.")
            project.mig_status = st  # vide = statut calculé à partir des instances
        project.save(update_fields=["mig_source", "mig_target", "mig_status"])
        audit.record(request.user, f"Projet {project.code}", "Migration paramétrée", "",
                     f"{project.mig_source} → {project.mig_target} · {LABELS.get(project.mig_status, 'statut auto')}", tenant=request.user.tenant)
        return Response(migration_data(request.user, project))


class MigrationInstanceView(APIView):
    """POST : nouvelle instance. PATCH / DELETE : modifier / supprimer une instance."""

    def _check(self, request, pk):
        from .workspace import _project
        project = _project(request.user, pk)
        if not _can_edit(request.user, project):
            raise ApiError("FORBIDDEN_PERMISSION", "Seuls le chef de projet, le tech lead ou l'admin gèrent les instances.", status.HTTP_403_FORBIDDEN)
        return project

    def post(self, request, pk):
        project = self._check(request, pk)
        inst = MigrationInstance(tenant=project.tenant, project=project, order=MigrationInstance.objects.filter(project=project).count() + 1,
                                 source_tool=project.mig_source, target_tool=project.mig_target)
        _apply_instance(inst, {"name": "", **request.data}, project)
        inst.save()
        if inst.is_pilot:
            MigrationInstance.objects.filter(project=project, is_pilot=True).exclude(pk=inst.pk).update(is_pilot=False)
        audit.record(request.user, f"Projet {project.code}", "Instance de migration créée", "", inst.name, tenant=request.user.tenant)
        return Response(migration_data(request.user, project), status=status.HTTP_201_CREATED)

    def patch(self, request, pk, inst_id):
        project = self._check(request, pk)
        inst = get_object_or_404(MigrationInstance, project=project, pk=inst_id)
        before = (inst.status, inst.objects_migrated)
        _apply_instance(inst, request.data, project)
        inst.save()
        if inst.is_pilot:
            MigrationInstance.objects.filter(project=project, is_pilot=True).exclude(pk=inst.pk).update(is_pilot=False)
        if before != (inst.status, inst.objects_migrated):
            audit.record(request.user, f"Instance {inst.name}", "Instance de migration mise à jour",
                         f"{LABELS.get(before[0])} · {before[1]} objets", f"{LABELS.get(inst.status)} · {inst.objects_migrated} objets",
                         tenant=request.user.tenant)
        return Response(migration_data(request.user, project))

    def delete(self, request, pk, inst_id):
        project = self._check(request, pk)
        inst = get_object_or_404(MigrationInstance, project=project, pk=inst_id)
        name = inst.name
        inst.delete()  # les actions de l'instance redeviennent des actions globales du projet
        audit.record(request.user, f"Projet {project.code}", "Instance de migration supprimée", name, "", tenant=request.user.tenant)
        return Response(migration_data(request.user, project))
