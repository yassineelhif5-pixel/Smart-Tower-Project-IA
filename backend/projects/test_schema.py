"""Lot 2b (schéma unique) : les tables reprises de Supabase reçoivent toutes les données de seed.sql, à
l'identique ; les migrations ne perdent aucune donnée existante ; les règles de lecture reprennent les RLS."""
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from accounts.models import Role, RolePermission
from configuration.models import AppSetting
from projects import models as m
from projects import seed_sql
from projects.access import visible

SEED = Path(__file__).resolve().parents[2] / "supabase" / "seed.sql"
User = get_user_model()


def norm(value):
    """Valeur comparable entre seed.sql et la base (nombres, dates, listes)."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value)).normalize()
    if isinstance(value, date):
        return value.isoformat()
    if value == "":
        return None
    return value


def code(user):
    return user.person_code if user else None


def codes(manager):
    return sorted(u.person_code for u in manager.all())


def ids(manager):
    return sorted(o.pk for o in manager.all())


# Pour chaque table de seed.sql : modèle, clé de rapprochement, et lecture de chaque colonne côté Django.
TABLES = {
    "clients": (m.Client, "id", lambda o: o.code, {
        "name": "name", "sector": "sector", "city": "city", "color": "color", "label": "label", "contacts": "contacts",
        "managers": lambda o: codes(o.managers), "sales": lambda o: codes(o.sales)}),
    "client_contracts": (m.ClientContract, "ref", lambda o: o.ref, {
        "client_id": "client_id", "label": "label", "amount": "amount", "end_date": "end_date", "kind": "kind", "renew": "renew"}),
    "people_internal": (m.PersonCapacity, "person_id", lambda o: o.user.person_code, {
        "cap": "cap", "meet": "meet", "skills": "skills"}),
    "projects": (m.Project, "id", lambda o: o.id, {
        **{k: k for k in ("code", "name", "client_id", "method", "start_date", "end_date", "forecast_end", "progress", "descr",
                          "phases", "milestones", "tests", "key_dates", "hyper", "lifecycle", "week_plans", "agile")},
        "pm": lambda o: code(o.pm), "tl": lambda o: code(o.tl), "team": lambda o: codes(o.team)}),
    "project_internal": (m.ProjectInternal, "project_id", lambda o: o.project_id, {
        k: k for k in ("days", "h_base", "h_done", "h_raf", "team_load", "staff")}),
    "project_finance": (m.ProjectFinance, "project_id", lambda o: o.project_id, {
        k: k for k in ("ca", "baseline", "approved", "consumed", "raf_cost", "lines", "causes", "series", "months")}),
    "user_stories": (m.UserStory, "id", lambda o: o.id, {
        k: k for k in ("project_id", "sprint", "title", "pts", "prio", "story", "ac", "closed")}),
    "actions": (m.Action, "id", lambda o: o.id, {
        **{k: k for k in ("project_id", "title", "phase", "prio", "status", "est0", "est", "done", "raf", "start_date",
                          "due", "fdue", "type", "block", "stage", "done_at", "history")},
        "owner": lambda o: code(o.owner), "us": "us_id"}),
    "objectives": (m.Objective, "id", lambda o: o.id, {
        **{k: k for k in ("scope", "project_id", "title", "due", "items")}, "owner": lambda o: code(o.owner)}),
    "risks": (m.Risk, "id", lambda o: o.id, {
        **{k: k for k in ("project_id", "title", "prob", "imp", "status", "due", "mitigation", "client_visible")},
        "owner": lambda o: code(o.owner), "actions": lambda o: ids(o.actions)}),
    "issues": (m.Issue, "id", lambda o: o.id, {
        **{k: k for k in ("project_id", "kind", "title", "prio", "due", "impact")}, "owner": lambda o: code(o.owner)}),
    "change_requests": (m.ChangeRequest, "id", lambda o: o.id, {
        **{k: k for k in ("project_id", "title", "hours", "days", "status", "vdate", "fn", "tech")},
        "requested_by": lambda o: code(o.requested_by)}),
    "change_request_amounts": (m.ChangeRequestAmount, "cr_id", lambda o: o.change_request_id, {"amount": "amount"}),
    "test_campaigns": (m.TestCampaign, "id", lambda o: o.id, {
        **{k: k for k in ("project_id", "name", "env", "version", "total", "fail", "todo", "crit")},
        "pass": "passed", "owner": lambda o: code(o.owner)}),
    "defects": (m.Defect, "id", lambda o: o.id, {
        **{k: k for k in ("project_id", "title", "sev", "status")}, "owner": lambda o: code(o.owner)}),
    "documents": (m.Document, "id", lambda o: o.id, {
        **{k: k for k in ("project_id", "name", "ext", "size_mb", "type", "dstat", "entity", "uploaded_at", "version",
                          "scan_status", "client_visible")}, "uploaded_by": lambda o: code(o.uploaded_by)}),
    "meetings": (m.Meeting, "id", lambda o: o.id, {
        **{k: k for k in ("project_id", "type", "title", "date", "time", "dur", "external", "agenda", "notes", "decisions",
                          "client_visible", "status")},
        "organizer": lambda o: code(o.organizer), "attendees": lambda o: codes(o.attendees),
        "actions": lambda o: ids(o.actions), "doc": "doc_id"}),
}


class DemoLoadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_demo", stdout=open("/dev/null", "w"))
        cls.seed = seed_sql.load(SEED)

    def test_every_seed_row_is_loaded_with_identical_values(self):
        for table, (model, key_col, key_of, columns) in TABLES.items():
            rows = {key_of(o): o for o in model.objects.all()}
            self.assertEqual(len(rows), len(self.seed[table]), table)
            for row in self.seed[table]:
                obj = rows[row[key_col]]
                for col, read in columns.items():
                    got = read(obj) if callable(read) else getattr(obj, read)
                    expected = sorted(row[col]) if isinstance(row[col], list) and col in (
                        "managers", "sales", "team", "attendees", "actions") else row[col]
                    self.assertEqual(norm(got), norm(expected), f"{table} {row[key_col]} · {col}")

    def test_tables_without_business_id_are_complete(self):
        self.assertEqual(m.TimeEntry.objects.count(), len(self.seed["time_entries"]))
        db = sorted((e.person.person_code, e.project_id, e.action_id or "", e.work_date.isoformat(), norm(e.hours), e.is_meeting)
                    for e in m.TimeEntry.objects.select_related("person"))
        seed = sorted((r["person_id"], r["project_id"], r["action_id"] or "", r["work_date"], norm(r["hours"]), r["is_meeting"])
                      for r in self.seed["time_entries"])
        self.assertEqual(db, seed)
        self.assertEqual(sorted((c.action_id, c.body, c.internal) for c in m.ActionComment.objects.all()),
                         sorted((r["action_id"], r["body"], r["internal"]) for r in self.seed["action_comments"]))
        self.assertEqual(sorted((t.owner.person_code, t.label, t.done) for t in m.Todo.objects.select_related("owner")),
                         sorted((r["owner"], r["label"], r["done"]) for r in self.seed["todos"]))
        self.assertEqual({s.key: s.value for s in AppSetting.objects.all()},
                         {r["key"]: r["value"] for r in self.seed["app_settings"]})

    def test_roles_and_rights_from_migrations_match_the_seed(self):
        for r in self.seed["roles"]:
            role = Role.objects.get(code=r["id"])
            self.assertEqual((role.label, role.money, role.margin, role.internal),
                             (r["label"], r["money"], r["margin"], r["internal"]), r["id"])
        for r in self.seed["role_permissions"]:
            # Matrice modèle de la plateforme (sans tenant), copiée dans chaque tenant au lot 3a.
            p = RolePermission.objects.get(role_id=r["role"], module=r["module"], tenant__isnull=True)
            self.assertEqual(p.as_list(), [r[f"can_{v}"] for v in ("read", "create", "update", "delete", "approve")])

    def test_loading_twice_adds_nothing(self):
        before = {model: model.objects.count() for model in (m.TimeEntry, m.ActionComment, m.Todo, m.ProjectAccess, m.Risk)}
        call_command("load_demo", stdout=open("/dev/null", "w"))
        self.assertEqual({model: model.objects.count() for model in before}, before)


class VisibilityTests(TestCase):
    """Règles de lecture reprises des RLS (l'équivalence complète a été vérifiée sur une copie Supabase : DATABASE.md)."""

    @classmethod
    def setUpTestData(cls):
        call_command("load_demo", stdout=open("/dev/null", "w"))
        cls.client_user = User.objects.get(person_code="lf")   # portail client Nordline
        cls.consultant = User.objects.get(person_code="ib")
        cls.direction = User.objects.get(person_code="nh")

    def test_client_portal_sees_only_shared_items(self):
        u = self.client_user
        self.assertTrue(visible(u, m.Risk).exists())
        self.assertTrue(all(r.client_visible for r in visible(u, m.Risk)))
        self.assertTrue(all(d.client_visible for d in visible(u, m.Document)))
        self.assertTrue(all(x.client_visible for x in visible(u, m.Meeting)))
        self.assertFalse(visible(u, m.ActionComment).filter(internal=True).exists())
        for model in (m.Defect, m.PersonCapacity, m.ProjectInternal, m.ProjectFinance, m.Objective):
            self.assertFalse(visible(u, model).exists(), model.__name__)

    def test_money_is_reserved_to_financial_profiles(self):
        self.assertFalse(visible(self.consultant, m.ProjectFinance).exists())
        self.assertFalse(visible(self.consultant, m.ChangeRequestAmount).exists())
        self.assertEqual(visible(self.direction, m.ProjectFinance).count(), m.ProjectFinance.objects.count())

    def test_personal_data_stays_personal(self):
        self.assertTrue(all(t.owner_id == self.consultant.pk for t in visible(self.consultant, m.Todo)))
        # Une consultante ne voit pas les heures des autres (ACT_ALL).
        self.assertTrue(all(e.person_id == self.consultant.pk for e in visible(self.consultant, m.TimeEntry)))

    def test_rows_stay_inside_the_project_scope(self):
        scope = set(self.consultant.project_accesses.values_list("project_id", flat=True))
        for model in (m.Risk, m.Document, m.Meeting, m.UserStory, m.Issue, m.ChangeRequest, m.TestCampaign, m.Defect):
            self.assertTrue(set(visible(self.consultant, model).values_list("project_id", flat=True)) <= scope, model.__name__)

    def test_a_model_without_rule_is_refused(self):
        with self.assertRaises(ValueError):
            visible(self.direction, m.ProjectAccess)


class MigrationKeepsDataTests(TransactionTestCase):
    """Les données saisies avant le lot 2b (Client, Project, Action, accès) traversent la migration intactes."""

    serialized_rollback = True  # garde rôles et droits créés par les migrations pour les autres tests
    # Retour de « projects » seul : la migration configuration 0005 (lot 3a) n'est pas réversible.
    before = [("projects", "0001_initial")]
    after = [("projects", "0002_metier_supabase")]

    def test_existing_rows_survive_with_new_fields_empty(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        old = executor.loader.project_state(self.before).apps
        # Les comptes ne sont pas migrés en arrière : modèle actuel.
        from tenants.models import Tenant
        user = User.objects.create(username="avant-2b", role_id="cdp", tenant=Tenant.objects.get(slug="demo-esn"))
        old.get_model("projects", "Client").objects.create(code="acme", name="ACME", sector="Industrie")
        old.get_model("projects", "Project").objects.create(id="px", code="ACM-1", name="Projet existant",
                                                            client_id="acme", pm_id=user.pk, progress=42)
        old.get_model("projects", "Action").objects.create(id="A-1", project_id="px", title="Tâche existante",
                                                           status="doing", owner_id=user.pk)
        old.get_model("projects", "ProjectAccess").objects.create(user_id=user.pk, project_id="px", can_edit=False)

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.after)
        new = executor.loader.project_state(self.after).apps
        project = new.get_model("projects", "Project").objects.get(id="px")
        self.assertEqual((project.code, project.name, project.progress, project.pm_id), ("ACM-1", "Projet existant", 42, user.pk))
        self.assertEqual((project.phases, project.descr, project.agile), ([], "", None))
        action = new.get_model("projects", "Action").objects.get(id="A-1")
        self.assertEqual((action.title, action.status, action.block, action.history), ("Tâche existante", "doing", "", []))
        self.assertEqual(new.get_model("projects", "Client").objects.get(code="acme").sector, "Industrie")
        self.assertFalse(new.get_model("projects", "ProjectAccess").objects.get(project_id="px").can_edit)

        # Remet la base au dernier état pour les autres tests.
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
