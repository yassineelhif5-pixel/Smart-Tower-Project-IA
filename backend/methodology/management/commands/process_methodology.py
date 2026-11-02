from django.core.management.base import BaseCommand

from methodology import services


class Command(BaseCommand):
    help = "Rétrospectives automatiques, rappels méthodologiques générés et envoyés (idempotent, avec nouvel essai)."

    def handle(self, *args, **options):
        r = services.process()
        self.stdout.write(f"Méthodologie : {r['retros']} rétrospective(s) programmée(s), {r['scheduled']} rappel(s) planifié(s), "
                          f"{r['sent']} envoyé(s), {r['failed']} en échec, {r['cancelled']} annulé(s).")
