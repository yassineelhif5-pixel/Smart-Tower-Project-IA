from django.core.management.base import BaseCommand

from licensing import models as L
from licensing import services


class Command(BaseCommand):
    help = ("Ferme les sessions inactives (licences concurrentes rendues) et passe en « Expiré » les abonnements échus. "
            "Ne supprime aucune donnée. À planifier toutes les 5 minutes.")

    def handle(self, *args, **options):
        sessions = services.expire_sessions()
        expired = 0
        for sub in L.Subscription.objects.filter(status__in=[L.TRIAL, L.ACTIVE]):
            if services._expire_if_due(sub).status == L.EXPIRED:
                expired += 1
        self.stdout.write(self.style.SUCCESS(f"{sessions} session(s) fermée(s), {expired} abonnement(s) expiré(s)."))
