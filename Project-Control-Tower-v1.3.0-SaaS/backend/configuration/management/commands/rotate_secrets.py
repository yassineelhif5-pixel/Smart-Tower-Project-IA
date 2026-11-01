from django.core.management.base import BaseCommand
from django.db import transaction

from configuration import audit, crypto
from configuration.models import ServiceSecret


class Command(BaseCommand):
    help = "Rechiffre tous les secrets avec la première clé de FIELD_ENCRYPTION_KEY (après ajout d'une nouvelle clé en tête)."

    def handle(self, *args, **options):
        count = 0
        with transaction.atomic():
            for secret in ServiceSecret.objects.select_for_update():
                secret.ciphertext = crypto.rotate(secret.ciphertext)
                secret.save(update_fields=["ciphertext", "updated_at"])
                count += 1
            audit.record(None, "Secrets", "Rotation de la clé de chiffrement", "", f"{count} secret(s) rechiffré(s)")
        self.stdout.write(self.style.SUCCESS(
            f"{count} secret(s) rechiffré(s). Vous pouvez retirer l'ancienne clé de FIELD_ENCRYPTION_KEY."))
