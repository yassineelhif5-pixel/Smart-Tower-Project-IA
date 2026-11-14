from django.apps import AppConfig


class ClientSpaceConfig(AppConfig):
    name = "clientspace"
    verbose_name = "Espace client : CRA, factures, validation des temps, support N1/N2/N3"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import signals  # noqa: F401
