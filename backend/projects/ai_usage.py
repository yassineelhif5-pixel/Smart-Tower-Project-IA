"""Consommation des assistants IA : interactions par assistant et par mois (appels IA, discussions, journal
d'orchestration, documents rédigés), quota mensuel et reste, coût et facture de consommation.

Quota et prix : fixés par l'administrateur (ou le Pilote) par assistant ; quota propre à un client possible.
Visibilité : administrateur (toute l'entreprise), chef de projet (ses projets), client et commercial (projets du client).
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.errors import ApiError
from configuration import audit
from configuration.models import AppSetting
from .access import visible_projects
from .ai_orchestrator import ROSTER, JOURNAL_KEY
from .models import Project

PRICING_KEY = "ai_usage_pricing"
DEFAULT_QUOTA, DEFAULT_PRICE = 200, Decimal("0.50")
SOURCES = {"call": "Appels IA", "discussion": "Discussions", "journal": "Orchestration", "document": "Documents rédigés"}
DOC_WEIGHT = 10  # un document rédigé compte pour 10 interactions


def pricing(tenant):
    row = AppSetting.objects.filter(tenant=tenant, key=PRICING_KEY).first()
    v = row.value if row and isinstance(row.value, dict) else {}
    out = {"currency": "EUR", "vatRate": 20.0, "assistants": {}, "clients": v.get("clients") or {}}
    for code in ROSTER:
        a = (v.get("assistants") or {}).get(code) or {}
        out["assistants"][code] = {"quota": int(a.get("quota", DEFAULT_QUOTA)), "price": str(Decimal(str(a.get("price", DEFAULT_PRICE))))}
    out["vatRate"] = float(v.get("vatRate", 20.0))
    return out


def save_pricing(tenant, data, by):
    cur = pricing(tenant)
    for code, a in (data.get("assistants") or {}).items():
        if code in ROSTER:
            if "quota" in a:
                cur["assistants"][code]["quota"] = max(0, int(a["quota"] or 0))
            if "price" in a:
                cur["assistants"][code]["price"] = str(max(Decimal("0"), Decimal(str(a["price"] or 0))))
    if isinstance(data.get("clients"), dict):
        cur["clients"] = {k: {c: max(0, int(q)) for c, q in (v or {}).items() if c in ROSTER} for k, v in data["clients"].items()}
    if "vatRate" in data:
        cur["vatRate"] = float(data["vatRate"] or 0)
    AppSetting.objects.update_or_create(tenant=tenant, key=PRICING_KEY, defaults={"value": cur})
    audit.record(by, "Assistants IA", "Quotas et tarifs IA", "", str(cur["assistants"])[:500], tenant=tenant)
    return cur


def _month(dt):
    if isinstance(dt, str):
        dt = timezone.datetime.fromisoformat(dt)
    if hasattr(dt, "tzinfo") and dt.tzinfo:
        dt = timezone.localtime(dt)
    return f"{dt.year:04d}-{dt.month:02d}"


def collect(projects):
    """Liste d'événements {assistant, project, month, source, units}."""
    from aicalls.models import AiCall
    from collaboration.models import DiscussionMessage
    ids = [p.id for p in projects]
    ev = defaultdict(int)
    for call in AiCall.objects.filter(project_id__in=ids).only("project_id", "turns", "lead", "document_id", "ended_at", "started_at"):
        for t in call.turns or []:
            if t.get("speaker") in ROSTER and t.get("at"):
                ev[(t["speaker"], call.project_id, _month(t["at"]), "call")] += 1
        if call.document_id and call.lead in ROSTER:
            ev[(call.lead, call.project_id, _month(call.ended_at or call.started_at), "document")] += DOC_WEIGHT
    for code, pid, created in DiscussionMessage.objects.filter(discussion__project_id__in=ids).exclude(ai_author="") \
            .values_list("ai_author", "discussion__project_id", "created_at"):
        if code in ROSTER:
            ev[(code, pid, _month(created), "discussion")] += 1
    tenants = {p.tenant_id for p in projects}
    for row in AppSetting.objects.filter(tenant_id__in=tenants, key=JOURNAL_KEY):
        for pid, items in (row.value or {}).items():
            if pid not in ids:
                continue
            for it in items or []:
                if it.get("assistant") in ROSTER and it.get("at"):
                    ev[(it["assistant"], pid, _month(it["at"]), "journal")] += 1
    return [{"assistant": a, "project": p, "month": m, "source": s, "units": n} for (a, p, m, s), n in ev.items()]


def _months(n, end=None):
    end = end or timezone.localdate()
    y, m = end.year, end.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def _scope(user):
    """Projets dont l'utilisateur voit la consommation IA, et audience."""
    from .budget_report import is_client_of
    vis = list(visible_projects(user).select_related("client"))
    if user.is_app_admin:
        return list(Project.objects.filter(tenant=user.tenant).select_related("client")), "admin"
    role = user.role_id or ""
    if user.role and not user.role.internal:
        return [p for p in vis if is_client_of(user, p)], "client"
    if role == "commercial":
        return [p for p in vis if p.client.sales.filter(pk=user.pk).exists()] or vis, "commercial"
    mine = [p for p in vis if p.pm_id == user.id]
    if mine:
        return mine, "cdp"
    raise ApiError("FORBIDDEN_PERMISSION", "La consommation IA est réservée au client, au chef de projet, au commercial et à l'administrateur.",
                   status.HTTP_403_FORBIDDEN)


def report(user, project_id=None, months=6, invoice_month=None):
    projects, audience = _scope(user)
    if project_id:
        projects = [p for p in projects if p.id == project_id]
        if not projects:
            raise ApiError("NOT_FOUND", "Projet introuvable dans votre périmètre.", status.HTTP_404_NOT_FOUND)
    price = pricing(user.tenant)
    months_l = _months(max(1, min(24, months)))
    inv_m = invoice_month or months_l[-1]
    events = collect(projects)
    clients = {p.client_id for p in projects}
    # Quota : propre au client (si un seul client dans le périmètre et quota défini), sinon quota de l'entreprise.
    client_q = price["clients"].get(next(iter(clients))) if len(clients) == 1 else None
    # En vue projet, le quota reste celui du périmètre client/entreprise : on calcule donc l'usage du périmètre complet.
    scope_events = collect(_scope(user)[0]) if project_id else events
    if audience == "admin" and not project_id and len(clients) != 1:
        client_q = None
    rows = []
    for code, meta in ROSTER.items():
        q = int((client_q or {}).get(code, price["assistants"][code]["quota"]))
        unit = Decimal(price["assistants"][code]["price"])
        by_month = {}
        for m in months_l:
            used = sum(e["units"] for e in events if e["assistant"] == code and e["month"] == m)
            scope_used = sum(e["units"] for e in scope_events if e["assistant"] == code and e["month"] == m)
            by_month[m] = {"used": used, "scopeUsed": scope_used, "quota": q, "remaining": max(0, q - scope_used),
                           "over": max(0, scope_used - q), "cost": str((unit * used).quantize(Decimal("0.01")))}
        total = sum(v["used"] for v in by_month.values())
        sources = defaultdict(int)
        for e in events:
            if e["assistant"] == code and e["month"] in by_month:
                sources[e["source"]] += e["units"]
        rows.append({"code": code, "name": meta["name"], "role": meta["role"], "avatar": meta["avatar"], "color": meta["color"],
                     "quota": q, "price": str(unit), "byMonth": by_month, "total": total,
                     "cost": str((unit * total).quantize(Decimal("0.01"))), "sources": dict(sources)})
    by_project = defaultdict(int)
    for e in events:
        if e["month"] in months_l:
            by_project[e["project"]] += e["units"]
    names = {p.id: p.name for p in projects}
    lines = []
    for r in rows:
        used = r["byMonth"].get(inv_m, {}).get("used") if inv_m in r["byMonth"] else \
            sum(e["units"] for e in events if e["assistant"] == r["code"] and e["month"] == inv_m)
        if used:
            amount = (Decimal(r["price"]) * used).quantize(Decimal("0.01"))
            lines.append({"assistant": r["code"], "name": r["name"], "units": used, "price": r["price"], "amount": str(amount)})
    ht = sum((Decimal(x["amount"]) for x in lines), Decimal("0"))
    vat = (ht * Decimal(str(price["vatRate"])) / 100).quantize(Decimal("0.01"))
    return {
        "audience": audience, "months": months_l, "assistants": rows,
        "byProject": sorted([{"id": k, "name": names.get(k, k), "units": v} for k, v in by_project.items()], key=lambda x: -x["units"]),
        "sources": SOURCES, "docWeight": DOC_WEIGHT,
        "invoice": {"month": inv_m, "lines": lines, "ht": str(ht), "vatRate": price["vatRate"], "vat": str(vat), "ttc": str(ht + vat)},
        "projects": [{"id": p.id, "code": p.code, "name": p.name} for p in projects] if not project_id else None,
        "canConfigure": bool(user.is_app_admin), "pricing": price if user.is_app_admin else None,
        "clientQuota": bool(client_q),
    }


class AiUsageView(APIView):
    """GET ?project=&months=6&month=AAAA-MM : consommation IA du périmètre. PUT (admin) : quotas et tarifs."""

    def get(self, request):
        p = request.query_params
        months = int(p.get("months") or 6) if str(p.get("months") or "6").isdigit() else 6
        return Response(report(request.user, p.get("project") or None, months, p.get("month") or None))

    def put(self, request):
        if not request.user.is_app_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé à l'administrateur et au Pilote.", status.HTTP_403_FORBIDDEN)
        save_pricing(request.user.tenant, request.data, request.user)
        return self.get(request)


class PilotAiUsagePricingView(APIView):
    def get(self, request, tenant_id):
        from tenants.models import Tenant
        if not request.user.is_platform_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé au Pilote.", status.HTTP_403_FORBIDDEN)
        return Response(pricing(Tenant.objects.get(pk=tenant_id)))

    def put(self, request, tenant_id):
        from tenants.models import Tenant
        if not request.user.is_platform_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé au Pilote.", status.HTTP_403_FORBIDDEN)
        return Response(save_pricing(Tenant.objects.get(pk=tenant_id), request.data, request.user))


class AiUsageInvoiceView(APIView):
    """GET ?month=AAAA-MM&project= : facture de consommation IA (Word)."""

    def get(self, request):
        from clientspace import docx
        p = request.query_params
        data = report(request.user, p.get("project") or None, 12, p.get("month") or None)
        inv = data["invoice"]
        y, m = map(int, inv["month"].split("-"))
        label = date(y, m, 1).strftime("%m/%Y")
        tenant = request.user.tenant
        scope = ", ".join(x["name"] for x in (data["projects"] or [])) if data["projects"] else (p.get("project") or "")
        eur = lambda v: f"{Decimal(v):,.2f} €".replace(",", " ").replace(".", ",")
        blocks = [docx.p(f"Facture de consommation IA — {label}", "Title"),
                  docx.p(tenant.name, bold=True),
                  docx.p(f"Périmètre : {scope or 'tous les projets'} · éditée le {timezone.localdate():%d/%m/%Y} par {request.user.display_name}"),
                  docx.p(f"Unité facturée : interaction d'un assistant (réponse en appel, message en discussion, action d'orchestration ; "
                         f"un document rédigé compte pour {DOC_WEIGHT} interactions)."),
                  docx.table([["Assistant", "Interactions", "Prix unitaire HT", "Montant HT"]]
                             + [[x["name"], str(x["units"]), eur(x["price"]), eur(x["amount"])] for x in inv["lines"]]
                             + [["Total HT", str(sum(x["units"] for x in inv["lines"])), "", eur(inv["ht"])]], [4200, 1600, 1900, 1900], total=True),
                  docx.table([["", "Montant"], ["Total HT", eur(inv["ht"])], [f"TVA {inv['vatRate']:g} %", eur(inv["vat"])], ["Total TTC", eur(inv["ttc"])]],
                             [7900, 1700], total=True),
                  docx.p("État d'utilisation (interactions / quota mensuel)", "Heading1"),
                  docx.table([["Assistant", "Utilisé", "Quota", "Reste"]]
                             + [[a["name"], str(a["byMonth"].get(inv["month"], {}).get("used", 0)), str(a["quota"]),
                                 str(a["byMonth"].get(inv["month"], {}).get("remaining", a["quota"]))] for a in data["assistants"]],
                             [4200, 1800, 1800, 1800], small=True)]
        content = docx.build(f"Consommation IA {label}", blocks)
        resp = HttpResponse(content, content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        resp["Content-Disposition"] = f'attachment; filename="consommation_ia_{inv["month"]}.docx"'
        audit.record(request.user, "Assistants IA", "Facture de consommation IA", "", f"{inv['month']} {inv['ht']} € HT", tenant=tenant)
        return resp
