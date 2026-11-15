from django.apps import AppConfig


class LicensingConfig(AppConfig):
    name = "licensing"
    verbose_name = "Offres, abonnements et licences"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import signals  # noqa: F401  (notifications des demandes de licence)
