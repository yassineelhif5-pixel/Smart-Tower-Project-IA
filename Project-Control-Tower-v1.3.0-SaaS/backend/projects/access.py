"""Périmètre d'un utilisateur sur les projets et les tâches (équivalent serveur de scopeOf / inScope).

Lot 3a : tout est d'abord limité au tenant de l'utilisateur, déduit côté serveur. Un utilisateur sans
tenant (le Pilote) ou d'un tenant inactif ne voit aucune donnée métier.

- Administrateur et Direction voient tous les projets, comme dans index.html.
- Les autres rôles voient les projets qui leur sont affectés (ProjectAccess).
- Pour les tâches d'un projet visible, on garde les règles de la page :
  le portail client ne voit que ses tâches et celles de type « Client » ;
  sans le droit action.read, on ne voit que ses propres tâches.
- Une tâche ouverte individuellement (ActionAccess) est visible en plus.
"""
from django.db.models import Q

from accounts.permissions import has_perm

from .models import Action, ActionAccess, Project, ProjectAccess

FULL_SCOPE_ROLES = {"admin", "direction"}


def in_active_tenant(user):
    """Vrai si l'utilisateur appartient à un tenant actif : condition de tout accès aux données métier."""
    return bool(user and user.is_authenticated and user.is_active and user.role_id and user.tenant_id
                and user.tenant.status == "active")


def has_full_scope(user):
    """Administrateur et Direction voient tous les projets… de leur tenant."""
    return in_active_tenant(user) and user.role_id in FULL_SCOPE_ROLES


def visible_projects(user):
    if not in_active_tenant(user):
        return Project.objects.none()
    mine = Project.objects.filter(tenant_id=user.tenant_id)
    if has_full_scope(user):
        return mine
    return mine.filter(accesses__user=user).distinct()


def visible_actions(user):
    if not in_active_tenant(user):
        return Action.objects.none()
    in_projects = Q(project__in=visible_projects(user))
    if not user.role.internal:
        in_projects &= Q(owner=user) | Q(type="Client")
    if not has_perm(user, "action", "read"):
        in_projects &= Q(owner=user)
    return Action.objects.filter(in_projects | Q(accesses__user=user), tenant_id=user.tenant_id).distinct()


# --------------------------------------------------------------------------- lot 2b : tables reprises de Supabase
# Règles de lecture reprises une à une des politiques RLS de supabase/migrations/20261030220000_schema.sql
# (app.in_scope devient visible_projects, app.me() l'utilisateur, app.can() has_perm). Elles serviront aux
# API des pages métier (lot 4a) ; aucune route ne les expose encore. Toute nouvelle API doit partir d'ici.

def _ready(user):
    return in_active_tenant(user)


def is_internal(user):
    return _ready(user) and user.role.internal


def has_money(user):
    """ROLES.money et droit budget.read (app.has_money)."""
    return _ready(user) and user.role.money and has_perm(user, "budget", "read")


def sees_all_activity(user):
    """ACT_ALL : rôles qui voient les heures des autres (app.sees_all_activity)."""
    return _ready(user) and user.role_id in {"techlead", "cdp", "client", "admin", "manager", "direction"}


def visible_clients(user):
    from .models import Client

    if not _ready(user):
        return Client.objects.none()
    mine = Client.objects.filter(tenant_id=user.tenant_id)
    if has_full_scope(user):
        return mine
    own = Q(projects__in=visible_projects(user)) | Q(managers=user) | Q(sales=user)
    if user.client_id:
        own |= Q(code=user.client_id)
    return mine.filter(own).distinct()


def visible(user, model):
    """Lignes de `model` que `user` peut lire : son tenant uniquement, puis la règle RLS correspondante."""
    if not _ready(user):
        return model.objects.none()
    return _visible(user, model).filter(tenant_id=user.tenant_id)


def _visible(user, model):
    from . import models as m

    projects = visible_projects(user)
    internal = user.role.internal
    in_scope = Q(project__in=projects)

    if model is m.Project:
        return projects
    if model is m.Action:
        return visible_actions(user)
    if model is m.Client:
        return visible_clients(user)
    if model is m.ClientContract:
        return m.ClientContract.objects.filter(client__in=visible_clients(user)) if has_money(user) else model.objects.none()
    if model is m.PersonCapacity:
        return m.PersonCapacity.objects.all() if internal else model.objects.none()
    if model is m.ProjectInternal:
        return m.ProjectInternal.objects.filter(in_scope) if internal else model.objects.none()
    if model is m.ProjectFinance:
        return m.ProjectFinance.objects.filter(in_scope) if has_money(user) else model.objects.none()
    if model is m.ActionComment:
        rows = m.ActionComment.objects.filter(action__in=visible_actions(user))
        return rows if internal else rows.filter(internal=False)
    if model in (m.UserStory, m.Issue, m.ChangeRequest):
        return model.objects.filter(in_scope)
    if model is m.ChangeRequestAmount:
        if not (has_money(user) or not internal):
            return model.objects.none()
        return m.ChangeRequestAmount.objects.filter(change_request__project__in=projects)
    if model is m.Objective:
        if not (internal and has_perm(user, "action", "read")):
            return model.objects.none()
        return m.Objective.objects.filter(Q(project__isnull=True) | in_scope)
    if model is m.Todo:
        return m.Todo.objects.filter(owner=user)
    if model is m.TimeEntry:
        mine = Q(person=user)
        return m.TimeEntry.objects.filter(mine | in_scope if sees_all_activity(user) else mine)
    if model is m.Risk:
        if not has_perm(user, "risk", "read"):
            return model.objects.none()
        rows = m.Risk.objects.filter(in_scope)
        return rows if internal else rows.filter(client_visible=True)
    if model is m.TestCampaign:
        return m.TestCampaign.objects.filter(in_scope) if has_perm(user, "test", "read") else model.objects.none()
    if model is m.Defect:
        ok = has_perm(user, "test", "read") and internal
        return m.Defect.objects.filter(in_scope) if ok else model.objects.none()
    if model is m.Document:
        if not has_perm(user, "document", "read"):
            return model.objects.none()
        rows = m.Document.objects.filter(in_scope)
        return rows if internal else rows.filter(client_visible=True)
    if model is m.Meeting:
        rows = m.Meeting.objects.filter(in_scope)
        return rows if internal else rows.filter(client_visible=True)
    raise ValueError(f"Aucune règle de lecture pour {model.__name__} : à définir avant toute exposition.")


def can_edit_project(user, project):
    if not has_perm(user, "project", "update") or project.tenant_id != user.tenant_id:
        return False
    if has_full_scope(user):
        return True
    return ProjectAccess.objects.filter(user=user, project=project, can_edit=True).exists()


def can_edit_action(user, action):
    if not has_perm(user, "action", "update") or action.tenant_id != user.tenant_id:
        return False
    if has_full_scope(user):
        return True
    if ActionAccess.objects.filter(user=user, action=action, can_edit=True).exists():
        return True
    return ProjectAccess.objects.filter(user=user, project_id=action.project_id, can_edit=True).exists()
