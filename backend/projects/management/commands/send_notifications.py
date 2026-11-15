from django.core.management.base import BaseCommand

from projects.notif_jobs import run_due, run_weekly
from tenants.models import Tenant


class Command(BaseCommand):
    help = "Notifications planifiées : échéances d'actions (une fois par jour) et récapitulatifs hebdomadaires des projets."

    def handle(self, *args, **options):
        for tenant in Tenant.objects.all():
            n = run_due(tenant)
            sent = run_weekly(tenant)
            if n or sent:
                self.stdout.write(f"{tenant}: {n} échéance(s) notifiée(s), récap envoyé(s) : {', '.join(sent) or '—'}")
