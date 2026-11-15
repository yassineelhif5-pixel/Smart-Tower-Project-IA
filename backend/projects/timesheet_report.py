"""Reporting standard des saisies : projet × consultant × mois, état de validation et état du CRA.

GET  /timesheets/report?months=3            lignes visibles par l'utilisateur (les siennes ; celles de ses projets s'il valide
                                            ou s'il a le droit d'approbation ; toutes pour l'administrateur ; le client : ses projets)
POST /timesheets/report/generate-cra        {client, period} : le collaborateur génère lui-même son CRA s'il ne l'a pas été
                                            automatiquement (toutes ses saisies du mois validées, mois terminé ou entièrement saisi)
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import has_perm
from config.errors import ApiError
from configuration import audit
from django.utils import timezone

from . import time_approval
from .access import in_active_tenant, visible_projects
from .models import Client, TimeAbsence, TimeEntry

STATUS_LABEL = {"draft": "Brouillon", "pending": "En validation interne", "client": "Chez le client", "approved": "Validé", "rejected": "Refusé"}


def _hpd(tenant):
    from planning.services import hours_per_day
    return Decimal(str(hours_per_day(tenant) or 8))


def _month_complete(user, period):
    """Mois terminé, ou chaque jour ouvré du mois couvert par du temps ou une absence."""
    from clientspace import billing
    from .timesheet_sheet import holidays
    first, last = billing.bounds(period)
    if timezone.localdate() > last:
        return True, ""
    hol = holidays(first.year)
    covered = set(TimeEntry.objects.filter(person=user, work_date__range=(first, last)).exclude(approval_status="rejected").values_list("work_date", flat=True))
    covered |= set(TimeAbsence.objects.filter(person=user, work_date__range=(first, last)).values_list("work_date", flat=True))
    d, missing = first, []
    while d <= last:
        if d.weekday() < 5 and d not in hol and d not in covered:
            missing.append(d)
        d += timedelta(days=1)
    return (not missing), (f"{len(missing)} jour(s) ouvré(s) non saisi(s) (dont le {missing[0]:%d/%m})" if missing else "")


def cra_state(user, person_id, client_id, period, counts, cra):
    """(code, libellé, peut générer) pour le CRA d'une personne × client × mois."""
    if cra:
        return "generated", f"Généré — v{cra.version} le {timezone.localtime(cra.created_at):%d/%m/%Y}", False
    n = sum(counts.values())
    if counts.get("draft") or counts.get("rejected"):
        return "blocked", "Saisies à envoyer ou à corriger", False
    if counts.get("pending") or counts.get("client"):
        return "waiting", "En attente des validations", False
    if n and counts.get("approved") == n:
        return "ready", "Prêt à générer (toutes les saisies validées)", True
    return "none", "—", False


class TimesheetReportView(APIView):
    def get(self, request):
        user = request.user
        if not in_active_tenant(user) or not has_perm(user, "timesheet", "read"):
            raise ApiError("FORBIDDEN_PERMISSION", "Vous n'avez pas accès au module Saisie de temps.", status.HTTP_403_FORBIDDEN)
        from clientspace import billing
        from clientspace.models import ClientDocument
        months = max(1, min(int(request.query_params.get("months") or 3), 12))
        today = timezone.localdate()
        start = (today.replace(day=1) - timedelta(days=31 * (months - 1))).replace(day=1)
        qs = TimeEntry.objects.filter(tenant=user.tenant, work_date__gte=start).select_related("project", "project__client", "person")
        if not user.role.internal:
            qs = qs.filter(project__in=visible_projects(user)).exclude(approval_status="draft")
        elif not user.is_app_admin:
            scope = Q(person=user) | Q(project_id__in=time_approval.decidable_project_ids(user))
            if has_perm(user, "timesheet", "approve"):
                scope |= Q(project__in=visible_projects(user))
            qs = qs.filter(scope)
        hpd = _hpd(user.tenant)
        rows = defaultdict(lambda: {"hours": Decimal("0"), "counts": defaultdict(int), "steps": set()})
        whole = defaultdict(lambda: defaultdict(int))  # (personne, client, mois) -> statuts (le CRA couvre tous les projets du client)
        for e in qs:
            period = f"{e.work_date:%Y-%m}"
            k = (e.project_id, e.person_id, period)
            r = rows[k]
            r.update(project=e.project.code, projectName=e.project.name, client=e.project.client_id, clientName=e.project.client.name if e.project.client_id else "",
                     person=e.person_id, personName=e.person.display_name, period=period, periodLabel=billing.label(period))
            r["hours"] += e.hours
            r["counts"][e.approval_status] += 1
            if e.approval_status == "pending":
                r["steps"].add(time_approval.step_label(e.project, e.approval_step))
            whole[(e.person_id, e.project.client_id, period)][e.approval_status] += 1
        cras = {}
        for d in ClientDocument.objects.filter(tenant=user.tenant, kind="cra", period__gte=f"{start:%Y-%m}").order_by("version"):
            cras[(d.person_id, d.client_id, d.period)] = d
        out = []
        for r in rows.values():
            c = r["counts"]
            n = sum(c.values())
            if c.get("rejected"):
                state = "rejected"
            elif c.get("draft"):
                state = "draft"
            elif c.get("pending"):
                state = "pending"
            elif c.get("client"):
                state = "client"
            else:
                state = "approved"
            label = STATUS_LABEL[state] + (f" ({', '.join(sorted(r['steps']))})" if state == "pending" and r["steps"] else "")
            if len([k for k in c if c[k]]) > 1:  # états mélangés : détail par état
                short = {"draft": "brouillon", "pending": "en validation", "client": "chez le client", "approved": "validée(s)", "rejected": "refusée(s)"}
                label += " · " + ", ".join(f"{c[k]} {short[k]}" for k in ("rejected", "draft", "pending", "client", "approved") if c.get(k))
            key = (r["person"], r["client"], r["period"])
            cra = cras.get(key)
            code, cra_label, can = cra_state(user, *key, whole[key], cra)
            mine = r["person"] == user.id
            out.append({k: v for k, v in r.items() if k not in ("counts", "steps", "hours")} | {
                "hours": str(r["hours"].quantize(Decimal("0.01"))), "days": str((r["hours"] / hpd).quantize(Decimal("0.01"))),
                "counts": dict(c), "entries": n, "state": state, "stateLabel": label,
                "cra": code, "craLabel": cra_label, "craId": cra.pk if cra else None, "craNumber": cra.number if cra else "",
                "mine": mine, "canGenerate": bool(can and mine)})
        out.sort(key=lambda x: (x["period"], x["project"], x["personName"]), reverse=False)
        out.sort(key=lambda x: x["period"], reverse=True)
        return Response({"rows": out, "since": f"{start:%Y-%m}"})


class GenerateMyCraView(APIView):
    def post(self, request):
        user = request.user
        if not in_active_tenant(user) or not user.role.internal:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé aux collaborateurs.", status.HTTP_403_FORBIDDEN)
        from clientspace import billing
        from clientspace.models import ClientDocument
        period = str(request.data.get("period") or "")
        client = Client.objects.filter(tenant=user.tenant, pk=request.data.get("client")).first()
        if len(period) != 7 or client is None:
            raise ApiError("VALIDATION_ERROR", "Client et période (AAAA-MM) attendus.")
        if ClientDocument.objects.filter(client=client, person=user, period=period, kind="cra").exists():
            raise ApiError("VALIDATION_ERROR", "Le CRA de ce mois est déjà généré.", status.HTTP_409_CONFLICT)
        _, counts = billing.state(user.tenant, user.pk, client, period)
        code, label, can = cra_state(user, user.pk, client.pk, period, counts, None)
        if not can:
            raise ApiError("VALIDATION_ERROR", f"CRA non générable : {label.lower()}.")
        ok, why = _month_complete(user, period)
        if not ok:
            raise ApiError("VALIDATION_ERROR", f"Le mois n'est pas terminé et n'est pas entièrement saisi : {why}.")
        try:
            cra, inv, _ = billing.generate(user.tenant, user, client, period, by=user, force=True)
        except billing.BillingError as exc:
            raise ApiError("VALIDATION_ERROR", str(exc)) from exc
        audit.record(user, f"Client {client.name}", "CRA généré manuellement par le collaborateur", "", f"{billing.label(period)} · v{cra.version}",
                     tenant=user.tenant)
        return Response({"cra": cra.pk, "version": cra.version, "invoice": inv.number if inv else "",
                         "message": f"CRA de {billing.label(period)} généré : vous avez reçu une notification."}, status=status.HTTP_201_CREATED)


class MyCrasView(APIView):
    """GET /timesheets/my-cras : CRA générés de l'utilisateur (toutes versions), pour l'arborescence projet › mois."""

    def get(self, request):
        user = request.user
        if not in_active_tenant(user):
            raise ApiError("FORBIDDEN_PERMISSION", "Accès réservé aux utilisateurs d'une entreprise.", status.HTTP_403_FORBIDDEN)
        from clientspace import billing
        from clientspace.models import ClientDocument
        from clientspace.doc_info import doc_code
        from .models import Project
        docs = list(ClientDocument.objects.filter(tenant=user.tenant, person=user, kind="cra").select_related("client").order_by("-period", "-version"))
        codes = {c for d in docs for c in (d.meta.get("projects") or [])}
        names = dict(Project.objects.filter(tenant=user.tenant, code__in=codes).values_list("code", "name"))
        latest = {}
        for d in docs:
            latest.setdefault((d.client_id, d.period), d.version)
        out = []
        for d in docs:
            out.append({"id": d.pk, "name": d.name, "period": d.period, "periodLabel": billing.label(d.period), "client": d.client.name,
                        "projects": [{"code": c, "name": names.get(c, c)} for c in (d.meta.get("projects") or [])] or [{"code": "—", "name": d.client.name}],
                        "version": d.version, "latest": latest[(d.client_id, d.period)] == d.version, "days": d.days,
                        "createdAt": d.created_at, "generatedBy": d.meta.get("generatedBy", ""), "approvers": d.meta.get("approvers", []),
                        "format": "pdf" if d.mime == "application/pdf" else "docx", "noInvoice": d.meta.get("noInvoice", ""),
                        "download": f"/timesheets/history/cra/{d.pk}", "code": doc_code(d)})
        return Response({"cras": out})


class RegenerateCraView(APIView):
    """POST /timesheets/my-cras/<id>/regenerate : nouvelle version du CRA (le collaborateur, l'administrateur ou le chef de
    projet d'un projet du client). Les saisies doivent toujours être toutes validées ; le numéro de facture est conservé."""

    def post(self, request, doc_id):
        user = request.user
        if not in_active_tenant(user):
            raise ApiError("FORBIDDEN_PERMISSION", "Accès réservé aux utilisateurs d'une entreprise.", status.HTTP_403_FORBIDDEN)
        from clientspace import billing
        from clientspace.models import ClientDocument
        from django.shortcuts import get_object_or_404
        doc = get_object_or_404(ClientDocument.objects.select_related("client", "person"), pk=doc_id, tenant=user.tenant, kind="cra")
        allowed = doc.person_id == user.id or user.is_app_admin or visible_projects(user).filter(client=doc.client, pm=user).exists()
        if not allowed or doc.person is None:
            raise ApiError("FORBIDDEN_PERMISSION", "Vous ne pouvez pas régénérer ce CRA.", status.HTTP_403_FORBIDDEN)
        try:
            cra, inv, _ = billing.generate(user.tenant, doc.person, doc.client, doc.period, by=user, force=True, regenerate=True)
        except billing.BillingError as exc:
            raise ApiError("VALIDATION_ERROR", str(exc)) from exc
        audit.record(user, f"Client {doc.client.name}", "CRA régénéré", f"v{doc.version}", f"v{cra.version} · {doc.person.display_name} · {billing.label(doc.period)}",
                     tenant=user.tenant)
        return Response({"cra": cra.pk, "version": cra.version, "name": cra.name, "invoice": inv.number if inv else "",
                         "message": f"CRA régénéré (version {cra.version})."}, status=status.HTTP_201_CREATED)
