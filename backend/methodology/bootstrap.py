"""Reprise des données méthodologiques déjà présentes (champs `method`, `phases`, `agile`, `staff`, user stories).

Utilisé par la migration `methodology/0002` (modèles historiques) et par `load_demo` (modèles courants) : la
fonction reçoit `M(nom)` qui renvoie la classe de modèle. Idempotent : un projet déjà repris n'est pas modifié.
Aucune donnée d'origine n'est modifiée ni supprimée.
"""
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
PRIO = {"Basse": "low", "Faible": "low", "Normale": "normal", "Moyenne": "normal", "Haute": "high",
        "Critique": "critical", "Bloquante": "critical"}


def kind_of(method):
    m = (method or "").lower()
    if "hybr" in m:
        return "hybrid"
    if "agile" in m or "scrum" in m:
        return "scrum"
    return "vcycle"


def _d(value):
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def bootstrap_project(M, project, today=None):
    today = today or date.today()
    if M("ProjectMethodology").objects.filter(project=project).exists():
        return False
    User = M("User")
    people = {u.person_code: u for u in User.objects.filter(tenant_id=project.tenant_id, person_code__isnull=False)}
    agile = project.agile or {}
    kind = kind_of(project.method)
    settings = {}
    if (agile.get("scrum") or {}).get("weeks"):
        settings["sprintWeeks"] = int(agile["scrum"]["weeks"])
    if kind == "vcycle":
        settings["retroFrequency"] = "phase"
    M("ProjectMethodology").objects.create(tenant_id=project.tenant_id, project=project, kind=kind, settings=settings)

    # Phases (planning macro) : [début, fin, fin prévue, avancement, responsable, nom].
    for i, ph in enumerate(project.phases or []):
        if not isinstance(ph, (list, tuple)) or len(ph) < 6:
            continue
        start, end, forecast, progress, owner, name = ph[:6]
        progress = int(progress or 0)
        status = "done" if progress >= 100 else ("doing" if progress else "todo")
        if status != "done" and _d(forecast) and _d(end) and _d(forecast) > _d(end):
            status = "late"
        M("VPhase").objects.create(tenant_id=project.tenant_id, project=project, order=i, name=str(name)[:120],
                                   start=_d(start), end=_d(end), forecast_end=_d(forecast), progress=min(progress, 100),
                                   owner=people.get(owner), status=status)

    # Affectations (staff) : capacité de chaque personne (PersonCapacity : heures par semaine et réunions).
    Capacity = M("PersonCapacity")
    internal = M("ProjectInternal").objects.filter(project=project).first()
    for s in (internal.staff if internal else []) or []:
        user = people.get(s.get("id"))
        if user is None or not user.is_active:
            continue
        cap = Capacity.objects.filter(user=user).first()
        weekly = Decimal(cap.cap) if cap and cap.cap else Decimal("35")
        pct = int(s.get("pct") or 100)
        role = s.get("role", "")
        scrum = ""
        if kind in ("scrum", "hybrid"):
            scrum = "po" if "product" in role.lower() or role.upper() == "PO" else "dev"
        M("TeamMemberAllocation").objects.get_or_create(
            project=project, user=user, defaults={
                "tenant_id": project.tenant_id, "project_role": role[:80], "scrum_role": scrum, "allocation_pct": min(pct, 100),
                "hours_per_day": (weekly / 5).quantize(Decimal("0.01")), "days_per_week": 5,
                "meeting_hours_per_week": (Decimal(cap.meet or 0) * pct / 100).quantize(Decimal("0.01")) if cap else 0,
                "skills": (cap.skills if cap else []) or [], "start": _d(s.get("from")), "end": _d(s.get("to"))})
    if project.pm_id and kind in ("scrum", "hybrid"):
        M("TeamMemberAllocation").objects.get_or_create(
            project=project, user_id=project.pm_id, defaults={
                "tenant_id": project.tenant_id, "project_role": "Chef de projet", "scrum_role": "sm", "allocation_pct": 20})

    # Sprints et objectifs.
    sprints = {}
    listed = {s.get("n"): s for s in agile.get("sprintList") or [] if isinstance(s, dict)}
    for row in agile.get("sprints") or []:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        n, start, end = int(row[0]), _d(row[1]), _d(row[2])
        if not (start and end):
            continue
        info = listed.get(n, {})
        status = {"done": "done", "active": "active"}.get(info.get("status")) or (
            "done" if end < today else "active" if start <= today else "planned")
        sp = M("Sprint").objects.create(tenant_id=project.tenant_id, project=project, number=n, start=start, end=end,
                                        status=status, completed_points=info.get("vel") if status == "done" else None)
        sprints[n] = sp
        goal = info.get("goal") or ((agile.get("sprint") or {}).get("goal") if (agile.get("sprint") or {}).get("n") == n else "")
        if goal:
            M("SprintGoal").objects.create(tenant_id=project.tenant_id, sprint=sp, objective=goal,
                                           status="achieved" if status == "done" else "on_track" if status == "active" else "not_started",
                                           progress=100 if status == "done" else 0)
        retro = info.get("retro")
        if isinstance(retro, dict):
            at = _d(retro.get("at")) or end
            r = M("Retrospective").objects.create(
                tenant_id=project.tenant_id, project=project, sprint=sp, trigger="sprint", format="wwi",
                title=f"Rétrospective du sprint {n}", scheduled_at=datetime.combine(at, time(16), tzinfo=PARIS),
                facilitator=people.get(retro.get("by")), status="closed", closed_at=datetime.combine(at, time(17), tzinfo=PARIS),
                report=f"Objectif : {retro.get('goal', '')}", dedupe_key=f"sprint:{sp.pk}")
            for text in retro.get("well") or []:
                M("RetrospectiveFeedback").objects.create(tenant_id=project.tenant_id, retro=r, category="well", text=text)
            for text in retro.get("improve") or []:
                M("RetrospectiveFeedback").objects.create(tenant_id=project.tenant_id, retro=r, category="improve", text=text)

    # User stories -> Product Backlog (et Sprint Backlog si rattachées à un sprint connu).
    rank = 0
    for us in M("UserStory").objects.filter(project=project).order_by("id"):
        rank += 1
        sp = sprints.get(us.sprint)
        item = M("ProductBacklogItem").objects.create(
            tenant_id=project.tenant_id, project=project, kind="story", key=us.id, title=us.title, user_story=us.story,
            acceptance=us.ac, rank=rank, priority=PRIO.get(us.prio, "normal"), story_points=us.pts, source_story=us,
            status="done" if us.closed else ("selected" if sp else "ready"))
        if sp:
            done_at = datetime.combine(us.closed, time(17), tzinfo=PARIS) if us.closed else None
            M("SprintBacklogItem").objects.create(
                tenant_id=project.tenant_id, sprint=sp, item=item, column="done" if us.closed else "todo", order=rank,
                points=us.pts, added_at=datetime.combine(sp.start, time(9), tzinfo=PARIS), done_at=done_at)
    for sp in sprints.values():
        pts = sum((i.points or 0) for i in M("SprintBacklogItem").objects.filter(sprint=sp))
        if pts:
            sp.committed_points = pts
            sp.save(update_fields=["committed_points"])
    return True


def bootstrap_all(M, today=None):
    return sum(bootstrap_project(M, p, today) for p in M("Project").objects.all())


def live_models(name):
    from django.apps import apps
    for app in ("methodology", "projects", "accounts"):
        try:
            return apps.get_model(app, name)
        except LookupError:
            continue
    raise LookupError(name)

