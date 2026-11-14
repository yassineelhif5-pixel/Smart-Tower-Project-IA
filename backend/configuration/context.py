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
