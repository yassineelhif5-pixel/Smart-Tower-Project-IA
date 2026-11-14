"""Portail client : tout ce dont le client a besoin sur ses projets, au même endroit.

- Saisies de temps : toutes les saisies envoyées (hors brouillons) des projets du client, filtres projet /
  personne / mois, totaux par utilisateur (heures, jours, montant au TJM facturé) et par état.
- Facturation : par utilisateur et par mois (jours, montant HT, état de validation, facture et CRA générés).
- Commandes : licences, modules, assistants IA, autres ressources (profil, jours) pour un ou plusieurs projets ;
  traitées par l'administrateur, le chef de projet ou le commercial (acceptée, refusée, livrée).
- Récap par e-mail : synthèse budget / temps / tâches des projets choisis, envoyée aux destinataires indiqués.
Le client valide les temps par personne et par mois (onglet « Temps à valider ») : la facture de la personne
est générée dès que son mois est entièrement validé.
"""
import secrets
from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.errors import ApiError
from configuration import audit
from configuration.models import AppSetting
from planning.services import hours_per_day
from projects.access import in_active_tenant, visible_projects
from projects.models import Action, Project, TimeEntry

from . import billing
from .models import ClientDocument

ORDERS_KEY = "client_orders"
KINDS = {"licence": "Licences utilisateurs", "module": "Module", "assistant": "Assistant IA", "resource": "Ressource / profil"}
MODULE_CHOICES = [("cra", "CRA & facturation"), ("support", "Support N1/N2/N3"), ("ai_calls", "Appels IA"), ("budget", "Budget & reporting"),
                  ("planning", "Planning"), ("documents", "Documents & GED"), ("collaboration", "Collaboration / Teams"), ("other", "Autre")]
Q2 = Decimal("0.01")


def _staff(user):
    return bool(user.is_app_admin or (user.role and user.role.internal and user.role_id in ("cdp", "commercial", "direction", "manager")))


STATUS_LABEL = {"active": "En cours", "paused": "En pause", "closed": "Clôturé"}


def _by_status(projects, wanted):
    """wanted : all | active (en cours) | inactive (en pause ou clôturé)."""
    if wanted == "active":
        return [p for p in projects if p.status == "active"]
    if wanted == "inactive":
        return [p for p in projects if p.status != "active"]
    return projects


def _projects(user, ids=None):
    if not in_active_tenant(user):
        raise ApiError("FORBIDDEN_PERMISSION", "Accès réservé aux utilisateurs d'une entreprise.", status.HTTP_403_FORBIDDEN)
    if not (user.role and (not user.role.internal or _staff(user))):
        raise ApiError("FORBIDDEN_PERMISSION", "Portail réservé au client, au chef de projet, au commercial et à l'administrateur.",
                       status.HTTP_403_FORBIDDEN)
    qs = visible_projects(user).select_related("client")
    if ids:
        qs = qs.filter(pk__in=ids)
    return list(qs.order_by("name"))


def _money(v):
    return (v or Decimal("0")).quantize(Q2)


class PortalTimesheetsView(APIView):
    """GET ?project=&person=&month=AAAA-MM : saisies + totaux par utilisateur et par projet."""

    def get(self, request):
        p = request.query_params
        projects = _by_status(_projects(request.user, [p["project"]] if p.get("project") else None), p.get("projectStatus") or "all")
        hpd = Decimal(str(hours_per_day(request.user.tenant) or 8))
        qs = TimeEntry.objects.filter(project__in=projects).exclude(approval_status="draft").select_related("person", "project", "action", "approved_by")
        if p.get("person"):
            qs = qs.filter(person_id=p["person"])
        if p.get("month"):
            first, last = billing.bounds(p["month"])
            qs = qs.filter(work_date__range=(first, last))
        rates = {}
        by_person = defaultdict(lambda: {"hours": Decimal("0"), "amount": Decimal("0"), "status": defaultdict(lambda: Decimal("0")), "projects": set()})
        by_project = defaultdict(lambda: {"hours": Decimal("0"), "amount": Decimal("0")})
        rows = []
        for e in qs.order_by("-work_date", "person__first_name"):
            key = (e.person_id, e.project_id)
            if key not in rates:
                rates[key] = billing.rate_for(e.person, e.project)
            rate = rates[key]
            amount = (e.hours / hpd * rate) if rate is not None and e.approval_status != "rejected" else Decimal("0")
            bp = by_person[e.person_id]
            bp.update(name=e.person.display_name, role=e.person.role.label if e.person.role else "")
            if e.approval_status != "rejected":
                bp["hours"] += e.hours
                bp["amount"] += amount
                by_project[e.project_id]["hours"] += e.hours
                by_project[e.project_id]["amount"] += amount
                by_project[e.project_id]["name"] = e.project.name
            bp["status"][e.approval_status] += e.hours
            bp["projects"].add(e.project.name)
            if len(rows) < 1000:
                rows.append({"id": e.id, "date": e.work_date, "person": e.person_id, "personName": e.person.display_name,
                             "project": e.project_id, "projectName": e.project.name, "task": e.action.title if e.action_id else "",
                             "line": e.line, "hours": e.hours, "days": (e.hours / hpd).quantize(Q2), "status": e.approval_status,
                             "approvedBy": e.approved_by.display_name if e.approved_by_id else None, "amount": _money(amount)})
        people = sorted([{"id": k, "name": v["name"], "role": v["role"], "hours": v["hours"], "days": (v["hours"] / hpd).quantize(Q2),
                          "amount": _money(v["amount"]), "status": {s: (h / hpd).quantize(Q2) for s, h in v["status"].items()},
                          "projects": sorted(v["projects"])} for k, v in by_person.items()], key=lambda x: -x["days"])
        return Response({
            "projects": [{"id": pr.id, "code": pr.code, "name": pr.name, "client": pr.client.name, "status": pr.status,
                          "statusLabel": STATUS_LABEL.get(pr.status, pr.status)} for pr in _projects(request.user)],
            "selectedProjects": len(projects),
            "people": people,
            "byProject": [{"id": k, "name": v.get("name", k), "days": (v["hours"] / hpd).quantize(Q2), "amount": _money(v["amount"])} for k, v in by_project.items()],
            "totals": {"days": sum((x["days"] for x in people), Decimal("0")), "amount": sum((x["amount"] for x in people), Decimal("0"))},
            "rows": rows, "hoursPerDay": hpd,
            "isClient": bool(request.user.role and not request.user.role.internal),
        })


class PortalBillingView(APIView):
    """GET ?months=6 : facturation par utilisateur et par mois (montant au TJM, état, facture et CRA)."""

    def get(self, request):
        projects = _by_status(_projects(request.user), request.query_params.get("projectStatus") or "all")
        months = max(1, min(24, int(request.query_params.get("months") or 6)))
        hpd = Decimal(str(hours_per_day(request.user.tenant) or 8))
        today = timezone.localdate()
        y, m = today.year, today.month - months + 1
        while m <= 0:
            y, m = y - 1, m + 12
        start = today.replace(year=y, month=m, day=1)
        cells = defaultdict(lambda: {"hours": Decimal("0"), "amount": Decimal("0"), "st": set()})
        names = {}
        rates = {}
        for e in TimeEntry.objects.filter(project__in=projects, work_date__gte=start).exclude(approval_status__in=("draft", "rejected")).select_related("person", "project"):
            key = (e.person_id, e.project_id)
            if key not in rates:
                rates[key] = billing.rate_for(e.person, e.project)
            c = cells[(e.person_id, f"{e.work_date:%Y-%m}")]
            c["hours"] += e.hours
            if rates[key] is not None:
                c["amount"] += e.hours / hpd * rates[key]
            c["st"].add(e.approval_status)
            names[e.person_id] = e.person.display_name
        clients = {pr.client_id for pr in projects}
        docs = defaultdict(dict)
        for d in ClientDocument.objects.filter(tenant=request.user.tenant, client_id__in=clients, kind__in=("cra", "invoice"), period__gte=f"{start:%Y-%m}"):
            docs[(d.person_id, d.period)][d.kind] = {"id": d.id, "name": d.name, "number": d.number, "ht": d.amount_ht, "ttc": d.amount_ttc, "version": d.version}
        out = []
        for (pid, period), c in sorted(cells.items(), key=lambda kv: (kv[0][1], names.get(kv[0][0], "")), reverse=True):
            st = "approved" if c["st"] == {"approved"} else "client" if "client" in c["st"] else "pending"
            out.append({"person": pid, "personName": names.get(pid, ""), "period": period, "periodLabel": billing.label(period),
                        "days": (c["hours"] / hpd).quantize(Q2), "amount": _money(c["amount"]), "state": st,
                        "invoice": docs[(pid, period)].get("invoice"), "cra": docs[(pid, period)].get("cra")})
        months_list = sorted({x["period"] for x in out}, reverse=True)
        return Response({"rows": out, "months": months_list,
                         "totals": {m_: _money(sum((x["amount"] for x in out if x["period"] == m_), Decimal("0"))) for m_ in months_list}})


# --------------------------------------------------------------------------- commandes du client
def _orders(tenant):
    row = AppSetting.objects.filter(tenant=tenant, key=ORDERS_KEY).first()
    return list(row.value) if row and isinstance(row.value, list) else []


def _save_orders(tenant, items):
    AppSetting.objects.update_or_create(tenant=tenant, key=ORDERS_KEY, defaults={"value": items})


def _notify_staff(tenant, projects, title, body):
    from django.contrib.auth import get_user_model
    from projects.timesheet_reminders import _send
    ids = {p.pm_id for p in projects if p.pm_id}
    for p in projects:
        ids |= set(p.client.sales.values_list("pk", flat=True))
    ids |= set(get_user_model().objects.filter(tenant=tenant, role_id="admin", is_active=True).values_list("pk", flat=True))
    for u in get_user_model().objects.filter(pk__in=ids, is_active=True):
        _send(u, title, body)


class PortalOrdersView(APIView):
    """GET : commandes visibles. POST {kind, projects[], quantity, item, note} : nouvelle commande du client."""

    def get(self, request):
        projects = _projects(request.user)
        ids = {p.id for p in projects}
        items = [o for o in _orders(request.user.tenant) if set(o.get("projects") or []) & ids or request.user.is_app_admin]
        from projects.ai_orchestrator import ROSTER
        return Response({"orders": list(reversed(items))[:100], "kinds": [{"code": k, "label": v} for k, v in KINDS.items()],
                         "modules": [{"code": c, "label": l} for c, l in MODULE_CHOICES],
                         "assistants": [{"code": c, "label": f"{a['name']} — {a['role']}"} for c, a in ROSTER.items()],
                         "projects": [{"id": p.id, "name": p.name} for p in projects],
                         "canDecide": _staff(request.user), "isClient": bool(request.user.role and not request.user.role.internal)})

    def post(self, request):
        user = request.user
        d = request.data
        if d.get("kind") not in KINDS:
            raise ApiError("VALIDATION_ERROR", "Type de commande inconnu.")
        projects = _projects(user, d.get("projects") or None) if d.get("projects") else []
        if not projects:
            raise ApiError("VALIDATION_ERROR", "Choisissez au moins un projet.")
        try:
            qty = max(Decimal("0.5"), Decimal(str(d.get("quantity") or 1)))
        except Exception:
            raise ApiError("VALIDATION_ERROR", "Quantité invalide.")
        item = str(d.get("item") or "").strip()[:120]
        if d["kind"] in ("module", "assistant", "resource") and not item:
            raise ApiError("VALIDATION_ERROR", "Précisez le module, l'assistant ou le profil commandé.")
        order = {"id": secrets.token_hex(4), "kind": d["kind"], "kindLabel": KINDS[d["kind"]], "item": item, "quantity": str(qty),
                 "unit": {"licence": "licence(s)", "module": "", "assistant": "mois", "resource": "jour(s)"}[d["kind"]],
                 "projects": [p.id for p in projects], "projectNames": [p.name for p in projects],
                 "note": str(d.get("note") or "")[:500], "by": user.display_name, "byId": user.id,
                 "at": timezone.now().isoformat(), "status": "pending", "history": []}
        with transaction.atomic():
            _save_orders(user.tenant, _orders(user.tenant) + [order])
        audit.record(user, "Commande client", f"Commande : {order['kindLabel']}", "", f"{item} × {qty} · {', '.join(order['projectNames'])}")
        _notify_staff(user.tenant, projects, f"Nouvelle commande client : {order['kindLabel']}",
                      f"{user.display_name} commande {item or order['kindLabel']} × {qty} {order['unit']} pour {', '.join(order['projectNames'])}."
                      + (f" Note : {order['note']}" if order["note"] else "") + " À traiter dans Espace client → Commandes.")
        return self.get(request)


class PortalOrderDecisionView(APIView):
    """POST {status: accepted|rejected|delivered, comment} : traitement par l'administrateur, le CP ou le commercial."""

    def post(self, request, order_id):
        from projects.timesheet_reminders import _send
        from django.contrib.auth import get_user_model
        user = request.user
        if not _staff(user):
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé à l'administrateur, au chef de projet et au commercial.", status.HTTP_403_FORBIDDEN)
        st = request.data.get("status")
        if st not in ("accepted", "rejected", "delivered"):
            raise ApiError("VALIDATION_ERROR", "Statut inconnu.")
        comment = str(request.data.get("comment") or "")[:500]
        with transaction.atomic():
            items = _orders(user.tenant)
            o = next((x for x in items if x["id"] == order_id), None)
            if o is None:
                raise ApiError("NOT_FOUND", "Commande introuvable.", status.HTTP_404_NOT_FOUND)
            o["history"].append({"at": timezone.now().isoformat(), "by": user.display_name, "from": o["status"], "to": st, "comment": comment})
            o["status"] = st
            _save_orders(user.tenant, items)
        label = {"accepted": "acceptée", "rejected": "refusée", "delivered": "livrée"}[st]
        buyer = get_user_model().objects.filter(pk=o.get("byId")).first()
        if buyer:
            _send(buyer, f"Votre commande ({o['kindLabel']}) est {label}",
                  f"{o['item'] or o['kindLabel']} × {o['quantity']} {o['unit']} — {', '.join(o['projectNames'])}." + (f" {comment}" if comment else ""))
        audit.record(user, "Commande client", f"Commande {label}", "", f"{o['kindLabel']} {o['item']} {comment}")
        return PortalOrdersView().get(request)


# --------------------------------------------------------------------------- récap par e-mail
def recap_text(user, projects, period=None):
    hpd = Decimal(str(hours_per_day(user.tenant) or 8))
    from projects.budget_report import compute
    lines = [f"Récapitulatif projets — {timezone.localdate():%d/%m/%Y}" + (f" (mois {billing.label(period)})" if period else ""), ""]
    first = last = None
    if period:
        first, last = billing.bounds(period)
    for p in projects:
        t = compute(p)["totals"]
        lines.append(f"■ {p.name} ({p.client.name})")
        if t.get("approved") is not None:
            lines.append(f"  Budget : {t['approved']} € · consommé {t['consumed']} € · engagé {t['engaged']} € · reste {t['remaining']} € ({t['rate']} %)")
        qs = TimeEntry.objects.filter(project=p).exclude(approval_status__in=("draft", "rejected"))
        if first:
            qs = qs.filter(work_date__range=(first, last))
        people = defaultdict(Decimal)
        for e in qs.select_related("person"):
            people[e.person.display_name] += e.hours
        if people:
            lines.append("  Temps : " + ", ".join(f"{n} {(h / hpd).quantize(Q2)} j" for n, h in sorted(people.items())))
        acts = Action.objects.filter(project=p)
        open_ = acts.exclude(status="done").count()
        late = acts.exclude(status="done").filter(due__lt=timezone.localdate()).count()
        lines.append(f"  Tâches : {acts.count()} au total, {open_} ouvertes, {late} en retard")
        lines.append("")
    lines.append(f"Envoyé par {user.display_name} depuis Control Tower.")
    return "\n".join(lines)


class PortalRecapView(APIView):
    """GET ?projects=a,b&month= : aperçu du récap. POST {projects[], to[], subject, month} : envoi par e-mail."""

    def get(self, request):
        ids = [x for x in (request.query_params.get("projects") or "").split(",") if x]
        projects = _projects(request.user, ids or None)
        return Response({"text": recap_text(request.user, projects, request.query_params.get("month") or None),
                         "to": [request.user.email] if request.user.email else []})

    def post(self, request):
        from configuration.models import NotificationChannel
        from configuration.notify import ChannelError, send_email
        user = request.user
        projects = _projects(user, request.data.get("projects") or None)
        to = [e.strip() for e in (request.data.get("to") or []) if isinstance(e, str) and "@" in e][:20]
        if not to:
            raise ApiError("VALIDATION_ERROR", "Indiquez au moins un destinataire.")
        text = str(request.data.get("text") or "") or recap_text(user, projects, request.data.get("month") or None)
        subject = str(request.data.get("subject") or "Récapitulatif projets — Control Tower")[:200]
        channel = NotificationChannel.objects.filter(tenant=user.tenant, kind="email", enabled=True).first()
        if channel is None:
            audit.record(user, "Reporting", "Récap e-mail non envoyé (e-mail non configuré)", "", ", ".join(to))
            return Response({"sent": False, "reason": "L'envoi d'e-mails n'est pas configuré par l'administrateur (Configuration → Notifications). "
                                                       "Utilisez « Ouvrir dans ma messagerie »."})
        try:
            send_email(channel, to, subject, text)
        except ChannelError as exc:
            return Response({"sent": False, "reason": str(exc)})
        audit.record(user, "Reporting", "Récap envoyé par e-mail", "", ", ".join(to))
        return Response({"sent": True, "to": to})
