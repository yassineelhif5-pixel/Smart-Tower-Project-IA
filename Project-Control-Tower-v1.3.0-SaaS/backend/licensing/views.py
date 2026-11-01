"""API des offres, abonnements, licences et demandes.

- /api/v1/licensing/…  : espace entreprise (administrateur du tenant ou rôle délégué, selon les droits).
- /api/v1/me/access    : ce que l'utilisateur connecté peut savoir de son propre accès.
- /api/v1/platform/…   : espace Pilote (offres, abonnements, stock, demandes, tableau de bord).
"""
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.capabilities import capabilities_of, has_capability
from accounts.serializers import permissions_of
from config.errors import ApiError
from configuration.views import PlatformView
from tenants.models import Tenant

from . import models as L
from . import services

User = get_user_model()


def fail(exc):
    return ApiError(exc.code, exc.message, exc.http_status)


# --------------------------------------------------------------------------- représentations
def version_row(v):
    return {
        "id": v.id, "number": v.number, "isPublished": v.is_published, "inUse": v.in_use,
        "price": str(v.price) if v.price is not None else None, "currency": v.currency, "billingPeriod": v.billing_period,
        "durationDays": v.duration_days, "trialDays": v.trial_days, "licenseModel": v.license_model,
        "maxUsers": v.max_users, "namedLicenses": v.named_licenses, "concurrentLicenses": v.concurrent_licenses,
        "maxSessionsPerUser": v.max_sessions_per_user, "features": v.features, "limits": v.limits,
        "conditions": v.conditions, "createdAt": v.created_at,
    }


def offer_row(o, with_versions=True):
    row = {"id": o.id, "code": o.code, "name": o.name, "description": o.description, "isActive": o.is_active,
           "position": o.position}
    current = o.current_version
    row["currentVersion"] = version_row(current) if current else None
    if with_versions:
        row["versions"] = [version_row(v) for v in o.versions.all()]
    return row


def subscription_row(s):
    if s is None:
        return None
    v = s.offer_version
    return {
        "id": s.id, "status": s.status, "statusLabel": s.get_status_display(), "startDate": s.start_date,
        "endDate": s.end_date, "trialEnd": s.trial_end, "offer": {"id": v.offer_id, "code": v.offer.code, "name": v.offer.name},
        "version": version_row(v), "contract": {"reference": s.contract.reference, "terms": s.contract.terms} if s.contract else None,
    }


def license_row(lic, holder=None, session=None):
    return {"id": lic.id, "number": lic.number, "kind": lic.kind, "status": lic.status, "statusLabel": lic.get_status_display(),
            "holder": {"id": holder.user_id, "username": holder.user.username, "since": holder.assigned_at} if holder else None,
            "session": {"user": session.user.username, "since": session.started_at} if session else None}


def request_row(r, with_events=False):
    row = {
        "id": r.id, "tenant": {"id": r.tenant_id, "name": r.tenant.name}, "kind": r.kind, "kindLabel": r.get_kind_display(),
        "quantity": r.quantity, "quantityGranted": r.quantity_granted,
        "targetOffer": {"id": r.target_offer_id, "name": r.target_offer.name} if r.target_offer_id else None,
        "justification": r.justification, "status": r.status, "createdAt": r.created_at, "submittedAt": r.submitted_at,
        "decidedAt": r.decided_at, "fulfilledAt": r.fulfilled_at,
        "createdBy": r.created_by.username if r.created_by else None,
    }
    if with_events:
        row["events"] = [{"at": e.at, "actor": e.actor.username if e.actor else None, "from": e.from_status,
                          "to": e.to_status, "comment": e.comment} for e in r.events.select_related("actor")]
    return row


def session_row(s):
    return {"id": s.id, "user": {"id": s.user_id, "username": s.user.username}, "license": s.license.number if s.license else None,
            "mode": "concurrente" if s.license_id else "nominative", "startedAt": s.started_at, "lastSeenAt": s.last_seen_at,
            "expiresAt": s.expires_at}


def overview(tenant):
    sub = services.current_subscription(tenant) if services.is_enforced(tenant) else None
    st = services.stock(tenant)
    active_users = User.objects.filter(tenant=tenant, is_active=True).count()
    active_sessions = L.ConcurrentSession.objects.filter(tenant=tenant, ended_at__isnull=True).count()
    return {
        "enforced": services.is_enforced(tenant), "subscription": subscription_row(sub),
        "stock": st, "users": {"active": active_users, "max": sub.offer_version.max_users if sub else None},
        "activeSessions": active_sessions,
        "pendingRequests": L.LicenseRequest.objects.filter(tenant=tenant, status__in=[L.SUBMITTED, L.UNDER_REVIEW, L.INFO_REQUIRED]).count(),
    }


# --------------------------------------------------------------------------- espace entreprise
class TenantView(APIView):
    """Vue de l'espace entreprise ; `capability` fixe le droit d'administration requis par méthode."""

    capabilities = {}

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.auth is not None:
            self.permission_denied(request, message="Ces opérations exigent une session interactive.")
        code = self.capabilities.get(request.method)
        if code is None or not has_capability(request.user, code):
            self.permission_denied(request, message="Vous n'avez pas le droit d'effectuer cette opération.")

    @property
    def tenant(self):
        return self.request.user.tenant


class OverviewView(TenantView):
    capabilities = {"GET": "licenses.view"}

    def get(self, request):
        return Response(overview(self.tenant))


class LicenseListView(TenantView):
    capabilities = {"GET": "licenses.view"}

    def get(self, request):
        lics = L.License.objects.filter(tenant=self.tenant).exclude(status=L.REVOKED)
        if request.query_params.get("kind") in (L.NAMED, L.CONCURRENT):
            lics = lics.filter(kind=request.query_params["kind"])
        holders = {a.license_id: a for a in L.LicenseAssignment.objects.filter(tenant=self.tenant, released_at__isnull=True).select_related("user")}
        sessions = {s.license_id: s for s in L.ConcurrentSession.objects.filter(tenant=self.tenant, ended_at__isnull=True,
                                                                                license__isnull=False).select_related("user")}
        users = User.objects.filter(tenant=self.tenant, is_active=True).order_by("username")
        licensed = set(a.user_id for a in holders.values())
        return Response({
            "licenses": [license_row(l, holders.get(l.id), sessions.get(l.id)) for l in lics],
            "unlicensedUsers": [{"id": u.id, "username": u.username, "name": u.display_name} for u in users if u.id not in licensed],
        })


class AssignSerializer(serializers.Serializer):
    user = serializers.IntegerField()
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True)


class LicenseActionView(TenantView):
    capabilities = {"POST": "licenses.assign"}

    def post(self, request, pk, action):
        lic = get_object_or_404(L.License, pk=pk, tenant=self.tenant)
        try:
            if action == "release":
                if not has_capability(request.user, "licenses.release"):
                    self.permission_denied(request, message="Vous n'avez pas le droit de libérer une licence.")
                services.release(by=request.user, license=lic, reason=request.data.get("reason", ""))
            else:
                s = AssignSerializer(data=request.data)
                s.is_valid(raise_exception=True)
                user = get_object_or_404(User, pk=s.validated_data["user"], tenant=self.tenant)
                if action == "assign":
                    services.assign(by=request.user, license=lic, user=user)
                elif action == "reassign":
                    if not has_capability(request.user, "licenses.release"):
                        self.permission_denied(request, message="Vous n'avez pas le droit de libérer une licence.")
                    services.reassign(by=request.user, license=lic, user=user, reason=s.validated_data.get("reason", ""))
                else:
                    raise ApiError("NOT_FOUND", "Action inconnue.", status.HTTP_404_NOT_FOUND)
        except services.LicenseError as exc:
            raise fail(exc) from exc
        lic.refresh_from_db()
        holder = L.LicenseAssignment.objects.filter(license=lic, released_at__isnull=True).select_related("user").first()
        return Response(license_row(lic, holder))


class SessionListView(TenantView):
    capabilities = {"GET": "sessions.view"}

    def get(self, request):
        services.expire_sessions(self.tenant)
        rows = L.ConcurrentSession.objects.filter(tenant=self.tenant, ended_at__isnull=True).select_related("user", "license")
        return Response([session_row(s) for s in rows])


class SessionRevokeView(TenantView):
    capabilities = {"POST": "sessions.revoke"}

    def post(self, request, pk):
        session = get_object_or_404(L.ConcurrentSession, pk=pk, tenant=self.tenant, ended_at__isnull=True)
        services.close_session(session, "revoked")
        from configuration import audit
        audit.record(request.user, f"Session de {session.user.username}", "Session révoquée", "", session.license.number if session.license else "")
        return Response(status=status.HTTP_204_NO_CONTENT)


class RequestCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=[k for k, _ in L.REQUEST_KINDS])
    quantity = serializers.IntegerField(min_value=1, max_value=100000, required=False, allow_null=True)
    targetOffer = serializers.IntegerField(required=False, allow_null=True)
    justification = serializers.CharField(max_length=4000)
    submit = serializers.BooleanField(default=True)


class RequestListView(TenantView):
    capabilities = {"GET": "requests.view", "POST": "requests.create"}

    def get(self, request):
        rows = L.LicenseRequest.objects.filter(tenant=self.tenant).select_related("tenant", "created_by", "target_offer")
        return Response([request_row(r) for r in rows])

    def post(self, request):
        s = RequestCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        offer = get_object_or_404(L.Offer, pk=d["targetOffer"], is_active=True) if d.get("targetOffer") else None
        try:
            req = services.create_request(by=request.user, kind=d["kind"], quantity=d.get("quantity"), target_offer=offer,
                                          justification=d["justification"], submit=d["submit"])
        except services.LicenseError as exc:
            raise fail(exc) from exc
        return Response(request_row(req, True), status=status.HTTP_201_CREATED)


class RequestDetailView(TenantView):
    capabilities = {"GET": "requests.view", "POST": "requests.create"}

    def get(self, request, pk):
        return Response(request_row(get_object_or_404(L.LicenseRequest, pk=pk, tenant=self.tenant), True))

    def post(self, request, pk, action):
        req = get_object_or_404(L.LicenseRequest, pk=pk, tenant=self.tenant)
        try:
            if action == "submit":
                services.tenant_move(by=request.user, req=req, status=L.SUBMITTED, comment=request.data.get("comment", ""))
            elif action == "cancel":
                if not has_capability(request.user, "requests.cancel"):
                    self.permission_denied(request, message="Vous n'avez pas le droit d'annuler une demande.")
                services.tenant_move(by=request.user, req=req, status=L.CANCELLED_R, comment=request.data.get("comment", ""))
            elif action == "comment":
                services.comment(by=request.user, req=req, text=request.data.get("comment", ""))
            else:
                raise ApiError("NOT_FOUND", "Action inconnue.", status.HTTP_404_NOT_FOUND)
        except services.LicenseError as exc:
            raise fail(exc) from exc
        req.refresh_from_db()
        return Response(request_row(req, True))


class OfferCatalogView(TenantView):
    """Offres actives, pour demander une évolution (sans prix d'achat ni conditions internes)."""

    capabilities = {"GET": "requests.create"}

    def get(self, request):
        return Response([{"id": o.id, "code": o.code, "name": o.name, "description": o.description}
                         for o in L.Offer.objects.filter(is_active=True)])


class MyAccessView(APIView):
    """Profil d'accès de l'utilisateur connecté : entreprise, licence, statut, rôle, droits, session."""

    def get(self, request):
        user = request.user
        tenant = user.tenant
        sub = services.current_subscription(tenant) if tenant and services.is_enforced(tenant) else None
        lic = services.named_license_of(user) if tenant else None
        session = services.active_session(user, request.session.session_key) if tenant and request.auth is None else None
        return Response({
            "user": {"username": user.username, "name": user.display_name, "email": user.email, "title": user.title},
            "company": {"name": tenant.name, "status": tenant.status} if tenant else None,
            "role": {"code": user.role_id, "label": user.role.label if user.role else None},
            "permissions": permissions_of(user.role_id, tenant) if tenant else {},
            "capabilities": capabilities_of(user) if tenant else [],
            "license": ({"mode": "nominative", "number": lic.number} if lic else
                        {"mode": "concurrente", "number": session.license.number} if session and session.license else
                        {"mode": "non soumis", "number": None} if not sub else {"mode": "aucune", "number": None}),
            "access": {"status": "actif" if not tenant or tenant.status == "active" else tenant.status,
                       "validUntil": (sub.trial_end or sub.end_date) if sub else None,
                       "subscriptionStatus": sub.get_status_display() if sub else None},
            "session": {"startedAt": session.started_at, "expiresAt": session.expires_at} if session else None,
        })


# --------------------------------------------------------------------------- espace Pilote
class VersionSerializer(serializers.Serializer):
    price = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    currency = serializers.CharField(max_length=3, required=False)
    billingPeriod = serializers.ChoiceField(choices=["month", "year", "once"], required=False)
    durationDays = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    trialDays = serializers.IntegerField(min_value=0, required=False)
    licenseModel = serializers.ChoiceField(choices=[m for m, _ in L.LICENSE_MODELS], required=False)
    maxUsers = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    namedLicenses = serializers.IntegerField(min_value=0, required=False)
    concurrentLicenses = serializers.IntegerField(min_value=0, required=False)
    maxSessionsPerUser = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    features = serializers.ListField(child=serializers.CharField(max_length=30), required=False)
    limits = serializers.DictField(required=False)
    conditions = serializers.CharField(required=False, allow_blank=True)
    publish = serializers.BooleanField(required=False)

    FIELDS = {"price": "price", "currency": "currency", "billingPeriod": "billing_period", "durationDays": "duration_days",
              "trialDays": "trial_days", "licenseModel": "license_model", "maxUsers": "max_users",
              "namedLicenses": "named_licenses", "concurrentLicenses": "concurrent_licenses",
              "maxSessionsPerUser": "max_sessions_per_user", "features": "features", "limits": "limits", "conditions": "conditions"}

    def apply(self, version):
        for key, attr in self.FIELDS.items():
            if key in self.validated_data:
                setattr(version, attr, self.validated_data[key])
        if self.validated_data.get("publish"):
            version.is_published = True
        return version


class OfferSerializer(serializers.Serializer):
    code = serializers.SlugField(max_length=30, required=False)
    name = serializers.CharField(max_length=80, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    isActive = serializers.BooleanField(required=False)
    position = serializers.IntegerField(min_value=0, required=False)


class OfferListView(PlatformView):
    def get(self, request):
        return Response([offer_row(o) for o in L.Offer.objects.prefetch_related("versions")])

    def post(self, request):
        s = OfferSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        if not d.get("code") or not d.get("name"):
            raise ApiError("VALIDATION_ERROR", "Le code et le nom de l'offre sont obligatoires.")
        if L.Offer.objects.filter(code=d["code"]).exists():
            raise ApiError("VALIDATION_ERROR", "Ce code d'offre existe déjà.")
        offer = L.Offer.objects.create(code=d["code"], name=d["name"], description=d.get("description", ""),
                                       position=d.get("position", 0))
        from configuration import audit
        audit.record(request.user, f"Offre {offer.name}", "Offre créée", tenant=None)
        return Response(offer_row(offer), status=status.HTTP_201_CREATED)


class OfferDetailView(PlatformView):
    def patch(self, request, pk):
        offer = get_object_or_404(L.Offer, pk=pk)
        s = OfferSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        from configuration import audit
        for key, attr in (("name", "name"), ("description", "description"), ("isActive", "is_active"), ("position", "position")):
            if key in s.validated_data and getattr(offer, attr) != s.validated_data[key]:
                before = getattr(offer, attr)
                setattr(offer, attr, s.validated_data[key])
                audit.record(request.user, f"Offre {offer.name}", f"Offre modifiée ({attr})", before, s.validated_data[key], tenant=None)
        offer.save()
        return Response(offer_row(offer))


class VersionCreateView(PlatformView):
    """Nouvelle version d'une offre (copie de la dernière, puis modifications) : c'est ainsi qu'on change un prix."""

    def post(self, request, pk):
        offer = get_object_or_404(L.Offer, pk=pk)
        s = VersionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        last = offer.versions.order_by("-number").first()
        version = L.OfferVersion(offer=offer, number=(last.number + 1) if last else 1, created_by=request.user)
        if last:
            for attr in VersionSerializer.FIELDS.values():
                setattr(version, attr, getattr(last, attr))
        s.apply(version).save()
        from configuration import audit
        audit.record(request.user, f"Offre {offer.name}", "Version créée", "", f"v{version.number}{' publiée' if version.is_published else ''}", tenant=None)
        return Response(version_row(version), status=status.HTTP_201_CREATED)


class VersionDetailView(PlatformView):
    def patch(self, request, pk):
        version = get_object_or_404(L.OfferVersion, pk=pk)
        s = VersionSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        changing = set(s.validated_data) - {"publish"}
        if changing and (version.in_use or version.is_published):
            raise ApiError("VERSION_LOCKED", "Version publiée ou déjà souscrite : créez une nouvelle version pour la modifier.", status.HTTP_409_CONFLICT)
        s.apply(version).save()
        from configuration import audit
        audit.record(request.user, f"Offre {version.offer.name}", "Version modifiée", "", f"v{version.number}", tenant=None)
        return Response(version_row(version))


class SubscriptionSerializer(serializers.Serializer):
    version = serializers.IntegerField()
    startDate = serializers.DateField(required=False)
    endDate = serializers.DateField(required=False, allow_null=True)
    contractReference = serializers.CharField(max_length=40, required=False, allow_blank=True)
    terms = serializers.CharField(required=False, allow_blank=True)


class SubscriptionChangeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[s for s, _ in L.SUB_STATUSES], required=False)
    endDate = serializers.DateField(required=False)
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True)


class TenantSubscriptionView(PlatformView):
    def get(self, request, pk):
        tenant = get_object_or_404(Tenant, pk=pk)
        history = L.Subscription.objects.filter(tenant=tenant).select_related("offer_version__offer", "contract")
        allocations = L.LicenseAllocation.objects.filter(tenant=tenant).select_related("by")[:100]
        return Response({
            **overview(tenant),
            "history": [subscription_row(s) for s in history],
            "allocations": [{"at": a.at, "kind": a.kind, "delta": a.delta, "reason": a.reason, "request": a.request_id,
                             "by": a.by.username if a.by else None} for a in allocations],
        })

    def post(self, request, pk):
        tenant = get_object_or_404(Tenant, pk=pk)
        s = SubscriptionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        version = get_object_or_404(L.OfferVersion, pk=d["version"])
        try:
            services.create_subscription(by=request.user, tenant=tenant, version=version, start_date=d.get("startDate"),
                                         end_date=d.get("endDate"), contract_reference=d.get("contractReference", ""),
                                         terms=d.get("terms", ""))
        except services.LicenseError as exc:
            raise fail(exc) from exc
        return self.get(request, pk)

    def patch(self, request, pk):
        tenant = get_object_or_404(Tenant, pk=pk)
        sub = L.Subscription.objects.filter(tenant=tenant).order_by("-id").first()
        if sub is None:
            raise ApiError("NOT_FOUND", "Aucun abonnement pour cette entreprise.", status.HTTP_404_NOT_FOUND)
        s = SubscriptionChangeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        try:
            services.change_subscription(by=request.user, sub=sub, status=d.get("status"), end_date=d.get("endDate"),
                                         reason=d.get("reason", ""))
        except services.LicenseError as exc:
            raise fail(exc) from exc
        return self.get(request, pk)


class AllocationSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=[L.NAMED, L.CONCURRENT])
    delta = serializers.IntegerField(min_value=-100000, max_value=100000)
    reason = serializers.CharField(max_length=300)


class TenantAllocationView(PlatformView):
    def post(self, request, pk):
        tenant = get_object_or_404(Tenant, pk=pk)
        s = AllocationSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            services.allocate(by=request.user, tenant=tenant, **s.validated_data)
        except services.LicenseError as exc:
            raise fail(exc) from exc
        return Response(overview(tenant), status=status.HTTP_201_CREATED)


class PilotRequestListView(PlatformView):
    def get(self, request):
        rows = L.LicenseRequest.objects.exclude(status=L.DRAFT).select_related("tenant", "created_by", "target_offer")
        if request.query_params.get("status"):
            rows = rows.filter(status=request.query_params["status"])
        if request.query_params.get("tenant"):
            rows = rows.filter(tenant_id=request.query_params["tenant"])
        return Response([request_row(r) for r in rows])


class DecisionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[L.UNDER_REVIEW, L.INFO_REQUIRED, L.APPROVED, L.PARTIALLY_APPROVED, L.REJECTED],
                                     required=False)
    quantityGranted = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    comment = serializers.CharField(required=False, allow_blank=True, max_length=4000)


class PilotRequestDetailView(PlatformView):
    def get(self, request, pk):
        return Response(request_row(get_object_or_404(L.LicenseRequest.objects.exclude(status=L.DRAFT), pk=pk), True))

    def post(self, request, pk, action):
        req = get_object_or_404(L.LicenseRequest.objects.exclude(status=L.DRAFT), pk=pk)
        s = DecisionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        try:
            if action == "decide":
                if "status" not in d:
                    raise ApiError("VALIDATION_ERROR", "Indiquez la décision.")
                services.pilot_decide(by=request.user, req=req, status=d["status"], quantity_granted=d.get("quantityGranted"),
                                      comment=d.get("comment", ""))
            elif action == "fulfil":
                services.fulfil(by=request.user, req=req, comment=d.get("comment", ""))
            elif action == "comment":
                services.comment(by=request.user, req=req, text=d.get("comment", ""))
            else:
                raise ApiError("NOT_FOUND", "Action inconnue.", status.HTTP_404_NOT_FOUND)
        except services.LicenseError as exc:
            raise fail(exc) from exc
        req.refresh_from_db()
        return Response(request_row(req, True))


class PilotDashboardView(PlatformView):
    def get(self, request):
        tenants = Tenant.objects.all()
        current = {s.tenant_id: s for s in L.Subscription.objects.filter(status__in=L.CURRENT).select_related("offer_version__offer")}
        for s in list(current.values()):
            services._expire_if_due(s)
        current = {t: s for t, s in current.items() if s.status in L.CURRENT}
        lic = L.License.objects.all()
        expired_tenants = [t.id for t in tenants if t.id not in current and L.Subscription.objects.filter(tenant=t).exists()]
        by_offer = {}
        for s in current.values():
            by_offer[s.offer_version.offer.name] = by_offer.get(s.offer_version.offer.name, 0) + 1
        from configuration.models import AuditEvent
        return Response({
            "tenants": {
                "total": tenants.count(), "active": tenants.filter(status="active").count(),
                "suspended": tenants.filter(status="suspended").count(), "disabled": tenants.filter(status="disabled").count(),
                "archived": tenants.filter(status="archived").count(),
                "trial": sum(1 for s in current.values() if s.status == L.TRIAL),
                "withoutSubscription": sum(1 for t in tenants if not L.Subscription.objects.filter(tenant=t).exists()),
            },
            "licenses": {
                "sold": sum(a.delta for a in L.LicenseAllocation.objects.filter(delta__gt=0)),
                "allocated": lic.exclude(status=L.REVOKED).count(),
                "available": lic.filter(status=L.AVAILABLE).count(),
                "used": lic.filter(status__in=[L.ASSIGNED, L.IN_USE]).count(),
                "expired": lic.exclude(status=L.REVOKED).filter(tenant_id__in=expired_tenants).count(),
                "byKind": {k: {"allocated": lic.filter(kind=k).exclude(status=L.REVOKED).count(),
                               "used": lic.filter(kind=k, status__in=[L.ASSIGNED, L.IN_USE]).count()} for k in (L.NAMED, L.CONCURRENT)},
            },
            "subscriptions": {
                "active": sum(1 for s in current.values() if s.status == L.ACTIVE),
                "trial": sum(1 for s in current.values() if s.status == L.TRIAL),
                "suspended": sum(1 for s in current.values() if s.status == L.SUSPENDED),
                "expired": L.Subscription.objects.filter(status=L.EXPIRED).count(),
            },
            "pendingRequests": L.LicenseRequest.objects.filter(status__in=[L.SUBMITTED, L.UNDER_REVIEW]).count(),
            "byOffer": [{"offer": k, "tenants": v} for k, v in sorted(by_offer.items())],
            "recentOperations": [{"at": e.at, "actor": e.actor.username if e.actor else None, "tenant": e.tenant.name if e.tenant else None,
                                  "entity": e.entity, "event": e.event, "result": e.result}
                                 for e in AuditEvent.objects.filter(Q(tenant__isnull=True) | Q(entity__startswith="Abonnement") |
                                                                    Q(entity__startswith="Stock") | Q(entity__startswith="Demande"))
                                 .select_related("actor", "tenant")[:15]],
        })


class TenantAuditView(TenantView):
    """Journal d'activité de l'entreprise : consultation (audit.view) ou export CSV (audit.export, ?export=csv)."""

    capabilities = {"GET": "audit.view"}

    def get(self, request):
        import csv

        from django.http import HttpResponse

        from configuration import audit
        from configuration.models import AuditEvent

        rows = AuditEvent.objects.filter(tenant=self.tenant).select_related("actor")[:5000]
        if request.query_params.get("export") != "csv":
            return Response([{"at": r.at, "actor": r.actor.username if r.actor else None, "entity": r.entity, "event": r.event,
                              "old": r.old_value, "new": r.new_value, "result": r.result, "ip": r.ip, "trace": r.trace}
                             for r in rows[:500]])
        if not has_capability(request.user, "audit.export"):
            self.permission_denied(request, message="Vous n'avez pas le droit d'exporter le journal.")
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="journal-{self.tenant.slug}.csv"'
        response.write("﻿")  # BOM : ouverture correcte dans Excel
        writer = csv.writer(response, delimiter=";")
        writer.writerow(["Date", "Auteur", "Objet", "Événement", "Avant", "Après", "Résultat", "Adresse IP", "Trace"])
        for r in rows:
            # Neutralise les formules (=, +, -, @) : une cellule ne doit jamais s'exécuter dans un tableur.
            safe = lambda v: f"'{v}" if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v
            writer.writerow([r.at.isoformat(), r.actor.username if r.actor else "", safe(r.entity), safe(r.event),
                             safe(r.old_value), safe(r.new_value), r.result, r.ip or "", r.trace])
        audit.record(request.user, "Journal d'activité", "Journal exporté", "", f"{len(rows)} ligne(s)")
        return response
