"""Mot de passe oublié : envoi d'un lien de réinitialisation par e-mail, puis choix d'un nouveau mot de passe.

- Le lien utilise le générateur de jetons de Django : il est signé, lié à l'état du compte (il devient
  invalide dès que le mot de passe change ou après une connexion) et expire après PASSWORD_RESET_TIMEOUT.
- La demande répond toujours la même chose, que le compte existe ou non (pas d'énumération des comptes).
- L'e-mail part par le canal SMTP configuré par l'entreprise dans Configuration › Notifications.
"""
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.db.models import Q
from django.utils.decorators import method_decorator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.csrf import csrf_protect
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from config.errors import ApiError
from configuration import audit, notify
from configuration.models import NotificationChannel

from .serializers import validate_new_password

logger = logging.getLogger("accounts")

GENERIC_ANSWER = (
    "Si un compte correspond à cette adresse, un e-mail contenant un lien de réinitialisation vient d'être envoyé."
)


class ForgotPasswordSerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=254)


class ResetPasswordSerializer(serializers.Serializer):
    uid = serializers.CharField(max_length=64)
    token = serializers.CharField(max_length=128)
    new_password = serializers.CharField(max_length=128, trim_whitespace=False)


def _reset_link(request, uid, token):
    base = settings.PUBLIC_BASE_URL or request.build_absolute_uri("/").rstrip("/")
    return f"{base}/?reset={uid}&token={token}"


def _send_reset_mail(request, user):
    """Envoie le lien ; renvoie False (sans lever) si l'entreprise n'a pas de canal e-mail utilisable."""
    channel = None
    if user.tenant_id:
        channel = NotificationChannel.objects.filter(tenant_id=user.tenant_id, kind="email").first()
    if channel is None or not channel.enabled or not channel.settings.get("host"):
        return False
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    minutes = max(1, settings.PASSWORD_RESET_TIMEOUT // 60)
    body = (
        f"Bonjour {user.get_full_name() or user.username},\n\n"
        "Une réinitialisation du mot de passe de votre compte Control Tower a été demandée.\n"
        f"Pour choisir un nouveau mot de passe, ouvrez ce lien (valable {minutes} minutes, une seule fois) :\n\n"
        f"{_reset_link(request, uid, token)}\n\n"
        "Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail : votre mot de passe actuel reste valable.\n"
    )
    try:
        notify.send_email(channel, [user.email], "Réinitialisation de votre mot de passe Control Tower", body)
    except notify.ChannelError:
        return False
    return True


@method_decorator(csrf_protect, name="post")
class ForgotPasswordView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        data = ForgotPasswordSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        identifier = data.validated_data["identifier"].strip()
        users = (
            get_user_model()
            .objects.filter(Q(email__iexact=identifier) | Q(username__iexact=identifier), is_active=True)
            .exclude(email="")
            .select_related("tenant")[:5]
        )
        for user in users:
            if user.auth_mode == "sso" or (user.tenant_id and user.tenant.status != "active"):
                audit.record(None, f"Utilisateur {user.username}", "Réinitialisation du mot de passe refusée",
                             tenant=user.tenant, result="denied")
                continue
            sent = _send_reset_mail(request, user)
            audit.record(
                None,
                f"Utilisateur {user.username}",
                "Lien de réinitialisation envoyé" if sent else "Réinitialisation demandée (aucun canal e-mail)",
                tenant=user.tenant,
                result="success" if sent else "failure",
            )
        # Même réponse dans tous les cas.
        return Response({"detail": GENERIC_ANSWER})


@method_decorator(csrf_protect, name="post")
class ResetPasswordView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        data = ResetPasswordSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        invalid = ApiError("RESET_LINK_INVALID", "Ce lien n'est plus valable. Faites une nouvelle demande.",
                           status.HTTP_400_BAD_REQUEST)
        try:
            pk = force_str(urlsafe_base64_decode(data.validated_data["uid"]))
            user = get_user_model().objects.select_related("tenant").get(pk=pk, is_active=True)
        except (ValueError, TypeError, OverflowError, get_user_model().DoesNotExist):
            raise invalid from None
        if not default_token_generator.check_token(user, data.validated_data["token"]):
            raise invalid
        if user.auth_mode == "sso":
            raise invalid
        validate_new_password(data.validated_data["new_password"], user)
        user.set_password(data.validated_data["new_password"])
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password"])
        audit.record(None, f"Utilisateur {user.username}", "Mot de passe réinitialisé par lien", tenant=user.tenant)
        user.refresh_from_db(fields=["password"])
        if not user.check_password(data.validated_data["new_password"]):  # confirmation relue en base
            return Response({"detail": "Le mot de passe n'a pas pu être enregistré. Réessayez."}, status=500)
        return Response({"detail": "Mot de passe validé. Vous pouvez vous connecter.", "confirmed": True,
                         "username": user.username})
