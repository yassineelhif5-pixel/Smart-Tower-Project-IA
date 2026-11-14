"""API des offres, abonnements, licences et demandes.

- /api/v1/licensing/…  : espace entreprise (administrateur du tenant ou rôle délégué, selon les droits).
- /api/v1/me/access    : ce que l'utilisateur connecté peut savoir de son propre accès.
- /api/v1/platform/…   : espace Pilote (offres, abonnements, stock, demandes, tableau de bord).
"""
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Min, Q
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import permissions, serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.capabilities import capabilities_of, has_capability
from accounts.permissions import IsPlatformSupport, LicenseIsValid, PasswordChangeNotRequired, TenantIsActive
from accounts.serializers import permissions_of
from config.errors import ApiError
from configuration import audit
from configuration.models import NotificationChannel
from configuration.notify import ChannelError, send_email
from configuration.views import PlatformView
from tenants.models import Tenant

from . import models as L
from . import services

User = get_user_model()


def fail(exc):
    return ApiError(exc.code, exc.message, exc.http_status)


def support_request_row(row):
    return {"id": row.pk, "tenant": row.tenant_id, "tenantName": row.tenant.name,
            "requester": row.requester.display_name if row.requester else "Compte supprimé",
            "email": row.requester.email if row.requester else "", "title": row.title,
            "description": row.description, "category": row.category, "status": row.status,
            "assignedTo": row.assigned_to.username if row.assigned_to else None,
            "createdAt": row.created_at, "updatedAt": row.updated_at,
            "aiStatus": row.ai_status, "aiAnalysis": row.ai_analysis, "aiReply": row.ai_reply}


def run_thor(row):
    """Première analyse locale du ticket; THOR ne consulte ni ne transmet les données externes."""
    text = row.description.casefold()
    checks = ["Vérifier si le problème est reproductible et noter les étapes exactes.",
              "Joindre les messages d'erreur, l'heure du problème et le navigateur utilisé."]
    if any(word in text for word in ("connexion", "connecter", "login", "authentification", "mot de passe")):
        checks.insert(0, "Contrôler l'identifiant, le mode de connexion (standard ou SSO) et l'état du compte.")
    if any(word in text for word in ("lent", "lenteur", "performance", "timeout", "temps de réponse")):
        checks.insert(0, "Comparer le temps de réponse sur une autre page et vérifier si plusieurs utilisateurs sont concernés.")
    if any(word in text for word in ("erreur", "échec", "echoue", "impossible", "bloqué", "bloque")):
        checks.insert(0, "Relever le texte complet de l'erreur et l'action effectuée juste avant son apparition.")
    row.ai_analysis = f"Catégorie : {row.get_category_display()}. Objet : {row.title}.\nPremières vérifications :\n• " + "\n• ".join(checks)
    row.ai_reply = (f"Bonjour, votre demande « {row.title} » a bien été reçue par le support Control Tower. "
                    "THOR a préparé ces premières vérifications pour accélérer le diagnostic. "
                    "Un agent support reste responsable du traitement et vous répondra dans le suivi de cette demande.")
    row.ai_status = "ready"
    row.save(update_fields=["ai_status", "ai_analysis", "ai_reply"])


class PilotMaintenanceView(PlatformView):
    def get(self, request):
        entitlements = L.MaintenanceEntitlement.objects.select_related("tenant", "assigned_by").order_by("tenant__name")
        tickets = L.SupportRequest.objects.select_related("tenant", "requester", "assigned_to").all()
        counts = {row["status"]: row["n"] for row in tickets.values("status").annotate(n=Count("id"))}
        return Response({"entitlements": [{"tenant": row.tenant_id, "tenantName": row.tenant.name,
            "enabled": row.enabled, "plan": row.plan, "startsAt": row.starts_at, "endsAt": row.ends_at,
            "assignedBy": row.assigned_by.username if row.assigned_by else None, "updatedAt": row.updated_at,
            "requestCount": row.tenant.support_requests.count()} for row in entitlements],
            "requests": [support_request_row(row) for row in tickets[:200]],
            "statistics": {"total": tickets.count(), "byStatus": counts}})

    def post(self, request, tenant_id):
        tenant = get_object_or_404(Tenant, pk=tenant_id)
        enabled = request.data.get("enabled")
        if not isinstance(enabled, bool):
            raise ApiError("VALIDATION_ERROR", "Choisissez si la maintenance est active.")
        starts_at, ends_at = request.data.get("startsAt"), request.data.get("endsAt")
        row, created = L.MaintenanceEntitlement.objects.update_or_create(tenant=tenant, defaults={
            "enabled": enabled, "plan": str(request.data.get("plan", "Maintenance Control Tower"))[:80],
            "starts_at": starts_at or None, "ends_at": ends_at or None, "assigned_by": request.user})
        audit.record(request.user, f"Maintenance · {tenant.name}", "Droit attribué" if enabled else "Droit retiré",
              "inactif" if created else ("inactif" if enabled else "actif"), "actif" if enabled else "inactif", tenant=tenant)
        return Response({"tenant": tenant.pk, "enabled": row.enabled, "plan": row.plan,
                         "startsAt": row.starts_at, "endsAt": row.ends_at, "requestCount": tenant.support_requests.count()})


class TenantSupportRequestsView(APIView):
    permission_classes = [permissions.IsAuthenticated, TenantIsActive, LicenseIsValid, PasswordChangeNotRequired]

    def get(self, request):
        if not request.user.tenant_id:
            raise ApiError("FORBIDDEN", "Espace client requis.", status.HTTP_403_FORBIDDEN)
        entitlement = L.MaintenanceEntitlement.objects.filter(tenant=request.user.tenant).first()
        enabled = services.maintenance_enabled(request.user.tenant)
        rows = L.SupportRequest.objects.filter(tenant=request.user.tenant).select_related("tenant", "requester", "assigned_to")
        return Response({"enabled": enabled, "plan": entitlement.plan if entitlement else "",
                         "endsAt": entitlement.ends_at if entitlement else None,
                         "requests": [support_request_row(row) for row in rows[:100]]})

    def post(self, request):
        if not services.maintenance_enabled(request.user.tenant):
            raise ApiError("MAINTENANCE_NOT_ASSIGNED", "Votre entreprise ne dispose pas de l’assistance Control Tower.", status.HTTP_403_FORBIDDEN)
        serializer = serializers.Serializer(data=request.data)
        serializer.fields["title"] = serializers.CharField(max_length=180)
        serializer.fields["description"] = serializers.CharField(max_length=10000)
        serializer.fields["category"] = serializers.ChoiceField(choices=[c for c, _ in L.SupportRequest.CATEGORIES], default="assistance")
        serializer.is_valid(raise_exception=True)
        row = L.SupportRequest.objects.create(tenant=request.user.tenant, requester=request.user,
            title=serializer.validated_data["title"].strip(), description=serializer.validated_data["description"].strip(),
            category=serializer.validated_data["category"])
        run_thor(row)
        row.refresh_from_db()
        audit.record(request.user, f"Assistance · {row.title}", "Demande Control Tower créée", "", row.category, tenant=request.user.tenant)
        return Response(support_request_row(row), status=status.HTTP_201_CREATED)


class SupportQueueView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsPlatformSupport]

    def get(self, request):
        rows = L.SupportRequest.objects.select_related("tenant", "requester", "assigned_to")[:300]
        staff = User.objects.filter(role_id="support", tenant__isnull=True, is_active=True).order_by("username")
        return Response({"requests": [support_request_row(row) for row in rows],
                         "staff": [{"id": user.pk, "username": user.username} for user in staff]})


class HelpChatView(APIView):
    """Aide locale, limitée aux fonctions que la session courante peut consulter."""
    permission_classes = [permissions.IsAuthenticated, TenantIsActive, PasswordChangeNotRequired]

    def post(self, request):
        question = str(request.data.get("question", "")).strip()
        if not question or len(question) > 1200:
            raise ApiError("VALIDATION_ERROR", "Saisissez une question de 1 à 1 200 caractères.")
        q = question.casefold()
        from accounts.permissions import has_perm
        module_hints = {
            "temps": ("timesheet", "Saisie de temps"), "feuille de temps": ("timesheet", "Saisie de temps"),
            "heure": ("timesheet", "Saisie de temps"), "projet": ("project", "Projets"),
            "action": ("action", "Actions"), "budget": ("budget", "Budget"),
            "risque": ("risk", "Risques"), "document": ("document", "Documents"),
            "planning": ("planning", "Planning"), "licence": ("licenses.view", "Licences"),
            "utilisateur": ("users.view", "Utilisateurs"), "profil": ("settings", "Paramétrage des profils"),
        }
        for hint, (code, label) in module_hints.items():
            if hint in q:
                allowed = has_capability(request.user, code) if code in {"licenses.view", "users.view"} else (
                    has_perm(request.user, code, "read") if request.user.tenant_id else False)
                if not allowed:
                    return Response({"answer": f"Je ne peux pas répondre sur {label} : votre profil ne dispose pas du droit de consultation correspondant. Demandez l'accès à votre administrateur."})
                return Response({"answer": f"Vous avez accès au module {label}. Ouvrez-le depuis le menu latéral. Les actions disponibles dépendent des droits attribués à votre profil. Je ne révèle pas de données de projets ou d'autres utilisateurs dans ce chat."})
        if any(word in q for word in ("mot de passe", "réinitialiser", "connexion", "connecter", "sso")):
            answer = "Utilisez la page de connexion avec le mode configuré pour votre compte. Si l'accès échoue ou si vous avez oublié votre mot de passe, contactez l'administrateur de votre entreprise."
        elif any(word in q for word in ("support", "assistance", "incident", "aide")):
            answer = "Pour une demande suivie par l'équipe, ouvrez « Assistance Control Tower » si ce service est activé pour votre entreprise. Décrivez l'objet, les étapes et le message d'erreur; THOR prépare une première orientation et le support traite la demande."
        elif any(word in q for word in ("droit", "autorisation", "accès", "acces", "permission")):
            answer = "Je peux expliquer uniquement les modules autorisés à votre profil. Consultez « Mon accès » pour voir vos droits, ou demandez une évolution à votre administrateur."
        else:
            answer = "Je peux vous guider dans l'utilisation générale de Control Tower. Pour protéger les données, ce chat ne consulte pas les informations métier ni les données d'autres utilisateurs. Reformulez votre question autour d'un module auquel vous avez accès, ou contactez votre administrateur."
        return Response({"answer": answer})

    @transaction.atomic
    def patch(self, request, pk):
        row = get_object_or_404(L.SupportRequest.objects.select_for_update(), pk=pk)
        if "status" in request.data:
            if request.data["status"] not in dict(L.SupportRequest.STATUSES):
                raise ApiError("VALIDATION_ERROR", "État de demande inconnu.")
            row.status = request.data["status"]
            row.resolved_at = timezone.now() if row.status == "resolved" else None
        if "assignedTo" in request.data:
            row.assigned_to = get_object_or_404(User, pk=request.data["assignedTo"], role_id="support", tenant__isnull=True, is_active=True) if request.data["assignedTo"] else None
        row.save()
        return Response(support_request_row(row))


class SupportUserView(PlatformView):
    def get(self, request):
        users = User.objects.filter(role_id="support", tenant__isnull=True).order_by("username")
        return Response([{"id": user.pk, "username": user.username, "email": user.email, "isActive": user.is_active}
                         for user in users])

    def post(self, request):
        serializer = serializers.Serializer(data=request.data)
        serializer.fields["username"] = serializers.RegexField(r"^[\w.@+-]+$", max_length=150)
        serializer.fields["email"] = serializers.EmailField(required=False, allow_blank=True)
        serializer.is_valid(raise_exception=True)
        username = serializer.validated_data["username"]
        if User.objects.filter(username__iexact=username).exists():
            raise ApiError("VALIDATION_ERROR", "Cet identifiant existe déjà.", status.HTTP_409_CONFLICT)
        from configuration.serializers import temporary_password
        password = temporary_password()
        user = User.objects.create(username=username, email=serializer.validated_data.get("email", ""),
                                   role_id="support", tenant=None, is_active=True, must_change_password=True,
                                   auth_mode="standard")
        user.set_password(password)
        user.save(update_fields=["password"])
        audit.record(request.user, f"Compte support {username}", "Agent support créé", "", "actif", tenant=None)
        return Response({"id": user.pk, "username": user.username, "email": user.email,
                         "isActive": user.is_active, "temporaryPassword": password}, status=status.HTTP_201_CREATED)


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
        "targetVersion": ({"id": r.target_version_id, "number": r.target_version.number,
                           "offer": r.target_version.offer.name, "price": str(r.target_version.price) if r.target_version.price is not None else None,
                           "currency": r.target_version.currency, "billingPeriod": r.target_version.billing_period,
                           "namedLicenses": r.target_version.named_licenses,
                           "concurrentLicenses": r.target_version.concurrent_licenses}
                          if r.target_version_id else None),
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
    targetVersion = serializers.IntegerField(required=False, allow_null=True)
    justification = serializers.CharField(max_length=4000)
    submit = serializers.BooleanField(default=True)


class RequestListView(TenantView):
    capabilities = {"GET": "requests.view", "POST": "requests.create"}

    def get(self, request):
        rows = L.LicenseRequest.objects.filter(tenant=self.tenant).select_related("tenant", "created_by", "target_offer", "target_version__offer")
        return Response([request_row(r) for r in rows])

    def post(self, request):
        s = RequestCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        version = get_object_or_404(L.OfferVersion, pk=d["targetVersion"], is_published=True,
                                    offer__is_active=True) if d.get("targetVersion") else None
        offer = version.offer if version else (
            get_object_or_404(L.Offer, pk=d["targetOffer"], is_active=True) if d.get("targetOffer") else None
        )
        if offer is not None and version is None:
            version = offer.current_version
        try:
            req = services.create_request(by=request.user, kind=d["kind"], quantity=d.get("quantity"),
                                          target_offer=offer, target_version=version,
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
    """Versions publiées que le client peut demander ; les conditions internes restent masquées."""

    capabilities = {"GET": "requests.create"}

    def get(self, request):
        rows = []
        for offer in L.Offer.objects.filter(is_active=True).prefetch_related("versions"):
            version = offer.current_version
            if version is None:
                continue
            rows.append({
                "id": offer.id, "code": offer.code, "name": offer.name, "description": offer.description,
                "version": {"id": version.id, "number": version.number, "price": str(version.price) if version.price is not None else None,
                            "currency": version.currency, "billingPeriod": version.billing_period,
                            "licenseModel": version.license_model, "namedLicenses": version.named_licenses,
                            "concurrentLicenses": version.concurrent_licenses, "maxUsers": version.max_users},
            })
        return Response(rows)


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


# --------------------------------------------------------------------------- vouchers
class VoucherBatchSerializer(serializers.Serializer):
    version = serializers.IntegerField()
    targetTenant = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, max_value=500)
    expiresAt = serializers.DateTimeField(required=False, allow_null=True)
    features = serializers.ListField(child=serializers.CharField(max_length=30), required=False, allow_empty=False)
    clientEmail = serializers.EmailField(required=False, allow_blank=True)


class VoucherBatchView(PlatformView):
    def get(self, request):
        rows = L.OfferVoucher.objects.values(
            "batch_id", "offer_version__offer__name", "offer_version__number", "target_tenant__name",
            "expires_at", "created_by__username",
        ).annotate(
            total=Count("id"), redeemed=Count("id", filter=Q(redeemed_at__isnull=False)),
            revoked=Count("id", filter=Q(revoked_at__isnull=False)),
            installed=Count("id", filter=Q(request__status=L.INSTALLED)), created_at=Min("created_at"),
        ).order_by("-created_at")
        return Response([{
            "batchId": row["batch_id"], "offer": row["offer_version__offer__name"],
            "version": row["offer_version__number"], "tenant": row["target_tenant__name"],
            "total": row["total"], "redeemed": row["redeemed"], "installed": row["installed"], "revoked": row["revoked"],
            "expiresAt": row["expires_at"], "createdAt": row["created_at"], "createdBy": row["created_by__username"],
        } for row in rows])

    def post(self, request):
        serializer = VoucherBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        version = get_object_or_404(L.OfferVersion, pk=data["version"], is_published=True, offer__is_active=True)
        tenant = get_object_or_404(Tenant, pk=data["targetTenant"])
        related_request = L.LicenseRequest.objects.filter(
            tenant=tenant, kind="offer", status__in=[L.APPROVED, L.PARTIALLY_APPROVED],
        ).filter(Q(target_version=version) | Q(target_version__isnull=True, target_offer=version.offer)).order_by("-created_at").first()
        expires_at = data.get("expiresAt")
        if expires_at and expires_at <= timezone.now():
            raise ApiError("VALIDATION_ERROR", "La date d'expiration doit être dans le futur.")
        try:
            batch_id, codes = services.issue_voucher_codes(by=request.user, version=version,
                                                           quantity=data["quantity"], target_tenant=tenant,
                                                           expires_at=expires_at, features=data.get("features"),
                                                           request=related_request)
        except services.LicenseError as exc:
            raise fail(exc) from exc
        admin_emails = list(User.objects.filter(tenant=tenant, role_id="admin", is_active=True).exclude(email="")
                            .values_list("email", flat=True))
        client_email = data.get("clientEmail", "").strip()
        recipients = list(dict.fromkeys(([client_email] if client_email else []) + admin_emails))
        email_sent, email_message = False, "Aucun destinataire client ou administrateur avec une adresse e-mail n'a été trouvé."
        email_channel = NotificationChannel.objects.filter(tenant=tenant, kind="email", enabled=True).first()
        if recipients and email_channel:
            try:
                body = (f"Bonjour,\n\nLe Pilote vous transmet {len(codes)} voucher(s) pour {version.offer.name} v{version.number}.\n"
                        f"Entreprise : {tenant.name}\nExpiration : {expires_at or 'sans expiration'}\n\n"
                        f"Codes à usage unique :\n" + "\n".join(codes) +
                        "\n\nChaque code s'impute dans votre espace Licences. Conservez ce message de façon sécurisée.")
                send_email(email_channel, recipients, f"Vos codes d'activation Control Tower · {version.offer.name}", body)
                email_sent, email_message = True, "Codes envoyés aux adresses client et administrateur configurées."
            except ChannelError as exc:
                email_message = str(exc)
        elif recipients:
            email_message = "Le canal e-mail du client n'est pas configuré ou activé."
        return Response({"batchId": batch_id, "offer": version.offer.name, "version": version.number,
                         "tenant": tenant.name, "codes": codes, "expiresAt": expires_at,
                         "features": data.get("features", version.features),
                         "email": {"sent": email_sent, "recipients": recipients, "message": email_message}}, status=status.HTTP_201_CREATED)


class VoucherBatchRevokeView(PlatformView):
    def post(self, request, batch_id):
        qs = L.OfferVoucher.objects.filter(batch_id=batch_id, redeemed_at__isnull=True, revoked_at__isnull=True)
        count = qs.count()
        if not count:
            raise ApiError("NOT_FOUND", "Aucun voucher disponible dans ce lot.", status.HTTP_404_NOT_FOUND)
        qs.update(revoked_at=timezone.now(), revoked_by=request.user)
        from configuration import audit
        audit.record(request.user, f"Vouchers {batch_id}", "Lot de vouchers révoqué", "", f"{count} code(s)", tenant=None)
        return Response({"revoked": count})


class VoucherRedeemSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=80, trim_whitespace=True)


class VoucherRedeemView(APIView):
    permission_classes = [permissions.IsAuthenticated, TenantIsActive, PasswordChangeNotRequired]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "voucher_redeem"

    def post(self, request):
        if not request.user.tenant_id or not has_capability(request.user, "licenses.assign"):
            self.permission_denied(request, message="L'imputation d'un voucher est réservée à un administrateur ou gestionnaire de licences du client.")
        serializer = VoucherRedeemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            subscription = services.redeem_voucher(code=serializer.validated_data["code"], by=request.user)
        except services.LicenseError as exc:
            raise fail(exc) from exc
        return Response({"tenant": subscription.tenant.name, "offer": subscription.offer_version.offer.name,
                         "version": subscription.offer_version.number, "status": subscription.get_status_display(),
                         "endDate": subscription.end_date,
                         "requestStatus": "INSTALLED" if L.LicenseRequest.objects.filter(vouchers__redeemed_at__isnull=False, vouchers__request__isnull=False, vouchers__redeemed_tenant=subscription.tenant, vouchers__offer_version=subscription.offer_version, status=L.INSTALLED).exists() else None})


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
