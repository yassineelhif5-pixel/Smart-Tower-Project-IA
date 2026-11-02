import secrets

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from accounts.models import PLATFORM_ROLE
from configuration import audit


class Command(BaseCommand):
    help = ("Crée un compte Pilote (Super Admin Global), sans tenant. Mot de passe provisoire affiché une fois, "
            "à changer à la première connexion. Seul moyen de créer un Pilote : aucune API ne le permet.")

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--email", default="")

    def handle(self, *args, username, email, **options):
        User = get_user_model()
        if User.objects.filter(username=username).exists():
            raise CommandError(f"L'identifiant « {username} » existe déjà : rien n'a été modifié.")
        password = secrets.token_urlsafe(12)
        user = User(username=username, email=email, role_id=PLATFORM_ROLE, tenant=None, must_change_password=True)
        user.set_password(password)
        user.save()
        audit.record(None, f"Utilisateur {username}", "Compte Pilote créé (ligne de commande)", "", "", tenant=None)
        self.stdout.write(self.style.WARNING(
            f"Compte Pilote « {username} » créé. Mot de passe provisoire : {password} (à changer à la première connexion)."))
