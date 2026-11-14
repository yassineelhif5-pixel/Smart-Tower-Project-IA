from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import TOKEN_PREFIX, ApiToken

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


class ApiTokenAuthentication(authentication.BaseAuthentication):
    """En-tête « Authorization: Bearer pct_… ». Le jeton agit avec les droits de son utilisateur."""

    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode(errors="ignore").split()
        if not header or header[0] != self.keyword:
            return None
        if len(header) != 2 or not header[1].startswith(TOKEN_PREFIX):
            raise exceptions.AuthenticationFailed("Jeton API invalide.")
        token = ApiToken.objects.select_related("user").filter(token_hash=ApiToken.hash(header[1])).first()
        if not token or not token.is_valid or not token.user.is_active or token.tenant_id != token.user.tenant_id:
            raise exceptions.AuthenticationFailed("Jeton API invalide, expiré ou révoqué.")
        if token.read_only and request.method not in SAFE_METHODS:
            raise exceptions.PermissionDenied("Ce jeton API est en lecture seule.")
        ApiToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
        return token.user, token

    def authenticate_header(self, request):
        return self.keyword
