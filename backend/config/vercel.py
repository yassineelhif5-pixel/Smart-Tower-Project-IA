"""Adaptations à l'hébergement Vercel."""


class ApiPrefixMiddleware:
    """Garantit que Django voit toujours le chemin public complet (/api/v1/…).

    Avec Vercel Services, le backend reçoit en principe le chemin d'origine. Si une configuration de routage
    retirait le préfixe /api, ce middleware le rétablit : les routes, la journalisation et le CSRF restent
    identiques. Actif uniquement sur Vercel (réglage ON_VERCEL) ; sans effet sur un chemin déjà complet.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path_info.startswith("/api/") and request.path_info != "/api":
            request.path_info = "/api" + (request.path_info if request.path_info.startswith("/") else "/" + request.path_info)
            request.path = request.path_info
            request.META["PATH_INFO"] = request.path_info
        return self.get_response(request)
