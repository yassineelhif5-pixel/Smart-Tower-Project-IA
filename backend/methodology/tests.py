"""Pilotage méthodologique (1.5.0) : capacité, Cycle en V, Scrum, rétrospectives, rappels, droits, isolation."""
from datetime import date, datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from configuration.models import Notification, NotificationChannel, NotificationRule, ServiceSecret
from planning.models import CalendarEvent
from projects.models import Action, Project
from tenants import services as tenant_services

from . import capacity as cap
from . import services as S
from .models import (ImprovementAction, MethodologyReminder, ProductBacklogItem, ProjectMethodology, Retrospective,
                     Sprint, SprintBacklogItem, TeamAvailability, TeamMemberAllocation, WeeklyPlan)

User = get_user_model()


def monday(offset_weeks=2):
    d = timezone.localdate() + timedelta(weeks=offset_weeks)
    return d - timedelta(days=d.weekday())


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_demo", stdout=open("/dev/null", "w"))
        cls.sm = User.objects.get(person_code="sm")   # cheffe de projet p1, p2, p3 (rôle cdp)
        cls.ib = User.objects.get(person_code="ib")   # consultante
        cls.tl = User.objects.get(person_code="tl")   # développeur
        cls.nb = User.objects.get(person_code="nb")   # manager Santé, hors p1/p2
        cls.p1 = Project.objects.get(pk="p1")         # Cycle en V
        cls.p2 = Project.objects.get(pk="p2")         # Scrum
        cls.pilot = User.objects.create(username="pilote.meth", role_id="superadmin", tenant=None)
        cls.t2, cls.admin2, _ = tenant_services.create_tenant(by=cls.pilot, name="Autre Meth", admin_username="admin.meth")
        cls.admin2.must_change_password = False
        cls.admin2.save()

    def api(self, user):
        c = APIClient()
        c.force_authenticate(User.objects.get(pk=user.pk))
        return c


class CapacityTests(Base):
    def alloc(self, user, project=None, **kw):
        defaults = {"tenant": self.p1.tenant, "allocation_pct": 80, "hours_per_day": 7, "days_per_week": 5,
                    "meeting_hours_per_week": 4}
        defaults.update(kw)
        a, _ = TeamMemberAllocation.objects.update_or_create(project=project or self.p1, user=user, defaults=defaults)
        return a

    def test_example_of_the_specification(self):
        """7 h × 5 j × 80 % = 28 h ; − 4 h de réunions − 2 h d'indisponibilité = 22 h."""
        a = self.alloc(self.ib)
        w = monday()
        TeamAvailability.objects.create(tenant=self.p1.tenant, user=self.ib, kind="unavailable", start=w, end=w, hours=2)
        absences = list(TeamAvailability.objects.filter(user=self.ib))
        c = cap.member_capacity(a, w, w + timedelta(days=4), absences)
        self.assertEqual((c["theoretical"], c["meetings"], c["unavailable"], c["available"]),
                         (Decimal("28.0"), Decimal("4.0"), Decimal("2"), Decimal("22.0")))

    def test_leave_holiday_and_overlap_are_not_counted_twice(self):
        a = self.alloc(self.ib)
        w = monday()
        TeamAvailability.objects.create(tenant=self.p1.tenant, user=self.ib, kind="leave", start=w, end=w + timedelta(days=1))
        TeamAvailability.objects.create(tenant=self.p1.tenant, user=None, kind="holiday", start=w + timedelta(days=1),
                                        end=w + timedelta(days=1), note="Férié")
        TeamAvailability.objects.create(tenant=self.p1.tenant, user=self.ib, kind="absence", start=w, end=w, hours=3)
        absences = list(TeamAvailability.objects.all())
        c = cap.member_capacity(a, w, w + timedelta(days=4), absences)
        # 2 jours d'absence (lundi congé + absence partielle le même jour ; mardi congé + férié) : 3 jours restants.
        self.assertEqual(c["offDays"], [w.isoformat(), (w + timedelta(days=1)).isoformat()])
        self.assertEqual(c["theoretical"] - c["unavailable"] - c["meetings"], c["available"])
        self.assertEqual(c["available"], Decimal("5.6") * 3 - Decimal("0.8") * 3)

    def test_days_per_week_and_productive_ratio(self):
        a = self.alloc(self.ib, allocation_pct=100, hours_per_day=8, days_per_week=4, meeting_hours_per_week=0)
        w = monday()
        c = cap.member_capacity(a, w, w + timedelta(days=6), [], Decimal("0.75"))
        self.assertEqual((c["workingDays"], c["available"], c["productive"]), (4, Decimal("32"), Decimal("24.00")))

    def test_multiple_allocations_and_overload(self):
        self.alloc(self.ib, allocation_pct=40)
        self.alloc(self.ib, project=self.p2, allocation_pct=60)
        w = monday()
        e = CalendarEvent.objects.create(tenant=self.p1.tenant, project=self.p1, title="Gros chantier", all_day=True,
                                         start=datetime.combine(w, datetime.min.time(), tzinfo=dt_tz.utc),
                                         end=datetime.combine(w + timedelta(days=5), datetime.min.time(), tzinfo=dt_tz.utc))
        e.assignments.create(tenant=self.p1.tenant, user=self.ib, role="owner", estimated_workload=30)
        c = cap.team_capacity(self.p1, w, w + timedelta(days=4))
        me = next(m for m in c["members"] if m["user"]["id"] == self.ib.pk)
        self.assertEqual(me["theoretical"], 14.0)                  # 7 h × 5 × 40 %
        self.assertEqual(me["state"], "over")
        self.assertIn(self.ib.pk, [u["id"] for u in c["overloaded"]])
        other = cap.team_capacity(self.p2, w, w + timedelta(days=4))
        self.assertGreaterEqual(next(m for m in other["members"] if m["user"]["id"] == self.ib.pk)["otherProjects"], 30.0)

    def test_capacity_api_and_rights(self):
        r = self.api(self.sm).get(f"/api/v1/methodology/projects/p1/capacity?start={monday()}")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("weeks", r.json())
        self.assertEqual(self.api(self.nb).get("/api/v1/methodology/projects/p1/capacity").status_code, 404)
        # Chacun gère ses propres disponibilités ; pas celles d'un autre sans droit.
        c = self.api(self.tl)
        self.assertEqual(c.post("/api/v1/methodology/availabilities", {"kind": "leave", "start": str(monday()),
                                                                      "end": str(monday())}, format="json").status_code, 201)
        self.assertEqual(c.post("/api/v1/methodology/availabilities", {"kind": "leave", "user": self.ib.pk,
                                                                      "start": str(monday())}, format="json").status_code, 403)
        self.assertEqual(c.post("/api/v1/methodology/availabilities", {"kind": "holiday", "start": str(monday())},
                                format="json").status_code, 403)
        self.assertEqual(self.api(self.sm).post("/api/v1/methodology/availabilities", {
            "kind": "absence", "user": self.ib.pk, "start": str(monday()), "hours": 2}, format="json").status_code, 201)


class VCycleTests(Base):
    def test_weekly_flow_prepare_goals_assign_validate_track_close(self):
        w = monday()
        c = self.api(self.sm)
        r = c.get(f"/api/v1/methodology/projects/p1/weeks/{w}")
        self.assertEqual(r.status_code, 200, r.content)
        prep = r.json()
        self.assertIn("capacity", prep)
        self.assertTrue(prep["proposals"])
        self.assertFalse(WeeklyPlan.objects.get(project=self.p1, week_start=w).goals.exists())  # rien n'est appliqué seul
        action = Action.objects.filter(project=self.p1).exclude(status="done").first()
        # Validation impossible sans objectif.
        self.assertEqual(c.post(f"/api/v1/methodology/projects/p1/weeks/{w}/validate", {}, format="json").status_code, 400)
        r = c.post(f"/api/v1/methodology/projects/p1/weeks/{w}/goals", {
            "title": "Livrer la recette du lot 2", "expectedResults": "PV signé", "priority": "high", "owner": self.sm.pk,
            "actions": [{"action": action.pk, "hours": 6}], "phases": [], "successCriteria": "0 anomalie bloquante"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(r.json()["plan"]["goals"]), 1)
        # Affectation via le calendrier.
        r = c.post(f"/api/v1/methodology/projects/p1/weeks/{w}/assign",
                   {"items": [{"action": action.pk, "user": self.ib.pk, "hours": 6}], "confirm": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(CalendarEvent.objects.get(action=action).assignments.get(role="owner").user_id, self.ib.pk)
        # Un développeur (sans droit Valider) ne valide pas la semaine.
        self.assertEqual(self.api(self.tl).post(f"/api/v1/methodology/projects/p1/weeks/{w}/validate", {}, format="json").status_code, 403)
        r = c.post(f"/api/v1/methodology/projects/p1/weeks/{w}/validate", {"confirm": True}, format="json")
        self.assertEqual(r.json()["plan"]["state"], "validated")
        self.assertTrue(self.p1.capacity_snapshots.filter(weekly_plan__week_start=w).exists())
        # Suivi puis bilan automatique.
        Action.objects.filter(pk=action.pk).update(status="blocked", block="Attente du client")
        r = c.post(f"/api/v1/methodology/projects/p1/weeks/{w}/close", {"correctiveActions": "Relance du client"}, format="json")
        plan = r.json()["plan"]
        self.assertEqual(plan["state"], "closed")
        self.assertEqual(plan["review"]["gaps"][0]["cause"], "Attente du client")
        self.assertIn("0 action(s) terminée(s) sur 1", plan["review"]["summary"])
        self.assertIn(plan["status"], ("partial", "missed"))

    def test_overload_warns_before_validation(self):
        w = monday()
        plan = S.plan_for(self.p1, w)
        S.save_goal(User.objects.get(pk=self.sm.pk), plan, {"title": "Objectif"})
        e = CalendarEvent.objects.create(tenant=self.p1.tenant, project=self.p1, title="Surcharge", all_day=True,
                                         start=datetime.combine(w, datetime.min.time(), tzinfo=dt_tz.utc),
                                         end=datetime.combine(w + timedelta(days=1), datetime.min.time(), tzinfo=dt_tz.utc))
        e.assignments.create(tenant=self.p1.tenant, user=self.ib, role="owner", estimated_workload=40)
        r = self.api(self.sm).post(f"/api/v1/methodology/projects/p1/weeks/{w}/validate", {}, format="json")
        self.assertEqual((r.status_code, r.json()["code"]), (409, "CAPACITY_OVERLOAD"))
        self.assertEqual(WeeklyPlan.objects.get(pk=plan.pk).state, "draft")

    def test_several_goals_and_phases(self):
        w = monday()
        phases = list(self.p1.v_phases.values_list("pk", flat=True)[:2])
        c = self.api(self.sm)
        for t in ("Objectif A", "Objectif B"):
            c.post(f"/api/v1/methodology/projects/p1/weeks/{w}/goals", {"title": t, "phases": phases}, format="json")
        plan = WeeklyPlan.objects.get(project=self.p1, week_start=w)
        self.assertEqual(plan.goals.count(), 2)
        self.assertEqual(plan.goals.first().phases.count(), 2)

    def test_meeting_creates_actions_event_and_report(self):
        w = monday()
        r = self.api(self.sm).post(f"/api/v1/methodology/projects/p1/weeks/{w}/meeting", {
            "agenda": "Avancement recette", "participants": [self.ib.pk, self.tl.pk], "decisions": "Report de la MEP",
            "actions": [{"title": "Mettre à jour le planning", "owner": self.ib.pk, "due": str(w + timedelta(days=3))}],
            "schedule": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        m = r.json()["plan"]["meeting"]
        self.assertTrue(Action.objects.filter(pk=m["actions"][0], owner=self.ib, type="Réunion hebdomadaire").exists())
        self.assertIn("Mettre à jour le planning", m["report"])
        ev = CalendarEvent.objects.get(pk=r.json()["plan"]["meetingEvent"])
        self.assertEqual(ev.start.astimezone(S._tz(self.p1)).hour, 9)

    def test_phases_crud(self):
        c = self.api(self.sm)
        r = c.post("/api/v1/methodology/projects/p1/phases", {"name": "Tests de non-régression", "start": "2026-12-01",
                                                               "end": "2026-12-10", "deliverables": [{"title": "PV"}]}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(c.patch(f"/api/v1/methodology/phases/{r.json()['id']}", {"end": "2026-11-01"}, format="json").status_code, 400)
        from projects.models import ProjectAccess
        ProjectAccess.objects.filter(user=self.tl, project=self.p1).update(can_edit=False)
        self.assertEqual(self.api(self.tl).post("/api/v1/methodology/projects/p1/phases", {"name": "x"}, format="json").status_code, 403)


class ScrumTests(Base):
    def setUp(self):
        super().setUp()
        self.po = User.objects.get(person_code="kd")
        TeamMemberAllocation.objects.filter(project=self.p2, user=self.po).update(scrum_role="po")
        TeamMemberAllocation.objects.update_or_create(project=self.p2, user=self.sm, defaults={"tenant": self.p2.tenant, "scrum_role": "sm"})
        Sprint.objects.filter(project=self.p2, status__in=("active", "planned")).update(status="done")

    def items(self, n=3, points=5):
        out = []
        for i in range(n):
            out.append(S.save_item(User.objects.get(pk=self.sm.pk), self.p2, {"title": f"Story {i}", "storyPoints": points, "status": "ready"}))
        return out

    def test_backlog_priority_by_po_only_and_history(self):
        a, b, c = self.items()
        self.assertEqual(self.api(self.tl).post("/api/v1/methodology/projects/p2/backlog/reorder",
                                                {"ids": [c.pk, a.pk]}, format="json").status_code, 403)
        r = self.api(self.po).post("/api/v1/methodology/projects/p2/backlog/reorder", {"ids": [c.pk, a.pk]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        c.refresh_from_db()
        self.assertEqual(c.rank, 1)
        self.assertEqual(c.history[-1]["event"], "Priorité modifiée")
        rows = self.api(self.tl).get("/api/v1/methodology/projects/p2/backlog?q=Story").json()
        self.assertEqual(rows[0]["id"], c.pk)

    def test_sprint_lifecycle(self):
        items = self.items(3, 5)
        c = self.api(self.sm)
        r = c.post("/api/v1/methodology/projects/p2/sprints", {"start": str(monday(3)), "weeks": 2}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        sid = r.json()["id"]
        sprint = Sprint.objects.get(pk=sid)
        self.assertEqual(sprint.end, monday(3) + timedelta(days=11))
        self.assertTrue(MethodologyReminder.objects.filter(sprint=sprint, kind="sprint_planning").exists())
        # Planning : propositions, aucune sélection automatique.
        plan = c.get(f"/api/v1/methodology/sprints/{sid}/planning").json()
        self.assertTrue(any(i["suggested"] for i in plan["backlog"]))
        self.assertFalse(sprint.items.exists())
        # Sélection au-delà de la vélocité : vérification explicite.
        vel = S.velocity_history(self.p2, sprint)["average"]
        big = self.items(6, 10)
        r = c.post(f"/api/v1/methodology/sprints/{sid}/select", {"items": [i.pk for i in big]}, format="json")
        self.assertEqual((r.status_code, r.json()["code"]), (409, "SPRINT_CHECKS"), vel)
        self.assertFalse(sprint.items.exists())  # rien d'enregistré
        r = c.post(f"/api/v1/methodology/sprints/{sid}/select", {"items": [i.pk for i in items]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["committedPoints"], 15.0)
        # Démarrage : objectif et double validation exigés.
        self.assertEqual(c.post(f"/api/v1/methodology/sprints/{sid}/start").status_code, 400)
        self.assertEqual(c.post(f"/api/v1/methodology/sprints/{sid}/goal", {"objective": ""}, format="json").status_code, 400)
        c.post(f"/api/v1/methodology/sprints/{sid}/goal", {"objective": "Les acheteurs fusionnent les doublons fournisseurs",
                                                         "successCriteria": "100 doublons traités"}, format="json")
        self.assertEqual(self.api(self.tl).post(f"/api/v1/methodology/sprints/{sid}/validate", {"as": "po"}, format="json").status_code, 403)
        self.assertEqual(self.api(self.po).post(f"/api/v1/methodology/sprints/{sid}/validate", {"as": "po"}, format="json").status_code, 200)
        self.assertEqual(self.api(self.tl).post(f"/api/v1/methodology/sprints/{sid}/validate", {"as": "team"}, format="json").status_code, 200)
        r = c.post(f"/api/v1/methodology/sprints/{sid}/start")
        self.assertEqual(r.status_code, 200, r.content)
        sprint.refresh_from_db()
        self.assertEqual(sprint.status, "active")
        self.assertIsNotNone(sprint.capacity_hours)
        # Cérémonies dans le calendrier, objectif visible.
        ev = CalendarEvent.objects.get(pk=sprint.events["sprint"])
        self.assertIn("fusionnent les doublons", ev.title)
        self.assertEqual(len(sprint.events["daily"]), 10)
        self.assertTrue(CalendarEvent.objects.filter(pk=sprint.events["review"]).exists())
        self.assertEqual(MethodologyReminder.objects.filter(sprint=sprint, kind="daily").count(), 10)
        # Board : déplacement tracé, colonne terminée.
        entry = sprint.items.first()
        r = self.api(self.tl).patch(f"/api/v1/methodology/sprint-items/{entry.pk}", {"column": "done"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.api(self.tl).patch(f"/api/v1/methodology/sprint-items/{entry.pk}", {"column": "nope"},
                                                 format="json").status_code, 400)
        entry.refresh_from_db()
        self.assertIsNotNone(entry.done_at)
        self.assertEqual(entry.history[-1]["to"], "done")
        # Indicateurs : le % de tâches n'est pas l'atteinte de l'objectif.
        m = S.sprint_metrics(sprint)
        self.assertEqual((m["pointsPlanned"], m["pointsDone"], m["pointsRemaining"]), (15.0, 5.0, 10.0))
        self.assertEqual(m["goal"]["status"], "not_started")
        self.assertEqual(len(m["burndown"]), 10)
        # Clôture : statut d'objectif explicite, retour au backlog, rétrospective programmée.
        self.assertEqual(c.post(f"/api/v1/methodology/sprints/{sid}/close", {}, format="json").status_code, 400)
        r = c.post(f"/api/v1/methodology/sprints/{sid}/close", {"goalStatus": "partial"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        sprint.refresh_from_db()
        self.assertEqual((sprint.status, sprint.completed_points, sprint.goal.status), ("done", Decimal("5.0"), "partial"))
        self.assertEqual(ProductBacklogItem.objects.get(pk=items[1].pk).status, "ready")
        retro = Retrospective.objects.get(sprint=sprint)
        self.assertEqual(retro.participants.count(), TeamMemberAllocation.objects.filter(project=self.p2, active=True).count())
        self.assertTrue(CalendarEvent.objects.filter(pk=retro.calendar_event_id).exists())
        self.assertEqual(MethodologyReminder.objects.filter(retro=retro, kind="retro").count(), 3)
        self.assertEqual(S.velocity_history(self.p2)["sprints"][-1]["completed"], 5.0)

    def test_burndown_and_burnup_from_real_dates(self):
        start = date(2026, 11, 2)
        sp = Sprint.objects.create(tenant=self.p2.tenant, project=self.p2, number=99, start=start, end=start + timedelta(days=11), status="active")
        tz = S._tz(self.p2)
        items = self.items(2, 4)
        for i, it in enumerate(items):
            SprintBacklogItem.objects.create(tenant=sp.tenant, sprint=sp, item=it, points=4,
                                             added_at=datetime(2026, 11, 2, 9, tzinfo=tz),
                                             done_at=datetime(2026, 11, 3 + i, 15, tzinfo=tz))
        late = self.items(1, 2)[0]
        SprintBacklogItem.objects.create(tenant=sp.tenant, sprint=sp, item=late, points=2, added_at=datetime(2026, 11, 4, 9, tzinfo=tz))
        with mock.patch("django.utils.timezone.localdate", return_value=date(2026, 11, 5)):
            m = S.sprint_metrics(sp)
        bd = {p["date"]: p for p in m["burndown"]}
        self.assertEqual(bd["2026-11-02"]["remaining"], 8.0)
        self.assertEqual(bd["2026-11-03"]["remaining"], 4.0)
        self.assertEqual(bd["2026-11-04"]["remaining"], 2.0)    # 0 restant de l'engagement + 2 points ajoutés
        self.assertIsNone(bd["2026-11-06"]["remaining"])        # futur : non tracé
        bu = {p["date"]: p for p in m["burnup"]}
        self.assertEqual((bu["2026-11-04"]["done"], bu["2026-11-04"]["scope"]), (8.0, 10.0))
        self.assertEqual(m["burndown"][0]["ideal"], 7.2)

    def test_daily_and_impediments(self):
        sp = Sprint.objects.create(tenant=self.p2.tenant, project=self.p2, number=98, start=monday(-1), end=monday(-1) + timedelta(days=11), status="active")
        d = monday(-1) + timedelta(days=1)
        r = self.api(self.tl).post(f"/api/v1/methodology/sprints/{sp.pk}/daily", {"date": str(d), "entry": {
            "progress": "API terminée", "plan": "Tests", "impediment": "Accès base de recette"}}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        imp = r.json()["impediments"][0]
        self.assertEqual(imp["impedimentStatus"], "open")
        r = self.api(self.sm).patch(f"/api/v1/methodology/impediments/{imp['id']}", {"status": "resolved", "resolution": "Accès ouvert"}, format="json")
        self.assertEqual(r.json()["impedimentStatus"], "resolved")

    def test_review_report(self):
        sp = Sprint.objects.create(tenant=self.p2.tenant, project=self.p2, number=97, start=monday(-1), end=monday(-1) + timedelta(days=4), status="active")
        r = self.api(self.sm).post(f"/api/v1/methodology/sprints/{sp.pk}/review", {"increment": "Fusion v1", "feedback": "Très utile", "held": True}, format="json")
        self.assertIn("Fusion v1", r.json()["report"])
        self.assertIsNotNone(r.json()["heldAt"])

    def test_board_columns_keep_traceability(self):
        sp = Sprint.objects.create(tenant=self.p2.tenant, project=self.p2, number=96, start=monday(), end=monday() + timedelta(days=4), status="active")
        it = self.items(1)[0]
        SprintBacklogItem.objects.create(tenant=sp.tenant, sprint=sp, item=it, column="testing", added_at=timezone.now())
        cols = [{"key": "todo", "label": "À faire"}, {"key": "done", "label": "Fini", "done": True}]
        r = self.api(self.sm).put("/api/v1/methodology/projects/p2", {"settings": {"boardColumns": cols}}, format="json")
        self.assertEqual(r.status_code, 400)
        cols.insert(1, {"key": "testing", "label": "Recette"})
        self.assertEqual(self.api(self.sm).put("/api/v1/methodology/projects/p2", {"settings": {"boardColumns": cols}}, format="json").status_code, 200)


class RetroTests(Base):
    def retro(self, **data):
        return S.create_retro(User.objects.get(pk=self.sm.pk), self.p1, {
            "title": "Rétro de phase", "scheduledAt": (timezone.now() + timedelta(days=3)).isoformat(), **data})

    def test_feedback_anonymity_policy(self):
        r = self.retro(participants=[self.ib.pk, self.tl.pk], anonymous=True)
        self.assertFalse(r.anonymous_allowed)  # politique de l'entreprise : désactivé par défaut
        c = self.api(self.ib)
        self.assertEqual(c.post(f"/api/v1/methodology/retros/{r.pk}/feedback", {"category": "start", "text": "x", "anonymous": True},
                                format="json").status_code, 400)
        admin = User.objects.get(person_code="hb")
        self.api(admin).put("/api/v1/methodology/policy", {"allowAnonymous": True}, format="json")
        r2 = self.retro(participants=[self.ib.pk], anonymous=True, title="Rétro 2")
        resp = c.post(f"/api/v1/methodology/retros/{r2.pk}/feedback", {"category": "stop", "text": "Trop de réunions", "anonymous": True}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        fb = resp.json()["feedback"][0]
        self.assertIsNone(fb["author"])
        self.assertIsNone(r2.feedback.first().author_id)  # l'auteur n'est pas enregistré
        self.assertEqual(self.api(self.nb).post(f"/api/v1/methodology/retros/{r2.pk}/feedback", {"category": "stop", "text": "x"},
                                                format="json").status_code, 404)

    def test_improvements_become_actions_and_close_rules(self):
        r = self.retro(participants=[self.ib.pk])
        c = self.api(self.sm)
        resp = c.post(f"/api/v1/methodology/retros/{r.pk}/improvements", {"title": "Daily de 15 min max"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        imp = ImprovementAction.objects.get(retro=r)
        self.assertEqual(imp.action.type, "Amélioration")
        resp = c.post(f"/api/v1/methodology/retros/{r.pk}/close", {"report": "Compte rendu"}, format="json")
        self.assertEqual((resp.status_code, resp.json()["code"]), (409, "RETRO_INCOMPLETE"))
        # Clôture forcée : droit « Valider » requis.
        self.assertEqual(self.api(self.tl).post(f"/api/v1/methodology/retros/{r.pk}/close", {"report": "x", "force": True}, format="json").status_code, 403)
        c.patch(f"/api/v1/methodology/improvements/{imp.pk}", {"owner": self.ib.pk, "due": str(timezone.localdate() + timedelta(days=7))}, format="json")
        resp = c.post(f"/api/v1/methodology/retros/{r.pk}/close", {"report": "Compte rendu"}, format="json")
        self.assertEqual(resp.json()["status"], "closed")
        self.assertFalse(r.reminders.filter(status="pending").exists())
        # L'action PCT terminée rend l'amélioration réalisée ; les actions ouvertes réapparaissent ensuite.
        r2 = self.retro(title="Suivante")
        detail = c.get(f"/api/v1/methodology/retros/{r2.pk}").json()
        self.assertEqual([i["title"] for i in detail["previousOpen"]], ["Daily de 15 min max"])
        Action.objects.filter(pk=imp.action_id).update(status="done")
        detail = c.get(f"/api/v1/methodology/retros/{r2.pk}").json()
        self.assertEqual((detail["previousOpen"], detail["improvementRate"]), ([], 100))

    def test_auto_retro_for_v_cycle_is_idempotent(self):
        m = S.methodology(self.p1)
        m.settings = {**m.settings, "retroFrequency": "phase"}
        m.save()
        ph = self.p1.v_phases.first()
        ph.end = timezone.localdate() + timedelta(days=3)
        ph.save()
        S.process()
        S.process()
        self.assertEqual(Retrospective.objects.filter(project=self.p1, dedupe_key=f"phase:{ph.pk}").count(), 1)


class ReminderTests(Base):
    def test_due_reminders_sent_once_and_respect_preferences(self):
        r = S._remind(self.p1, "retro", timezone.now() + timedelta(minutes=1), [self.ib], "Rétro demain", key="t:1")
        self.assertIsNone(S._remind(self.p1, "retro", timezone.now() + timedelta(minutes=1), [self.ib], "Rétro demain", key="t:1"))
        Notification.objects.all().delete()
        later = timezone.now() + timedelta(minutes=2)
        S.process(later)
        S.process(later)
        self.assertEqual(Notification.objects.filter(user=self.ib, event="retro_reminder").count(), 1)
        r.refresh_from_db()
        self.assertEqual(r.status, "sent")

    def test_failure_is_retried_then_marked_failed(self):
        r = S._remind(self.p1, "daily", timezone.now(), [self.ib], "Daily", key="t:2")
        with mock.patch("methodology.services.notify", side_effect=RuntimeError("panne")):
            for i in range(3):
                S.process(timezone.now() + timedelta(hours=i + 1))
        r.refresh_from_db()
        self.assertEqual((r.status, r.attempts), ("failed", 3))
        self.assertIn("panne", r.last_error)

    def test_teams_channel_receives_reminder(self):
        t = self.p1.tenant
        NotificationChannel.objects.filter(tenant=t, kind="teams").update(enabled=True)
        NotificationRule.objects.filter(tenant=t, event="sprint_review", channel="teams").update(enabled=True)
        s = ServiceSecret(tenant=t, key="teams_webhook_url")
        s.set_value("https://acme.webhook.office.com/webhookb2/x")
        s.save()
        S._remind(self.p1, "sprint_review", timezone.now(), [self.ib], "Sprint Review demain", key="t:3")
        with mock.patch("configuration.notify.send_webhook") as hook:
            S.process(timezone.now() + timedelta(minutes=1))
        hook.assert_called_once()
        self.assertIn("Sprint Review demain", hook.call_args[0][2])

    def test_obsolete_reminders_are_cancelled(self):
        sp = Sprint.objects.create(tenant=self.p2.tenant, project=self.p2, number=95, start=monday(), end=monday() + timedelta(days=4), status="done")
        r = S._remind(self.p2, "daily", timezone.now(), [self.tl], "Daily", key="t:4", sprint=sp)
        S.process(timezone.now() + timedelta(minutes=1))
        r.refresh_from_db()
        self.assertEqual(r.status, "cancelled")


class MethodologyChangeTests(Base):
    def test_change_requires_impact_confirmation_and_approval(self):
        c = self.api(self.sm)
        r = c.post("/api/v1/methodology/projects/p1/impact", {"kind": "scrum"}, format="json")
        self.assertIn("phases", r.json()["disabled"])
        r = c.put("/api/v1/methodology/projects/p1", {"kind": "scrum"}, format="json")
        self.assertEqual((r.status_code, r.json()["code"]), (409, "METHODOLOGY_IMPACT"))
        self.assertEqual(ProjectMethodology.objects.get(project=self.p1).kind, "vcycle")
        self.assertEqual(self.api(self.tl).put("/api/v1/methodology/projects/p1", {"kind": "scrum", "confirm": True}, format="json").status_code, 403)
        r = c.put("/api/v1/methodology/projects/p1", {"kind": "scrum", "confirm": True}, format="json")
        self.assertEqual(r.json()["kind"], "scrum")
        self.assertEqual(r.json()["history"][-1]["from"], "vcycle")
        self.assertTrue(self.p1.v_phases.exists())  # données conservées, seulement masquées
        self.assertEqual(c.get(f"/api/v1/methodology/projects/p1/weeks/{monday()}").status_code, 409)

    def test_custom_features(self):
        c = self.api(self.sm)
        r = c.put("/api/v1/methodology/projects/p1", {"kind": "custom", "features": ["weekly", "retro"], "confirm": True}, format="json")
        self.assertEqual(sorted(r.json()["features"]), ["retro", "weekly"])


class IsolationTests(Base):
    def test_other_tenant_and_pilot_see_nothing(self):
        sp = Sprint.objects.filter(project=self.p2).first()
        retro = Retrospective.objects.filter(project__tenant=self.p2.tenant).first()
        c = self.api(self.admin2)
        self.assertEqual(c.get("/api/v1/methodology/projects").json(), [])
        for url in ("/api/v1/methodology/projects/p2", f"/api/v1/methodology/sprints/{sp.pk}", f"/api/v1/methodology/retros/{retro.pk}",
                    "/api/v1/methodology/projects/p2/backlog", "/api/v1/methodology/projects/p1/capacity"):
            self.assertEqual(c.get(url).status_code, 404, url)
        self.assertEqual(c.get("/api/v1/methodology/availabilities").json()["rows"], [])
        self.assertEqual(self.api(self.pilot).get("/api/v1/methodology/projects").status_code, 403)

    def test_client_portal_has_no_access(self):
        client = User.objects.get(person_code="lf")
        self.assertEqual(self.api(client).get("/api/v1/methodology/projects").status_code, 403)


class TimezoneTests(Base):
    def test_ceremonies_follow_project_timezone(self):
        m = S.methodology(self.p2)
        m.settings = {**m.settings, "timezone": "America/New_York", "dailyTime": "09:30"}
        m.save()
        at = S._at(self.p2, date(2026, 7, 1), "09:30")
        self.assertEqual(at.astimezone(dt_tz.utc).hour, 13)
        self.assertEqual(S._at(self.p2, date(2026, 12, 1), "09:30").astimezone(dt_tz.utc).hour, 14)


class AssistTests(Base):
    def test_assist_only_proposes(self):
        c = self.api(self.sm)
        before = (WeeklyPlan.objects.count(), Action.objects.count(), Sprint.objects.count())
        for topic in ("weekly_goals", "delays", "capacity", "risks", "priorities"):
            r = c.get(f"/api/v1/methodology/projects/p1/assist?topic={topic}")
            self.assertEqual(r.status_code, 200, topic)
            self.assertEqual(r.json()["engine"], "rules")
        for topic in ("sprint_goal", "blockers", "sprint_summary", "retro_synthesis", "recurring_improvements"):
            self.assertEqual(c.get(f"/api/v1/methodology/projects/p2/assist?topic={topic}").status_code, 200, topic)
        self.assertEqual(before, (WeeklyPlan.objects.count(), Action.objects.count(), Sprint.objects.count()))


class BootstrapTests(Base):
    def test_existing_data_was_imported(self):
        self.assertEqual(ProjectMethodology.objects.get(project=self.p2).kind, "scrum")
        self.assertEqual(ProjectMethodology.objects.get(project_id="p3").kind, "hybrid")
        self.assertTrue(self.p1.v_phases.filter(name="Note de cadrage", status="done").exists())
        self.assertTrue(Sprint.objects.filter(project=self.p2, number=12, goal__objective__isnull=False).exists())
        self.assertEqual(ProductBacklogItem.objects.filter(key="US-34").get().story_points, Decimal("8.0"))
        self.assertTrue(TeamMemberAllocation.objects.filter(project=self.p1, user=self.ib, allocation_pct=40).exists())
