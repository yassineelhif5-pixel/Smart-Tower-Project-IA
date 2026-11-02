"""Erreurs métier de l'API (sans dépendance à rest_framework.views, pour éviter les imports circulaires)."""
from rest_framework import exceptions, status


class ApiError(exceptions.APIException):
    """Erreur métier avec un code explicite."""

    def __init__(self, code, message, http_status=status.HTTP_400_BAD_REQUEST, details=None):
        super().__init__(detail=message)
        self.status_code = http_status
        self.error_code = code
        self.details = details or []


class PasswordChangeRequired(exceptions.PermissionDenied):
    default_detail = "Vous devez changer votre mot de passe avant de continuer."
    error_code = "PASSWORD_CHANGE_REQUIRED"


class TenantInactive(exceptions.PermissionDenied):
    default_detail = "L'accès à votre organisation est suspendu. Contactez votre administrateur."
    error_code = "TENANT_INACTIVE"
