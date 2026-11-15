"""Contexte technique de la requête en cours (adresse IP), lu par le journal d'audit."""
from contextvars import ContextVar

from django.conf import settings

_client_ip = ContextVar("client_ip", default=None)


def client_ip_of(request):
    if getattr(settings, "TRUST_X_FORWARDED_FOR", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip()[:45] or None
    return request.META.get("REMOTE_ADDR") or None


def set_client_ip(ip):
    return _client_ip.set(ip)


def reset(token):
    _client_ip.reset(token)


def current_ip():
    return _client_ip.get()


_request = ContextVar("current_request", default=None)


def set_request(request):
    return _request.set(request)


def reset_request(token):
    _request.reset(token)


def current_user():
    """Utilisateur authentifié de la requête en cours (auteur d'une modification), ou None (tâche planifiée…)."""
    request = _request.get()
    user = getattr(request, "user", None) if request is not None else None
    return user if (user is not None and getattr(user, "is_authenticated", False)) else None
