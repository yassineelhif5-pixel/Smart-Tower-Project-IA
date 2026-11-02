"""Calcul de la capacité réelle d'une équipe projet.

Par collaborateur et par jour travaillé (selon ses jours travaillés par semaine) :
- capacité théorique affectée = heures par jour × taux d'affectation ;
- journée entière d'absence (congé, absence, jour férié, indisponibilité sans heures) : la journée vaut 0 ;
- sinon on retire les indisponibilités partielles (heures), puis la part quotidienne des réunions récurrentes,
  sans jamais descendre sous 0 : une même journée n'est jamais déduite deux fois (une réunion n'est pas retirée
  d'un jour de congé, deux absences le même jour ne comptent qu'une fois).
Capacité productive = capacité disponible × ratio productif du projet.

Exemple du cahier : 7 h × 5 j × 80 % = 28 h ; − 4 h de réunions − 2 h d'indisponibilité = 22 h disponibles.

Charge planifiée : affectations du calendrier (charge estimée répartie sur les jours ouvrés), projet courant.
Charge consommée : temps réellement saisi (`TimeEntry`) sur le projet.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Q, Sum

from projects.models import TimeEntry

from .models import TeamAvailability, TeamMemberAllocation

ZERO = Decimal("0")
UNDER_USED = Decimal("0.6")


def days(start, end):
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _works(alloc, day):
    """Jours travaillés : les `days_per_week` premiers jours de la semaine (lundi d'abord), dans la période d'affectation."""
    if alloc.start and day < alloc.start or alloc.end and day > alloc.end:
        return False
    return day.weekday() < alloc.days_per_week


def member_capacity(alloc, start, end, absences, productive_ratio=Decimal("1")):
    hpd = Decimal(alloc.hours_per_day) * Decimal(alloc.allocation_pct) / 100
    working = [d for d in days(start, end) if _works(alloc, d)]
    meeting_per_day = (Decimal(alloc.meeting_hours_per_week) / alloc.days_per_week) if alloc.days_per_week else ZERO
    theoretical = available = meetings = unavailable = ZERO
    per_day = {}
    off_days = []
    for d in working:
        theoretical += hpd
        todays = [a for a in absences if a.start <= d <= a.end and (a.user_id in (None, alloc.user_id))]
        if any(a.hours is None for a in todays):
            off_days.append(d.isoformat())
            unavailable += hpd
            per_day[d.isoformat()] = 0.0
            continue
        left = hpd
        partial = min(sum((Decimal(a.hours) for a in todays), ZERO), left)
        left -= partial
        unavailable += partial
        meet = min(meeting_per_day, left)
        left -= meet
        meetings += meet
        available += left
        per_day[d.isoformat()] = round(float(left), 2)
    productive = available * Decimal(str(productive_ratio))
    return {
        "theoretical": theoretical, "unavailable": unavailable, "meetings": meetings, "available": available,
        "productive": productive, "perDay": per_day, "offDays": off_days, "workingDays": len(working),
    }


def team_capacity(project, start, end, members=None, scrum_only=False):
    """Capacité individuelle et collective d'un projet sur une période, avec charge planifiée et consommée."""
    from planning import services as planning
    from planning.models import CalendarEvent

    meth = getattr(project, "methodology", None)
    ratio = Decimal(str(meth.conf("productiveRatio") if meth else 1))
    allocs = TeamMemberAllocation.objects.filter(project=project, active=True).select_related("user")
    if members is not None:
        allocs = allocs.filter(user_id__in=members)
    if scrum_only:
        allocs = allocs.filter(scrum_role="dev")
    allocs = list(allocs)
    user_ids = [a.user_id for a in allocs]
    absences = list(TeamAvailability.objects.filter(tenant=project.tenant, start__lte=end, end__gte=start)
                    .filter(Q(user__isnull=True) | Q(user_id__in=user_ids)))

    # Charge planifiée sur CE projet, et charge des autres projets (autres engagements, pour information).
    events = list(planning.events_in(CalendarEvent.objects.filter(tenant=project.tenant), start, end)
                  .prefetch_related("assignments__user"))
    mine = [e for e in events if e.project_id == project.pk]
    others = [e for e in events if e.project_id != project.pk]
    load = planning.workload(project.tenant, mine, start, end)
    load.pop("_contributions")
    other_load = planning.workload(project.tenant, others, start, end)
    other_load.pop("_contributions")
    planned = {int(r["key"]): Decimal(str(r["total"])) for r in load["rows"]}
    elsewhere = {int(r["key"]): Decimal(str(r["total"])) for r in other_load["rows"]}
    consumed = dict(TimeEntry.objects.filter(project=project, work_date__range=(start, end), person_id__in=user_ids)
                    .values_list("person_id").annotate(h=Sum("hours")))

    rows = []
    totals = {k: ZERO for k in ("theoretical", "unavailable", "meetings", "available", "productive", "planned", "consumed")}
    for a in allocs:
        c = member_capacity(a, start, end, absences, ratio)
        p = planned.get(a.user_id, ZERO)
        used = Decimal(consumed.get(a.user_id) or 0)
        util = (p / c["productive"]) if c["productive"] else (Decimal("9.99") if p else ZERO)
        state = "over" if p > c["productive"] + Decimal("0.01") else ("under" if util < UNDER_USED else "ok")
        rows.append({
            "user": {"id": a.user_id, "name": a.user.display_name, "team": a.user.team},
            "allocationId": a.pk, "role": a.project_role, "scrumRole": a.scrum_role,
            "allocationPct": a.allocation_pct, "hoursPerDay": float(a.hours_per_day), "daysPerWeek": a.days_per_week,
            "meetingHoursPerWeek": float(a.meeting_hours_per_week), "skills": a.skills,
            "theoretical": _f(c["theoretical"]), "unavailable": _f(c["unavailable"]), "meetings": _f(c["meetings"]),
            "available": _f(c["available"]), "productive": _f(c["productive"]), "planned": _f(p), "consumed": _f(used),
            "remaining": _f(c["productive"] - p), "otherProjects": _f(elsewhere.get(a.user_id, ZERO)),
            "utilization": round(float(util) * 100, 1), "state": state, "perDay": c["perDay"], "offDays": c["offDays"],
        })
        for k in ("theoretical", "unavailable", "meetings", "available", "productive"):
            totals[k] += c[k]
        totals["planned"] += p
        totals["consumed"] += used
    util = (totals["planned"] / totals["productive"]) if totals["productive"] else ZERO
    return {
        "start": start.isoformat(), "end": end.isoformat(), "productiveRatio": float(ratio),
        "members": rows,
        "totals": {**{k: _f(v) for k, v in totals.items()}, "remaining": _f(totals["productive"] - totals["planned"]),
                   "utilization": round(float(util) * 100, 1)},
        "overloaded": [r["user"] for r in rows if r["state"] == "over"],
        "underUsed": [r["user"] for r in rows if r["state"] == "under"],
    }


def _f(v):
    return round(float(v), 2)
