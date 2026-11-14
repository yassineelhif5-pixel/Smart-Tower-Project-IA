"""Rapport budgétaire automatique : consommation = heures saisies × TJM du membre sur le projet.

- Validé = consommé ; à valider = engagé ; refusé = ignoré. Recalculé à chaque saisie (signal sur TimeEntry).
- Filtres : période (du / au), personne, regroupement par mois ou par semaine.
- Audience : chef de projet, administrateur et profils financiers voient tout (TJM, coût par personne) ;
  le client voit la synthèse et l'évolution si le chef de projet l'a rendu visible (aucun TJM ni coût individuel).
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.errors import ApiError
from configuration import audit
from configuration.models import AppSetting
from planning.services import hours_per_day

from .models import ProjectAccess, ProjectFinance, TimeEntry
from .timesheet_reminders import missing_for_project, remind_project, save_settings, settings_of
from .workspace import _project, _rights

CLIENT_KEY = "budget_client_visible"
SUPPLEMENTS_KEY, THRESHOLD_KEY, REQUESTS_KEY = "budget_supplements", "budget_threshold_state", "budget_requests"
THRESHOLDS = (80, 100)
MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
Q2 = Decimal("0.01")


def client_visible(project):
    row = AppSetting.objects.filter(tenant=project.tenant, key=CLIENT_KEY).first()
    v = row.value if row and isinstance(row.value, dict) else {}
    return bool(v.get(project.id, True))  # visible par défaut : le reporting client inclut le budget


def _bucket(d, group):
    if group == "week":
        y, w, _ = d.isocalendar()
        monday = d - timedelta(days=d.weekday())
        return f"{y}-S{w:02d}", f"sem. {w} ({monday:%d/%m})"
    return f"{d:%Y-%m}", f"{MONTHS[d.month - 1]} {d.year}"


def _money(x):
    return x.quantize(Q2) if x is not None else None


def compute(project, date_from=None, date_to=None, person=None, group="month"):
    hpd = hours_per_day(project.tenant) or Decimal("8")
    rates = dict(ProjectAccess.objects.filter(project=project).values_list("user_id", "daily_rate"))
    missing_ids = [uid for uid, r in rates.items() if r is None]
    if missing_ids:  # profils support : TJM du niveau défini dans le contrat de support du client
        try:
            from django.contrib.auth import get_user_model
            from clientspace.billing import rate_for
            for u in get_user_model().objects.filter(pk__in=missing_ids):
                rates[u.pk] = rate_for(u, project)
        except Exception:
            pass
    qs = TimeEntry.objects.filter(project=project).exclude(approval_status__in=("rejected", "draft"))
    if person:
        qs = qs.filter(person_id=person)
    rows = list(qs.values("person_id", "person__first_name", "person__last_name", "person__username", "person__role__label",
                          "work_date", "approval_status", "action_id", "action__title").annotate(h=Sum("hours")))
    total = {"consumed": Decimal("0"), "engaged": Decimal("0"), "hours": Decimal("0")}
    period = {"consumed": Decimal("0"), "engaged": Decimal("0"), "hours": Decimal("0")}
    buckets = defaultdict(lambda: {"consumed": Decimal("0"), "engaged": Decimal("0"), "hours": Decimal("0")})
    labels = {}
    people = {}
    tasks = {}
    recent = Decimal("0")
    today = timezone.localdate()
    missing_rate = set()
    for r in rows:
        h = r["h"] or Decimal("0")
        rate = rates.get(r["person_id"])
        name = (f"{r['person__first_name']} {r['person__last_name']}".strip() or r["person__username"])
        if rate is None:
            missing_rate.add(name)
        cost = h / hpd * rate if rate is not None else Decimal("0")
        kind = "consumed" if r["approval_status"] == "approved" else "engaged"
        total[kind] += cost
        total["hours"] += h
        if r["work_date"] >= today - timedelta(days=30):
            recent += cost
        k, label = _bucket(r["work_date"], group)
        labels[k] = label
        b = buckets[k]
        b[kind] += cost
        b["hours"] += h
        b["inPeriod"] = b.get("inPeriod", False) or ((date_from is None or r["work_date"] >= date_from) and (date_to is None or r["work_date"] <= date_to))
        if (date_from and r["work_date"] < date_from) or (date_to and r["work_date"] > date_to):
            continue
        period[kind] += cost
        period["hours"] += h
        p = people.setdefault(r["person_id"], {"id": r["person_id"], "name": name, "role": r["person__role__label"] or "",
                                               "dailyRate": rate, "hours": Decimal("0"), "consumed": Decimal("0"), "engaged": Decimal("0")})
        p["hours"] += h
        p[kind] += cost
        t = tasks.setdefault(r["action_id"] or "-", {"id": r["action_id"], "title": r["action__title"] or "Sans tâche (réunions, divers)",
                                                     "hours": Decimal("0"), "cost": Decimal("0")})
        t["hours"] += h
        t["cost"] += cost
    fin = ProjectFinance.objects.filter(project=project).first()
    approved = fin.approved if fin else None
    initial = (fin.baseline if fin and fin.baseline is not None else approved)
    spent = total["consumed"] + total["engaged"]
    series, cumul = [], Decimal("0")
    for k in sorted(buckets):
        b = buckets[k]
        cumul += b["consumed"] + b["engaged"]
        if b.get("inPeriod"):
            series.append({"key": k, "label": labels[k], "consumed": _money(b["consumed"]), "engaged": _money(b["engaged"]),
                           "hours": b["hours"], "cumulative": _money(cumul)})
    forecast = None
    if project.end_date and project.end_date > today:
        days_left = (project.end_date - today).days
        projected = spent + recent / 30 * days_left
        forecast = {"endDate": project.end_date, "projected": _money(projected), "dailyBurn": _money(recent / 30),
                    "overrun": _money(projected - approved) if approved is not None and projected > approved else None}
    return {
        "hoursPerDay": hpd, "currency": "€",
        "totals": {"initial": initial, "approved": approved, "consumed": _money(total["consumed"]), "engaged": _money(total["engaged"]),
                   "spent": _money(spent), "remaining": _money(approved - spent) if approved is not None else None,
                   "rate": round(float(spent / approved * 100), 1) if approved else None, "hours": total["hours"],
                   "days": (total["hours"] / hpd).quantize(Q2)},
        "period": {"from": date_from, "to": date_to, "consumed": _money(period["consumed"]), "engaged": _money(period["engaged"]),
                   "hours": period["hours"], "days": (period["hours"] / hpd).quantize(Q2)},
        "forecast": forecast, "series": series,
        "byPerson": sorted(({**p, "days": (p["hours"] / hpd).quantize(Q2), "consumed": _money(p["consumed"]), "engaged": _money(p["engaged"])}
                            for p in people.values()), key=lambda x: -(x["consumed"] + x["engaged"])),
        "byTask": sorted(({**t, "cost": _money(t["cost"])} for t in tasks.values()), key=lambda x: -x["cost"])[:30],
        "missingRates": sorted(missing_rate),
    }


def sync_finance(project):
    """Tient ProjectFinance.consumed à jour (consommation validée) et vérifie les seuils : appelé à chaque saisie de temps."""
    data = compute(project)
    fin = ProjectFinance.objects.filter(project=project).first()
    if fin is None:
        ProjectFinance.objects.create(tenant=project.tenant, project=project, consumed=data["totals"]["consumed"])
    elif fin.consumed != data["totals"]["consumed"]:
        fin.consumed = data["totals"]["consumed"]
        fin.save(update_fields=["consumed"])
    check_thresholds(project, data)


def client_users(project):
    """Comptes du client du projet (profil externe), actifs."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    ids = set(User.objects.filter(tenant=project.tenant, is_active=True, client_id=project.client_id, role__internal=False)
              .values_list("pk", flat=True))
    ids |= set(ProjectAccess.objects.filter(project=project, user__is_active=True, user__role__internal=False).values_list("user_id", flat=True))
    return list(User.objects.filter(pk__in=ids))


def check_thresholds(project, data=None):
    """Alerte (notification + e-mail) le client et le chef de projet au franchissement de 80 % puis 100 % du budget."""
    from .timesheet_reminders import _send
    data = data or compute(project)
    t = data["totals"]
    if not t["approved"]:
        return None
    rate = float(t["spent"] / t["approved"] * 100)
    reached = max([x for x in THRESHOLDS if rate >= x], default=0)
    row, _ = AppSetting.objects.get_or_create(tenant=project.tenant, key=THRESHOLD_KEY, defaults={"value": {}})
    state = dict(row.value or {})
    last = int(state.get(project.id, 0))
    if reached == last:
        return None
    state[project.id] = reached
    row.value = state
    row.save(update_fields=["value"])
    if reached < last:  # budget complété : l'alerte pourra se redéclencher
        return None
    word = "atteint" if reached == 80 else "dépassé"
    title = f"[{project.code}] Budget {word} : {rate:.0f} % consommé"
    body = (f"Le budget du projet {project.name} est consommé à {rate:.0f} % : {t['spent']} € sur {t['approved']} € "
            f"(dont {t['engaged']} € de temps à valider). Reste : {t['remaining']} €. "
            + ("Chef de projet : envoyez une demande de budget supplémentaire au client depuis le reporting (rubrique Budget). "
               if reached >= 100 else "")
            + "Le client peut ajouter un budget supplémentaire depuis le reporting du projet (rubrique Budget).")
    recipients = {u.pk: u for u in client_users(project)}
    if project.pm and project.pm.is_active:
        recipients[project.pm.pk] = project.pm
    for u in recipients.values():
        _send(u, title, body)
    audit.record(None, f"Projet {project.code}", f"Seuil budgétaire {reached} %", "", f"{rate:.1f} %", tenant=project.tenant)
    return reached


def supplements_of(project):
    row = AppSetting.objects.filter(tenant=project.tenant, key=SUPPLEMENTS_KEY).first()
    return list(((row.value if row and isinstance(row.value, dict) else {}) or {}).get(project.id, []))


def can_add_budget(user, project, rights):
    if rights["isPm"] or user.is_app_admin:
        return True
    return bool(user.role and not user.role.internal and (user.client_id == project.client_id
                or ProjectAccess.objects.filter(project=project, user=user).exists()))


class BudgetReportView(APIView):
    """GET : rapport filtré. PUT : visibilité client (chef de projet) et relances (administrateur)."""

    def _audience(self, request, project):
        rights = _rights(request.user, project)
        if rights["canSeeMoney"]:
            return "full", rights
        if request.user.role and not request.user.role.internal and client_visible(project):
            return "client", rights
        raise ApiError("FORBIDDEN_PERMISSION", "Le budget de ce projet n'est pas accessible avec votre profil.", status.HTTP_403_FORBIDDEN)

    def get(self, request, pk):
        project = _project(request.user, pk)
        audience, rights = self._audience(request, project)
        p = request.query_params
        group = "week" if p.get("group") == "week" else "month"
        person = p.get("person") if audience == "full" else None
        data = compute(project, parse_date(p.get("from") or "") or None, parse_date(p.get("to") or "") or None,
                       int(person) if person and str(person).isdigit() else None, group)
        out = {"audience": audience, "project": {"id": project.id, "code": project.code, "name": project.name,
                                                 "start": project.start_date, "end": project.end_date}, "group": group, **data}
        out["supplements"] = supplements_of(project)
        out["canAddBudget"] = can_add_budget(request.user, project, rights)
        out["requests"] = list(reversed(requests_of(project)))[:10]
        out["canRequest"] = bool(rights["isPm"] or request.user.is_app_admin)
        out["canDecide"] = is_client_of(request.user, project) or request.user.is_app_admin
        out["thresholds"] = list(THRESHOLDS)
        out["budgetMode"] = budget_mode(project)
        out["orders"] = list(reversed(orders_of(project)))[:30]
        ordered = ordered_by_person(project)
        seen = {x["id"] for x in out["byPerson"]}
        for acc in ProjectAccess.objects.filter(project=project, user_id__in=[k for k in ordered if k not in seen]).select_related("user", "user__role"):
            out["byPerson"].append({"id": acc.user_id, "name": acc.user.display_name, "role": acc.user.role.label if acc.user.role else "",
                                    "dailyRate": acc.daily_rate, "hours": Decimal("0"), "days": Decimal("0"), "consumed": Decimal("0"), "engaged": Decimal("0")})
        for p_ in out["byPerson"]:
            o = ordered.get(p_["id"])
            p_["orderedDays"] = o["days"] if o else None
            p_["orderedAmount"] = o["amount"] if o else None
            p_["remainingAmount"] = (o["amount"] - p_["consumed"] - p_["engaged"]) if o else None
        out["ordered"] = [{"person": k, "days": v["days"], "amount": v["amount"]} for k, v in ordered.items()]
        out["canOrder"] = bool(is_client_of(request.user, project) or is_commercial(request.user, project) or rights["isPm"] or request.user.is_app_admin)
        out["canChooseMode"] = bool(is_client_of(request.user, project) or request.user.is_app_admin)
        out["policy"] = policy_of(project)
        out["canSetPolicy"] = request.user.is_app_admin
        out["team"] = [{"id": a.user_id, "name": a.user.display_name} for a in
                       ProjectAccess.objects.filter(project=project, user__role__internal=True).select_related("user")]
        if audience == "client":
            out["missingRates"] = []
            out["byPerson"] = list(out["byPerson"])  # le client voit le détail par utilisateur (TJM facturé inclus)
            out["byTask"] = [{"id": t["id"], "title": t["title"], "cost": t["cost"]} for t in out["byTask"]]
            return Response(out)
        is_pm = rights["isPm"] or request.user.is_app_admin
        out["people"] = [{"id": a.user_id, "name": a.user.display_name} for a in
                         ProjectAccess.objects.filter(project=project).select_related("user").order_by("user__first_name")]
        out["settings"] = {"clientVisible": client_visible(project), "canEdit": is_pm, "isAdmin": request.user.is_app_admin,
                           "reminders": settings_of(project.tenant)}
        out["missingTimesheets"] = [{"user": u.display_name, "userId": u.pk, "days": d} for u, d in missing_for_project(project).items()]
        return Response(out)

    def put(self, request, pk):
        project = _project(request.user, pk)
        rights = _rights(request.user, project)
        if request.data.get("budgetMode") in ("global", "resource"):
            if not (is_client_of(request.user, project) or request.user.is_app_admin):
                raise ApiError("FORBIDDEN_PERMISSION", "Le mode de budget est choisi par le client.", status.HTTP_403_FORBIDDEN)
            from django.db import transaction
            with transaction.atomic():
                _set_project_map(project, MODE_KEY, request.data["budgetMode"])
            audit.record(request.user, f"Projet {project.code}", "Mode de budget", "", request.data["budgetMode"])
            return self.get(request, pk)
        if not (rights["isPm"] or request.user.is_app_admin):
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé au chef de projet et à l'administrateur.", status.HTTP_403_FORBIDDEN)
        if "clientVisible" in request.data:
            row, _ = AppSetting.objects.get_or_create(tenant=project.tenant, key=CLIENT_KEY, defaults={"value": {}})
            row.value = {**(row.value or {}), project.id: bool(request.data["clientVisible"])}
            row.save(update_fields=["value"])
            audit.record(request.user, f"Projet {project.code}", "Budget visible du client", "", str(bool(request.data["clientVisible"])))
        if isinstance(request.data.get("reminders"), dict):
            if not request.user.is_app_admin:
                raise ApiError("FORBIDDEN_PERMISSION", "Les relances se règlent par l'administrateur.", status.HTTP_403_FORBIDDEN)
            save_settings(project.tenant, request.data["reminders"])
            audit.record(request.user, "Relances de saisie", "Paramètres modifiés", "", str(request.data["reminders"]))
        return self.get(request, pk)


def _amount(raw, required=True):
    try:
        amount = Decimal(str(raw if raw not in (None, "") else "0")).quantize(Q2)
    except Exception:
        amount = Decimal("-1")
    if not amount.is_finite() or amount < 0 or amount > Decimal("100000000") or (required and amount == 0):
        raise ApiError("VALIDATION_ERROR", "Indiquez un montant positif.")
    return amount


def _project_people(project, exclude=None):
    out = {u.pk: u for u in client_users(project)}
    if project.pm and project.pm.is_active:
        out[project.pm.pk] = project.pm
    if exclude is not None:
        out.pop(exclude.pk, None)
    return out


def add_supplement(project, user, amount, reason):
    """Ajoute un budget supplémentaire : budget validé augmenté, budget initial conservé, historique, notifications, seuils."""
    from django.db import transaction
    from .timesheet_reminders import _send
    with transaction.atomic():
        fin = ProjectFinance.objects.select_for_update().filter(project=project).first()
        if fin is None:
            fin = ProjectFinance.objects.create(tenant=project.tenant, project=project)
        old = fin.approved or Decimal("0")
        if fin.baseline is None:
            fin.baseline = old  # le budget initial reste visible après les ajouts
        fin.approved = old + amount
        fin.save(update_fields=["baseline", "approved"])
        row, _ = AppSetting.objects.select_for_update().get_or_create(tenant=project.tenant, key=SUPPLEMENTS_KEY, defaults={"value": {}})
        value = dict(row.value or {})
        value[project.id] = list(value.get(project.id, [])) + [{
            "amount": str(amount), "reason": reason, "by": user.display_name, "role": user.role.label if user.role else "",
            "at": timezone.now().isoformat(), "before": str(old), "after": str(fin.approved)}]
        row.value = value
        row.save(update_fields=["value"])
    audit.record(user, f"Projet {project.code}", "Budget supplémentaire", str(old), f"{fin.approved} (+{amount}) {reason}")
    for u in _project_people(project, exclude=user).values():
        _send(u, f"[{project.code}] Budget supplémentaire : +{amount} €",
              f"{user.display_name} a ajouté {amount} € au budget du projet {project.name}"
              + (f" ({reason})" if reason else "") + f". Nouveau budget validé : {fin.approved} €.")
    check_thresholds(project)
    return fin


class BudgetSupplementView(APIView):
    """POST {amount, reason} : budget supplémentaire ajouté directement (client du projet, chef de projet ou administrateur)."""

    def post(self, request, pk):
        project = _project(request.user, pk)
        if not can_add_budget(request.user, project, _rights(request.user, project)):
            raise ApiError("FORBIDDEN_PERMISSION", "Seuls le client du projet, le chef de projet et l'administrateur ajoutent du budget.",
                           status.HTTP_403_FORBIDDEN)
        add_supplement(project, request.user, _amount(request.data.get("amount")), str(request.data.get("reason") or "").strip()[:300])
        return BudgetReportView().get(request, pk)


# --------------------------------------------------------------------------- demandes de budget (CP -> client)
def requests_of(project):
    row = AppSetting.objects.filter(tenant=project.tenant, key=REQUESTS_KEY).first()
    return list(((row.value if row and isinstance(row.value, dict) else {}) or {}).get(project.id, []))


def _save_requests(project, items):
    row, _ = AppSetting.objects.select_for_update().get_or_create(tenant=project.tenant, key=REQUESTS_KEY, defaults={"value": {}})
    value = dict(row.value or {})
    value[project.id] = items
    row.value = value
    row.save(update_fields=["value"])


def is_client_of(user, project):
    return bool(user.role and not user.role.internal and (user.client_id == project.client_id
                or ProjectAccess.objects.filter(project=project, user=user).exists()))


class BudgetRequestView(APIView):
    """POST {amount, reason} : le chef de projet demande un budget supplémentaire au client (notification + e-mail)."""

    def post(self, request, pk):
        import secrets
        from django.db import transaction
        from .timesheet_reminders import _send
        project = _project(request.user, pk)
        rights = _rights(request.user, project)
        if not (rights["isPm"] or request.user.is_app_admin):
            raise ApiError("FORBIDDEN_PERMISSION", "Seul le chef de projet demande un budget supplémentaire.", status.HTTP_403_FORBIDDEN)
        amount = _amount(request.data.get("amount"), required=False)
        reason = str(request.data.get("reason") or "").strip()[:500]
        if not reason:
            raise ApiError("VALIDATION_ERROR", "Expliquez au client pourquoi un budget supplémentaire est nécessaire.")
        data = compute(project)["totals"]
        with transaction.atomic():
            items = requests_of(project)
            if any(x["status"] == "pending" for x in items):
                raise ApiError("CONFLICT", "Une demande est déjà en attente de réponse du client.", status.HTTP_409_CONFLICT)
            req = {"id": secrets.token_hex(4), "amount": str(amount) if amount else None, "reason": reason, "by": request.user.display_name,
                   "at": timezone.now().isoformat(), "status": "pending", "rate": data["rate"], "spent": str(data["spent"]),
                   "approved": str(data["approved"]) if data["approved"] is not None else None}
            _save_requests(project, items + [req])
        clients = client_users(project)
        for u in clients:
            _send(u, f"[{project.code}] Demande de budget supplémentaire",
                  f"{request.user.display_name}, chef de projet, demande un budget supplémentaire"
                  + (f" de {amount} €" if amount else "") + f" pour le projet {project.name}. Motif : {reason}. "
                  f"Budget consommé : {data['rate']} % ({data['spent']} € sur {data['approved']} €). "
                  "Ouvrez le reporting du projet (rubrique Budget) pour accepter en saisissant le montant accordé, ou refuser.")
        audit.record(request.user, f"Projet {project.code}", "Demande de budget supplémentaire", "",
                     f"{amount or 'montant libre'} · {reason}")
        resp = BudgetReportView().get(request, pk)
        resp.data["notice"] = (f"Demande envoyée à {', '.join(u.display_name for u in clients)}." if clients else
                               "Demande enregistrée, mais aucun compte client n'est rattaché au projet : personne n'a été prévenu.")
        return resp


class BudgetRequestDecisionView(APIView):
    """POST {decision: approved|rejected, amount, comment} : réponse du client. Accepter = saisir le budget accordé."""

    def post(self, request, pk, req_id):
        from django.db import transaction
        from .timesheet_reminders import _send
        project = _project(request.user, pk)
        if not (is_client_of(request.user, project) or request.user.is_app_admin):
            raise ApiError("FORBIDDEN_PERMISSION", "Seul le client du projet répond à une demande de budget.", status.HTTP_403_FORBIDDEN)
        decision = request.data.get("decision")
        if decision not in ("approved", "rejected"):
            raise ApiError("VALIDATION_ERROR", "Décision inconnue.")
        comment = str(request.data.get("comment") or "").strip()[:500]
        amount = _amount(request.data.get("amount")) if decision == "approved" else None
        if decision == "rejected" and not comment:
            raise ApiError("VALIDATION_ERROR", "Indiquez le motif du refus.")
        with transaction.atomic():
            items = requests_of(project)
            req = next((x for x in items if x["id"] == req_id), None)
            if req is None or req["status"] != "pending":
                raise ApiError("CONFLICT", "Cette demande a déjà reçu une réponse.", status.HTTP_409_CONFLICT)
            req.update(status=decision, decidedBy=request.user.display_name, decidedAt=timezone.now().isoformat(),
                       granted=str(amount) if amount else None, comment=comment)
            _save_requests(project, items)
        if amount:
            add_supplement(project, request.user, amount, f"Demande du {req['at'][:10]} acceptée" + (f" — {comment}" if comment else ""))
        elif project.pm:
            _send(project.pm, f"[{project.code}] Demande de budget refusée",
                  f"{request.user.display_name} a refusé la demande de budget supplémentaire. Motif : {comment}")
        audit.record(request.user, f"Projet {project.code}", "Réponse à la demande de budget",
                     "En attente", f"{'Acceptée : ' + str(amount) + ' €' if amount else 'Refusée'} {comment}")
        return BudgetReportView().get(request, pk)


class BudgetRemindView(APIView):
    """POST : relance immédiate des membres sans saisie (et du chef de projet)."""

    def post(self, request, pk):
        project = _project(request.user, pk)
        rights = _rights(request.user, project)
        if not (rights["isPm"] or request.user.is_app_admin):
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé au chef de projet et à l'administrateur.", status.HTTP_403_FORBIDDEN)
        return Response(remind_project(project, request.user))


# --------------------------------------------------------------------------- commandes de jours et mode de budget
ORDERS_KEY, MODE_KEY, POLICY_KEY, POLICY_STATE_KEY = "day_orders", "budget_mode", "overrun_policy", "overrun_state"


def _project_map(project, key):
    row = AppSetting.objects.filter(tenant=project.tenant, key=key).first()
    return ((row.value if row and isinstance(row.value, dict) else {}) or {}).get(project.id)


def _set_project_map(project, key, value):
    row, _ = AppSetting.objects.select_for_update().get_or_create(tenant=project.tenant, key=key, defaults={"value": {}})
    data = dict(row.value or {})
    data[project.id] = value
    row.value = data
    row.save(update_fields=["value"])


def budget_mode(project):
    return _project_map(project, MODE_KEY) or "global"


def orders_of(project):
    return list(_project_map(project, ORDERS_KEY) or [])


def ordered_by_person(project):
    """Jours et montants commandés (validés par le client) par personne."""
    out = {}
    for o in orders_of(project):
        if o["status"] == "approved":
            r = out.setdefault(o["person"], {"days": Decimal("0"), "amount": Decimal("0")})
            r["days"] += Decimal(o["days"])
            r["amount"] += Decimal(o["amount"])
    return out


def is_commercial(user, project):
    return bool(user.role_id == "commercial" or project.client.sales.filter(pk=user.pk).exists())


class DayOrdersView(APIView):
    """POST {person, days, rate?, note} : commande de jours pour un consultant (commercial, client, chef de projet).
    Commande du client : validée d'office. Commande du commercial ou du CP : en attente de validation du client."""

    def post(self, request, pk):
        import secrets
        from django.db import transaction
        from .timesheet_reminders import _send
        project = _project(request.user, pk)
        rights = _rights(request.user, project)
        user = request.user
        client = is_client_of(user, project)
        if not (client or is_commercial(user, project) or rights["isPm"] or user.is_app_admin):
            raise ApiError("FORBIDDEN_PERMISSION", "Commande réservée au commercial, au client et au chef de projet.", status.HTTP_403_FORBIDDEN)
        acc = ProjectAccess.objects.filter(project=project, user_id=request.data.get("person")).select_related("user").first()
        if acc is None:
            raise ApiError("VALIDATION_ERROR", "Choisissez un membre de l'équipe du projet.")
        days = _amount(request.data.get("days"))
        rate = acc.daily_rate
        if rate is None:
            from clientspace.billing import rate_for
            rate = rate_for(acc.user, project)
        if rate is None:
            raise ApiError("VALIDATION_ERROR", f"Le TJM de {acc.user.display_name} n'est pas renseigné (Projet → Équipe).")
        status_ = "approved" if client else "pending"
        order = {"id": secrets.token_hex(4), "person": acc.user_id, "personName": acc.user.display_name, "days": str(days),
                 "rate": str(rate), "amount": str((days * rate).quantize(Q2)), "note": str(request.data.get("note") or "")[:300],
                 "by": user.display_name, "byRole": user.role.label if user.role else "", "at": timezone.now().isoformat(), "status": status_}
        if client:
            order.update(decidedBy=user.display_name, decidedAt=order["at"])
        with transaction.atomic():
            _set_project_map(project, ORDERS_KEY, orders_of(project) + [order])
        audit.record(user, f"Projet {project.code}", "Commande de jours", "", f"{acc.user.display_name} · {days} j × {rate} € ({status_})")
        if client:
            add_supplement(project, user, Decimal(order["amount"]), f"Commande de {days} j pour {acc.user.display_name}")
        else:
            for u in client_users(project):
                _send(u, f"[{project.code}] Commande de jours à valider : {acc.user.display_name}",
                      f"{user.display_name} commande {days} jour(s) de {acc.user.display_name} à {rate} €/j, soit {order['amount']} € HT. "
                      "Validez ou refusez la commande dans le reporting du projet (rubrique Budget).")
        return BudgetReportView().get(request, pk)


class DayOrderDecisionView(APIView):
    def post(self, request, pk, order_id):
        from django.db import transaction
        from .timesheet_reminders import _send
        project = _project(request.user, pk)
        if not (is_client_of(request.user, project) or request.user.is_app_admin):
            raise ApiError("FORBIDDEN_PERMISSION", "Seul le client valide une commande de jours.", status.HTTP_403_FORBIDDEN)
        decision = request.data.get("decision")
        if decision not in ("approved", "rejected"):
            raise ApiError("VALIDATION_ERROR", "Décision inconnue.")
        comment = str(request.data.get("comment") or "")[:300]
        with transaction.atomic():
            items = orders_of(project)
            order = next((o for o in items if o["id"] == order_id), None)
            if order is None or order["status"] != "pending":
                raise ApiError("CONFLICT", "Cette commande a déjà été traitée.", status.HTTP_409_CONFLICT)
            order.update(status=decision, decidedBy=request.user.display_name, decidedAt=timezone.now().isoformat(), comment=comment)
            _set_project_map(project, ORDERS_KEY, items)
        if decision == "approved":
            add_supplement(project, request.user, Decimal(order["amount"]), f"Commande de {order['days']} j pour {order['personName']}")
        for u in {project.pm, *project.client.sales.all()} - {None}:
            _send(u, f"[{project.code}] Commande de jours {'validée' if decision == 'approved' else 'refusée'}",
                  f"{request.user.display_name} a {'validé' if decision == 'approved' else 'refusé'} la commande de {order['days']} j "
                  f"pour {order['personName']}" + (f" ({comment})" if comment else "") + ".")
        audit.record(request.user, f"Projet {project.code}", "Décision sur commande de jours", "En attente", f"{decision} {comment}")
        return BudgetReportView().get(request, pk)


# --------------------------------------------------------------------------- politique de dépassement (admin / Pilote)
def policy_of(project):
    return {"mode": "continue", "graceDays": 0, "scope": "both", **(_project_map(project, POLICY_KEY) or {})}


def overrun_status(project, person_id=None):
    """Dépassement du projet (et de la ressource en mode « par ressource ») : (dépassé, motif)."""
    data = compute(project)
    t = data["totals"]
    reasons = []
    pol = policy_of(project)
    if pol["scope"] in ("project", "both") and t["approved"] and t["spent"] >= t["approved"]:
        reasons.append(f"budget du projet consommé ({t['spent']} € / {t['approved']} €)")
    if pol["scope"] in ("resource", "both") and person_id and budget_mode(project) == "resource":
        ordered = ordered_by_person(project).get(person_id)
        mine = next((p for p in data["byPerson"] if p["id"] == person_id), None)
        if ordered is not None and mine and (mine["consumed"] + mine["engaged"]) >= ordered["amount"]:
            reasons.append(f"jours commandés consommés ({mine['days']} j / {ordered['days']} j)")
        if ordered is None and orders_of(project):
            reasons.append("aucun jour commandé pour cette ressource")
    return bool(reasons), "; ".join(reasons)


def check_entry_allowed(project, person):
    """Appelé avant chaque saisie : bloque si la politique l'exige et que le délai de grâce est écoulé."""
    pol = policy_of(project)
    if pol["mode"] != "block":
        return None
    over, why = overrun_status(project, person.pk)
    state = _project_map(project, POLICY_STATE_KEY) or {}
    key = str(person.pk)
    today = timezone.localdate()
    if not over:
        if key in state:
            from django.db import transaction
            with transaction.atomic():
                state.pop(key, None)
                _set_project_map(project, POLICY_STATE_KEY, state)
        return None
    since = state.get(key)
    if since is None:
        from django.db import transaction
        with transaction.atomic():
            state[key] = today.isoformat()
            _set_project_map(project, POLICY_STATE_KEY, state)
        since = today.isoformat()
    from datetime import date as _date
    elapsed = (today - _date.fromisoformat(since)).days
    if elapsed >= int(pol.get("graceDays") or 0):
        return (f"Saisie bloquée sur {project.name} : {why}. Délai de grâce de {pol.get('graceDays', 0)} jour(s) écoulé. "
                "Demandez un budget supplémentaire ou une commande de jours au client.")
    return None


class OverrunPolicyView(APIView):
    """PUT {mode: continue|block, graceDays, scope: project|resource|both} : administrateur de l'entreprise."""

    def put(self, request, pk):
        from django.db import transaction
        project = _project(request.user, pk)
        if not request.user.is_app_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé à l'administrateur et au Pilote.", status.HTTP_403_FORBIDDEN)
        with transaction.atomic():
            _save_policy(project, request.data, request.user)
        return BudgetReportView().get(request, pk)


def _save_policy(project, data, by):
    pol = policy_of(project)
    if data.get("mode") in ("continue", "block"):
        pol["mode"] = data["mode"]
    if data.get("scope") in ("project", "resource", "both"):
        pol["scope"] = data["scope"]
    if "graceDays" in data:
        pol["graceDays"] = max(0, min(365, int(data.get("graceDays") or 0)))
    _set_project_map(project, POLICY_KEY, pol)
    audit.record(by, f"Projet {project.code}", "Politique de dépassement", "", str(pol), tenant=project.tenant)
    return pol


class PilotOverrunPolicyView(APIView):
    """Pilote : GET liste des projets d'une entreprise avec leur politique ; PUT {project, mode, graceDays, scope}."""

    def get(self, request, tenant_id):
        if not request.user.is_platform_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé au Pilote.", status.HTTP_403_FORBIDDEN)
        from projects.models import Project
        return Response([{"id": p.id, "code": p.code, "policy": policy_of(p)} for p in Project.objects.filter(tenant_id=tenant_id)])

    def put(self, request, tenant_id):
        from django.db import transaction
        from projects.models import Project
        if not request.user.is_platform_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé au Pilote.", status.HTTP_403_FORBIDDEN)
        project = Project.objects.filter(tenant_id=tenant_id, pk=request.data.get("project")).first()
        if project is None:
            raise ApiError("NOT_FOUND", "Projet introuvable.", status.HTTP_404_NOT_FOUND)
        with transaction.atomic():
            return Response(_save_policy(project, request.data, request.user))
