from django.core.management.base import BaseCommand

from projects.timesheet_reminders import run_daily
from tenants.models import Tenant


class Command(BaseCommand):
    help = "Relance (notification + e-mail) les membres sans saisie de temps et leur chef de projet. Une fois par jour ouvré."

    def handle(self, *args, **options):
        for tenant in Tenant.objects.all():
            done = run_daily(tenant)
            if done is not None:
                n = sum(len(r["missing"]) for r in done)
                self.stdout.write(f"{tenant}: {n} membre(s) relancé(s)")
