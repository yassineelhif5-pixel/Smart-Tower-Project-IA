"""API de l'Espace client.

GET  /client-space                         clients accessibles, documents lisibles, contrats de support, droits
GET  /client-space/documents/<id>          téléchargement (lecteurs du document et administrateurs)
POST /client-space/generate                génération manuelle {client, person, period, force}
GET  /client-space/time-validation         temps en attente de validation client (groupés personne × mois)
POST /client-space/time-validation         {client, person, period, decision, comment}
GET/PUT /client-space/support              contrats de support (administrateur)
GET/PUT /client-space/billing-settings     mentions de facturation (administrateur)
GET/PUT /platform/tenants/<id>/support-license   licence support accordée par le Pilote
"""
from collections import defaultdict
from decimal import Decimal
from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.errors import ApiError
from configuration import audit
from planning.services import hours_per_day
from projects.access import in_active_tenant, visible_projects
from projects.models import Client, TimeEntry

from . import billing
from .models import LEVEL_ROLE, LEVELS, ClientDocument, SupportContract
from .support import license_of, save_license, sync_access

User = get_user_model()


PROFILES_KEY = "clientspace_profiles"
DEFAULT_PROFILES = ["client", "cdp", "commercial"]


def enabled_profiles(tenant):
    from configuration.models import AppSetting
    row = AppSetting.objects.filter(tenant=tenant, key=PROFILES_KEY).first()
    v = row.value if row and isinstance(row.value, dict) else {}
    return list(v.get("roles", DEFAULT_PROFILES))


def has_module(user):
    """Module CRA & facturation : profil client par défaut, tout profil activé par l'admin ou le Pilote, et l'admin."""
    return bool(user.is_app_admin or (user.role_id and user.role_id in enabled_profiles(user.tenant)))


def _guard(user):
    if not in_active_tenant(user):
        raise ApiError("FORBIDDEN_PERMISSION", "Accès réservé aux utilisateurs d'une entreprise.", status.HTTP_403_FORBIDDEN)
    if not has_module(user):
        raise ApiError("FORBIDDEN_PERMISSION", "Le module CRA & facturation n'est pas activé pour votre profil (à demander à l'administrateur).",
                       status.HTTP_403_FORBIDDEN)


def _is_client(user):
    return bool(user.role and not user.role.internal)


def _clients_for(user):
    qs = Client.objects.filter(tenant_id=user.tenant_id)
    if user.is_app_admin:
        return qs
    ids = set(visible_projects(user).values_list("client_id", flat=True))
    if user.client_id:
        ids.add(user.client_id)
    ids |= set(ClientDocument.objects.filter(readers=user).values_list("client_id", flat=True))
    return qs.filter(pk__in=ids)


def _doc_row(d):
    return {"id": d.pk, "kind": d.kind, "kindLabel": d.get_kind_display(), "client": d.client_id, "clientName": d.client.name,
            "period": d.period, "periodLabel": billing.label(d.period) if d.period else "", "person": d.person.display_name if d.person_id else "",
            "personId": d.person_id, "name": d.name, "number": d.number, "version": d.version, "days": d.days,
            "amountHt": d.amount_ht, "vatRate": d.vat_rate, "amountTtc": d.amount_ttc, "createdAt": d.created_at,
            "projects": d.meta.get("projects", []), "approvers": d.meta.get("approvers", []), "due": d.meta.get("due")}


def _readable(user):
    from django.db.models import Q
    qs = ClientDocument.objects.filter(tenant_id=user.tenant_id).select_related("client", "person")
    if user.is_app_admin:
        return qs
    if _is_client(user) or user.role_id in DEFAULT_PROFILES:
        return qs.filter(readers=user)
    # Profil activé par l'admin / le Pilote : documents des clients de ses projets.
    scope = set(visible_projects(user).values_list("client_id", flat=True))
    return qs.filter(Q(readers=user) | Q(client_id__in=scope)).distinct()


class ClientSpaceView(APIView):
    def get(self, request):
        user = request.user
        _guard(user)
        clients = list(_clients_for(user).order_by("name"))
        client = request.query_params.get("client")
        docs = _readable(user).filter(client__in=clients)
        if client:
            docs = docs.filter(client_id=client)
        if request.query_params.get("period"):
            docs = docs.filter(period=request.query_params["period"])
        if request.query_params.get("person"):
            docs = docs.filter(person_id=request.query_params["person"])
        contracts = {c.client_id: c for c in SupportContract.objects.filter(client__in=clients).prefetch_related("members")}
        lic = license_of(user.tenant)
        out_clients = []
        for c in clients:
            k = contracts.get(c.pk)
            out_clients.append({"code": c.pk, "name": c.name, "support": {
                "enabled": bool(k and k.enabled), "levels": k.levels if k else [], "startsOn": k.starts_on if k else None,
                "endsOn": k.ends_on if k else None, "members": [{"id": u.pk, "name": u.display_name, "role": u.role.label if u.role else ""}
                                                                 for u in k.members.select_related("role")] if k else [],
                **({"rates": k.rates} if k and (user.is_app_admin or not _is_client(user)) else {})}})
        pending = TimeEntry.objects.filter(tenant_id=user.tenant_id, approval_status="client", project__client__in=clients)
        people = []
        if not _is_client(user):
            since = timezone.localdate().replace(day=1) - timezone.timedelta(days=95)
            people = [{"id": pid, "name": f"{fn} {ln}".strip() or un} for pid, fn, ln, un in
                      TimeEntry.objects.filter(tenant_id=user.tenant_id, project__client__in=clients, work_date__gte=since)
                      .values_list("person_id", "person__first_name", "person__last_name", "person__username").distinct()]
        return Response({"clients": out_clients, "documents": [_doc_row(d) for d in docs[:500]],
                         "isClient": _is_client(user), "isAdmin": user.is_app_admin, "supportLicense": lic,
                         "levels": [{"code": c, "label": l} for c, l in LEVELS], "people": people,
                         "clientValidationPending": pending.count() if (_is_client(user) or user.is_app_admin) else 0,
                         "canGenerate": user.is_app_admin or visible_projects(user).filter(pm=user).exists(),
                         "billing": billing.settings_of(user.tenant) if user.is_app_admin else None})


class ClientDocumentView(APIView):
    def get(self, request, doc_id):
        _guard(request.user)
        d = get_object_or_404(_readable(request.user), pk=doc_id)
        audit.record(request.user, f"Client {d.client.name}", f"{d.get_kind_display()} consulté", "", d.name)
        resp = HttpResponse(bytes(d.content), content_type=d.mime)
        resp["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(d.name)}"
        resp["X-Content-Type-Options"] = "nosniff"
        return resp


class GenerateView(APIView):
    def post(self, request):
        user = request.user
        _guard(user)
        client = get_object_or_404(_clients_for(user), pk=request.data.get("client"))
        person = get_object_or_404(User.objects.filter(tenant_id=user.tenant_id), pk=request.data.get("person"))
        period = str(request.data.get("period") or "")
        if len(period) != 7:
            raise ApiError("VALIDATION_ERROR", "Période attendue : AAAA-MM.")
        is_pm = visible_projects(user).filter(pm=user, client=client).exists()
        if not (user.is_app_admin or is_pm):
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé au chef de projet du client et à l'administrateur.", status.HTTP_403_FORBIDDEN)
        try:
            cra, inv, created = billing.generate(user.tenant, person, client, period, user, force=bool(request.data.get("force")))
        except billing.BillingError as exc:
            raise ApiError("VALIDATION_ERROR", str(exc)) from exc
        return Response({"created": created, "cra": _doc_row(cra), "invoice": _doc_row(inv) if inv else None})


class TimeValidationView(APIView):
    """Validation des temps par le client (après le valideur interne), par personne et par mois."""

    def _scope(self, user):
        _guard(user)
        if not (_is_client(user) or user.is_app_admin):
            raise ApiError("FORBIDDEN_PERMISSION", "La validation client est réservée aux comptes du client.", status.HTTP_403_FORBIDDEN)
        return _clients_for(user)

    def get(self, request):
        clients = self._scope(request.user)
        hpd = hours_per_day(request.user.tenant) or Decimal("8")
        groups = defaultdict(lambda: {"hours": Decimal("0"), "entries": [], "projects": set()})
        qs = (TimeEntry.objects.filter(tenant_id=request.user.tenant_id, approval_status="client", project__client__in=clients)
              .select_related("person", "project", "action", "approved_by").order_by("work_date"))
        for e in qs:
            key = (e.project.client_id, e.person_id, f"{e.work_date:%Y-%m}")
            g = groups[key]
            g.update(client=e.project.client_id, clientName=e.project.client.name, person=e.person_id, personName=e.person.display_name,
                     period=key[2], periodLabel=billing.label(key[2]))
            g["hours"] += e.hours
            g["projects"].add(e.project.code)
            g["entries"].append({"id": e.id, "date": e.work_date, "project": e.project.code, "task": e.action.title if e.action_id else "Activité générale",
                                 "hours": e.hours, "approvedBy": e.approved_by.display_name if e.approved_by_id else ""})
        return Response([{**{k: v for k, v in g.items() if k != "projects"}, "projects": sorted(g["projects"]),
                          "days": (g["hours"] / hpd).quantize(Decimal("0.01"))} for g in groups.values()])

    def post(self, request):
        clients = self._scope(request.user)
        client = get_object_or_404(clients, pk=request.data.get("client"))
        decision = request.data.get("decision")
        if decision not in ("approved", "rejected"):
            raise ApiError("VALIDATION_ERROR", "Choisissez valider ou refuser.")
        comment = str(request.data.get("comment") or "").strip()[:500]
        if decision == "rejected" and not comment:
            raise ApiError("VALIDATION_ERROR", "Indiquez le motif du refus.")
        period = str(request.data.get("period") or "")
        first, last = billing.bounds(period)
        qs = TimeEntry.objects.filter(tenant_id=request.user.tenant_id, approval_status="client", project__client=client,
                                      person_id=request.data.get("person"), work_date__range=(first, last))
        if isinstance(request.data.get("entries"), list) and request.data["entries"]:
            qs = qs.filter(pk__in=[int(x) for x in request.data["entries"] if str(x).isdigit()])  # saisies choisies une à une
        entries = list(qs.select_related("person", "project"))
        if not entries:
            raise ApiError("CONFLICT", "Rien à valider pour cette personne sur ce mois.", status.HTTP_409_CONFLICT)
        now = timezone.now()
        for e in entries:  # save() un par un : budget et CRA se recalculent automatiquement (signaux)
            e.approval_status, e.approved_by, e.approved_at = decision, request.user, now
            e.save(update_fields=["approval_status", "approved_by", "approved_at"])
        person = entries[0].person
        audit.record(request.user, f"Client {client.name}", "Temps validés par le client" if decision == "approved" else "Temps refusés par le client",
                     "Chez le client", f"{person.display_name} · {billing.label(period)} · {len(entries)} saisie(s) {comment}")
        from projects.timesheet_reminders import _send
        pms = {e.project.pm for e in entries if e.project.pm_id}
        for u in {person, *pms}:
            _send(u, f"Temps de {billing.label(period)} {'validés' if decision == 'approved' else 'refusés'} par le client",
                  f"{request.user.display_name} ({client.name}) a {'validé' if decision == 'approved' else 'refusé'} {len(entries)} saisie(s) de "
                  f"{person.display_name}" + (f". Motif : {comment}" if comment else "."))
        generated = None
        if decision == "approved" and timezone.localdate() > last:
            res = billing.try_generate(request.user.tenant, person.pk, client.pk, period, request.user)
            generated = res[1].number if res and res[1] else None
        return Response({"updated": len(entries), "invoice": generated})


class SupportView(APIView):
    def get(self, request):
        _guard(request.user)
        if not request.user.is_app_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé à l'administrateur.", status.HTTP_403_FORBIDDEN)
        staff = User.objects.filter(tenant_id=request.user.tenant_id, is_active=True, role_id__in=LEVEL_ROLE.values()).select_related("role")
        return Response({"license": license_of(request.user.tenant), "levels": [{"code": c, "label": l} for c, l in LEVELS],
                         "staff": [{"id": u.pk, "name": u.display_name, "role": u.role_id, "roleLabel": u.role.label} for u in staff]})

    def put(self, request):
        _guard(request.user)
        if not request.user.is_app_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé à l'administrateur.", status.HTTP_403_FORBIDDEN)
        lic = license_of(request.user.tenant)
        client = get_object_or_404(Client.objects.filter(tenant_id=request.user.tenant_id), pk=request.data.get("client"))
        contract, _ = SupportContract.objects.get_or_create(tenant=request.user.tenant, client=client)
        enabled = bool(request.data.get("enabled", contract.enabled))
        if enabled and not lic["enabled"]:
            raise ApiError("FORBIDDEN_PERMISSION", "La licence support n'est pas accordée à votre entreprise (à demander au Pilote).",
                           status.HTTP_403_FORBIDDEN)
        if enabled and lic["maxClients"] and not contract.enabled and \
                SupportContract.objects.filter(tenant=request.user.tenant, enabled=True).count() >= lic["maxClients"]:
            raise ApiError("FORBIDDEN_PERMISSION", f"Licence support limitée à {lic['maxClients']} client(s).", status.HTTP_403_FORBIDDEN)
        levels = [lv for lv in (request.data.get("levels") or contract.levels) if lv in lic["levels"]]
        contract.enabled, contract.levels = enabled, levels
        if isinstance(request.data.get("rates"), dict):
            contract.rates = {k: v for k, v in request.data["rates"].items() if k in LEVEL_ROLE and str(v).replace(".", "", 1).isdigit()}
        for f in ("startsOn", "endsOn"):
            if f in request.data:
                from django.utils.dateparse import parse_date
                setattr(contract, "starts_on" if f == "startsOn" else "ends_on", parse_date(str(request.data[f] or "")) or None)
        contract.updated_by = request.user
        contract.save()
        if isinstance(request.data.get("members"), list):
            roles = {LEVEL_ROLE[lv] for lv in levels}
            members = User.objects.filter(tenant_id=request.user.tenant_id, pk__in=request.data["members"], role_id__in=roles)
            contract.members.set(members)
        n = sync_access(contract, request.user)
        audit.record(request.user, f"Client {client.name}", "Contrat de support modifié", "",
                     f"{'actif' if enabled else 'inactif'} · {', '.join(levels)} · {contract.members.count()} membre(s) · {n} accès projet")
        return ClientSpaceView().get(request)


class BillingSettingsView(APIView):
    def put(self, request):
        _guard(request.user)
        if not request.user.is_app_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé à l'administrateur.", status.HTTP_403_FORBIDDEN)
        conf = billing.save_settings(request.user.tenant, request.data or {})
        audit.record(request.user, "Facturation", "Paramètres de facturation modifiés", "", f"TVA {conf['vatRate']} % · {conf['paymentDays']} j")
        return Response(conf)


class ProfilesView(APIView):
    """Profils ayant accès au module CRA & facturation : GET/PUT (administrateur)."""

    def get(self, request):
        if not in_active_tenant(request.user) or not request.user.is_app_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé à l'administrateur.", status.HTTP_403_FORBIDDEN)
        from accounts.models import Role
        from django.db.models import Q
        roles = Role.objects.filter(Q(tenant__isnull=True) | Q(tenant=request.user.tenant)).exclude(code__in=["superadmin", "support"])
        return Response({"enabled": enabled_profiles(request.user.tenant),
                         "roles": [{"code": r.code, "label": r.label, "internal": r.internal} for r in roles]})

    def put(self, request):
        if not in_active_tenant(request.user) or not request.user.is_app_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé à l'administrateur.", status.HTTP_403_FORBIDDEN)
        return Response(_save_profiles(request.user.tenant, request.data.get("roles"), request.user))


def _save_profiles(tenant, roles, by):
    from configuration.models import AppSetting
    roles = [str(r)[:20] for r in (roles or []) if r not in ("superadmin", "support")]
    old = enabled_profiles(tenant)
    AppSetting.objects.update_or_create(tenant=tenant, key=PROFILES_KEY, defaults={"value": {"roles": roles}})
    audit.record(by, "CRA & facturation", "Profils ayant accès modifiés", ", ".join(old), ", ".join(roles),
                 tenant=None if by.is_platform_admin else tenant)
    return {"enabled": roles}


class PilotProfilesView(APIView):
    def get(self, request, tenant_id):
        if not request.user.is_platform_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé au Pilote.", status.HTTP_403_FORBIDDEN)
        from tenants.models import Tenant
        from accounts.models import Role
        t = get_object_or_404(Tenant, pk=tenant_id)
        return Response({"tenant": t.name, "enabled": enabled_profiles(t),
                         "roles": [{"code": r.code, "label": r.label} for r in Role.objects.filter(tenant__isnull=True).exclude(code__in=["superadmin", "support"])]})

    def put(self, request, tenant_id):
        if not request.user.is_platform_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé au Pilote.", status.HTTP_403_FORBIDDEN)
        from tenants.models import Tenant
        return Response(_save_profiles(get_object_or_404(Tenant, pk=tenant_id), request.data.get("roles"), request.user))


class PilotSupportLicenseView(APIView):
    def _pilot(self, request):
        if not request.user.is_platform_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé au Pilote.", status.HTTP_403_FORBIDDEN)

    def get(self, request, tenant_id):
        self._pilot(request)
        from tenants.models import Tenant
        t = get_object_or_404(Tenant, pk=tenant_id)
        return Response({"tenant": t.name, **license_of(t), "allLevels": [{"code": c, "label": l} for c, l in LEVELS]})

    def put(self, request, tenant_id):
        self._pilot(request)
        from tenants.models import Tenant
        t = get_object_or_404(Tenant, pk=tenant_id)
        lic = save_license(t, request.data or {})
        audit.record(request.user, f"Entreprise {t.name}", "Licence support modifiée", "",
                     f"{'accordée' if lic['enabled'] else 'retirée'} · {', '.join(lic['levels'])}", tenant=None)
        for contract in SupportContract.objects.filter(tenant=t):
            sync_access(contract)
        return self.get(request, tenant_id)
