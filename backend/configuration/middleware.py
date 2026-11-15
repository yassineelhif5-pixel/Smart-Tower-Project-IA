import logging
import time

from . import context
from .models import ApiRequestLog, ApiToken

logger = logging.getLogger("api")


class ApiRequestLogMiddleware:
    """Enregistre chaque appel /api/ : méthode, chemin (sans paramètres), statut, durée, utilisateur ou jeton."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith("/api/"):
            return self.get_response(request)
        # L'adresse IP sert au journal d'audit des opérations sensibles ; le journal des appels n'en garde aucune.
        token = context.set_client_ip(context.client_ip_of(request))
        req_token = context.set_request(request)
        start = time.perf_counter()
        try:
            response = self.get_response(request)
        finally:
            context.reset(token)
            context.reset_request(req_token)
        duration = (time.perf_counter() - start) * 1000
        try:
            user = getattr(request, "user", None)
            auth = getattr(request, "auth", None)
            authenticated = user is not None and user.is_authenticated
            ApiRequestLog.objects.create(
                tenant_id=user.tenant_id if authenticated else None,
                method=request.method[:8],
                path=request.path[:300],
                status=response.status_code,
                duration_ms=round(duration, 2),
                user=user if (user is not None and user.is_authenticated) else None,
                token=auth if isinstance(auth, ApiToken) else None,
            )
        except Exception:  # le journal ne doit jamais faire échouer la requête
            logger.warning("Écriture du journal API impossible", exc_info=True)
        return response


class PilotConfigMiddleware:
    """Le Pilote administre la configuration d'une entreprise depuis le menu Configuration.

    Quand un Pilote (super administrateur de la plateforme, session interactive) envoie l'en-tête X-Pilot-Tenant, la
    requête est traitée comme celle d'un administrateur de cette entreprise : mêmes écrans, mêmes contrôles, mêmes
    journaux d'audit (auteur : le Pilote, entreprise : celle choisie). L'objet utilisateur n'est modifié qu'en mémoire,
    pour cette seule requête ; l'authentification et l'espace Pilote (/auth, /platform) ne sont jamais concernés.
    """

    SKIP = ("/api/v1/auth/", "/api/v1/platform/", "/api/auth/", "/api/platform/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tid = request.META.get("HTTP_X_PILOT_TENANT")
        if tid and request.path.startswith("/api/") and not request.path.startswith(self.SKIP):
            try:
                user = request.user
                if user.is_authenticated and user.is_platform_admin and str(tid).isdigit():
                    from accounts.models import ADMIN_ROLE, Role
                    from tenants.models import Tenant
                    tenant = Tenant.objects.filter(pk=int(tid)).first()
                    role = Role.objects.filter(code=ADMIN_ROLE).first()
                    if tenant is not None and role is not None:
                        user.tenant = tenant
                        user.role = role
                        user.pilot_mode = True
                        user.save = _no_save  # garde-fou : jamais d'enregistrement du Pilote dans l'entreprise
            except Exception:  # noqa: BLE001
                logger.warning("Mode Pilote : en-tête ignoré", exc_info=True)
        return self.get_response(request)


def _no_save(*args, **kwargs):
    return None
