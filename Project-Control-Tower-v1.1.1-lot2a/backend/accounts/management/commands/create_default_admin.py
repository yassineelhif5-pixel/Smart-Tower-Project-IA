from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from accounts.models import ADMIN_ROLE


class Command(BaseCommand):
    help = "Crée le compte initial admin / admin. Le mot de passe devra être changé à la première connexion."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Remet le mot de passe admin et le changement obligatoire.")

    def handle(self, *args, reset=False, **options):
        User = get_user_model()
        user = User.objects.filter(username="admin").first()
        if user and not reset:
            self.stdout.write("Le compte admin existe déjà : rien n'a été modifié (utilisez --reset pour le réinitialiser).")
            return
        user = user or User(username="admin", first_name="Administrateur")
        user.role_id = ADMIN_ROLE
        user.is_active = True
        user.must_change_password = True
        # Mot de passe provisoire demandé ; il ne respecte pas les règles de mot de passe,
        # d'où le changement imposé avant tout autre accès à l'API.
        user.set_password("admin")
        user.save()
        self.stdout.write(self.style.WARNING(
            "Compte admin prêt (mot de passe provisoire : admin). Il devra être changé à la première connexion."))
