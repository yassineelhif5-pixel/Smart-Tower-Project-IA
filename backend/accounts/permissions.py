from rest_framework.permissions import BasePermission

from config.errors import ApiError, PasswordChangeRequired, TenantInactive

from .models import VERBS, RolePermission

VERB_FIELDS = {verb: f"can_{verb}" for verb, _ in VERBS}


def has_perm(user, module, verb):
    """Équivalent serveur de can('module.verbe') de index.html."""
    if not (user and user.is_authenticated and user.is_active and user.role_id and user.tenant_id):
        return False
    cache = getattr(user, "_perm_cache", None)
    if cache is None:
        # Matrice du tenant de l'utilisateur uniquement : un tenant ne subit jamais les réglages d'un autre.
        cache = {p.module: p for p in RolePermission.objects.filter(role_id=user.role_id, tenant_id=user.tenant_id)}
        # Les fonctionnalités de l'offre souscrite limitent les modules, quelle que soit la matrice.
        from licensing.services import module_enabled
        cache = {m: p for m, p in cache.items() if module_enabled(user.tenant, m)}
        user._perm_cache = cache
    row = cache.get(module)
    return bool(row and getattr(row, VERB_FIELDS[verb]))


class PasswordChangeNotRequired(BasePermission):
    """Bloque toute l'API, sauf la connexion et le changement de mot de passe, tant que le mot de passe provisoire n'est pas changé."""

    def has_permission(self, request, view):
        if request.user and request.user.is_authenticated and request.user.must_change_password:
            raise PasswordChangeRequired()
        return True


class IsAppAdmin(BasePermission):
    """Module Configuration : administrateur de son tenant, en session interactive uniquement (pas de jeton API)."""

    message = "Le module Configuration est réservé aux administrateurs connectés."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_app_admin and request.auth is None)


class IsPlatformAdmin(BasePermission):
    """Administration de la plateforme (tenants, base, supervision) : super administrateur, en session uniquement."""

    message = "Réservé au super administrateur de la plateforme."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_platform_admin and request.auth is None)


class TenantIsActive(BasePermission):
    """Bloque toute l'API pour les utilisateurs d'un tenant suspendu, désactivé ou archivé."""

    def has_permission(self, request, view):
        user = request.user
        if user and user.is_authenticated and user.tenant_id and user.tenant.status != "active":
            raise TenantInactive()
        return True


class IsAnyAdmin(BasePermission):
    """Administrateur de tenant ou Pilote, en session (documentation de l'API)."""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and (user.is_app_admin or user.is_platform_admin) and request.auth is None)


class LicenseIsValid(BasePermission):
    """Vérifie à chaque requête que l'abonnement est valide et que la session détient toujours sa licence.

    Une session dont la licence a été libérée, révoquée ou a expiré est déconnectée (code LICENSE_SESSION_ENDED).
    Les jetons API ne consomment pas de licence concurrente mais exigent un abonnement valide.
    """

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated and user.tenant_id) or user.is_platform_admin:
            return True
        from licensing import services
        if not services.is_enforced(user.tenant):
            return True
        problem = services.subscription_problem(user.tenant)
        if problem:
            raise ApiError(problem.code, problem.message, problem.http_status)
        if request.auth is not None:  # jeton API
            return True
        session = services.active_session(user, request.session.session_key)
        if session is None or not services.touch(session):
            from django.contrib.auth import logout
            logout(request._request)
            raise ApiError("LICENSE_SESSION_ENDED", "Votre session a expiré ou votre licence a été libérée. Reconnectez-vous.", 401)
        return True
