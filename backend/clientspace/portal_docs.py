"""Espace client : rapport de consommation budgétaire mensuelle et bibliothèque documentaire.

GET /client-portal/budget-report?projects=A,B&months=6&status=all&as=json|docx|csv&save=1
    Consommation par mois de toutes les ressources affectées aux projets (jours × TJM) et des assistants intelligents
    (unités × prix), budget validé, cumul et reste. `save=1` (format docx) l'archive dans la documentation du client.
GET /client-portal/orders/<id>/document   bon de commande (.docx)
GET /client-space/library                 documentation classée : CRA, factures, commandes, rapports budgétaires, contrats
"""
import csv
import io
import secrets
from collections import defaultdict
from decimal import Decimal
from urllib.parse import quote

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.errors import ApiError
from configuration import audit
from planning.services import hours_per_day
from projects.models import ProjectAccess, TimeEntry

from . import billing, docx
from .client_portal import _by_status, _orders, _projects
from .doc_info import doc_code
from .models import ClientDocument, SupportContract

Q2 = Decimal("0.01")
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _months(n):
    from projects.ai_usage import _months as m
    return m(max(1, min(24, n)))


def build(user, projects, months_n):
    from projects import ai_usage
    from projects.ai_orchestrator import ROSTER
    months = _months(months_n)
    first, _ = billing.bounds(months[0])
    _, last = billing.bounds(months[-1])
    hpd = Decimal(str(hours_per_day(user.tenant) or 8))
    res = {}
    entries = (TimeEntry.objects.filter(project__in=projects, work_date__range=(first, last)).exclude(approval_status__in=["draft", "rejected"])
               .select_related("person", "person__role", "project"))
    rate_cache = {}
    for e in entries:
        m = f"{e.work_date:%Y-%m}"
        key = (e.person_id, e.project_id)
        if key not in rate_cache:
            rate_cache[key] = billing.rate_for(e.person, e.project)
        rate = rate_cache[key]
        r = res.setdefault(e.person_id, {"person": e.person_id, "name": e.person.display_name, "role": e.person.role.label if e.person.role else "",
                                         "external": e.person.external, "rates": set(), "byMonth": defaultdict(lambda: {"days": Decimal("0"), "amount": Decimal("0")}),
                                         "noRate": False})
        days = e.hours / hpd
        r["byMonth"][m]["days"] += days
        if rate is None:
            r["noRate"] = True
        else:
            r["rates"].add(rate)
            r["byMonth"][m]["amount"] += days * rate
    # membres affectés sans saisie sur la période
    for acc in ProjectAccess.objects.filter(project__in=projects, user__is_active=True, user__role__internal=True).select_related("user", "user__role"):
        res.setdefault(acc.user_id, {"person": acc.user_id, "name": acc.user.display_name, "role": acc.user.role.label if acc.user.role else "",
                                     "external": acc.user.external, "rates": set(), "byMonth": defaultdict(lambda: {"days": Decimal("0"), "amount": Decimal("0")}),
                                     "noRate": False})
    resources = []
    for r in res.values():
        bm = {m: {"days": str(r["byMonth"][m]["days"].quantize(Q2)), "amount": str(r["byMonth"][m]["amount"].quantize(Q2))} for m in months}
        days = sum((r["byMonth"][m]["days"] for m in months), Decimal("0"))
        amount = sum((r["byMonth"][m]["amount"] for m in months), Decimal("0"))
        rates = sorted(r["rates"])
        resources.append({"person": r["person"], "name": r["name"], "role": r["role"], "external": r["external"],
                          "rate": str(rates[0]) if len(rates) == 1 else ("variable" if rates else None), "noRate": r["noRate"],
                          "byMonth": bm, "days": str(days.quantize(Q2)), "amount": str(amount.quantize(Q2))})
    resources.sort(key=lambda x: (-Decimal(x["amount"]), x["name"]))
    price = ai_usage.pricing(user.tenant)["assistants"]
    events = ai_usage.collect(projects)
    ai = []
    for code, meta in ROSTER.items():
        unit = Decimal(str(price.get(code, {}).get("price", 0) or 0))
        bm = {}
        for m in months:
            u = sum(ev["units"] for ev in events if ev["assistant"] == code and ev["month"] == m)
            bm[m] = {"units": u, "cost": str((unit * u).quantize(Q2))}
        units = sum(v["units"] for v in bm.values())
        if units:
            ai.append({"code": code, "name": f"{meta['name']} — {meta['role']}", "price": str(unit), "byMonth": bm, "units": units,
                       "cost": str((unit * units).quantize(Q2))})
    totals, cum = {}, Decimal("0")
    for m in months:
        rs = sum((Decimal(r["byMonth"][m]["amount"]) for r in resources), Decimal("0"))
        a = sum((Decimal(x["byMonth"][m]["cost"]) for x in ai), Decimal("0"))
        cum += rs + a
        totals[m] = {"resources": str(rs.quantize(Q2)), "ai": str(a.quantize(Q2)), "total": str((rs + a).quantize(Q2)), "cumulative": str(cum.quantize(Q2)),
                     "days": str(sum((Decimal(r["byMonth"][m]["days"]) for r in resources), Decimal("0")).quantize(Q2))}
    budget = Decimal("0")
    has_budget = False
    for p in projects:
        fin = getattr(p, "finance", None)
        if fin is not None and fin.approved is not None:
            budget += fin.approved
            has_budget = True
    res_total = sum((Decimal(r["amount"]) for r in resources), Decimal("0"))
    ai_total = sum((Decimal(x["cost"]) for x in ai), Decimal("0"))
    return {"months": months, "monthLabels": {m: billing.label(m) for m in months},
            "projects": [{"code": p.code, "name": p.name, "client": p.client.name, "status": p.status} for p in projects],
            "resources": resources, "ai": ai, "totals": totals,
            "summary": {"resources": str(res_total.quantize(Q2)), "ai": str(ai_total.quantize(Q2)), "total": str((res_total + ai_total).quantize(Q2)),
                        "budget": str(budget.quantize(Q2)) if has_budget else None,
                        "remaining": str((budget - res_total - ai_total).quantize(Q2)) if has_budget else None,
                        "rate": round(float((res_total + ai_total) / budget * 100), 1) if has_budget and budget else None},
            "generatedAt": timezone.now(), "generatedBy": user.display_name}


def _strip_money(data):
    """Compte client sans autorisation : jours et unités seulement, ni TJM ni montants."""
    for r in data["resources"]:
        r["rate"] = "masqué" if r["rate"] else None
        r["amount"] = None
        for v in r["byMonth"].values():
            v["amount"] = None
    for x in data["ai"]:
        x["price"], x["cost"] = None, None
        for v in x["byMonth"].values():
            v["cost"] = None
    for v in data["totals"].values():
        v.update(resources=None, ai=None, total=None, cumulative=None)
    data["summary"] = {k: None for k in data["summary"]}
    data["amountsHidden"] = True


def _docx(data, tenant):
    months = data["months"]
    lab = lambda m: data["monthLabels"][m][:4] + data["monthLabels"][m][-2:] if False else data["monthLabels"][m]
    e = lambda v: "—" if v in (None, "", "masqué") else billing.eur(v)
    w_first = 2600
    w = max(700, int((15000 - w_first - 1300) / max(1, len(months))))
    blocks = [docx.p("Rapport de consommation budgétaire", "Title"),
              docx.p(f"{tenant.name} · Projets : " + ", ".join(f"{p['code']} — {p['name']}" for p in data["projects"]), bold=True),
              docx.p(f"Période : {lab(months[0])} → {lab(months[-1])} · Généré le {timezone.localtime(data['generatedAt']):%d/%m/%Y %H:%M} par {data['generatedBy']}",
                     color="64748B", size=18),
              docx.p("Synthèse", "Heading1")]
    s = data["summary"]
    rows = [["Indicateur", "Montant"], ["Ressources (jours × TJM)", e(s["resources"])], ["Assistants intelligents", e(s["ai"])], ["Total consommé", e(s["total"])]]
    if data.get("amountsHidden"):
        rows = [["Indicateur", "Valeur"], ["Jours consommés", billing.num(sum(Decimal(r["days"]) for r in data["resources"]))],
                ["Unités d'assistants IA", str(sum(x["units"] for x in data["ai"]))]]
    elif s["budget"] is not None:
        rows += [["Budget validé", e(s["budget"])], ["Reste", e(s["remaining"])], ["Taux de consommation", f"{s['rate']} %"]]
    blocks.append(docx.table(rows, [9000, 3000], total=False))
    blocks.append(docx.p("Consommation mensuelle", "Heading1"))
    blocks.append(docx.table([["Mois"] + [lab(m) for m in months] + ["Total"],
                              ["Jours"] + [billing.num(data["totals"][m]["days"]) for m in months] + [billing.num(sum(Decimal(data["totals"][m]["days"]) for m in months))],
                              ["Ressources"] + [e(data["totals"][m]["resources"]) for m in months] + [e(s["resources"])],
                              ["Assistants IA"] + [e(data["totals"][m]["ai"]) for m in months] + [e(s["ai"])],
                              ["Total"] + [e(data["totals"][m]["total"]) for m in months] + [e(s["total"])],
                              ["Cumul"] + [e(data["totals"][m]["cumulative"]) for m in months] + [""]],
                             [w_first] + [w] * len(months) + [1300], small=True))
    blocks.append(docx.p("Ressources affectées (montant HT par mois)", "Heading1"))
    blocks.append(docx.table([["Ressource", "TJM"] + [lab(m) for m in months] + ["Jours", "Total"]]
                             + [[f"{r['name']} ({r['role']})", (e(r["rate"]) if r["rate"] not in (None, "variable", "masqué") else (r["rate"] or "interne"))]
                                + [(e(r["byMonth"][m]["amount"]) if r["byMonth"][m]["amount"] is not None else f"{billing.num(r['byMonth'][m]['days'])} j") if Decimal(r["byMonth"][m]["days"]) else "—" for m in months]
                                + [billing.num(r["days"]), e(r["amount"])] for r in data["resources"]],
                             [2200, 900] + [max(600, w - 150)] * len(months) + [700, 1100], small=True))
    blocks.append(docx.p("Assistants intelligents (coût HT par mois)", "Heading1"))
    if data["ai"]:
        blocks.append(docx.table([["Assistant", "Prix / unité"] + [lab(m) for m in months] + ["Unités", "Total"]]
                                 + [[x["name"], e(x["price"])] + [f"{x['byMonth'][m]['units']} u · {e(x['byMonth'][m]['cost'])}" if x["byMonth"][m]["units"] else "—" for m in months]
                                    + [str(x["units"]), e(x["cost"])] for x in data["ai"]],
                                 [2200, 900] + [max(600, w - 150)] * len(months) + [700, 1100], small=True))
    else:
        blocks.append(docx.p("Aucune utilisation des assistants intelligents sur la période.", color="64748B"))
    if any(r["noRate"] for r in data["resources"]):
        blocks.append(docx.p("Ressources sans TJM (internes) : temps compté en jours, non valorisé.", size=16, color="64748B"))
    return docx.build("Rapport de consommation budgétaire", blocks, landscape=True)


def _c(v):
    return str(v or "").replace(".", ",")


def _file(name, content, mime):
    r = HttpResponse(content, content_type=mime)
    r["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(name)}"
    return r


class BudgetReportView(APIView):
    def get(self, request):
        user = request.user
        ids = [x for x in str(request.query_params.get("projects") or "").split(",") if x and x != "all"]
        projects = _by_status(_projects(user, ids or None), request.query_params.get("status") or "all")
        if not projects:
            raise ApiError("VALIDATION_ERROR", "Aucun projet dans la sélection.")
        data = build(user, projects, int(request.query_params.get("months") or 6))
        from .client_rates import hide_amounts
        if hide_amounts(user, {p.client_id for p in projects}):
            _strip_money(data)
        fmt = request.query_params.get("as") or "json"
        stamp = timezone.localdate().strftime("%Y-%m-%d")
        if fmt == "csv":
            buf = io.StringIO()
            w = csv.writer(buf, delimiter=";")
            w.writerow(["Type", "Ligne"] + [data["monthLabels"][m] for m in data["months"]] + ["Total"])
            for r in data["resources"]:
                w.writerow(["Ressource", r["name"]] + [_c(r["byMonth"][m]["amount"] if r["byMonth"][m]["amount"] is not None else r["byMonth"][m]["days"] + " j") for m in data["months"]] + [_c(r["amount"] if r["amount"] is not None else r["days"] + " j")])
            for x in data["ai"]:
                w.writerow(["Assistant IA", x["name"]] + [_c(x["byMonth"][m]["cost"] if x["byMonth"][m]["cost"] is not None else f"{x['byMonth'][m]['units']} u") for m in data["months"]] + [_c(x["cost"] if x["cost"] is not None else f"{x['units']} u")])
            w.writerow(["Total", ""] + [_c(data["totals"][m]["total"] or data["totals"][m]["days"] + " j") for m in data["months"]] + [_c(data["summary"]["total"] or "")])
            return _file(f"rapport-budgetaire-{stamp}.csv", "﻿" + buf.getvalue(), "text/csv; charset=utf-8")
        if fmt == "docx":
            content = _docx(data, user.tenant)
            name = f"rapport-budgetaire-{'-'.join(p.code for p in projects[:3])}-{stamp}.docx"
            clients = {p.client_id for p in projects}
            if request.query_params.get("save") and len(clients) == 1:
                client = projects[0].client
                doc = ClientDocument.objects.create(id=f"CD{secrets.token_hex(6).upper()}", tenant=user.tenant, client=client, kind="other",
                                                    period=data["months"][-1], name=name, content=content, size_bytes=len(content),
                                                    amount_ht=Decimal(data["summary"]["total"]),
                                                    meta={"category": "budget", "projects": [p.code for p in projects], "generatedBy": user.display_name,
                                                          "months": data["months"]})
                readers = set(billing.client_users(user.tenant, client, projects)) | {user}
                readers |= {p.pm for p in projects if p.pm_id}
                doc.readers.set([u for u in readers if u])
                audit.record(user, f"Client {client.name}", "Rapport budgétaire archivé", "", name, tenant=user.tenant)
            return _file(name, content, DOCX)
        return Response(data)


ORDER_STATUS = {"pending": "En attente", "accepted": "Acceptée", "rejected": "Refusée", "delivered": "Livrée"}


class OrderDocumentView(APIView):
    def get(self, request, order_id):
        projects = _projects(request.user)
        ids = {p.id for p in projects}
        o = next((x for x in _orders(request.user.tenant) if x["id"] == order_id and (set(x.get("projects") or []) & ids or request.user.is_app_admin)), None)
        if o is None:
            raise ApiError("NOT_FOUND", "Commande introuvable.", status.HTTP_404_NOT_FOUND)
        t = request.user.tenant
        blocks = [docx.p(f"Bon de commande n° {o['id'].upper()}", "Title"),
                  docx.p(f"{t.name} · Date : {o['at'][8:10]}/{o['at'][5:7]}/{o['at'][:4]} · Statut : {ORDER_STATUS.get(o.get('status'), o.get('status'))}", bold=True),
                  docx.table([["Rubrique", "Détail"], ["Type", o.get("kindLabel", "")], ["Article", o.get("item") or "—"],
                              ["Quantité", f"{o.get('quantity')} {o.get('unit', '')}".strip()], ["Projets", ", ".join(o.get("projectNames") or [])],
                              ["Commandé par", o.get("by", "")], ["Note", o.get("note") or "—"]], [3000, 6600]),
                  docx.p("Historique", "Heading1"),
                  docx.table([["Date", "Par", "Décision", "Commentaire"]] + [[str(h.get("at", ""))[:10], h.get("by", ""), ORDER_STATUS.get(h.get("to") or h.get("status"), h.get("to") or ""),
                                                                            h.get("comment", "")] for h in (o.get("history") or [])] or [["—", "", "", ""]],
                             [1800, 2600, 1800, 3400])]
        content = docx.build(f"Bon de commande {o['id']}", blocks)
        if request.query_params.get("preview"):
            from .preview import preview_response
            return preview_response(content, DOCX, f"bon-de-commande-{o['id']}.docx")
        return _file(f"bon-de-commande-{o['id']}.docx", content, DOCX)


class LibraryView(APIView):
    """Documentation classée de l'Espace client."""

    def get(self, request):
        from .views import _clients_for, _guard, _readable
        user = request.user
        _guard(user)
        items = []
        from .client_rates import hide_amounts
        for d in _readable(user).order_by("-created_at")[:1000]:
            cat = d.kind if d.kind in ("cra", "invoice") else (d.meta.get("category") or "other")
            items.append({"id": d.pk, "category": cat, "title": d.name, "client": d.client.name, "period": d.period,
                          "periodLabel": billing.label(d.period) if d.period else "", "person": d.person.display_name if d.person_id else "",
                          "number": d.number, "version": d.version,
                          "amount": None if d.kind == "cra" and hide_amounts(user, [d.client_id]) else d.amount_ht, "date": d.created_at,
                          "projects": d.meta.get("projects", []), "note": d.meta.get("noInvoice", ""), "craId": d.meta.get("cra") if d.kind == "invoice" else None,
                          "code": doc_code(d), "ref": d.pk,
                          "download": f"/client-space/documents/{d.pk}"})
        try:
            projects = _projects(user)
            ids = {p.id for p in projects}
            for o in _orders(user.tenant):
                if set(o.get("projects") or []) & ids or user.is_app_admin:
                    items.append({"id": o["id"], "category": "order", "title": f"Bon de commande — {o.get('kindLabel', '')} {o.get('item') or ''}".strip(),
                                  "client": "", "period": o["at"][:7], "periodLabel": billing.label(o["at"][:7]), "person": o.get("by", ""),
                                  "number": o["id"].upper(), "status": ORDER_STATUS.get(o.get("status"), o.get("status")), "date": o["at"],
                                  "projects": o.get("projectNames") or [], "download": f"/client-portal/orders/{o['id']}/document",
                                  "code": f"CMD-{o['id'].upper()}", "ref": f"order:{o['id']}"})
        except ApiError:
            pass
        for c in SupportContract.objects.filter(client__in=_clients_for(user), enabled=True).select_related("client"):
            items.append({"id": f"SC{c.pk}", "category": "contract", "title": f"Contrat de support {', '.join(c.levels or [])} — {c.client.name}",
                          "client": c.client.name, "period": f"{c.starts_on:%Y-%m}" if c.starts_on else "", "periodLabel": "",
                          "status": f"du {c.starts_on:%d/%m/%Y} au {c.ends_on:%d/%m/%Y}" if c.starts_on and c.ends_on else "", "date": c.updated_at,
                          "projects": [], "download": None, "code": f"CTR-{c.pk:06d}", "ref": f"contract:{c.pk}"})
        # Rattachement aux projets : chaque document est classé sous ses projets (le contrat de support couvre tous les projets du client).
        from projects.models import Project
        allp = {p.id: p for p in Project.objects.filter(tenant=user.tenant).select_related("client")}
        by_name = {p.name: p.id for p in allp.values()}
        visible = None
        if not user.is_app_admin:
            from projects.access import visible_projects
            visible = set(visible_projects(user).values_list("id", flat=True))
        for it in items:
            refs = []
            if it["category"] == "contract":
                refs = [p.id for p in allp.values() if p.client.name == it["client"]]
            elif it["category"] == "order":
                refs = [by_name.get(n, n) for n in it["projects"]]
            else:
                refs = list(it["projects"])
            refs = [r for r in refs if r in allp and (visible is None or r in visible)] or ["_general"]
            it["projectRefs"] = refs
        projects_out = sorted({r for it in items for r in it["projectRefs"] if r != "_general"})
        cats = [("cra", "Comptes rendus d'activité"), ("invoice", "Factures"), ("order", "Commandes"), ("budget", "Rapports budgétaires"),
                ("contract", "Contrats"), ("other", "Autres documents")]
        counts = defaultdict(int)
        for it in items:
            counts[it["category"]] += 1
        return Response({"items": items, "categories": [{"code": c, "label": l, "count": counts.get(c, 0)} for c, l in cats],
                         "projects": [{"code": c, "name": allp[c].name, "client": allp[c].client.name, "status": allp[c].status,
                                       "count": sum(1 for it in items if c in it["projectRefs"])} for c in projects_out]
                                     + ([{"code": "_general", "name": "Documents généraux", "client": "", "status": "",
                                          "count": sum(1 for it in items if it["projectRefs"] == ["_general"])}]
                                        if any(it["projectRefs"] == ["_general"] for it in items) else [])})
