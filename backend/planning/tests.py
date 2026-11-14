"""Calendrier (1.4.0) : événements, affectations multiples, conflits, charge, retards, fuseaux, droits, isolation, ICS."""
from datetime import date, datetime, timedelta, timezone as dt_tz
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from configuration.models import Notification
from projects.models import Action, Project, ProjectAccess
from tenants import services as tenant_services

from . import models as M
from . import services as S

User = get_user_model()


def nextweek(days=0):
    """Un mardi à venir (jour ouvré), pour des tests indépendants de la date du jour."""
    d = timezone.localdate() + timedelta(days=14)
    d += timedelta(days=(1 - d.weekday()) % 7)
    return d + timedelta(days=days)


class Base(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_demo", stdout=open("/dev/null", "w"))
        cls.sm = User.objects.get(person_code="sm")   # cheffe de projet (p1, p2, p3)
        cls.ib = User.objects.get(person_code="ib")   # consultante (p1, p2, p3, p5)
        cls.nb = User.objects.get(person_code="nb")   # manager Santé (p5 uniquement)
        cls.nh = User.objects.get(person_code="nh")   # direction : tout le tenant
        cls.p1 = Project.objects.get(pk="p1")
        cls.p5 = Project.objects.get(pk="p5")
        pilot = User.objects.create(username="pilote.cal", role_id="superadmin", tenant=None)
        cls.pilot = pilot
        cls.t2, cls.admin2, _ = tenant_services.create_tenant(by=pilot, name="Autre", admin_username="admin.autre")
        cls.admin2.must_change_password = False
        cls.admin2.save()

    def as_user(self, user):
        c = APIClient()
        c.force_authenticate(User.objects.get(pk=user.pk))
        return c

    def create(self, user, **data):
        payload = {"project": "p1", "title": "Atelier", "allDay": True, "start": nextweek().isoformat(),
                   "end": nextweek().isoformat(), "assignments": [{"user": user.pk, "role": "owner"}], **data}
        return self.as_user(user).post("/api/v1/calendar/events", payload, format="json")


class EventTests(Base):
    def test_create_event_with_multiple_assignments(self):
        r = self.create(self.sm, assignments=[{"user": self.sm.pk, "role": "owner", "estimatedWorkload": 3},
                                               {"user": self.ib.pk, "role": "contributor", "estimatedWorkload": 2}])
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(sorted(a["role"] for a in body["assignments"]), ["contributor", "owner"])
        self.assertEqual(body["startDate"], nextweek().isoformat())
        self.assertEqual(body["endDate"], nextweek().isoformat())
        # Visible des personnes affectées et du projet ; reprise dans la liste par période.
        rows = self.as_user(self.ib).get("/api/v1/calendar/events", {"start": nextweek(-1).isoformat(),
                                                                     "end": nextweek(1).isoformat(), "mine": "1"}).json()
        self.assertIn(body["id"], [e["id"] for e in rows["results"]])

    def test_single_owner_and_tenant_members_only(self):
        r = self.create(self.sm, assignments=[{"user": self.sm.pk, "role": "owner"}, {"user": self.ib.pk, "role": "owner"}])
        self.assertEqual(r.status_code, 400)
        r = self.create(self.sm, assignments=[{"user": self.admin2.pk, "role": "owner"}])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(M.CalendarEvent.objects.filter(title="Atelier").count(), 0)  # rien d'enregistré

    def test_validation(self):
        self.assertEqual(self.create(self.sm, title="").status_code, 400)
        self.assertEqual(self.create(self.sm, start=nextweek(2).isoformat(), end=nextweek().isoformat()).status_code, 400)
        self.assertEqual(self.create(self.sm, priority="urgentissime").status_code, 400)
        self.assertEqual(self.create(self.sm, progress=140).status_code, 400)
        self.assertEqual(self.create(self.sm, timezone="Mars/Olympus").status_code, 400)

    def test_moving_action_event_updates_action_and_notifies(self):
        action = Action.objects.filter(project=self.p1, calendar_event__isnull=False, owner=self.ib).first()
        event = action.calendar_event
        Notification.objects.all().delete()
        r = self.as_user(self.sm).patch(f"/api/v1/calendar/events/{event.pk}", {
            "start": nextweek().isoformat(), "end": nextweek(2).isoformat(), "allDay": True, "confirm": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        action.refresh_from_db()
        self.assertEqual((action.start_date, action.due), (nextweek(), nextweek(2)))
        self.assertTrue(Notification.objects.filter(user=self.ib, event="date_changed").exists())

    def test_owner_change_is_copied_to_action(self):
        action = Action.objects.filter(project=self.p1, calendar_event__isnull=False, owner=self.ib).first()
        r = self.as_user(self.sm).patch(f"/api/v1/calendar/events/{action.calendar_event.pk}", {
            "assignments": [{"user": self.sm.pk, "role": "owner"}, {"user": self.ib.pk, "role": "contributor"}],
            "confirm": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        action.refresh_from_db()
        self.assertEqual(action.owner_id, self.sm.pk)
        # L'ancienne responsable est prévenue ; l'auteur du changement ne se notifie pas lui-même.
        self.assertTrue(Notification.objects.filter(user=self.ib, event="owner_changed").exists())
        self.assertFalse(Notification.objects.filter(user=self.sm, event="owner_changed").exists())

    def test_done_sets_progress_and_completion(self):
        e = self.create(self.sm, assignments=[{"user": self.sm.pk, "role": "owner"}]).json()
        r = self.as_user(self.sm).patch(f"/api/v1/calendar/events/{e['id']}", {"status": "done"}, format="json")
        self.assertEqual((r.json()["progress"], bool(r.json()["completedAt"])), (100, True))

    def test_dependency_cycle_is_refused(self):
        a = self.create(self.sm, title="A").json()
        b = self.create(self.sm, title="B", dependencies=[{"predecessor": a["id"], "type": "FS"}], confirm=True)
        self.assertEqual(b.status_code, 201, b.content)
        r = self.as_user(self.sm).patch(f"/api/v1/calendar/events/{a['id']}",
                                        {"dependencies": [{"predecessor": b.json()["id"]}]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("circulaire", r.json()["message"])

    def test_delete(self):
        e = self.create(self.sm).json()
        self.assertEqual(self.as_user(self.ib).delete(f"/api/v1/calendar/events/{e['id']}").status_code, 403)
        self.assertEqual(self.as_user(self.sm).delete(f"/api/v1/calendar/events/{e['id']}").status_code, 204)


class TimezoneTests(Base):
    def test_all_day_covers_local_midnight_to_midnight(self):
        e = self.create(self.sm, start="2026-11-10", end="2026-11-11").json()
        ev = M.CalendarEvent.objects.get(pk=e["id"])
        self.assertEqual(ev.start, datetime(2026, 11, 9, 23, 0, tzinfo=dt_tz.utc))   # Paris = UTC+1 en novembre
        self.assertEqual(ev.end, datetime(2026, 11, 11, 23, 0, tzinfo=dt_tz.utc))    # fin incluse côté saisie
        self.assertEqual((e["startDate"], e["endDate"]), ("2026-11-10", "2026-11-11"))

    def test_timed_event_in_other_zone_and_dst(self):
        e = self.create(self.sm, allDay=False, timezone="America/New_York",
                        start="2027-07-01T09:00", end="2027-07-01T10:30", confirm=True).json()
        ev = M.CalendarEvent.objects.get(pk=e["id"])
        self.assertEqual(ev.start, datetime(2027, 7, 1, 13, 0, tzinfo=dt_tz.utc))    # New York = UTC-4 en été
        self.assertEqual(ev.end - ev.start, timedelta(minutes=90))
        winter = self.create(self.sm, allDay=False, start="2026-12-01T09:00", end="2026-12-01T10:00").json()
        self.assertEqual(M.CalendarEvent.objects.get(pk=winter["id"]).start, datetime(2026, 12, 1, 8, 0, tzinfo=dt_tz.utc))


class ConflictTests(Base):
    def timed(self, user, start, end, **extra):
        day = nextweek().isoformat()
        return self.create(user, allDay=False, start=f"{day}T{start}", end=f"{day}T{end}",
                           assignments=[{"user": self.ib.pk, "role": "owner"}], **extra)

    def test_overlap_requires_confirmation_and_nothing_is_saved(self):
        self.assertEqual(self.timed(self.sm, "10:00", "12:00", title="Revue").status_code, 201)
        r = self.timed(self.sm, "11:00", "13:00", title="Démo")
        self.assertEqual(r.status_code, 409)
        body = r.json()
        self.assertEqual(body["code"], "CALENDAR_CONFLICTS")
        conflict = next(c for c in body["details"] if c["type"] == "double_booking")
        self.assertIn("se chevauchent", conflict["explanation"])
        self.assertEqual(conflict["suggestion"]["action"], "move")
        self.assertFalse(M.CalendarEvent.objects.filter(title="Démo").exists())  # rien n'est déplacé ni créé
        # Confirmation explicite : enregistré tel quel.
        self.assertEqual(self.timed(self.sm, "11:00", "13:00", title="Démo", confirm=True).status_code, 201)

    def test_overload_detected_and_workload_reported(self):
        r = self.create(self.sm, title="Gros lot", assignments=[{"user": self.ib.pk, "role": "owner", "estimatedWorkload": 16}])
        self.assertEqual(r.status_code, 409)
        self.assertIn("overload", [c["type"] for c in r.json()["details"]])
        self.create(self.sm, title="Gros lot", confirm=True,
                    assignments=[{"user": self.ib.pk, "role": "owner", "estimatedWorkload": 16}])
        load = self.as_user(self.sm).get("/api/v1/calendar/workload", {"start": nextweek().isoformat(),
                                                                       "end": nextweek().isoformat()}).json()
        row = next(r for r in load["rows"] if r["key"] == str(self.ib.pk))
        self.assertIn(nextweek().isoformat(), row["over"])

    def test_assignee_progress_update_is_not_blocked_by_conflicts(self):
        self.timed(self.sm, "10:00", "12:00", title="Revue")
        e = self.timed(self.sm, "11:00", "13:00", title="Démo", confirm=True).json()
        r = self.as_user(self.ib).patch(f"/api/v1/calendar/events/{e['id']}", {"progress": 50, "status": "doing"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def test_invisible_events_are_never_named(self):
        # ib est affectée à un événement de p5 (que sm ne voit pas) et à un événement de p1, au même moment.
        day = nextweek().isoformat()
        tz = S.zone("Europe/Paris")
        secret = M.CalendarEvent.objects.create(
            tenant=self.p5.tenant, project=self.p5, title="Secret santé", all_day=False,
            start=datetime.combine(nextweek(), datetime.min.time().replace(hour=10), tzinfo=tz),
            end=datetime.combine(nextweek(), datetime.min.time().replace(hour=12), tzinfo=tz))
        M.CalendarAssignment.objects.create(tenant=secret.tenant, event=secret, user=self.ib, role="owner")
        self.assertEqual(day, nextweek().isoformat())
        r = self.timed(self.sm, "11:00", "12:30", title="Point Nordline")
        self.assertEqual(r.status_code, 409)
        text = str(r.json())
        self.assertNotIn("Secret santé", text)
        self.assertIn("un autre engagement", text)

    def test_conflict_list_and_dependency_conflict(self):
        a = self.create(self.sm, title="Conception", start=nextweek(1).isoformat(), end=nextweek(3).isoformat(),
                        assignments=[{"user": self.sm.pk, "role": "owner"}]).json()
        r = self.create(self.sm, title="Développement", start=nextweek(2).isoformat(), end=nextweek(4).isoformat(),
                        assignments=[{"user": self.sm.pk, "role": "owner"}], dependencies=[{"predecessor": a["id"], "type": "FS"}])
        self.assertEqual(r.status_code, 409)
        self.assertIn("dependency", [c["type"] for c in r.json()["details"]])
        rows = self.as_user(self.sm).get("/api/v1/calendar/conflicts", {"start": nextweek().isoformat(),
                                                                        "end": nextweek(7).isoformat()}).json()
        self.assertIsInstance(rows, list)


class DelayAndDashboardTests(Base):
    def test_late_events_are_notified_once_and_counted(self):
        past = (timezone.localdate() - timedelta(days=5)).isoformat()
        e = self.create(self.sm, title="En retard", start=past, end=past, confirm=True,
                        assignments=[{"user": self.ib.pk, "role": "owner"}]).json()
        Notification.objects.all().delete()
        S.notify_late()
        S.notify_late()
        self.assertEqual(Notification.objects.filter(user=self.ib, event="action_late", body="En retard").count(), 1)
        dash = self.as_user(self.sm).get("/api/v1/calendar/dashboard", {"start": past, "end": timezone.localdate().isoformat()}).json()
        self.assertGreaterEqual(dash["late"], 1)
        self.assertTrue(self.as_user(self.sm).get(f"/api/v1/calendar/events/{e['id']}").json()["late"])

    def test_reminders_are_sent_once(self):
        e = self.create(self.sm, assignments=[{"user": self.ib.pk, "role": "owner"}]).json()
        event = M.CalendarEvent.objects.get(pk=e["id"])
        M.CalendarReminder.objects.create(tenant=event.tenant, event=event, user=self.ib, channel="inapp",
                                          remind_at=timezone.now() - timedelta(minutes=1))
        Notification.objects.all().delete()
        S.process_due_reminders()
        S.process_due_reminders()
        self.assertEqual(Notification.objects.filter(user=self.ib, event="deadline_reminder").count(), 1)

    def test_portfolio_and_dashboard_scope(self):
        rows = self.as_user(self.nb).get("/api/v1/calendar/portfolio").json()
        self.assertEqual({r["code"] for r in rows}, {"ORP-PAT"})
        self.assertEqual(len(self.as_user(self.nh).get("/api/v1/calendar/portfolio").json()), 5)


class AccessTests(Base):
    def test_project_scope_and_quick_update(self):
        e = self.create(self.sm, assignments=[{"user": self.sm.pk, "role": "owner"}, {"user": self.ib.pk, "role": "contributor"}]).json()
        self.assertEqual(self.as_user(self.nb).get(f"/api/v1/calendar/events/{e['id']}").status_code, 404)
        c = self.as_user(self.ib)
        ProjectAccess.objects.filter(user=self.ib, project=self.p1).update(can_edit=False)
        self.assertEqual(c.patch(f"/api/v1/calendar/events/{e['id']}", {"title": "Autre"}, format="json").status_code, 403)
        r = c.patch(f"/api/v1/calendar/events/{e['id']}", {"progress": 40, "actualWorkload": 2.5}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        mine = next(a for a in r.json()["assignments"] if a["user"]["id"] == self.ib.pk)
        self.assertEqual(mine["actualWorkload"], 2.5)

    def test_tenant_isolation_and_pilot(self):
        e = self.create(self.sm).json()
        self.assertEqual(self.as_user(self.admin2).get(f"/api/v1/calendar/events/{e['id']}").status_code, 404)
        rows = self.as_user(self.admin2).get("/api/v1/calendar/events").json()
        self.assertEqual(rows["count"], 0)
        self.assertEqual(self.as_user(self.pilot).get("/api/v1/calendar/events").status_code, 403)
        # Un autre tenant ne peut pas viser un projet ni une action d'ici.
        r = self.as_user(self.admin2).post("/api/v1/calendar/events", {"project": "p1", "title": "x", "start": "2026-12-01",
                                                                       "end": "2026-12-01"}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_colors_are_per_tenant_and_validated(self):
        admin = User.objects.get(person_code="hb")
        c = self.as_user(admin)
        self.assertEqual(c.put("/api/v1/calendar/settings", {"status": {"done": "vert"}}, format="json").status_code, 400)
        r = c.put("/api/v1/calendar/settings", {"status": {"done": "#00AA00"}, "colorBy": "priority"}, format="json")
        self.assertEqual((r.status_code, r.json()["status"]["done"], r.json()["colorBy"]), (200, "#00AA00", "priority"))
        self.assertEqual(self.as_user(self.admin2).get("/api/v1/calendar/settings").json()["status"]["done"], "#1D8A57")
        self.assertEqual(self.as_user(self.ib).put("/api/v1/calendar/settings", {}, format="json").status_code, 403)


class FeedTests(Base):
    def test_ics_feed_lifecycle(self):
        self.create(self.sm, title="Comité; pilotage", assignments=[{"user": self.sm.pk, "role": "owner"}])
        c = self.as_user(self.sm)
        url = c.post("/api/v1/calendar/feed-token").json()["url"]
        path = url[url.index("/api/"):]
        r = APIClient().get(path)
        self.assertEqual(r.status_code, 200)
        text = r.content.decode()
        self.assertTrue(text.startswith("BEGIN:VCALENDAR"))
        self.assertIn("Comité\\; pilotage", text)
        self.assertNotIn("Secret", text)
        c.delete("/api/v1/calendar/feed-token")
        self.assertEqual(APIClient().get(path).status_code, 404)
        self.assertEqual(APIClient().get("/api/v1/calendar/feed/nimporte.ics").status_code, 404)


class MigrationTests(Base):
    def test_existing_actions_are_planned_once(self):
        dated = Action.objects.filter(tenant=self.p1.tenant).exclude(due__isnull=True, start_date__isnull=True).count()
        self.assertEqual(M.CalendarEvent.objects.filter(kind="action").count(), dated)
        self.assertEqual(S.plan_existing_actions(self.p1.tenant), 0)
        e = M.CalendarEvent.objects.filter(action__owner__isnull=False).first()
        self.assertEqual(e.assignments.get(role="owner").user_id, e.action.owner_id)


class UnitTests(Base):
    def test_working_days(self):
        self.assertEqual(S.add_working_days(date(2026, 11, 6), 1), date(2026, 11, 9))  # vendredi + 1 = lundi
        self.assertEqual(len(list(S.working_days(date(2026, 11, 2), date(2026, 11, 8)))), 5)

    def test_hours_per_day_setting(self):
        self.assertEqual(S.hours_per_day(self.p1.tenant), Decimal("8"))
