"""TJM et durée de contrat (en jours) par consultant et par client.

GET /client-space/rates?client=<code>   consultants du client (accès à ses projets ou déjà paramétrés), TJM, jours contractés,
                                       période, jours consommés / restants. Lecture : lecteurs de l'espace client.
PUT /client-space/rates                {client, user, rate, days, start, end} — administrateur, chef de projet d'un projet
                                       du client ou commercial du client.
Le TJM sert à la facture générée avec le CRA : TJM du projet > TJM client (ici) > TJM du profil > TJM du contrat de support.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.errors import ApiError
from configuration import audit
from configuration.models import AppSetting
from planning.services import hours_per_day
from projects.access import visible_projects
from projects.models import ProjectAccess, TimeEntry

KEY = "client_user_rates"
SHOW_KEY = "client_show_amounts"  # {client: true} : TJM et montants visibles (désactivé par défaut)
User = get_user_model()


def _all(tenant):
    row = AppSetting.objects.filter(tenant=tenant, key=KEY).first()
    return row.value if row and isinstance(row.value, dict) else {}


def rate_of(tenant, client_id, user_id, day=None):
    """TJM client de la personne (None si non renseigné ou hors période du contrat)."""
    c = (_all(tenant).get(str(client_id)) or {}).get(str(user_id)) or {}
    if c.get("rate") in (None, ""):
        return None
    if day:
        if c.get("start") and str(day) < c["start"]:
            return None
        if c.get("end") and str(day) > c["end"]:
            return None
    return Decimal(str(c["rate"]))


def show_amounts(tenant, client_id):
    row = AppSetting.objects.filter(tenant=tenant, key=SHOW_KEY).first()
    return bool((row.value or {}).get(str(client_id))) if row and isinstance(row.value, dict) else False


def hide_amounts(user, client_ids):
    """Vrai pour un compte client dont l'un des clients n'autorise pas l'affichage du TJM et des montants."""
    if not user.role or user.role.internal:
        return False
    return any(not show_amounts(user.tenant, c) for c in client_ids)


def billable(tenant, client_id, user_id):
    c = (_all(tenant).get(str(client_id)) or {}).get(str(user_id)) or {}
    return c.get("billable", True) is not False


def _can_edit(user, client):
    if user.is_app_admin:
        return True
    if not user.role or not user.role.internal:
        return False
    if client.sales.filter(pk=user.pk).exists():
        return True
    return visible_projects(user).filter(client=client, pm=user).exists()


def _num(v, field, cast=Decimal):
    if v in (None, ""):
        return None
    try:
        x = cast(str(v).replace(",", "."))
    except (InvalidOperation, ValueError):
        raise ApiError("VALIDATION_ERROR", f"{field} invalide.")
    if x < 0:
        raise ApiError("VALIDATION_ERROR", f"{field} doit être positif.")
    return x


def _date(v, field):
    if not v:
        return ""
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        raise ApiError("VALIDATION_ERROR", f"{field} invalide.")


class ClientRatesView(APIView):
    def _client(self, request, code):
        from .views import _clients_for, _guard
        _guard(request.user)
        return get_object_or_404(_clients_for(request.user), pk=code)

    def get(self, request):
        client = self._client(request, request.query_params.get("client"))
        tenant = request.user.tenant
        conf = _all(tenant).get(str(client.pk)) or {}
        hpd = Decimal(str(hours_per_day(tenant) or 8))
        ids = set(ProjectAccess.objects.filter(project__client=client, user__is_active=True, user__role__internal=True).values_list("user_id", flat=True))
        ids |= set(TimeEntry.objects.filter(project__client=client).values_list("person_id", flat=True))
        ids |= {int(k) for k in conf if str(k).isdigit()}
        rows = []
        for u in User.objects.filter(pk__in=ids, tenant=tenant).select_related("role").order_by("first_name", "last_name"):
            if u.role and not u.role.internal:
                continue
            c = conf.get(str(u.pk)) or {}
            qs = TimeEntry.objects.filter(person=u, project__client=client).exclude(approval_status__in=["draft", "rejected"])
            if c.get("start"):
                qs = qs.filter(work_date__gte=c["start"])
            if c.get("end"):
                qs = qs.filter(work_date__lte=c["end"])
            hours = sum((e.hours for e in qs), Decimal("0"))
            validated = sum((e.hours for e in qs if e.approval_status == "approved"), Decimal("0"))
            used = (hours / hpd).quantize(Decimal("0.01"))
            days = Decimal(str(c["days"])) if c.get("days") not in (None, "") else None
            rows.append({"user": u.pk, "name": u.display_name, "role": u.role.label if u.role else "", "company": u.company,
                         "rate": c.get("rate"), "days": c.get("days"), "start": c.get("start", ""), "end": c.get("end", ""),
                         "profileRate": u.daily_rate, "billable": c.get("billable", True) is not False, "external": u.external, "usedDays": used, "validatedDays": (validated / hpd).quantize(Decimal("0.01")),
                         "remainingDays": (days - used).quantize(Decimal("0.01")) if days is not None else None,
                         "pct": float(used / days * 100) if days else None,
                         "amount": (used * Decimal(str(c["rate"]))).quantize(Decimal("0.01")) if c.get("rate") not in (None, "") else None,
                         "budget": (days * Decimal(str(c["rate"]))).quantize(Decimal("0.01")) if days is not None and c.get("rate") not in (None, "") else None,
                         "updatedBy": c.get("updatedBy", ""), "updatedAt": c.get("updatedAt", "")})
        show = show_amounts(tenant, client.pk)
        if hide_amounts(request.user, [client.pk]):
            for r in rows:
                for k in ("rate", "profileRate", "amount", "budget"):
                    r[k] = None
        return Response({"client": client.pk, "clientName": client.name, "canEdit": _can_edit(request.user, client), "rows": rows,
                         "showAmounts": show, "canToggleAmounts": request.user.is_app_admin, "amountsHidden": hide_amounts(request.user, [client.pk])})

    def put(self, request):
        client = self._client(request, request.data.get("client"))
        if not _can_edit(request.user, client):
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé à l'administrateur, au chef de projet ou au commercial du client.", status.HTTP_403_FORBIDDEN)
        u = get_object_or_404(User, pk=request.data.get("user"), tenant=request.user.tenant)
        rate = _num(request.data.get("rate"), "Le TJM")
        days = _num(request.data.get("days"), "La durée du contrat")
        start, end = _date(request.data.get("start"), "La date de début"), _date(request.data.get("end"), "La date de fin")
        bill = request.data.get("billable", True) is not False
        if start and end and end < start:
            raise ApiError("VALIDATION_ERROR", "La date de fin précède la date de début.")
        from django.utils import timezone
        with transaction.atomic():
            row, _ = AppSetting.objects.select_for_update().get_or_create(tenant=request.user.tenant, key=KEY, defaults={"value": {}})
            data = dict(row.value or {})
            cl = dict(data.get(str(client.pk)) or {})
            old = cl.get(str(u.pk)) or {}
            if rate is None and days is None and not start and not end and bill:
                cl.pop(str(u.pk), None)
            else:
                cl[str(u.pk)] = {"rate": str(rate) if rate is not None else "", "days": str(days) if days is not None else "", "start": start, "end": end, "billable": bill,
                                 "updatedBy": request.user.display_name, "updatedAt": timezone.now().isoformat()}
            data[str(client.pk)] = cl
            row.value = data
            row.save(update_fields=["value"])
        audit.record(request.user, f"Client {client.name}", "TJM / contrat consultant modifié",
                     f"{old.get('rate', '')} € · {old.get('days', '')} j", f"{u.display_name} : {rate or '—'} € · {days or '—'} j {start}→{end}",
                     tenant=request.user.tenant)
        return Response({"ok": True})


class ClientAmountsVisibilityView(APIView):
    """PUT /client-space/rates/visibility {client, show} : l'administrateur autorise l'affichage du TJM et des montants
    (CRA et écrans du client). Désactivé par défaut pour chaque client."""

    def put(self, request):
        from .views import _clients_for, _guard
        _guard(request.user)
        if not request.user.is_app_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé à l'administrateur.", status.HTTP_403_FORBIDDEN)
        client = get_object_or_404(_clients_for(request.user), pk=request.data.get("client"))
        show = bool(request.data.get("show"))
        with transaction.atomic():
            row, _ = AppSetting.objects.select_for_update().get_or_create(tenant=request.user.tenant, key=SHOW_KEY, defaults={"value": {}})
            data = dict(row.value or {})
            data[str(client.pk)] = show
            row.value = data
            row.save(update_fields=["value"])
        audit.record(request.user, f"Client {client.name}", "Affichage TJM et montants " + ("autorisé" if show else "masqué"), "", "",
                     tenant=request.user.tenant)
        return Response({"showAmounts": show})
