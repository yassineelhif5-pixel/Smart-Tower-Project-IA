"""Lecture et validation des variables d'environnement côté serveur.

Aucune valeur n'est jamais écrite dans un message d'erreur ou un journal :
seuls les noms des variables manquantes ou invalides sont cités.
"""
import os
from urllib.parse import parse_qs, unquote, urlparse

from django.core.exceptions import ImproperlyConfigured


def get(name, default=None, required=False):
    value = os.environ.get(name, default)
    if required and not value:
        raise ImproperlyConfigured(
            f"Variable d'environnement manquante : {name}. "
            "Voir backend/.env.example."
        )
    return value


def get_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def get_int(name, default, minimum=None):
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        raise ImproperlyConfigured(f"Variable d'environnement invalide : {name} (nombre entier attendu).") from None
    if minimum is not None and value < minimum:
        raise ImproperlyConfigured(f"Variable d'environnement invalide : {name} (minimum {minimum}).")
    return value


def get_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


def database_from_url(name="DATABASE_URL"):
    """Convertit une URL postgres://utilisateur:motdepasse@hôte:port/base?sslmode=… en réglages Django."""
    url = get(name, required=True)
    parsed = urlparse(url)
    if parsed.scheme not in ("postgres", "postgresql") or not parsed.path.strip("/"):
        raise ImproperlyConfigured(
            f"Variable d'environnement invalide : {name}. "
            "Format attendu : postgresql://utilisateur:motdepasse@hôte:port/base"
        )
    options = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or ""),
        "OPTIONS": options,
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }
