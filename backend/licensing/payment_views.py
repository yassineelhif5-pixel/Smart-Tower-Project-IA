"""API du paiement en ligne (Stripe Checkout)."""
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.capabilities import has_capability
from accounts.permissions import IsPlatformAdmin, PasswordChangeNotRequired, TenantIsActive
from config.errors import ApiError
from tenants.models import Tenant

from . import models as L
from . import payments


def _base_url(request):
    return request.build_absolute_uri("/").rstrip("/")


def _resolve(request, data):
    """Entreprise concernée : celle demandée par le Pilote, sinon celle de l'utilisateur (admin ou gestionnaire)."""
    user = request.user
    req_id = data.get("request")
    if user.is_platform_admin:
        req = get_object_or_404(L.LicenseRequest.objects.select_related("tenant", "target_version__offer"), pk=req_id) if req_id else None
        tenant = req.tenant if req else get_object_or_404(Tenant, pk=data.get("tenant"))
        return tenant, req
    if request.auth is not None or not user.tenant_id:
        raise ApiError("FORBIDDEN_PERMISSION", "Paiement réservé aux administrateurs connectés.", status.HTTP_403_FORBIDDEN)
    if not (user.is_app_admin or has_capability(user, "requests.create")):
        raise ApiError("FORBIDDEN_PERMISSION", "Seul un administrateur de l'entreprise peut payer un abonnement.", status.HTTP_403_FORBIDDEN)
    req = (get_object_or_404(L.LicenseRequest.objects.select_related("tenant", "target_version__offer"), pk=req_id, tenant=user.tenant)
           if req_id else None)
    return user.tenant, req


class PaymentBase(APIView):
    permission_classes = [permissions.IsAuthenticated, TenantIsActive, PasswordChangeNotRequired]
    onboarding_safe = True  # une démo terminée peut payer son abonnement


class PaymentOptionsView(PaymentBase):
    """GET /payments/options?tenant=&request= : offres payables, prix des licences, abonnement actuel."""

    def get(self, request):
        tenant, req = _resolve(request, request.query_params)
        return Response(payments.options(tenant, req))


class PaymentCheckoutView(PaymentBase):
    """POST /payments/checkout {mode, versionId | licenseKind+quantity, tenant?, request?} → {url, paymentId}."""

    def post(self, request):
        d = request.data or {}
        tenant, req = _resolve(request, d)
        if req is not None and req.status not in (L.APPROVED, L.PARTIALLY_APPROVED, L.SUBMITTED, L.UNDER_REVIEW):
            raise ApiError("VALIDATION_ERROR", "Cette demande ne peut plus être payée (déjà exécutée, refusée ou annulée).")
        p = payments.checkout(by=request.user, tenant=tenant, base_url=_base_url(request), mode=d.get("mode"),
                              version_id=d.get("versionId"), license_kind=d.get("licenseKind", ""),
                              quantity=d.get("quantity", 1), request_obj=req)
        return Response({"url": p.checkout_url, "paymentId": p.pk, "payment": payments.payment_row(p)}, status=status.HTTP_201_CREATED)


class PaymentConfirmView(PaymentBase):
    """POST /payments/confirm {sessionId} : retour de Stripe, applique le paiement s'il est confirmé."""

    def post(self, request):
        sid = str((request.data or {}).get("sessionId") or "").strip()
        if not sid.startswith("cs_"):
            raise ApiError("VALIDATION_ERROR", "Session de paiement invalide.")
        p = payments.confirm(sid, request.user)
        if p.status == L.Payment.APPLIED and request.user.tenant_id == p.tenant_id:
            # L'activation de l'offre ferme les sessions de l'entreprise : on rouvre celle du payeur.
            from accounts.signup_views import open_license_session
            from . import services as lic
            try:
                open_license_session(request, request.user)
            except lic.LicenseError:
                pass
        return Response(payments.payment_row(p))


class PaymentListView(PaymentBase):
    def get(self, request):
        user = request.user
        rows = L.Payment.objects.select_related("tenant", "offer_version__offer", "created_by")
        if user.is_platform_admin:
            if request.query_params.get("tenant"):
                rows = rows.filter(tenant_id=request.query_params["tenant"])
        else:
            tenant, _ = _resolve(request, {})
            rows = rows.filter(tenant=tenant)
        return Response({"payments": [payments.payment_row(p) for p in rows[:200]]})


class StripeWebhookView(APIView):
    """POST /payments/stripe/webhook : événements Stripe signés (aucune session, aucun cookie)."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        kind = payments.webhook(request.body, request.headers.get("Stripe-Signature", ""))
        return Response({"received": True, "type": kind})


class PlatformStripeView(APIView):
    """Pilote : GET/PUT /platform/config/stripe."""

    permission_classes = [permissions.IsAuthenticated, PasswordChangeNotRequired, IsPlatformAdmin]

    def get(self, request):
        data = payments.config()
        base = _base_url(request)
        data["webhookUrl"] = f"{base}/api/v1/payments/stripe/webhook"
        data["events"] = ["checkout.session.completed", "checkout.session.expired", "checkout.session.async_payment_succeeded",
                          "customer.subscription.deleted", "invoice.payment_failed"]
        return Response(data)

    def put(self, request):
        payments.save_config(request.user, request.data or {})
        return self.get(request)
