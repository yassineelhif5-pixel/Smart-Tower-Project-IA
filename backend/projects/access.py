"""Périmètre d'un utilisateur sur les projets et les tâches (équivalent serveur de scopeOf / inScope).

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


def has_full_scope(user):
    return user.is_authenticated and user.role_id in FULL_SCOPE_ROLES


def visible_projects(user):
    if not (user.is_authenticated and user.role_id):
        return Project.objects.none()
    if has_full_scope(user):
        return Project.objects.all()
    return Project.objects.filter(accesses__user=user).distinct()


def visible_actions(user):
    if not (user.is_authenticated and user.role_id):
        return Action.objects.none()
    in_projects = Q(project__in=visible_projects(user))
    if not user.role.internal:
        in_projects &= Q(owner=user) | Q(type="Client")
    if not has_perm(user, "action", "read"):
        in_projects &= Q(owner=user)
    return Action.objects.filter(in_projects | Q(accesses__user=user)).distinct()


def can_edit_project(user, project):
    if not has_perm(user, "project", "update"):
        return False
    if has_full_scope(user):
        return True
    return ProjectAccess.objects.filter(user=user, project=project, can_edit=True).exists()


def can_edit_action(user, action):
    if not has_perm(user, "action", "update"):
        return False
    if has_full_scope(user):
        return True
    if ActionAccess.objects.filter(user=user, action=action, can_edit=True).exists():
        return True
    return ProjectAccess.objects.filter(user=user, project_id=action.project_id, can_edit=True).exists()
