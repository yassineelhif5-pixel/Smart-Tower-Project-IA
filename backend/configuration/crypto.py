"""Chiffrement des secrets saisis dans le module Configuration (Fernet : AES-128-CBC + HMAC-SHA256)."""
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _fernet():
    try:
        return Fernet(settings.FIELD_ENCRYPTION_KEY.encode())
    except (ValueError, TypeError) as exc:
        raise ImproperlyConfigured(
            "Variable d'environnement invalide : FIELD_ENCRYPTION_KEY (clé Fernet attendue, "
            "générée par python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\")."
        ) from exc


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ImproperlyConfigured("Un secret enregistré ne peut pas être déchiffré avec FIELD_ENCRYPTION_KEY.") from exc
