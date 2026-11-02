"""Réglages de la description OpenAPI (drf-spectacular)."""


def only_current_version(endpoints):
    """Ne documente que /api/v1/ : l'ancien chemin /api/ sans version en est un alias exact."""
    return [e for e in endpoints if e[0].startswith("/api/v1/")]
