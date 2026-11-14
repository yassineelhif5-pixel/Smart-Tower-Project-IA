"""Charge les données de démonstration dans la base de développement.

Sources (aucune n'est modifiée) :
- supabase/seed.sql : toutes les tables métier (générées depuis index.html) ;
- projects/fixtures/demo.json : identifiants de connexion des personnes et périmètre (scopeOf de index.html).

La commande est idempotente : relancée, elle met à jour les fiches de démonstration et
n'ajoute pas de doublons. Elle ne supprime jamais rien.
"""
import json
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from configuration.models import AppSetting, AuditEvent
from projects import seed_sql
from tenants.models import DEFAULT_TENANT_SLUG, Tenant
from projects.models import (
    Action, ActionComment, ChangeRequest, ChangeRequestAmount, Client, ClientContract, Defect, Document, Issue,
    Meeting, Objective, PersonCapacity, Project, ProjectAccess, ProjectFinance, ProjectInternal, Risk, TestCampaign,
    TimeEntry, Todo, UserStory,
)

BACKEND = Path(__file__).resolve().parents[3]
FIXTURE = BACKEND / "projects" / "fixtures" / "demo.json"
SEED = BACKEND.parent / "supabase" / "seed.sql"


def dec(value):
    return None if value is None else Decimal(str(value))


def text(value):
    return "" if value is None else value


class Command(BaseCommand):
    help = ("Charge les données de démonstration (supabase/seed.sql et projects/fixtures/demo.json) : clients, "
            "personnes, projets, tâches, temps, risques, documents, réunions… Les comptes de démonstration n'ont pas "
            "de mot de passe utilisable : un administrateur le définit depuis le module Configuration.")

    def handle(self, *args, **options):
        for path in (FIXTURE, SEED):
            if not path.exists():
                raise CommandError(f"Fichier introuvable : {path}. Lancez python3 supabase/generate_seed.py.")
        logins = json.loads(FIXTURE.read_text(encoding="utf-8"))
        seed = seed_sql.load(SEED)
        with transaction.atomic():
            counts = self.load(seed, logins)
        self.stdout.write(self.style.SUCCESS(
            f"{counts['clients']} clients, {counts['people']} personnes, {counts['projects']} projets, "
            f"{counts['actions']} tâches, {counts['time']} saisies de temps chargés."))

    def load(self, seed, logins):
        User = get_user_model()
        # Toutes les données de démonstration appartiennent au tenant « Demo ESN ».
        T = Tenant.objects.get(slug=DEFAULT_TENANT_SLUG)
        login_of = {p["code"]: p for p in logins["people"]}

        # Clients (sans les relations vers les personnes, qui n'existent pas encore).
        for c in seed["clients"]:
            Client.objects.update_or_create(code=c["id"], defaults={"tenant": T, 
                "name": c["name"], "sector": text(c["sector"]), "city": text(c["city"]), "color": text(c["color"]),
                "label": text(c["label"]), "contacts": c["contacts"]})

        # Personnes -> utilisateurs.
        users = {}
        for p in seed["people"]:
            login = login_of.get(p["id"], {})
            user = User.objects.filter(person_code=p["id"]).first()
            if user is None:
                user = User(username=login.get("username") or (p["email"] or p["id"]).split("@")[0], person_code=p["id"])
                user.set_unusable_password()
            first, _, last = p["name"].partition(" ")
            user.first_name, user.last_name = login.get("first_name", first), login.get("last_name", last)
            user.email, user.title, user.team = text(p["email"]), text(p["title"]), text(p["team"])
            user.role_id, user.client_id, user.is_active = p["role"], p["client_id"], not p["is_virtual"]
            user.tenant = T
            user.save()
            users[p["id"]] = user
        U = users.get

        for c in seed["clients"]:
            client = Client.objects.get(code=c["id"])
            client.managers.set([U(x) for x in c["managers"]])
            client.sales.set([U(x) for x in c["sales"]])
        for row in seed["people_internal"]:
            PersonCapacity.objects.update_or_create(user=U(row["person_id"]), defaults={"tenant": T, 
                "cap": dec(row["cap"]), "meet": dec(row["meet"]), "skills": row["skills"]})
        for row in seed["client_contracts"]:
            ClientContract.objects.update_or_create(ref=row["ref"], defaults={"tenant": T, 
                "client_id": row["client_id"], "label": text(row["label"]), "amount": dec(row["amount"]),
                "end_date": row["end_date"], "kind": text(row["kind"]), "renew": row["renew"]})

        # Projets.
        for p in seed["projects"]:
            project, _ = Project.objects.update_or_create(id=p["id"], defaults={"tenant": T, 
                "code": p["code"], "name": p["name"], "client_id": p["client_id"], "method": text(p["method"]),
                "pm": U(p["pm"]), "tl": U(p["tl"]), "start_date": p["start_date"], "end_date": p["end_date"],
                "progress": p["progress"], "descr": text(p["descr"]), "forecast_end": p["forecast_end"],
                "phases": p["phases"], "milestones": p["milestones"], "tests": p["tests"], "key_dates": p["key_dates"],
                "hyper": p["hyper"], "lifecycle": p["lifecycle"], "week_plans": p["week_plans"], "agile": p["agile"]})
            project.team.set([U(x) for x in p["team"]])
        for row in seed["project_internal"]:
            ProjectInternal.objects.update_or_create(project_id=row["project_id"], defaults={"tenant": T, 
                "days": dec(row["days"]), "h_base": dec(row["h_base"]), "h_done": dec(row["h_done"]),
                "h_raf": dec(row["h_raf"]), "team_load": dec(row["team_load"]), "staff": row["staff"]})
        for row in seed["project_finance"]:
            ProjectFinance.objects.update_or_create(project_id=row["project_id"], defaults={"tenant": T, 
                **{k: dec(row[k]) for k in ("ca", "baseline", "approved", "consumed", "raf_cost")},
                "lines": row["lines"], "causes": row["causes"], "series": row["series"], "months": row["months"]})

        # Exécution.
        for row in seed["user_stories"]:
            UserStory.objects.update_or_create(id=row["id"], defaults={"tenant": T, 
                "project_id": row["project_id"], "sprint": row["sprint"], "title": row["title"], "pts": dec(row["pts"]),
                "prio": text(row["prio"]), "story": text(row["story"]), "ac": text(row["ac"]), "closed": row["closed"]})
        for a in seed["actions"]:
            Action.objects.update_or_create(id=a["id"], defaults={"tenant": T, 
                "project_id": a["project_id"], "title": a["title"], "phase": text(a["phase"]), "owner": U(a["owner"]),
                "prio": text(a["prio"]), "status": a["status"], "est0": dec(a["est0"]), "est": dec(a["est"]),
                "done": dec(a["done"]), "raf": dec(a["raf"]), "start_date": a["start_date"], "due": a["due"],
                "fdue": a["fdue"], "type": text(a["type"]), "block": text(a["block"]), "stage": text(a["stage"]),
                "us_id": a["us"], "done_at": a["done_at"], "history": a["history"]})
        demo_actions = [a["id"] for a in seed["actions"]]
        # Tables sans identifiant métier : créées une seule fois, jamais en double.
        if not ActionComment.objects.filter(action_id__in=demo_actions).exists():
            ActionComment.objects.bulk_create(ActionComment(
                tenant=T, action_id=r["action_id"], author=U(r["author"]), at=text(r["at"]), body=r["body"], internal=r["internal"])
                for r in seed["action_comments"])
        for row in seed["objectives"]:
            Objective.objects.update_or_create(id=row["id"], defaults={"tenant": T, 
                "scope": text(row["scope"]), "project_id": row["project_id"], "owner": U(row["owner"]),
                "title": row["title"], "due": row["due"], "items": row["items"]})
        demo_people = list(users.values())
        if not Todo.objects.filter(owner__in=demo_people).exists():
            Todo.objects.bulk_create(Todo(tenant=T, owner=U(r["owner"]), label=r["label"], done=r["done"], position=r["position"])
                                     for r in seed["todos"])
        demo_projects = [p["id"] for p in seed["projects"]]
        if not TimeEntry.objects.filter(project_id__in=demo_projects).exists():
            TimeEntry.objects.bulk_create(TimeEntry(
                tenant=T, person=U(r["person_id"]), action_id=r["action_id"], project_id=r["project_id"], work_date=r["work_date"],
                hours=dec(r["hours"]), is_meeting=r["is_meeting"]) for r in seed["time_entries"])

        # Contrôle.
        for row in seed["risks"]:
            risk, _ = Risk.objects.update_or_create(id=row["id"], defaults={"tenant": T, 
                "project_id": row["project_id"], "title": row["title"], "prob": row["prob"], "imp": row["imp"],
                "owner": U(row["owner"]), "status": text(row["status"]), "due": row["due"],
                "mitigation": text(row["mitigation"]), "client_visible": row["client_visible"]})
            risk.actions.set(row["actions"])
        for row in seed["issues"]:
            Issue.objects.update_or_create(id=row["id"], defaults={"tenant": T, 
                "project_id": row["project_id"], "kind": text(row["kind"]), "title": row["title"],
                "prio": text(row["prio"]), "owner": U(row["owner"]), "due": row["due"], "impact": text(row["impact"])})
        for row in seed["change_requests"]:
            ChangeRequest.objects.update_or_create(id=row["id"], defaults={"tenant": T, 
                "project_id": row["project_id"], "title": row["title"], "requested_by": U(row["requested_by"]),
                "hours": dec(row["hours"]), "days": dec(row["days"]), "status": text(row["status"]),
                "vdate": row["vdate"], "fn": text(row["fn"]), "tech": text(row["tech"])})
        for row in seed["change_request_amounts"]:
            ChangeRequestAmount.objects.update_or_create(change_request_id=row["cr_id"], defaults={"tenant": T, "amount": dec(row["amount"])})
        for row in seed["test_campaigns"]:
            TestCampaign.objects.update_or_create(id=row["id"], defaults={"tenant": T, 
                "project_id": row["project_id"], "name": text(row["name"]), "env": text(row["env"]),
                "version": text(row["version"]), "total": row["total"], "passed": row["pass"], "fail": row["fail"],
                "todo": row["todo"], "crit": row["crit"], "owner": U(row["owner"])})
        for row in seed["defects"]:
            Defect.objects.update_or_create(id=row["id"], defaults={"tenant": T, 
                "project_id": row["project_id"], "title": row["title"], "sev": text(row["sev"]),
                "status": text(row["status"]), "owner": U(row["owner"])})
        for row in seed["documents"]:
            Document.objects.update_or_create(id=row["id"], defaults={"tenant": T, 
                "project_id": row["project_id"], "name": row["name"], "ext": text(row["ext"]),
                "size_mb": dec(row["size_mb"]), "type": text(row["type"]), "dstat": text(row["dstat"]),
                "entity": text(row["entity"]), "uploaded_by": U(row["uploaded_by"]), "uploaded_at": row["uploaded_at"],
                "version": row["version"], "scan_status": text(row["scan_status"]), "client_visible": row["client_visible"]})
        for row in seed["meetings"]:
            meeting, _ = Meeting.objects.update_or_create(id=row["id"], defaults={"tenant": T, 
                "project_id": row["project_id"], "type": text(row["type"]), "title": row["title"], "date": row["date"],
                "time": text(row["time"]), "dur": row["dur"], "organizer": U(row["organizer"]),
                "external": row["external"], "agenda": row["agenda"], "notes": text(row["notes"]),
                "decisions": row["decisions"], "doc_id": row["doc"], "client_visible": row["client_visible"],
                "status": text(row["status"])})
            meeting.attendees.set([U(x) for x in row["attendees"]])
            meeting.actions.set(row["actions"])

        # Paramétrage et historique d'audit de la démo.
        for row in seed["app_settings"]:
            AppSetting.objects.update_or_create(tenant=T, key=row["key"], defaults={"tenant": T, "value": row["value"]})
        for row in seed["audit_log"]:
            if AuditEvent.objects.filter(trace=row["trace"]).exists():
                continue
            at = parse_datetime(row["at"])
            AuditEvent.objects.create(
                tenant=T, actor=U(row["actor"]), entity=text(row["entity"])[:200], event=text(row["event"])[:120],
                old_value=text(row["old_value"]), new_value=text(row["new_value"]), trace=row["trace"],
                at=timezone.make_aware(at) if at else timezone.now())

        # Périmètre de la page (scopeOf) traduit en affectations ; « * » = tout voir par le rôle.
        for code, scope in logins["scope"].items():
            if scope == "*" or code not in users:
                continue
            for pid in scope:
                ProjectAccess.objects.get_or_create(user=users[code], project_id=pid, defaults={"tenant": T, "can_edit": True})

        # 1.4.0 : les actions datées apparaissent dans le calendrier ; les commentaires deviennent des discussions.
        from collaboration.services import import_action_comments
        from planning.services import plan_existing_actions
        plan_existing_actions(T)
        import_action_comments(T)
        # 1.5.0 : méthodologies, phases, équipes, sprints et backlog repris des données du projet.
        from methodology.bootstrap import bootstrap_all, live_models
        bootstrap_all(live_models)

        return {"clients": len(seed["clients"]), "people": len(users), "projects": len(seed["projects"]),
                "actions": len(seed["actions"]), "time": len(seed["time_entries"])}
