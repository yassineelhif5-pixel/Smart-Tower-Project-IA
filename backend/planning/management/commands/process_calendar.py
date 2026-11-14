from django.core.management.base import BaseCommand

from planning import services


class Command(BaseCommand):
    help = "Envoie les rappels échus du calendrier et signale les événements passés en retard (idempotent)."

    def handle(self, *args, **options):
        sent = services.process_due_reminders()
        late = services.notify_late()
        self.stdout.write(f"Calendrier : {sent} rappel(s) traité(s), {late} retard(s) signalé(s).")
