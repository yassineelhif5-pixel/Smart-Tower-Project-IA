from django.apps import AppConfig
from django.db.models.signals import post_migrate


class ConfigurationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "configuration"

    def ready(self):
        from .supabase_lockdown import on_post_migrate

        # Après chaque migrate : tables Django fermées à l'API publique de Supabase (sans effet ailleurs).
        post_migrate.connect(on_post_migrate, dispatch_uid="configuration.supabase_lockdown")
