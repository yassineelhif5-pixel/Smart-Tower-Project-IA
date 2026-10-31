from rest_framework.permissions import BasePermission

from config.errors import PasswordChangeRequired

from .models import VERBS, RolePermission

VERB_FIELDS = {verb: f"can_{verb}" for verb, _ in VERBS}


def has_perm(user, module, verb):
    """Équivalent serveur de can('module.verbe') de index.html."""
    if not (user and user.is_authenticated and user.is_active and user.role_id):
        return False
    cache = getattr(user, "_perm_cache", None)
    if cache is None:
        cache = {p.module: p for p in RolePermission.objects.filter(role_id=user.role_id)}
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
    """Module Configuration : rôle Administrateur, en session interactive uniquement (pas de jeton API)."""

    message = "Le module Configuration est réservé aux administrateurs connectés."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_app_admin and request.auth is None)
