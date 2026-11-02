"""Réglages Django de Project Control Tower.

Tous les paramètres sensibles viennent des variables d'environnement (voir .env.example).
Le démarrage échoue avec un message explicite si un paramètre obligatoire manque.
"""
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from . import env

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = env.get("DJANGO_SECRET_KEY", required=True)
DEBUG = env.get_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env.get_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env.get_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

# Hébergement Vercel (variable VERCEL=1 posée par la plateforme) : les adresses *.vercel.app du projet sont
# servies sans réglage. Un domaine personnalisé s'ajoute dans DJANGO_ALLOWED_HOSTS.
ON_VERCEL = env.get_bool("VERCEL", False)
if ON_VERCEL and ".vercel.app" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(".vercel.app")

# Clé(s) de chiffrement des secrets du module Configuration : une clé Fernet, ou plusieurs séparées par des
# virgules pendant une rotation (la première chiffre, toutes déchiffrent ; voir configuration/crypto.py).
FIELD_ENCRYPTION_KEY = env.get("FIELD_ENCRYPTION_KEY", required=True)

# Durées de conservation des journaux, appliquées par `python manage.py purge_logs` (à planifier chaque jour).
API_LOG_RETENTION_DAYS = env.get_int("API_LOG_RETENTION_DAYS", 90, minimum=1)
AUDIT_LOG_RETENTION_DAYS = env.get_int("AUDIT_LOG_RETENTION_DAYS", 365, minimum=30)

# Licences concurrentes : une session inactive depuis ce délai rend sa licence (commande expire_licenses).
LICENSE_SESSION_IDLE_MINUTES = env.get_int("LICENSE_SESSION_IDLE_MINUTES", 30, minimum=5)
# Adresse IP enregistrée dans le journal d'audit : en-tête X-Forwarded-For pris en compte seulement derrière un
# reverse proxy de confiance (sinon, un client pourrait y écrire n'importe quelle adresse).
# Sur Vercel, la plateforme réécrit cet en-tête avec l'adresse réelle du client : il est fiable par défaut.
TRUST_X_FORWARDED_FOR = env.get_bool("TRUST_X_FORWARDED_FOR", ON_VERCEL)

# Maintenance planifiée par HTTP (Vercel Cron) : jeton partagé, envoyé par Vercel dans « Authorization: Bearer ».
CRON_SECRET = env.get("CRON_SECRET", "")
# Adresse publique de l'application (https://…), utilisée pour les liens vers PCT dans Teams, le retour OAuth
# Microsoft et les notifications de modification Microsoft Graph. Vide : déduite de la requête, sans webhook.
PUBLIC_BASE_URL = env.get("PUBLIC_BASE_URL", "").rstrip("/")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "rest_framework",
    "drf_spectacular",
    "tenants",
    "licensing",
    "accounts",
    "projects",
    "configuration",
    "planning",
    "collaboration",
    "methodology",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "configuration.middleware.ApiRequestLogMiddleware",
]

if ON_VERCEL:
    MIDDLEWARE.insert(0, "config.vercel.ApiPrefixMiddleware")

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
# Seule la page Swagger (documentation de l'API, réservée aux administrateurs) utilise un gabarit HTML.
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True, "OPTIONS": {}}]

DATABASES = {"default": env.database_from_url("DATABASE_URL")}
# Durée de vie des connexions : 60 s par défaut ; 0 conseillé en serverless pour ne pas saturer le pooler Supabase.
DATABASES["default"]["CONN_MAX_AGE"] = env.get_int("DB_CONN_MAX_AGE", 60, minimum=0)

# Cache partagé par tous les processus serveur, stocké dans PostgreSQL (table créée par la migration
# configuration 0003). Il porte notamment le compteur de tentatives de connexion.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "pct_cache"}}

# Les tests ne doivent jamais viser la base Supabase partagée.
if "test" in sys.argv and "supabase" in DATABASES["default"]["HOST"]:
    raise ImproperlyConfigured(
        "Les tests refusent une base Supabase : définissez DATABASE_URL vers une base Postgres de développement."
    )

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Sessions : cookie HttpOnly, expiration après 8 h (règle de l'onglet Sécurité existant).
SESSION_COOKIE_AGE = 8 * 3600
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # Sur Vercel, le HTTPS est imposé par la plateforme avant d'atteindre Django.
    SECURE_SSL_REDIRECT = env.get_bool("DJANGO_SSL_REDIRECT", not ON_VERCEL)
    SECURE_HSTS_SECONDS = 31536000

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        # Jeton en premier : un appel sans session reçoit un 401 (et non un 403).
        "configuration.authentication.ApiTokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
        "accounts.permissions.TenantIsActive",
        "accounts.permissions.LicenseIsValid",
        "accounts.permissions.PasswordChangeNotRequired",
    ],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "EXCEPTION_HANDLER": "config.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_RATES": {"login": "10/min"},
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# Description OpenAPI de l'API (GET /api/v1/schema, page Swagger /api/v1/docs, administrateurs uniquement).
SPECTACULAR_SETTINGS = {
    "TITLE": "Project Control Tower API",
    "DESCRIPTION": "API du Project Control Tower. Toutes les erreurs ont la forme {code, message, details, traceId}.",
    "VERSION": "1.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": r"/api/v1",
    "PREPROCESSING_HOOKS": ["config.openapi.only_current_version"],
    "SERVE_PERMISSIONS": ["accounts.permissions.IsAnyAdmin"],
    "SERVE_AUTHENTICATION": ["rest_framework.authentication.SessionAuthentication"],
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env.get("DJANGO_LOG_LEVEL", "INFO")},
}
