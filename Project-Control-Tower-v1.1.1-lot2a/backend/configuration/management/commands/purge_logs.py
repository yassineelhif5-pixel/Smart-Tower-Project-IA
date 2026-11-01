from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from configuration import audit
from configuration.models import ApiRequestLog, AuditEvent


class Command(BaseCommand):
    help = (
        "Supprime les entrées du journal des appels API et du journal d'audit plus anciennes que leur durée de "
        "conservation (API_LOG_RETENTION_DAYS, AUDIT_LOG_RETENTION_DAYS). À planifier une fois par jour."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Affiche ce qui serait supprimé sans rien supprimer.")

    def handle(self, *args, dry_run=False, **options):
        now = timezone.now()
        api_days, audit_days = settings.API_LOG_RETENTION_DAYS, settings.AUDIT_LOG_RETENTION_DAYS
        api_old = ApiRequestLog.objects.filter(at__lt=now - timedelta(days=api_days))
        audit_old = AuditEvent.objects.filter(at__lt=now - timedelta(days=audit_days))
        n_api, n_audit = api_old.count(), audit_old.count()
        if dry_run:
            self.stdout.write(f"Simulation : {n_api} appel(s) API de plus de {api_days} j et "
                              f"{n_audit} événement(s) d'audit de plus de {audit_days} j seraient supprimés.")
            return
        api_old.delete()
        audit_old.delete()
        # La purge elle-même reste tracée, après la suppression pour ne jamais s'effacer.
        audit.record(None, "Journaux", "Purge planifiée", "",
                     f"{n_api} appel(s) API (> {api_days} j), {n_audit} événement(s) d'audit (> {audit_days} j)")
        self.stdout.write(self.style.SUCCESS(
            f"{n_api} appel(s) API et {n_audit} événement(s) d'audit supprimés."))
