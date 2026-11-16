"""API de l'inscription libre, de la connexion Google plateforme et du parcours d'accueil."""
from django.contrib.auth import get_user_model, login
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from config.errors import ApiError
from configuration import audit
from licensing import services as license_services

from . import signup
from .models import TenantJoinRequest
from .permissions import IsPlatformAdmin, PasswordChangeNotRequired, TenantIsActive

User = get_user_model()


def open_license_session(request, user):
    """Réserve une licence si l'utilisateur travaille dans une entreprise (sauf démo expirée : parcours d'accueil)."""
    if not user.tenant_id or signup.demo_expired(user):
        return
    if license_services.active_session(user, request.session.session_key):
        return
    license_services.open_session(user, request.session.session_key)


class ProvidersView(APIView):
    """GET /auth/providers : options de la page de connexion (public)."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        from .google_oauth import config
        return Response({"google": config()["enabled"], "signup": True})


@method_decorator(csrf_protect, name="post")
class SignupView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "signup"

    def post(self, request):
        d = request.data or {}
        if not d.get("acceptTerms"):
            raise ApiError("VALIDATION_ERROR", "Acceptez les conditions d'utilisation pour créer votre compte.")
        user = signup.register(email=d.get("email"), password=str(d.get("password") or ""),
                               first_name=d.get("firstName"), last_name=d.get("lastName"), invite_token=d.get("invite", ""))
        if user is not None:
            # Invitation : l'adresse est prouvée par le lien reçu, la session s'ouvre directement.
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            request.session.save()
            try:
                open_license_session(request, user)
            except license_services.LicenseError:
                pass
            return Response({"detail": "Compte créé.", "email": user.email, "loggedIn": True}, status=status.HTTP_201_CREATED)
        return Response({"detail": "Si l'adresse est valide, un e-mail de confirmation vient d'être envoyé.",
                         "email": str(d.get("email") or "").strip().lower()}, status=status.HTTP_201_CREATED)


class SignupVerifyView(APIView):
    """GET /auth/signup/verify?token=… (lien de l'e-mail) : confirme l'adresse puis ouvre la session."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        user = signup.verify(request.query_params.get("token", ""))
        if user is None:
            return HttpResponseRedirect("/?verified=0")
        if user.is_active:
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            request.session.save()
            try:
                open_license_session(request, user)
            except license_services.LicenseError:
                pass
        return HttpResponseRedirect("/?verified=1")


@method_decorator(csrf_protect, name="post")
class SignupResendView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "signup"

    def post(self, request):
        signup.resend((request.data or {}).get("email"))
        return Response({"detail": "Si un compte attend une confirmation, un nouvel e-mail a été envoyé."})


class GoogleStartView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "sso_start"

    def get(self, request):
        from .google_oauth import begin
        from .sso import SSOError
        token = request.query_params.get("invite", "")
        if token:
            request.session["pct_invite"] = token[:100]
        try:
            return HttpResponseRedirect(begin(request))
        except (SSOError, ValueError):
            return HttpResponseRedirect("/?google=unavailable")


class GoogleCallbackView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        from django.contrib.auth import logout
        from .google_oauth import finish
        from .sso import SSOError
        try:
            user = finish(request, request.query_params.get("code", ""), request.query_params.get("state", ""))
        except (SSOError, ValueError):
            return HttpResponseRedirect("/?google=error")
        token = request.session.pop("pct_invite", "")
        if token:
            from . import invitations
            inv = invitations.find(token)
            if inv is not None:
                invitations.accept(inv, user)
                user.refresh_from_db()
        if user.tenant_id and user.tenant.status != "active":
            return HttpResponseRedirect("/?sso=unavailable")
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        request.session.save()
        try:
            open_license_session(request, user)
        except license_services.LicenseError as exc:
            logout(request)
            audit.record(user, f"Utilisateur {user.username}", "Connexion Google refusée (licence)", "", exc.code, result="denied")
            return HttpResponseRedirect("/?sso=unavailable")
        audit.record(user, f"Utilisateur {user.username}", "Connexion Google")
        return HttpResponseRedirect("/")


# --------------------------------------------------------------------------- parcours d'accueil
class OnboardingBase(APIView):
    """Accessible sans entreprise ni licence valide (compte libre, démo expirée)."""

    permission_classes = [permissions.IsAuthenticated, TenantIsActive, PasswordChangeNotRequired]
    onboarding_safe = True

    def state(self, request):
        from .serializers import MeSerializer
        me = MeSerializer(request.user).data
        data = signup.onboarding_state(request.user) or {}
        if data.get("reason") == "demo_expired":
            data["offers"] = signup.activation_offers()
            data["licenseRequest"] = signup.pending_license_request(request.user.tenant)
        return Response({"onboarding": data, "me": me})


class OnboardingView(OnboardingBase):
    def get(self, request):
        return self.state(request)


class OnboardingProfileView(OnboardingBase):
    def post(self, request):
        signup.save_profile(request.user, request.data or {})
        return self.state(request)


class OnboardingDemoView(OnboardingBase):
    def post(self, request):
        try:
            signup.start_demo(request.user)
        finally:
            request.user.refresh_from_db()  # annulation : l'utilisateur en mémoire ne garde pas le tenant supprimé
        try:
            open_license_session(request, request.user)
        except license_services.LicenseError as exc:
            raise ApiError(exc.code, exc.message, exc.http_status) from exc
        return self.state(request)


class OnboardingJoinView(OnboardingBase):
    def post(self, request, pk=None):
        if pk is not None:
            signup.cancel_join(request.user, pk)
        else:
            d = request.data or {}
            signup.request_join(request.user, d.get("code"), d.get("message", ""))
        return self.state(request)


class OnboardingActivateView(OnboardingBase):
    def post(self, request):
        result = signup.activate(request.user, request.data or {})
        resp = self.state(request)
        resp.data["result"] = result
        return resp


class OnboardingEnterView(OnboardingBase):
    """POST : après une adhésion acceptée ou une activation, ouvre la session de licence dans l'entreprise."""

    def post(self, request):
        try:
            open_license_session(request, request.user)
        except license_services.LicenseError as exc:
            raise ApiError(exc.code, exc.message, exc.http_status) from exc
        return self.state(request)


# --------------------------------------------------------------------------- validation des adhésions
def _can_review(user):
    from .capabilities import has_capability
    return bool(user.tenant_id and has_capability(user, "users.approve_sso"))


class TenantJoinRequestsView(APIView):
    """Admin d'entreprise : GET liste + code secret ; POST <id> {action, role, comment} ; POST code {regenerate}."""

    permission_classes = [permissions.IsAuthenticated, TenantIsActive, PasswordChangeNotRequired]

    def _check(self, request):
        from .permissions import LicenseIsValid
        LicenseIsValid().has_permission(request, self)
        if not _can_review(request.user):
            raise ApiError("FORBIDDEN_PERMISSION", "Vous n'êtes pas habilité à traiter les demandes d'accès.", status.HTTP_403_FORBIDDEN)
        return request.user.tenant

    def get(self, request):
        tenant = self._check(request)
        rows = TenantJoinRequest.objects.filter(tenant=tenant).select_related("user", "tenant", "role", "decided_by")[:200]
        return Response({"code": None if tenant.demo_until else signup.join_code_of(tenant), "isDemo": bool(tenant.demo_until),
                         "requests": [signup.join_row(r) for r in rows],
                         "roles": [{"code": r.code, "label": r.label} for r in signup.assignable_roles(tenant)]})

    def post(self, request, pk=None):
        tenant = self._check(request)
        if pk is None:
            if not request.user.is_app_admin:
                raise ApiError("FORBIDDEN_PERMISSION", "Seul un administrateur peut régénérer le code.", status.HTTP_403_FORBIDDEN)
            code = signup.join_code_of(tenant, regenerate=True)
            audit.record(request.user, f"Entreprise {tenant.name}", "Code entreprise régénéré", tenant=tenant)
            return Response({"code": code})
        req = get_object_or_404(TenantJoinRequest, pk=pk, tenant=tenant)
        d = request.data or {}
        if d.get("action") not in ("approve", "reject"):
            raise ApiError("VALIDATION_ERROR", "Choisissez accepter ou refuser.")
        req = signup.decide_join(by=request.user, req=req, approve=d["action"] == "approve",
                                 role_code=d.get("role", ""), comment=d.get("comment", ""))
        return Response(signup.join_row(req))


class PlatformJoinRequestsView(APIView):
    """Pilote : toutes les demandes d'adhésion ; POST <id> pour décider."""

    permission_classes = [permissions.IsAuthenticated, PasswordChangeNotRequired, IsPlatformAdmin]

    def get(self, request):
        status_filter = request.query_params.get("status", "pending")
        rows = TenantJoinRequest.objects.select_related("user", "tenant", "role", "decided_by")
        if status_filter != "all":
            rows = rows.filter(status=status_filter)
        out = []
        for r in rows[:300]:
            row = signup.join_row(r)
            row["roles"] = [{"code": x.code, "label": x.label} for x in signup.assignable_roles(r.tenant)] if r.status == "pending" else []
            out.append(row)
        return Response({"requests": out})

    def post(self, request, pk):
        req = get_object_or_404(TenantJoinRequest, pk=pk)
        d = request.data or {}
        if d.get("action") not in ("approve", "reject"):
            raise ApiError("VALIDATION_ERROR", "Choisissez accepter ou refuser.")
        req = signup.decide_join(by=request.user, req=req, approve=d["action"] == "approve",
                                 role_code=d.get("role", ""), comment=d.get("comment", ""))
        return Response(signup.join_row(req))


class PlatformTenantJoinCodeView(APIView):
    """Pilote : GET/POST /platform/tenants/<id>/join-code (POST = régénérer)."""

    permission_classes = [permissions.IsAuthenticated, PasswordChangeNotRequired, IsPlatformAdmin]

    def get(self, request, pk):
        from tenants.models import Tenant
        t = get_object_or_404(Tenant, pk=pk)
        return Response({"code": None if t.demo_until else signup.join_code_of(t), "isDemo": bool(t.demo_until),
                         "demoUntil": t.demo_until})

    def post(self, request, pk):
        from tenants.models import Tenant
        t = get_object_or_404(Tenant, pk=pk)
        code = signup.join_code_of(t, regenerate=True)
        audit.record(request.user, f"Entreprise {t.name}", "Code entreprise régénéré (Pilote)", tenant=None)
        return Response({"code": code})


class PlatformGoogleView(APIView):
    """Pilote : GET/PUT /platform/config/google {clientId, clientSecret?, enabled}."""

    permission_classes = [permissions.IsAuthenticated, PasswordChangeNotRequired, IsPlatformAdmin]

    def get(self, request):
        from configuration.mailer import app_url
        from .google_oauth import config
        data = config()
        data["redirectUri"] = f"{app_url().rstrip('/')}/api/v1/auth/google/callback"
        data["origin"] = app_url().rstrip("/")
        return Response(data)

    def put(self, request):
        from configuration import crypto
        from configuration.models import PlatformSetting
        from .google_oauth import SETTING_KEY
        d = request.data or {}
        row, _ = PlatformSetting.objects.get_or_create(key=SETTING_KEY)
        v = dict(row.value or {})
        if d.get("reset"):
            row.value = {}
        else:
            client_id = str(d.get("clientId") or "").strip()
            if client_id and not client_id.endswith(".apps.googleusercontent.com"):
                raise ApiError("VALIDATION_ERROR", "L'ID client Google se termine par « .apps.googleusercontent.com ».")
            v["client_id"] = client_id
            if d.get("clientSecret"):
                secret = str(d["clientSecret"]).strip()
                v["client_secret"] = crypto.encrypt(secret)
                v["hint"] = secret[-4:] if len(secret) >= 12 else ""
            v["enabled"] = d.get("enabled", True) is not False
            row.value = v
        row.updated_by = request.user
        row.save()
        audit.record(request.user, "Configuration de la plateforme", "Connexion Google modifiée", "",
                     "réinitialisée" if d.get("reset") else ("activée" if v.get("enabled") else "désactivée"), tenant=None)
        return self.get(request)


# --------------------------------------------------------------------------- invitations
def _inviter_tenant(request, data):
    """Pilote : entreprise facultative (data.tenant) ; admin d'entreprise : la sienne."""
    from tenants.models import Tenant
    from .capabilities import has_capability
    user = request.user
    if user.is_platform_admin:
        tid = data.get("tenant")
        return get_object_or_404(Tenant, pk=tid) if tid not in (None, "", "none") else None
    if not user.tenant_id or not (user.is_app_admin or has_capability(user, "users.create")):
        raise ApiError("FORBIDDEN_PERMISSION", "Seuls le Pilote et les administrateurs peuvent inviter des personnes.",
                       status.HTTP_403_FORBIDDEN)
    if user.tenant.demo_until and not user.is_app_admin:
        raise ApiError("FORBIDDEN_PERMISSION", "Invitation réservée à l'administrateur.", status.HTTP_403_FORBIDDEN)
    return user.tenant


class InvitationsView(APIView):
    """GET : invitations envoyées ; POST {emails, role?, message?, tenant? (Pilote)} : inviter."""

    permission_classes = [permissions.IsAuthenticated, TenantIsActive, PasswordChangeNotRequired]

    def _scope(self, request):
        from .models import Invitation
        rows = Invitation.objects.select_related("tenant", "role", "invited_by", "accepted_user")
        if request.user.is_platform_admin:
            return rows
        tenant = _inviter_tenant(request, {})
        return rows.filter(tenant=tenant)

    def get(self, request):
        from . import invitations
        from .signup import assignable_roles
        rows = self._scope(request)[:300]
        roles = []
        if not request.user.is_platform_admin:
            roles = [{"code": r.code, "label": r.label} for r in assignable_roles(request.user.tenant)]
        return Response({"invitations": [invitations.row(i) for i in rows], "roles": roles})

    def post(self, request):
        from . import invitations
        d = request.data or {}
        tenant = _inviter_tenant(request, d)
        result = invitations.invite(by=request.user, emails_raw=d.get("emails", ""), base_url=request.build_absolute_uri("/"),
                                    tenant=tenant, role_code=d.get("role", ""), message=d.get("message", ""))
        return Response(result, status=status.HTTP_201_CREATED)


class InvitationDetailView(InvitationsView):
    def post(self, request, pk):
        from . import invitations
        inv = get_object_or_404(self._scope(request), pk=pk)
        return Response(invitations.row(invitations.resend(request.user, inv, request.build_absolute_uri("/"))))

    def delete(self, request, pk):
        from . import invitations
        inv = get_object_or_404(self._scope(request), pk=pk)
        return Response(invitations.row(invitations.revoke(inv)))


class InvitationRolesView(APIView):
    """Pilote : profils proposables pour une entreprise donnée (GET ?tenant=)."""

    permission_classes = [permissions.IsAuthenticated, PasswordChangeNotRequired, IsPlatformAdmin]

    def get(self, request):
        from tenants.models import Tenant
        from .signup import assignable_roles
        t = get_object_or_404(Tenant, pk=request.query_params.get("tenant"))
        return Response({"roles": [{"code": r.code, "label": r.label} for r in assignable_roles(t)]})


class InvitationInfoView(APIView):
    """GET /auth/invitation?token= (public) : pour préremplir la page d'inscription."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        from . import invitations
        return Response(invitations.public_info(request.query_params.get("token", "")))


class InvitationAcceptView(OnboardingBase):
    """POST /auth/invitation/accept {token} : un compte existant accepte l'invitation reçue à son adresse."""

    def post(self, request):
        from . import invitations
        inv = invitations.find(str((request.data or {}).get("token") or ""))
        if inv is None:
            raise ApiError("VALIDATION_ERROR", "Invitation invalide ou expirée.")
        if inv.email.lower() != (request.user.email or "").lower():
            raise ApiError("VALIDATION_ERROR", f"Cette invitation est destinée à {inv.email} : connectez-vous avec ce compte.")
        invitations.accept(inv, request.user)
        request.user.refresh_from_db()
        try:
            open_license_session(request, request.user)
        except license_services.LicenseError:
            pass
        return self.state(request)
