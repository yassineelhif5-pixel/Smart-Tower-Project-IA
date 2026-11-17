"""API du module Recette (/api/v1/recette/…).

Droits : le projet doit être visible. Rédiger et passer les tests : administrateur, chef de projet, AMOA, testeur
(ou droit « test » en modification dans la matrice). Déclarer et affecter un bug : les mêmes et le tech lead.
La personne à qui le bug est affecté le fait avancer (en cours, clôturé). Tout le monde peut discuter.
"""
import re

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import LicenseIsValid, PasswordChangeNotRequired, TenantIsActive, has_perm
from config.errors import ApiError
from projects.access import visible_projects
from projects.models import Project, ProjectAccess

from .models import BUG_STATUSES, OPEN_BUG, PRIORITIES, STORY_STATUSES, Bug, TestComment, TestStory

User = get_user_model()
MANAGERS = {"admin", "direction", "manager", "cdp", "amoa", "testeur"}
BUG_ROLES = MANAGERS | {"techlead"}
PRIO_ORDER = {code: i for i, (code, _) in enumerate(PRIORITIES)}
STORY_LABEL, BUG_LABEL, PRIO_LABEL = dict(STORY_STATUSES), dict(BUG_STATUSES), dict(PRIORITIES)


def _projects(user):
    if user.is_app_admin:
        return Project.objects.filter(tenant_id=user.tenant_id)
    return visible_projects(user)


def can_manage(user):
    return user.role_id in MANAGERS or has_perm(user, "test", "update")


def can_report(user):
    return user.role_id in BUG_ROLES or has_perm(user, "test", "create")


def _project(user, pk):
    p = _projects(user).filter(pk=pk).first()
    if p is None:
        raise ApiError("NOT_FOUND", "Projet introuvable.", status.HTTP_404_NOT_FOUND)
    return p


def _members(project):
    ids = set(ProjectAccess.objects.filter(project=project).values_list("user_id", flat=True))
    users = User.objects.filter(Q(pk__in=ids) | Q(tenant_id=project.tenant_id, role_id__in=["admin", "cdp"]), is_active=True)
    return users.select_related("role").order_by("first_name", "last_name")


def _member(project, user_id):
    if user_id in (None, ""):
        return None
    u = _members(project).filter(pk=user_id).first()
    if u is None:
        raise ApiError("VALIDATION_ERROR", "Cette personne n'est pas membre du projet.")
    return u


def _name(u):
    return u.display_name if u else None


def _next_code(model, project, prefix):
    nums = [int(m.group(1)) for c in model.objects.filter(project=project).values_list("code", flat=True)
            if (m := re.match(rf"^{prefix}-(\d+)$", c))]
    return f"{prefix}-{(max(nums) if nums else 0) + 1}"


def _create_numbered(model, project, prefix, **fields):
    for _ in range(5):
        try:
            with transaction.atomic():
                return model.objects.create(project=project, tenant_id=project.tenant_id, code=_next_code(model, project, prefix), **fields)
        except IntegrityError:
            continue
    raise ApiError("CONFLICT", "Numérotation impossible, réessayez.", status.HTTP_409_CONFLICT)


def _event(project, actor, text, story=None, bug=None):
    TestComment.objects.create(project=project, tenant_id=project.tenant_id, story=story, bug=bug, author=actor, body=text, kind="event")


def _notify(event, users, title, body, project, actor):
    from configuration.mailer import app_url, dispatch
    dispatch(event, [u for u in users if u], title, body, project=project, actor=actor, link=f"{app_url()}/#recette/{project.pk}")


def story_row(s, open_bugs=None, total_bugs=None):
    return {"id": s.pk, "code": s.code, "title": s.title, "description": s.description, "acceptance": s.acceptance,
            "scenario": s.scenario, "expected": s.expected, "feature": s.feature,
            "priority": s.priority, "priorityLabel": PRIO_LABEL.get(s.priority, s.priority),
            "status": s.status, "statusLabel": STORY_LABEL.get(s.status, s.status),
            "tester": s.tester_id, "testerName": _name(s.tester), "createdBy": _name(s.created_by),
            "createdAt": s.created_at, "updatedAt": s.updated_at, "testedAt": s.tested_at, "testedBy": _name(s.tested_by),
            "openBugs": open_bugs if open_bugs is not None else s.bugs.filter(status__in=OPEN_BUG).count(),
            "bugs": total_bugs if total_bugs is not None else s.bugs.count()}


def bug_row(b):
    return {"id": b.pk, "code": b.code, "story": b.story_id, "storyCode": b.story.code, "storyTitle": b.story.title,
            "title": b.title, "description": b.description, "steps": b.steps, "resolution": b.resolution,
            "severity": b.severity, "severityLabel": PRIO_LABEL.get(b.severity, b.severity),
            "status": b.status, "statusLabel": BUG_LABEL.get(b.status, b.status), "open": b.status in OPEN_BUG,
            "assignee": b.assignee_id, "assigneeName": _name(b.assignee), "reportedBy": _name(b.reported_by),
            "reporter": b.reported_by_id, "createdAt": b.created_at, "updatedAt": b.updated_at, "closedAt": b.closed_at}


def refresh_story_after_bug(story, actor):
    """Plus aucun bug ouvert sur une US en échec : elle devient « Prête à retester »."""
    if story.status in ("echec", "en_test", "bloquee") and story.bugs.exists() and not story.bugs.filter(status__in=OPEN_BUG).exists():
        story.status = "a_retester"
        story.save(update_fields=["status", "updated_at"])
        _event(story.project, actor, "Tous les bugs sont clôturés : US prête à retester.", story=story)
        targets = [story.tester] + [b.reported_by for b in story.bugs.select_related("reported_by")]
        _notify("action_updated", targets, f"{story.code} prête à retester", story.title, story.project, actor)
        return True
    return False


class Base(APIView):
    permission_classes = [permissions.IsAuthenticated, TenantIsActive, PasswordChangeNotRequired, LicenseIsValid]

    def setup_user(self, request):
        u = request.user
        # Tous les profils internes (dont développeurs et consultants qui traitent les bugs) ; pas le portail client.
        if not u.tenant_id or not (has_perm(u, "test", "read") or u.is_app_admin or (u.role_id and u.role.internal)):
            raise ApiError("FORBIDDEN_PERMISSION", "Le module Recette n'est pas ouvert à votre profil.", status.HTTP_403_FORBIDDEN)
        return request.user


class ProjectsView(Base):
    """GET /recette/projects : projets visibles avec l'avancement de la recette."""

    def get(self, request):
        user = self.setup_user(request)
        projects = list(_projects(user).order_by("name"))
        stories = (TestStory.objects.filter(project__in=projects).values("project_id", "status").annotate(n=Count("id")))
        bugs = Bug.objects.filter(project__in=projects, status__in=OPEN_BUG).values("project_id").annotate(n=Count("id"))
        st, bg = {}, {b["project_id"]: b["n"] for b in bugs}
        for r in stories:
            st.setdefault(r["project_id"], {})[r["status"]] = r["n"]
        return Response({"projects": [{"id": p.pk, "code": p.code, "name": p.name, "stories": sum(st.get(p.pk, {}).values()),
                                       "byStatus": st.get(p.pk, {}), "openBugs": bg.get(p.pk, 0)} for p in projects],
                         "perms": {"manage": can_manage(user), "report": can_report(user)}})


class BoardView(Base):
    """GET /recette/board?project= : US, bugs, membres et droits pour un projet."""

    def get(self, request):
        user = self.setup_user(request)
        project = _project(user, request.query_params.get("project"))
        stories = list(TestStory.objects.filter(project=project).select_related("tester", "created_by", "tested_by")
                       .annotate(n_open=Count("bugs", filter=Q(bugs__status__in=OPEN_BUG)), n_bugs=Count("bugs")))
        bugs = list(Bug.objects.filter(project=project).select_related("story", "assignee", "reported_by"))
        comments = dict(TestComment.objects.filter(project=project, kind="comment").values_list("story_id").annotate(n=Count("id")))
        bug_comments = dict(TestComment.objects.filter(project=project, kind="comment", bug__isnull=False).values_list("bug_id").annotate(n=Count("id")))
        rows = []
        for s in sorted(stories, key=lambda x: (PRIO_ORDER.get(x.priority, 9), x.pk)):
            r = story_row(s, s.n_open, s.n_bugs)
            r["comments"] = comments.get(s.pk, 0)
            rows.append(r)
        brows = []
        for b in sorted(bugs, key=lambda x: (x.status not in OPEN_BUG, PRIO_ORDER.get(x.severity, 9), x.pk)):
            r = bug_row(b)
            r["comments"] = bug_comments.get(b.pk, 0)
            brows.append(r)
        return Response({
            "project": {"id": project.pk, "code": project.code, "name": project.name},
            "stories": rows, "bugs": brows,
            "members": [{"id": u.pk, "name": u.display_name, "role": u.role.label if u.role_id else ""} for u in _members(project)],
            "me": user.pk,
            "perms": {"manage": can_manage(user), "report": can_report(user), "assign": can_report(user)},
            "priorities": [{"code": c, "label": l} for c, l in PRIORITIES],
            "storyStatuses": [{"code": c, "label": l} for c, l in STORY_STATUSES],
            "bugStatuses": [{"code": c, "label": l} for c, l in BUG_STATUSES],
        })


def _clean(d, key, limit=None):
    v = str(d.get(key) or "").strip()
    return v[:limit] if limit else v


def _apply_story_fields(story, d):
    for key, field, limit in (("title", "title", 300), ("description", "description", None), ("acceptance", "acceptance", None),
                              ("scenario", "scenario", None), ("expected", "expected", None), ("feature", "feature", 120)):
        if key in d:
            setattr(story, field, _clean(d, key, limit))
    if "priority" in d:
        if d["priority"] not in PRIO_LABEL:
            raise ApiError("VALIDATION_ERROR", "Priorité inconnue.")
        story.priority = d["priority"]
    if not story.title:
        raise ApiError("VALIDATION_ERROR", "Indiquez le titre de l'US.")


class StoriesView(Base):
    def post(self, request, pk=None):
        user = self.setup_user(request)
        if not can_manage(user):
            raise ApiError("FORBIDDEN_PERMISSION", "Seuls le chef de projet, l'AMOA, l'administrateur et les testeurs créent des US.",
                           status.HTTP_403_FORBIDDEN)
        d = request.data or {}
        project = _project(user, d.get("project"))
        story = TestStory(project=project)
        _apply_story_fields(story, d)
        tester = _member(project, d.get("tester"))
        story = _create_numbered(TestStory, project, "US", title=story.title, description=story.description,
                                 acceptance=story.acceptance, scenario=story.scenario, expected=story.expected,
                                 feature=story.feature, priority=story.priority, tester=tester, created_by=user)
        _event(project, user, "US créée.", story=story)
        if tester and tester != user:
            _notify("action_created", [tester], f"{story.code} à tester", story.title, project, user)
        return Response(story_row(story), status=status.HTTP_201_CREATED)


class StoryView(Base):
    def _get(self, request, pk):
        user = self.setup_user(request)
        story = get_object_or_404(TestStory.objects.select_related("project", "tester"), pk=pk, project__in=_projects(user))
        return user, story

    def patch(self, request, pk):
        user, story = self._get(request, pk)
        if not can_manage(user):
            raise ApiError("FORBIDDEN_PERMISSION", "Modification réservée au chef de projet, à l'AMOA, à l'administrateur et aux testeurs.",
                           status.HTTP_403_FORBIDDEN)
        d = request.data or {}
        _apply_story_fields(story, d)
        if "tester" in d:
            tester = _member(story.project, d.get("tester"))
            if tester != story.tester and tester and tester != user:
                _notify("action_created", [tester], f"{story.code} à tester", story.title, story.project, user)
            story.tester = tester
        story.save()
        return Response(story_row(story))

    def delete(self, request, pk):
        user, story = self._get(request, pk)
        if not (user.is_app_admin or user.role_id in {"cdp", "amoa", "manager", "direction"}):
            raise ApiError("FORBIDDEN_PERMISSION", "Suppression réservée au chef de projet, à l'AMOA et à l'administrateur.",
                           status.HTTP_403_FORBIDDEN)
        story.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StoryStatusView(StoryView):
    """POST /recette/stories/<id>/status {status, comment?} : résultat du test."""

    def post(self, request, pk):
        user, story = self._get(request, pk)
        if not can_manage(user):
            raise ApiError("FORBIDDEN_PERMISSION", "Seuls les testeurs, le chef de projet, l'AMOA et l'administrateur passent les tests.",
                           status.HTTP_403_FORBIDDEN)
        d = request.data or {}
        new = d.get("status")
        if new not in STORY_LABEL:
            raise ApiError("VALIDATION_ERROR", "Statut inconnu.")
        if new == "validee" and story.bugs.filter(status__in=OPEN_BUG).exists():
            raise ApiError("VALIDATION_ERROR", "Des bugs sont encore ouverts sur cette US : clôturez-les avant de la valider.")
        old = story.status
        story.status = new
        if new in ("validee", "echec", "bloquee"):
            story.tested_at, story.tested_by = timezone.now(), user
        story.save()
        note = _clean(d, "comment", 2000)
        _event(story.project, user, f"Statut : {STORY_LABEL.get(old, old)} → {STORY_LABEL[new]}" + (f" — {note}" if note else ""), story=story)
        if new in ("validee", "echec") and story.created_by_id and story.created_by != user:
            _notify("action_updated", [story.created_by], f"{story.code} : {STORY_LABEL[new]}", story.title, story.project, user)
        return Response(story_row(story))


class BugsView(Base):
    """POST /recette/bugs {story, title, description, steps, severity, assignee?} : déclarer un bug."""

    def post(self, request):
        user = self.setup_user(request)
        if not can_report(user):
            raise ApiError("FORBIDDEN_PERMISSION", "Votre profil ne peut pas déclarer de bug.", status.HTTP_403_FORBIDDEN)
        d = request.data or {}
        story = get_object_or_404(TestStory.objects.select_related("project"), pk=d.get("story"), project__in=_projects(user))
        title = _clean(d, "title", 300)
        if not title:
            raise ApiError("VALIDATION_ERROR", "Indiquez le titre du bug.")
        severity = d.get("severity") or "majeure"
        if severity not in PRIO_LABEL:
            raise ApiError("VALIDATION_ERROR", "Sévérité inconnue.")
        assignee = _member(story.project, d.get("assignee"))
        bug = _create_numbered(Bug, story.project, "BUG", story=story, title=title, description=_clean(d, "description"),
                               steps=_clean(d, "steps"), severity=severity, assignee=assignee, reported_by=user,
                               status="assigne" if assignee else "nouveau")
        if story.status != "echec":
            old = story.status
            story.status, story.tested_at, story.tested_by = "echec", timezone.now(), user
            story.save(update_fields=["status", "tested_at", "tested_by", "updated_at"])
            _event(story.project, user, f"Statut : {STORY_LABEL.get(old, old)} → En échec ({bug.code} déclaré)", story=story)
        _event(story.project, user, f"Bug {bug.code} déclaré ({PRIO_LABEL[severity]})." + (f" Affecté à {assignee.display_name}." if assignee else ""), bug=bug)
        _event(story.project, user, f"Bug {bug.code} déclaré : {title}", story=story)
        if assignee:
            _notify("action_created", [assignee], f"Bug {bug.code} affecté ({PRIO_LABEL[severity]})", f"{title} — {story.code} {story.title}",
                    story.project, user)
        return Response(bug_row(bug), status=status.HTTP_201_CREATED)


class BugView(Base):
    """PATCH /recette/bugs/<id> {title?, description?, steps?, severity?, assignee?, status?, resolution?, comment?}."""

    def patch(self, request, pk):
        user = self.setup_user(request)
        bug = get_object_or_404(Bug.objects.select_related("project", "story", "assignee", "reported_by"), pk=pk,
                                project__in=_projects(user))
        d = request.data or {}
        manager = can_report(user)
        is_assignee = bug.assignee_id == user.pk
        if not (manager or is_assignee):
            raise ApiError("FORBIDDEN_PERMISSION", "Seuls la personne affectée, le testeur, le tech lead et le chef de projet modifient ce bug.",
                           status.HTTP_403_FORBIDDEN)
        events = []
        for key, limit in (("title", 300), ("description", None), ("steps", None)):
            if key in d:
                if not manager:
                    raise ApiError("FORBIDDEN_PERMISSION", "Seul le déclarant ou le chef de projet modifie la description.", status.HTTP_403_FORBIDDEN)
                setattr(bug, key, _clean(d, key, limit))
        if "severity" in d and d["severity"] != bug.severity:
            if not manager or d["severity"] not in PRIO_LABEL:
                raise ApiError("VALIDATION_ERROR", "Sévérité invalide.")
            events.append(f"Sévérité : {PRIO_LABEL[bug.severity]} → {PRIO_LABEL[d['severity']]}")
            bug.severity = d["severity"]
        if "assignee" in d:
            if not manager:
                raise ApiError("FORBIDDEN_PERMISSION", "Seuls le testeur, le tech lead et le chef de projet affectent un bug.", status.HTTP_403_FORBIDDEN)
            new = _member(bug.project, d.get("assignee"))
            if new != bug.assignee:
                events.append(f"Affecté à {new.display_name}" if new else "Affectation retirée")
                bug.assignee = new
                if bug.status == "nouveau" and new:
                    bug.status = "assigne"
                if new and new != user:
                    _notify("action_created", [new], f"Bug {bug.code} affecté ({PRIO_LABEL[bug.severity]})",
                            f"{bug.title} — {bug.story.code} {bug.story.title}", bug.project, user)
        if "resolution" in d:
            bug.resolution = _clean(d, "resolution")
        closed_now = False
        if "status" in d and d["status"] != bug.status:
            new = d["status"]
            if new not in BUG_LABEL:
                raise ApiError("VALIDATION_ERROR", "Statut inconnu.")
            if not manager and new not in ("en_cours", "cloture"):
                raise ApiError("FORBIDDEN_PERMISSION", "La personne affectée passe le bug « En cours » ou « Clôturé ».", status.HTTP_403_FORBIDDEN)
            events.append(f"Statut : {BUG_LABEL[bug.status]} → {BUG_LABEL[new]}")
            was_open = bug.status in OPEN_BUG
            bug.status = new
            if new in ("cloture", "rejete"):
                bug.closed_at = timezone.now()
                closed_now = was_open
            else:
                bug.closed_at = None
            if new == "rouvert" and bug.story.status == "a_retester":
                bug.story.status = "echec"
                bug.story.save(update_fields=["status", "updated_at"])
                _event(bug.project, user, f"Statut : Prête à retester → En échec ({bug.code} rouvert)", story=bug.story)
            if new in ("cloture", "rejete") and bug.reported_by and bug.reported_by != user:
                _notify("action_updated", [bug.reported_by], f"Bug {bug.code} {BUG_LABEL[new].lower()}", bug.title, bug.project, user)
            if new == "rouvert" and bug.assignee and bug.assignee != user:
                _notify("action_updated", [bug.assignee], f"Bug {bug.code} rouvert", bug.title, bug.project, user)
        bug.save()
        note = _clean(d, "comment", 2000)
        if events or note:
            _event(bug.project, user, " · ".join(events) + (f" — {note}" if note else "") if events else note, bug=bug)
        if closed_now:
            refresh_story_after_bug(bug.story, user)
        return Response(bug_row(bug))


class ThreadView(Base):
    """GET /recette/thread?story=|bug= ; POST {story|bug, body} : discussion."""

    def _target(self, request, data):
        user = self.setup_user(request)
        projects = _projects(user)
        if data.get("bug"):
            bug = get_object_or_404(Bug.objects.select_related("project"), pk=data.get("bug"), project__in=projects)
            return user, {"bug": bug, "project": bug.project}
        story = get_object_or_404(TestStory.objects.select_related("project"), pk=data.get("story"), project__in=projects)
        return user, {"story": story, "project": story.project}

    def get(self, request):
        _, t = self._target(request, request.query_params)
        rows = TestComment.objects.filter(**{k: v for k, v in t.items() if k != "project"}).select_related("author")
        return Response({"comments": [{"id": c.pk, "author": _name(c.author) or "Système", "authorId": c.author_id, "body": c.body,
                                       "kind": c.kind, "createdAt": c.created_at} for c in rows]})

    def post(self, request):
        user, t = self._target(request, request.data or {})
        body = _clean(request.data or {}, "body", 5000)
        if not body:
            raise ApiError("VALIDATION_ERROR", "Le message est vide.")
        c = TestComment.objects.create(tenant_id=t["project"].tenant_id, author=user, body=body, kind="comment", **t)
        # Prévenir les personnes concernées (testeur, déclarant, personne affectée), sauf l'auteur.
        target = t.get("bug") or t.get("story")
        people = ([target.assignee, target.reported_by] if t.get("bug") else [target.tester, target.created_by])
        _notify("action_updated", people, f"Nouveau message sur {target.code}", body[:300], t["project"], user)
        return Response({"id": c.pk, "author": user.display_name, "authorId": user.pk, "body": c.body, "kind": c.kind,
                         "createdAt": c.created_at}, status=status.HTTP_201_CREATED)
