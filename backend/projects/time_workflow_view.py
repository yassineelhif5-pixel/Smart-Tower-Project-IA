"""Administrateur (et Pilote) : workflow de validation des temps par projet — étapes successives
(chef de projet, tech lead, personne désignée, administrateurs), puis validation client facultative.
Application à un ou plusieurs projets ; « null » remet le circuit par défaut de l'entreprise."""
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.errors import ApiError
from configuration import audit
from configuration.models import AppSetting

from . import time_approval as ta
from .models import Project, TimeEntry

User = get_user_model()


def _describe(project, wf, users):
    if not wf:
        mode = ta.approval_mode(project.tenant)
        return [ta.MODES[mode]] + (["Client"] if ta.client_step(project.tenant) and mode != "auto" else [])
    out = []
    for st in wf["steps"]:
        if st["kind"] == "pm":
            out.append(f"Chef de projet ({users.get(project.pm_id, '—')})")
        elif st["kind"] == "tl":
            out.append(f"Tech Lead ({users.get(project.tl_id, '—')})")
        elif st["kind"] == "user":
            out.append(users.get(st.get("user"), "Personne supprimée"))
        else:
            out.append("Administrateurs")
    return out + (["Client"] if wf.get("client") else [])


def _payload(tenant):
    users = {u.id: u.display_name for u in User.objects.filter(tenant=tenant, is_active=True)}
    wfs = ta.workflows(tenant)
    projects = Project.objects.filter(tenant=tenant).select_related("client", "pm", "tl").order_by("client__name", "name")
    pending = {}
    for pid, step in TimeEntry.objects.filter(tenant=tenant, approval_status="pending").values_list("project_id", "approval_step"):
        pending.setdefault(pid, {}).setdefault(step, 0)
        pending[pid][step] += 1
    return {
        "projects": [{"id": p.id, "name": p.name, "client": p.client.name, "status": p.status, "pm": users.get(p.pm_id), "tl": users.get(p.tl_id),
                      "workflow": wfs.get(p.id) if wfs.get(p.id, {}).get("steps") else None,
                      "chain": _describe(p, wfs.get(p.id) if wfs.get(p.id, {}).get("steps") else None, users),
                      "pending": pending.get(p.id, {})} for p in projects],
        "users": [{"id": u.id, "name": u.display_name, "role": u.role.label if u.role else ""}
                  for u in User.objects.filter(tenant=tenant, is_active=True, role__internal=True).select_related("role").order_by("first_name")],
        "kinds": [{"code": k, "label": v} for k, v in ta.STEP_KINDS.items()],
        "defaultMode": ta.MODES[ta.approval_mode(tenant)], "defaultClient": ta.client_step(tenant),
    }


def _save(tenant, data, by):
    ids = data.get("projects") or []
    if not isinstance(ids, list) or not ids:
        raise ApiError("VALIDATION_ERROR", "Choisissez au moins un projet.")
    known = set(Project.objects.filter(tenant=tenant, pk__in=ids).values_list("pk", flat=True))
    if set(ids) - known:
        raise ApiError("NOT_FOUND", "Projet introuvable.", status.HTTP_404_NOT_FOUND)
    wf = data.get("workflow")
    if wf is not None:
        steps = []
        for st in (wf.get("steps") or [])[:6]:
            kind = st.get("kind")
            if kind not in ta.STEP_KINDS:
                raise ApiError("VALIDATION_ERROR", "Type de valideur inconnu.")
            item = {"kind": kind}
            if kind == "user":
                u = User.objects.filter(tenant=tenant, pk=st.get("user"), is_active=True).first()
                if u is None:
                    raise ApiError("VALIDATION_ERROR", "Choisissez la personne qui valide à chaque étape « Personne désignée ».")
                item["user"] = u.id
            steps.append(item)
        if not steps:
            raise ApiError("VALIDATION_ERROR", "Ajoutez au moins un valideur.")
        wf = {"steps": steps, "client": bool(wf.get("client"))}
    row, _ = AppSetting.objects.get_or_create(tenant=tenant, key=ta.WORKFLOW_KEY, defaults={"value": {}})
    value = dict(row.value or {})
    for pid in ids:
        if wf is None:
            value.pop(pid, None)
        else:
            value[pid] = wf
    row.value = value
    row.save(update_fields=["value"])
    # Les saisies en attente reprennent à la première étape du nouveau circuit.
    TimeEntry.objects.filter(tenant=tenant, project_id__in=ids, approval_status="pending").update(approval_step=0)
    audit.record(by, "Validation des temps", "Workflow de validation modifié" if wf else "Workflow par défaut rétabli",
                 "", f"{', '.join(ids)} : {wf}", tenant=tenant)
    return _payload(tenant)


class TimeWorkflowView(APIView):
    """GET : projets et leur circuit. PUT {projects: [...], workflow: {steps, client} | null}."""

    def get(self, request):
        if not request.user.is_app_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé à l'administrateur.", status.HTTP_403_FORBIDDEN)
        return Response(_payload(request.user.tenant))

    def put(self, request):
        if not request.user.is_app_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé à l'administrateur.", status.HTTP_403_FORBIDDEN)
        return Response(_save(request.user.tenant, request.data, request.user))


class PilotTimeWorkflowView(APIView):
    def get(self, request, tenant_id):
        from tenants.models import Tenant
        if not request.user.is_platform_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé au Pilote.", status.HTTP_403_FORBIDDEN)
        return Response(_payload(get_object_or_404(Tenant, pk=tenant_id)))

    def put(self, request, tenant_id):
        from tenants.models import Tenant
        if not request.user.is_platform_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé au Pilote.", status.HTTP_403_FORBIDDEN)
        return Response(_save(get_object_or_404(Tenant, pk=tenant_id), request.data, request.user))
