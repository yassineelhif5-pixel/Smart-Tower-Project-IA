"""Format d'erreur unique de l'API, repris de la page existante :
{"code": "...", "message": "...", "details": [...], "traceId": "..."}.
"""
import logging
import uuid

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from .errors import ApiError, PasswordChangeRequired  # noqa: F401  (réexport)

logger = logging.getLogger("api")


CODES = {
    exceptions.ValidationError: ("VALIDATION_ERROR", "Certaines valeurs sont invalides."),
    exceptions.ParseError: ("BAD_REQUEST", "Requête mal formée."),
    exceptions.NotAuthenticated: ("UNAUTHENTICATED", "Vous devez être connecté."),
    exceptions.AuthenticationFailed: ("UNAUTHENTICATED", "Authentification refusée."),
    exceptions.PermissionDenied: ("FORBIDDEN_PERMISSION", "Vous n'avez pas le droit d'effectuer cette opération."),
    exceptions.NotFound: ("NOT_FOUND", "Élément introuvable."),
    exceptions.MethodNotAllowed: ("METHOD_NOT_ALLOWED", "Méthode non autorisée."),
    exceptions.Throttled: ("TOO_MANY_REQUESTS", "Trop de tentatives. Réessayez dans un instant."),
    exceptions.UnsupportedMediaType: ("UNSUPPORTED_MEDIA_TYPE", "Format de requête non pris en charge."),
}


def _flatten(detail, prefix=""):
    if isinstance(detail, dict):
        out = []
        for key, value in detail.items():
            out += _flatten(value, f"{prefix}{key}." if key != "non_field_errors" else prefix)
        return out
    if isinstance(detail, list):
        out = []
        for value in detail:
            out += _flatten(value, prefix)
        return out
    return [{"field": prefix.rstrip(".") or None, "message": str(detail)}]


def api_exception_handler(exc, context):
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied()

    response = exception_handler(exc, context)
    trace_id = uuid.uuid4().hex[:8]
    if response is None:
        logger.exception("Erreur interne [%s]", trace_id, exc_info=exc)
        return Response(
            {"code": "INTERNAL_ERROR", "message": "Erreur interne du serveur.", "details": [], "traceId": trace_id},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if isinstance(exc, ApiError) or getattr(exc, "error_code", None):
        code, message = exc.error_code, str(exc.detail)
        details = getattr(exc, "details", [])
    else:
        code, message = next(
            (value for klass, value in CODES.items() if isinstance(exc, klass)),
            ("ERROR", "La requête a échoué."),
        )
        details = _flatten(exc.detail) if isinstance(exc, exceptions.ValidationError) else []
        if isinstance(exc, (exceptions.PermissionDenied, exceptions.AuthenticationFailed)) and str(exc.detail) not in (
            exceptions.PermissionDenied.default_detail,
            exceptions.AuthenticationFailed.default_detail,
        ):
            message = str(exc.detail)
    response.data = {"code": code, "message": message, "details": details, "traceId": trace_id}
    return response
