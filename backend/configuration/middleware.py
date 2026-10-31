import logging
import time

from .models import ApiRequestLog, ApiToken

logger = logging.getLogger("api")


class ApiRequestLogMiddleware:
    """Enregistre chaque appel /api/ : méthode, chemin (sans paramètres), statut, durée, utilisateur ou jeton."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith("/api/"):
            return self.get_response(request)
        start = time.perf_counter()
        response = self.get_response(request)
        duration = (time.perf_counter() - start) * 1000
        try:
            user = getattr(request, "user", None)
            auth = getattr(request, "auth", None)
            ApiRequestLog.objects.create(
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
