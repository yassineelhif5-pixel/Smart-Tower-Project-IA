"""Circuit de validation des temps, réglable par l'administrateur (Configuration › Saisie de temps).

Modes (clé « approval » du réglage AppSetting « time ») :
- pm      : le chef de projet du projet valide (par défaut) ;
- pm_tl   : le chef de projet ou le Tech Lead ;
- role    : tout profil ayant le droit « Valider » sur la saisie de temps et accès au projet ;
- admin   : les administrateurs de l'entreprise ;
- auto    : validation automatique à l'envoi.

Si personne n'est désigné (projet sans chef de projet, par exemple), les administrateurs valident.
Une délégation active (absence) permet au délégué de valider à la place du délégant.
Un administrateur peut toujours valider. Personne ne valide ses propres saisies.
"""
from django.contrib.auth import get_user_model
from django.utils import timezone

from accounts.models import ADMIN_ROLE
from accounts.permissions import has_perm
from configuration.models import AppSetting

from .access import visible_projects
from .models import Project, TimeApprovalDelegation

MODES = {
    "pm": "Chef de projet du projet",
    "pm_tl": "Chef de projet ou Tech Lead",
    "role": "Tout responsable ayant le droit « Valider »",
    "admin": "Administrateurs de l'entreprise",
    "auto": "Validation automatique",
}
DEFAULT_MODE = "pm"


def approval_mode(tenant):
    row = AppSetting.objects.filter(tenant=tenant, key="time").first()
    value = row.value if row and isinstance(row.value, dict) else {}
    mode = value.get("approval", DEFAULT_MODE)
    return mode if mode in MODES else DEFAULT_MODE


def client_step(tenant):
    """Étape de validation par le client après le valideur interne (réglage « clientApproval » de l'entreprise)."""
    row = AppSetting.objects.filter(tenant=tenant, key="time").first()
    value = row.value if row and isinstance(row.value, dict) else {}
    return bool(value.get("clientApproval", False))


def after_internal_approval(tenant):
    """Statut d'une saisie validée en interne : « client » si le client doit encore valider, sinon « approved »."""
    return "client" if client_step(tenant) else "approved"


def _tenant_users(tenant):
    return get_user_model().objects.filter(tenant=tenant, is_active=True)


def _admin_ids(tenant):
    return set(_tenant_users(tenant).filter(role_id=ADMIN_ROLE).values_list("id", flat=True))


def base_approvers(project, mode):
    """Valideurs désignés par le circuit, avant délégations."""
    tenant = project.tenant
    if mode == "pm":
        ids = {project.pm_id} - {None}
    elif mode == "pm_tl":
        ids = {project.pm_id, project.tl_id} - {None}
    elif mode == "role":
        ids = {u.id for u in _tenant_users(tenant).select_related("role")
               if u.role and u.role.internal and has_perm(u, "timesheet", "approve")
               and visible_projects(u).filter(pk=project.pk).exists()}
    else:  # admin, auto
        ids = set()
    active = set(_tenant_users(tenant).filter(id__in=ids).values_list("id", flat=True))
    return active or _admin_ids(tenant)


def delegates_of(tenant, user_ids, day=None):
    day = day or timezone.localdate()
    return set(TimeApprovalDelegation.objects.filter(
        tenant=tenant, delegator_id__in=user_ids, start_date__lte=day, end_date__gte=day, delegate__is_active=True,
    ).values_list("delegate_id", flat=True))


# --------------------------------------------------------------------------- workflow propre à un projet
WORKFLOW_KEY = "time_workflows"
STEP_KINDS = {"pm": "Chef de projet", "tl": "Tech Lead", "user": "Personne désignée", "admin": "Administrateurs"}


def workflows(tenant):
    row = AppSetting.objects.filter(tenant=tenant, key=WORKFLOW_KEY).first()
    return dict(row.value) if row and isinstance(row.value, dict) else {}


def workflow_of(project):
    """{"steps": [{"kind": pm|tl|user|admin, "user": id?}], "client": bool} ou None (circuit de l'entreprise)."""
    wf = workflows(project.tenant).get(project.id)
    return wf if wf and wf.get("steps") else None


def step_approvers(project, step):
    wf = workflow_of(project)
    steps = wf["steps"]
    st = steps[min(step, len(steps) - 1)]
    tenant = project.tenant
    if st["kind"] == "pm":
        ids = {project.pm_id} - {None}
    elif st["kind"] == "tl":
        ids = {project.tl_id} - {None}
    elif st["kind"] == "user":
        ids = {st.get("user")} - {None}
    else:
        ids = set()
    active = set(_tenant_users(tenant).filter(id__in=ids).values_list("id", flat=True))
    return active or _admin_ids(tenant)


def next_status(entry):
    """Après une validation interne : (statut, étape). Étape suivante du workflow, puis client ou validé."""
    wf = workflow_of(entry.project)
    if wf:
        if entry.approval_step + 1 < len(wf["steps"]):
            return "pending", entry.approval_step + 1
        return ("client" if wf.get("client") else "approved"), entry.approval_step
    return after_internal_approval(entry.tenant), entry.approval_step


def approvers(project, mode=None, step=None):
    if workflow_of(project):
        if step is None:  # tous les valideurs du workflow (vue projet)
            ids = set()
            for i in range(len(workflow_of(project)["steps"])):
                ids |= step_approvers(project, i)
        else:
            ids = step_approvers(project, step)
        return ids | delegates_of(project.tenant, ids)
    mode = mode or approval_mode(project.tenant)
    ids = base_approvers(project, mode)
    return ids | delegates_of(project.tenant, ids)


def decidable_project_ids(user):
    """Projets dont l'utilisateur peut valider les temps (circuit + délégations)."""
    if not user.tenant_id or not user.is_active:
        return set()
    projects = Project.objects.filter(tenant_id=user.tenant_id).select_related("tenant")
    if user.is_app_admin:
        return set(projects.values_list("id", flat=True))
    mode = approval_mode(user.tenant)
    return {p.id for p in projects if user.id in approvers(p, mode)}


def can_decide(user, entry):
    if entry.person_id == user.id or entry.tenant_id != user.tenant_id:
        return False
    return user.is_app_admin or user.id in approvers(entry.project, step=entry.approval_step)
