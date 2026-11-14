from django.contrib.auth import get_user_model
from decimal import Decimal, InvalidOperation
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import has_perm
from configuration import audit
from configuration.models import AppSetting
from planning.services import hours_per_day
from .access import can_edit_project, in_active_tenant, visible_actions, visible_projects
from .models import Action, Project, TimeApprovalDelegation, TimeEntry
from . import time_approval
from config.errors import ApiError


def project_row(p, user=None):
    row = {"id": p.id, "code": p.code, "name": p.name, "client": {"code": p.client_id, "name": p.client.name},
           "method": p.method, "progress": p.progress, "status": p.status, "statusLabel": p.get_status_display(),
           "closedAt": p.closed_at, "endDate": p.end_date}
    if user is not None:
        row["canEdit"] = can_edit_project(user, p)
    return row


def action_row(a):
    return {"id": a.id, "project": a.project_id, "title": a.title, "status": a.status, "type": a.type,
            "owner": a.owner.display_name if a.owner else None, "due": a.due}


class ProjectListView(APIView):
    """Projets du périmètre de l'utilisateur connecté."""

    def get(self, request):
        projects = visible_projects(request.user).select_related("client")
        return Response([project_row(p, request.user) for p in projects])


class ProjectActionsView(APIView):
    """Tâches visibles d'un projet du périmètre."""

    def get(self, request, pk):
        project = get_object_or_404(visible_projects(request.user), pk=pk)
        actions = visible_actions(request.user).filter(project=project).select_related("owner")
        return Response([action_row(a) for a in actions])


def _time_settings(tenant):
    row = AppSetting.objects.filter(tenant=tenant, key="time").first()
    value = row.value if row and isinstance(row.value, dict) else {}
    return value.get("entryUnit", "hour"), hours_per_day(tenant), value.get("clientVisible", True)


def _time_row(entry, unit, hpd):
    amount = Decimal(entry.hours) / hpd if unit == "day" else Decimal(entry.hours)
    return {"id": entry.pk, "project": entry.project_id, "projectName": entry.project.name,
            "action": entry.action_id, "actionName": entry.action.title if entry.action else "",
            "user": entry.person_id, "userName": entry.person.display_name, "workDate": entry.work_date,
            "amount": str(amount.quantize(Decimal("0.01"))), "unit": unit,
            "status": entry.approval_status, "line": entry.line, "approvedBy": entry.approved_by.display_name if entry.approved_by else None,
            "approvedAt": entry.approved_at}


class TimeEntryListView(APIView):
    def get(self, request):
        if not in_active_tenant(request.user) or not has_perm(request.user, "timesheet", "read"):
            raise ApiError("FORBIDDEN_PERMISSION", "Vous n'avez pas accès au module Saisie de temps.", status.HTTP_403_FORBIDDEN)
        user = request.user
        projects = visible_projects(user)
        rows = TimeEntry.objects.filter(tenant=user.tenant).select_related("project", "action", "person", "approved_by")
        unit, hpd, client_visible = _time_settings(user.tenant)
        mode = time_approval.approval_mode(user.tenant)
        if not user.role.internal:
            if not client_visible:
                return Response({"unit": unit, "approval": mode, "rows": []})
            rows = rows.filter(project__in=projects).exclude(approval_status="draft")  # le client voit toutes les saisies envoyées
            decidable = set()
        else:
            decidable = time_approval.decidable_project_ids(user)
            scope = Q(person=user) | Q(project_id__in=decidable)
            if has_perm(user, "timesheet", "approve"):
                scope |= Q(project__in=projects)
            rows = rows.filter(scope).exclude(Q(approval_status="draft") & ~Q(person=user))
        out = []
        for entry in rows.order_by("-work_date", "-pk")[:500]:
            row = _time_row(entry, unit, hpd)
            row["canDecide"] = (entry.approval_status == "pending" and entry.project_id in decidable
                                and time_approval.can_decide(user, entry))
            out.append(row)
        return Response({"unit": unit, "approval": mode, "rows": out})

    def post(self, request):
        if not in_active_tenant(request.user) or not has_perm(request.user, "timesheet", "create") or not request.user.role.internal:
            raise ApiError("FORBIDDEN_PERMISSION", "La saisie est réservée aux collaborateurs autorisés.", status.HTTP_403_FORBIDDEN)
        project = get_object_or_404(visible_projects(request.user), pk=request.data.get("project"))
        unit, hpd, _ = _time_settings(request.user.tenant)
        try:
            amount = Decimal(str(request.data.get("amount", "")))
            work_date = timezone.datetime.strptime(request.data.get("workDate", ""), "%Y-%m-%d").date()
        except (InvalidOperation, TypeError, ValueError):
            raise ApiError("VALIDATION_ERROR", "Indiquez une date et une durée valides.")
        hours = amount * hpd if unit == "day" else amount
        if not amount.is_finite() or amount <= 0 or hours > 24:
            raise ApiError("VALIDATION_ERROR", "La durée doit être positive et ne pas dépasser 24 heures par jour.")
        action = None
        if request.data.get("action"):
            action = get_object_or_404(Action, pk=request.data["action"], project=project, tenant=request.user.tenant)
        from .budget_report import check_entry_allowed
        blocked = check_entry_allowed(project, request.user)
        if blocked:
            raise ApiError("FORBIDDEN_PERMISSION", blocked, status.HTTP_403_FORBIDDEN)
        auto = time_approval.approval_mode(request.user.tenant) == "auto"
        entry = TimeEntry.objects.create(tenant=request.user.tenant, person=request.user, project=project, action=action,
            work_date=work_date, hours=hours,
            approval_status=time_approval.after_internal_approval(request.user.tenant) if auto else "pending",
            approved_at=timezone.now() if auto else None)
        audit.record(request.user, f"Saisie de temps · {project.name}",
                     "Saisie validée automatiquement" if auto else "Saisie transmise pour validation", "",
                     f"{amount} {unit}", tenant=request.user.tenant)
        return Response(_time_row(entry, unit, hpd), status=status.HTTP_201_CREATED)


class TimeEntryDetailView(APIView):
    def post(self, request, pk):
        entry = get_object_or_404(TimeEntry.objects.select_related("project", "person", "action"), pk=pk, tenant=request.user.tenant)
        if entry.person_id == request.user.id:
            raise ApiError("FORBIDDEN_PERMISSION", "Vous ne pouvez pas valider vos propres saisies.", status.HTTP_403_FORBIDDEN)
        if not time_approval.can_decide(request.user, entry):
            raise ApiError("FORBIDDEN_PERMISSION", "Ce temps doit être validé par le valideur désigné du projet "
                           "(ou son délégué pendant une absence).", status.HTTP_403_FORBIDDEN)
        if entry.approval_status != "pending":
            raise ApiError("VALIDATION_ERROR", "Cette saisie a déjà été traitée.", status.HTTP_409_CONFLICT)
        decision = request.data.get("decision")
        if decision not in {"approved", "rejected"}:
            raise ApiError("VALIDATION_ERROR", "Choisissez valider ou refuser.")
        if decision == "approved":  # étape suivante du workflow du projet, puis client ou validé
            decision, entry.approval_step = time_approval.next_status(entry)
        entry.approval_status, entry.approved_by, entry.approved_at = decision, request.user, timezone.now()
        entry.save(update_fields=["approval_status", "approved_by", "approved_at", "approval_step"])
        delegated = not request.user.is_app_admin and request.user.id not in time_approval.base_approvers(
            entry.project, time_approval.approval_mode(request.user.tenant))
        audit.record(request.user, f"Saisie de temps · {entry.project.name}",
                     ({"approved": "Temps validé", "client": "Temps validé (transmis au client)",
                       "pending": f"Temps validé (étape {entry.approval_step} → valideur suivant)"}.get(decision, "Temps refusé"))
                     + (" (par délégation)" if delegated else ""),
                     "À valider", decision, tenant=request.user.tenant)
        unit, hpd, _ = _time_settings(request.user.tenant)
        return Response(_time_row(entry, unit, hpd))


def _delegation_row(d):
    today = timezone.localdate()
    state = "active" if d.start_date <= today <= d.end_date else ("future" if d.start_date > today else "past")
    return {"id": d.pk, "delegator": d.delegator_id, "delegatorName": d.delegator.display_name,
            "delegate": d.delegate_id, "delegateName": d.delegate.display_name,
            "startDate": d.start_date, "endDate": d.end_date, "reason": d.reason, "state": state}


class TimeDelegationView(APIView):
    """Absences : chacun délègue ses validations de temps ; l'administrateur gère toutes les délégations."""

    def _check(self, request):
        if not in_active_tenant(request.user) or not request.user.role.internal:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé aux collaborateurs de l'entreprise.", status.HTTP_403_FORBIDDEN)

    def get(self, request):
        self._check(request)
        user = request.user
        rows = TimeApprovalDelegation.objects.filter(tenant=user.tenant).select_related("delegator", "delegate")
        if not user.is_app_admin:
            rows = rows.filter(Q(delegator=user) | Q(delegate=user))
        rows = rows.filter(end_date__gte=timezone.localdate() - timezone.timedelta(days=90))
        people = get_user_model().objects.filter(tenant=user.tenant, is_active=True, role__internal=True).order_by("first_name", "username")
        return Response({
            "mode": time_approval.approval_mode(user.tenant),
            "modes": [{"code": c, "label": l} for c, l in time_approval.MODES.items()],
            "canManageAll": user.is_app_admin,
            "people": [{"id": p.id, "name": p.display_name} for p in people],
            "rows": [_delegation_row(d) for d in rows],
        })

    def post(self, request):
        self._check(request)
        user = request.user
        users = get_user_model().objects.filter(tenant=user.tenant, is_active=True, role__internal=True)
        delegator = user
        if request.data.get("delegator") and user.is_app_admin:
            delegator = get_object_or_404(users, pk=request.data.get("delegator"))
        delegate = get_object_or_404(users, pk=request.data.get("delegate"))
        try:
            start = timezone.datetime.strptime(str(request.data.get("startDate", "")), "%Y-%m-%d").date()
            end = timezone.datetime.strptime(str(request.data.get("endDate", "")), "%Y-%m-%d").date()
        except ValueError:
            raise ApiError("VALIDATION_ERROR", "Indiquez des dates de début et de fin valides.")
        if delegate.pk == delegator.pk:
            raise ApiError("VALIDATION_ERROR", "Choisissez une autre personne que l'absent.")
        if end < start or (end - start).days > 366:
            raise ApiError("VALIDATION_ERROR", "La période doit être valide et ne pas dépasser un an.")
        if end < timezone.localdate():
            raise ApiError("VALIDATION_ERROR", "La période est déjà passée.")
        d = TimeApprovalDelegation.objects.create(tenant=user.tenant, delegator=delegator, delegate=delegate,
                                                  start_date=start, end_date=end, created_by=user,
                                                  reason=str(request.data.get("reason", "")).strip()[:200])
        audit.record(user, f"Délégation de validation · {delegator.display_name}", "Délégation créée", "",
                     f"{delegate.display_name} du {start:%d/%m/%Y} au {end:%d/%m/%Y}", tenant=user.tenant)
        return Response(_delegation_row(d), status=status.HTTP_201_CREATED)

    def delete(self, request, pk):
        self._check(request)
        user = request.user
        d = get_object_or_404(TimeApprovalDelegation.objects.select_related("delegator", "delegate"), pk=pk, tenant=user.tenant)
        if not (user.is_app_admin or d.delegator_id == user.id or d.created_by_id == user.id):
            raise ApiError("FORBIDDEN_PERMISSION", "Seul l'absent ou un administrateur peut retirer cette délégation.", status.HTTP_403_FORBIDDEN)
        audit.record(user, f"Délégation de validation · {d.delegator.display_name}", "Délégation retirée",
                     f"{d.delegate.display_name}", "", tenant=user.tenant)
        d.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
