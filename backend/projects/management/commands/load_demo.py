import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from projects.models import Action, Client, Project, ProjectAccess

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "demo.json"


class Command(BaseCommand):
    help = ("Charge les données de démonstration de index.html (clients, personnes, projets, tâches, périmètres) "
            "dans la base de développement. Les comptes de démonstration n'ont pas de mot de passe utilisable : "
            "un administrateur le définit depuis le module Configuration.")

    def handle(self, *args, **options):
        if not FIXTURE.exists():
            raise CommandError(f"Fichier introuvable : {FIXTURE}. Lancez python3 supabase/generate_seed.py.")
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        User = get_user_model()
        with transaction.atomic():
            for c in data["clients"]:
                Client.objects.update_or_create(code=c["code"], defaults={k: c[k] for k in ("name", "sector", "city", "color")})
            users = {}
            for p in data["people"]:
                user = User.objects.filter(person_code=p["code"]).first() or User(username=p["username"], person_code=p["code"])
                if user.pk is None:
                    user.set_unusable_password()
                for field in ("first_name", "last_name", "email", "title", "team"):
                    setattr(user, field, p[field])
                user.role_id = p["role"]
                user.client_id = p["client"]
                user.is_active = not p["virtual"]
                user.save()
                users[p["code"]] = user
            for p in data["projects"]:
                Project.objects.update_or_create(id=p["id"], defaults={
                    "code": p["code"], "name": p["name"], "client_id": p["client"], "method": p["method"],
                    "pm": users.get(p["pm"]), "tl": users.get(p["tl"]), "start_date": p["start"],
                    "end_date": p["end"], "progress": p["progress"]})
            for a in data["actions"]:
                Action.objects.update_or_create(id=a["id"], defaults={
                    "project_id": a["project"], "title": a["title"], "owner": users.get(a["owner"]),
                    "status": a["status"], "type": a["type"], "due": a["due"]})
            # Périmètre de la page (scopeOf) traduit en affectations ; « * » = tout voir par le rôle.
            for code, scope in data["scope"].items():
                if scope == "*" or code not in users:
                    continue
                for pid in scope:
                    ProjectAccess.objects.get_or_create(user=users[code], project_id=pid, defaults={"can_edit": True})
        self.stdout.write(self.style.SUCCESS(
            f"{len(data['clients'])} clients, {len(data['people'])} personnes, {len(data['projects'])} projets, "
            f"{len(data['actions'])} tâches chargés."))
