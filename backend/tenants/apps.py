from django.apps import AppConfig


class TenantsConfig(AppConfig):
    name = "tenants"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import signals  # noqa: F401  (contrôle des relations plusieurs-à-plusieurs entre tenants)
