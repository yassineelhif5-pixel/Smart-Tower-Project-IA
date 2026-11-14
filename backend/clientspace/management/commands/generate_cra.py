from django.core.management.base import BaseCommand

from clientspace.billing import run_monthly
from tenants.models import Tenant


class Command(BaseCommand):
    help = "Génère les CRA et factures du mois écoulé (saisies entièrement validées). Une fois par jour."

    def handle(self, *args, **options):
        for tenant in Tenant.objects.filter(status="active"):
            done = run_monthly(tenant)
            if done:
                self.stdout.write(f"{tenant}: {len(done)} CRA généré(s)")
