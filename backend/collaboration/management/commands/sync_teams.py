from django.core.management.base import BaseCommand

from collaboration import services


class Command(BaseCommand):
    help = "Renouvelle les abonnements Microsoft Graph, relit les discussions Teams en secours, purge les accusés."

    def handle(self, *args, **options):
        renewed = services.renew_subscriptions()
        synced = services.fallback_sync()
        purged = services.purge_receipts()
        self.stdout.write(f"Teams : {renewed['renewed']} abonnement(s) renouvelé(s), {renewed['failed']} en échec ; "
                          f"{synced['synced']} discussion(s) relue(s), {synced['failed']} en échec ; {purged} accusé(s) purgé(s).")
