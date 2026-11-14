"""Chiffrement des secrets saisis dans le module Configuration (Fernet : AES-128-CBC + HMAC-SHA256).

FIELD_ENCRYPTION_KEY accepte une ou plusieurs clés séparées par des virgules :
la première chiffre, toutes déchiffrent. Pour changer de clé sans perdre les secrets,
placez la nouvelle clé en tête, gardez l'ancienne derrière, puis lancez
`python manage.py rotate_secrets` avant de retirer l'ancienne.
"""
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

KEY_HELP = (
    "Variable d'environnement invalide : FIELD_ENCRYPTION_KEY (une ou plusieurs clés Fernet séparées par des virgules, "
    "générées par python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\")."
)


def _keys():
    return [k.strip() for k in str(settings.FIELD_ENCRYPTION_KEY or "").split(",") if k.strip()]


def _fernet():
    keys = _keys()
    if not keys:
        raise ImproperlyConfigured(KEY_HELP)
    try:
        return MultiFernet([Fernet(k.encode()) for k in keys])
    except (ValueError, TypeError) as exc:
        raise ImproperlyConfigured(KEY_HELP) from exc


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ImproperlyConfigured("Un secret enregistré ne peut pas être déchiffré avec FIELD_ENCRYPTION_KEY.") from exc


def rotate(token: str) -> str:
    """Rechiffre un secret avec la première clé de FIELD_ENCRYPTION_KEY."""
    try:
        return _fernet().rotate(token.encode()).decode()
    except InvalidToken as exc:
        raise ImproperlyConfigured("Un secret enregistré ne peut pas être déchiffré avec FIELD_ENCRYPTION_KEY.") from exc
