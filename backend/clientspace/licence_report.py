"""Espace client : consommation de licences par ressource et reporting global.

GET /client-portal/licences?client=<code>&months=3
  Ressources du client (membres de ses projets et comptes du client) : licence nominative détenue, sessions (licences
  concurrentes ou connexions) sur la période, durée, jours d'activité, dernière connexion. Global : stock du tenant
  (nominatives / concurrentes, affectées, disponibles), pic d'utilisateurs simultanés, tendance mensuelle et licences
  commandées par le client.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from licensing.models import ASSIGNED, AVAILABLE, CONCURRENT, IN_USE, NAMED, REVOKED, ConcurrentSession, License, LicenseAssignment
from projects.models import ProjectAccess

from . import billing
from .client_portal import _orders

User = get_user_model()


class LicenceReportView(APIView):
    def get(self, request):
        from .views import _clients_for, _guard
        user = request.user
        _guard(user)
        client = get_object_or_404(_clients_for(user), pk=request.query_params.get("client"))
        tenant = user.tenant
        months = max(1, min(12, int(request.query_params.get("months") or 3)))
        from projects.ai_usage import _months
        ml = _months(months)
        start = timezone.make_aware(timezone.datetime.combine(billing.bounds(ml[0])[0], timezone.datetime.min.time()))
        projects = list(client.projects.all())
        ids = set(ProjectAccess.objects.filter(project__in=projects, user__is_active=True).values_list("user_id", flat=True))
        ids |= set(User.objects.filter(tenant=tenant, client=client, is_active=True).values_list("pk", flat=True))
        people = list(User.objects.filter(pk__in=ids, tenant=tenant).select_related("role").order_by("first_name", "last_name"))
        named = {a.user_id: a for a in LicenseAssignment.objects.filter(tenant=tenant, user_id__in=ids, released_at__isnull=True)
                 .select_related("license")}
        sessions = list(ConcurrentSession.objects.filter(tenant=tenant, user_id__in=ids, started_at__gte=start).select_related("license"))
        now = timezone.now()
        per = defaultdict(lambda: {"sessions": 0, "seconds": 0, "days": set(), "concurrent": 0})
        monthly = {m: {"users": set(), "sessions": 0, "hours": 0.0, "named": 0} for m in ml}
        daily = defaultdict(set)
        for s in sessions:
            end = s.ended_at or min(s.last_seen_at, now)
            secs = max(0, (end - s.started_at).total_seconds())
            p = per[s.user_id]
            p["sessions"] += 1
            p["seconds"] += secs
            local = timezone.localtime(s.started_at)
            p["days"].add(local.date())
            if s.license_id and s.license.kind == CONCURRENT:
                p["concurrent"] += 1
            m = f"{local:%Y-%m}"
            if m in monthly:
                monthly[m]["users"].add(s.user_id)
                monthly[m]["sessions"] += 1
                monthly[m]["hours"] += secs / 3600
            daily[local.date()].add(s.user_id)
        rows = []
        for u in people:
            a = named.get(u.pk)
            p = per.get(u.pk) or {"sessions": 0, "seconds": 0, "days": set(), "concurrent": 0}
            kind = "named" if a else ("concurrent" if p["concurrent"] else ("none" if not p["sessions"] else "session"))
            rows.append({"user": u.pk, "name": u.display_name, "role": u.role.label if u.role else "", "internal": bool(u.role and u.role.internal),
                         "company": u.company, "licence": {"named": "Nominative", "concurrent": "Concurrente", "session": "Connexion", "none": "Aucune"}[kind],
                         "licenceKind": kind, "licenceNumber": a.license.number if a else "", "since": a.assigned_at if a else None,
                         "sessions": p["sessions"], "hours": round(p["seconds"] / 3600, 1), "activeDays": len(p["days"]),
                         "lastLogin": u.last_login, "inactive": not p["sessions"] and (not u.last_login or u.last_login < start)})
        for m in ml:  # licences nominatives actives à la fin de chaque mois
            _, last = billing.bounds(m)
            monthly[m]["named"] = sum(1 for a in LicenseAssignment.objects.filter(tenant=tenant, user_id__in=ids, assigned_at__date__lte=last)
                                      if not a.released_at or a.released_at.date() > last)
        stock = defaultdict(lambda: defaultdict(int))
        for kind, st in License.objects.filter(tenant=tenant).exclude(status=REVOKED).values_list("kind", "status"):
            stock[kind][st] += 1
        def block(kind):
            s = stock.get(kind, {})
            total = sum(s.values())
            used = s.get(ASSIGNED, 0) + s.get(IN_USE, 0)
            return {"total": total, "used": used, "available": s.get(AVAILABLE, 0), "rate": round(used / total * 100, 1) if total else None}
        pids = {p.id for p in projects}
        ordered = defaultdict(lambda: Decimal("0"))
        orders = []
        for o in _orders(tenant):
            if o.get("kind") == "licence" and set(o.get("projects") or []) & pids:
                ordered[o.get("status", "pending")] += Decimal(str(o.get("quantity") or 0))
                orders.append({"id": o["id"], "item": o.get("item") or "Licence", "quantity": o.get("quantity"), "status": o.get("status"),
                               "at": o.get("at"), "projects": o.get("projectNames") or []})
        peak = max((len(v) for v in daily.values()), default=0)
        peak_day = max(daily.items(), key=lambda kv: len(kv[1]))[0] if daily else None
        holders = sum(1 for r in rows if r["licenceKind"] == "named")
        return Response({
            "client": client.pk, "clientName": client.name, "months": ml, "monthLabels": {m: billing.label(m) for m in ml},
            "rows": rows,
            "global": {"resources": len(rows), "namedHolders": holders, "activeResources": sum(1 for r in rows if r["sessions"]),
                       "inactiveHolders": sum(1 for r in rows if r["licenceKind"] == "named" and r["inactive"]),
                       "sessions": sum(r["sessions"] for r in rows), "hours": round(sum(r["hours"] for r in rows), 1),
                       "peakUsers": peak, "peakDay": peak_day,
                       "tenantNamed": block(NAMED), "tenantConcurrent": block(CONCURRENT),
                       "ordered": {k: str(v) for k, v in ordered.items()}, "orders": list(reversed(orders))[:20]},
            "monthly": [{"month": m, "label": billing.label(m), "activeUsers": len(v["users"]), "sessions": v["sessions"],
                         "hours": round(v["hours"], 1), "named": v["named"]} for m, v in monthly.items()],
        })
