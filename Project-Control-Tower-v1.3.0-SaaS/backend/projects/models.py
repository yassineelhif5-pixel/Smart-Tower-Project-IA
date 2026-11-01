"""Modèle métier de Project Control Tower.

Lot 2b : Django devient le seul propriétaire du schéma. Toutes les tables métier de
supabase/migrations/20261030220000_schema.sql sont reprises ici, colonne par colonne
(correspondance détaillée dans DATABASE.md). Les champs historiques des modèles
Client, Project et Action sont conservés à l'identique ; seuls des champs facultatifs
ont été ajoutés, pour ne perdre aucune donnée existante.

Lot 3a : chaque modèle hérite de TenantOwned (colonne `tenant`). Le tenant est repris du parent
(`tenant_source`) et une relation vers un autre tenant est refusée (voir tenants/models.py et tenants/signals.py).

Conventions :
- une personne de Supabase (`people.id`, ex. « sm ») est un utilisateur Django (`User.person_code`) ;
- une colonne jsonb devient un JSONField, une colonne text[] de libellés une liste JSON,
  une colonne text[] d'identifiants une relation (ManyToMany) ;
- les montants et les heures sont des DecimalField, jamais des flottants.
"""
from django.conf import settings
from django.db import models

from tenants.models import TenantOwned

USER = settings.AUTH_USER_MODEL

ACTION_STATUSES = [
    ("todo", "À faire"), ("planned", "Planifiée"), ("doing", "En cours"),
    ("review", "En revue"), ("blocked", "Bloquée"), ("done", "Terminée"),
]


def _money():
    return models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)


def _hours():
    return models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)


# --------------------------------------------------------------------------- référentiels
class Client(TenantOwned):
    code = models.CharField(primary_key=True, max_length=20)
    name = models.CharField(max_length=120)
    sector = models.CharField(max_length=120, blank=True)
    city = models.CharField(max_length=120, blank=True)
    color = models.CharField(max_length=9, blank=True)
    # Lot 2b (clients) :
    label = models.CharField(max_length=60, blank=True, help_text="Libellé anonymisé, ex. « Client A »")
    managers = models.ManyToManyField(USER, blank=True, related_name="managed_clients")
    sales = models.ManyToManyField(USER, blank=True, related_name="sold_clients")
    contacts = models.JSONField(default=list, blank=True, help_text="[{n: nom, r: fonction, e: e-mail}]")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ClientContract(TenantOwned):
    """client_contracts : contrats d'un client. Montants réservés aux profils financiers."""

    tenant_source = 'client'

    ref = models.CharField(primary_key=True, max_length=40)
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="contracts")
    label = models.CharField(max_length=200, blank=True)
    amount = _money()
    end_date = models.DateField(null=True, blank=True)
    kind = models.CharField(max_length=40, blank=True)
    renew = models.BooleanField(default=False)

    class Meta:
        ordering = ["ref"]


class PersonCapacity(TenantOwned):
    """people_internal : capacité et compétences d'une personne (données internes, jamais au portail client)."""

    tenant_source = 'user'

    user = models.OneToOneField(USER, primary_key=True, on_delete=models.CASCADE, related_name="capacity")
    cap = _hours()
    meet = _hours()
    skills = models.JSONField(default=list, blank=True)


# --------------------------------------------------------------------------- projets
class Project(TenantOwned):
    tenant_source = ['client', 'pm', 'tl']

    id = models.CharField(primary_key=True, max_length=20)
    code = models.CharField(max_length=20)  # unique par tenant (contrainte ci-dessous)
    name = models.CharField(max_length=200)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="projects")
    method = models.CharField(max_length=20, blank=True)
    pm = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    tl = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    progress = models.PositiveSmallIntegerField(default=0)
    # Lot 2b (projects) :
    team = models.ManyToManyField(USER, blank=True, related_name="team_projects")
    descr = models.TextField(blank=True)
    forecast_end = models.DateField(null=True, blank=True)
    phases = models.JSONField(default=list, blank=True, help_text="Planning macro")
    milestones = models.JSONField(default=list, blank=True)
    tests = models.JSONField(default=dict, blank=True, help_text="Synthèse de recette")
    key_dates = models.JSONField(default=list, blank=True)
    hyper = models.JSONField(null=True, blank=True, help_text="Hypercare")
    lifecycle = models.JSONField(default=list, blank=True, help_text="Historique des états")
    week_plans = models.JSONField(default=dict, blank=True)
    agile = models.JSONField(null=True, blank=True, help_text="Sprints (projets Agile)")

    class Meta:
        ordering = ["code"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uniq_tenant_project_code")]

    def __str__(self):
        return f"{self.code} · {self.name}"


class ProjectInternal(TenantOwned):
    """project_internal : heures vendues, consommées, reste à faire et affectations (données internes)."""

    tenant_source = 'project'

    project = models.OneToOneField(Project, primary_key=True, on_delete=models.CASCADE, related_name="internal")
    days = _hours()
    h_base = _hours()
    h_done = _hours()
    h_raf = _hours()
    team_load = _hours()
    staff = models.JSONField(default=list, blank=True, help_text="[{id, role, pct, from, to}]")


class ProjectFinance(TenantOwned):
    """project_finance : CA, budget et coûts (profils financiers uniquement)."""

    tenant_source = 'project'

    project = models.OneToOneField(Project, primary_key=True, on_delete=models.CASCADE, related_name="finance")
    ca = _money()
    baseline = _money()
    approved = _money()
    consumed = _money()
    raf_cost = _money()
    lines = models.JSONField(default=list, blank=True)
    causes = models.JSONField(default=list, blank=True)
    series = models.JSONField(null=True, blank=True)
    months = models.JSONField(null=True, blank=True)


# --------------------------------------------------------------------------- exécution
class UserStory(TenantOwned):
    tenant_source = 'project'

    id = models.CharField(primary_key=True, max_length=20)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="user_stories")
    sprint = models.IntegerField(null=True, blank=True)
    title = models.CharField(max_length=300)
    pts = _hours()
    prio = models.CharField(max_length=20, blank=True)
    story = models.TextField(blank=True)
    ac = models.TextField(blank=True, help_text="Critères d'acceptation")
    closed = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["id"]


class Action(TenantOwned):
    tenant_source = ['project', 'owner', 'us']

    id = models.CharField(primary_key=True, max_length=20)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="actions")
    title = models.CharField(max_length=300)
    owner = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    status = models.CharField(max_length=10, choices=ACTION_STATUSES)
    type = models.CharField(max_length=40, blank=True)
    due = models.DateField(null=True, blank=True)
    # Lot 2b (actions) :
    phase = models.CharField(max_length=60, blank=True)
    prio = models.CharField(max_length=20, blank=True)
    est0 = _hours()
    est = _hours()
    done = _hours()
    raf = _hours()
    start_date = models.DateField(null=True, blank=True)
    fdue = models.DateField(null=True, blank=True, help_text="Échéance prévisionnelle")
    block = models.TextField(blank=True, default="")
    stage = models.CharField(max_length=20, blank=True)
    us = models.ForeignKey(UserStory, on_delete=models.SET_NULL, null=True, blank=True, related_name="actions")
    done_at = models.DateField(null=True, blank=True)
    history = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["id"]


class ActionComment(TenantOwned):
    """action_comments. Un commentaire interne n'est jamais visible du portail client."""

    tenant_source = ['action', 'author']

    action = models.ForeignKey(Action, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    at = models.CharField(max_length=20, blank=True)
    body = models.TextField()
    internal = models.BooleanField(default=False)

    class Meta:
        ordering = ["id"]


class Objective(TenantOwned):
    tenant_source = ['project', 'owner']

    id = models.CharField(primary_key=True, max_length=20)
    scope = models.CharField(max_length=120, blank=True)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, null=True, blank=True, related_name="objectives")
    owner = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    title = models.CharField(max_length=300)
    due = models.DateField(null=True, blank=True)
    items = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["id"]


class Todo(TenantOwned):
    """todos : liste personnelle, visible de son seul propriétaire."""

    tenant_source = 'owner'

    owner = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="todos")
    label = models.CharField(max_length=300)
    done = models.BooleanField(default=False)
    position = models.IntegerField(default=0)

    class Meta:
        ordering = ["owner", "position", "id"]


class TimeEntry(TenantOwned):
    """time_entries : heures réellement saisies (jamais déduites de la présence)."""

    tenant_source = ['project', 'person', 'action']

    person = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="time_entries")
    action = models.ForeignKey(Action, on_delete=models.SET_NULL, null=True, blank=True, related_name="time_entries")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="time_entries")
    work_date = models.DateField()
    hours = models.DecimalField(max_digits=6, decimal_places=2)
    is_meeting = models.BooleanField(default=False)

    class Meta:
        ordering = ["work_date", "id"]
        indexes = [models.Index(fields=["person", "work_date"]), models.Index(fields=["project"])]
        constraints = [models.CheckConstraint(condition=models.Q(hours__gt=0), name="time_hours_positive")]


# --------------------------------------------------------------------------- contrôle
class Risk(TenantOwned):
    tenant_source = ['project', 'owner']

    id = models.CharField(primary_key=True, max_length=20)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="risks")
    title = models.CharField(max_length=300)
    prob = models.IntegerField(null=True, blank=True)
    imp = models.IntegerField(null=True, blank=True)
    owner = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    status = models.CharField(max_length=30, blank=True)
    due = models.DateField(null=True, blank=True)
    mitigation = models.TextField(blank=True)
    client_visible = models.BooleanField(default=False)
    actions = models.ManyToManyField(Action, blank=True, related_name="risks")

    class Meta:
        ordering = ["id"]


class Issue(TenantOwned):
    tenant_source = ['project', 'owner']

    id = models.CharField(primary_key=True, max_length=20)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="issues")
    kind = models.CharField(max_length=40, blank=True)
    title = models.CharField(max_length=300)
    prio = models.CharField(max_length=20, blank=True)
    owner = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    due = models.DateField(null=True, blank=True)
    impact = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]


class ChangeRequest(TenantOwned):
    tenant_source = ['project', 'requested_by']

    id = models.CharField(primary_key=True, max_length=20)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="change_requests")
    title = models.CharField(max_length=300)
    requested_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    hours = _hours()
    days = _hours()
    status = models.CharField(max_length=40, blank=True)
    vdate = models.DateField(null=True, blank=True, help_text="Date de validation")
    fn = models.TextField(blank=True, help_text="Impact fonctionnel")
    tech = models.TextField(blank=True, help_text="Impact technique")

    class Meta:
        ordering = ["id"]


class ChangeRequestAmount(TenantOwned):
    """change_request_amounts : montant séparé, vu par les profils financiers et le client, pas par l'équipe technique."""

    tenant_source = 'change_request'

    change_request = models.OneToOneField(ChangeRequest, primary_key=True, on_delete=models.CASCADE, related_name="amount")
    amount = _money()


class TestCampaign(TenantOwned):
    tenant_source = ['project', 'owner']

    id = models.CharField(primary_key=True, max_length=20)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="test_campaigns")
    name = models.CharField(max_length=200, blank=True)
    env = models.CharField(max_length=60, blank=True)
    version = models.CharField(max_length=30, blank=True)
    total = models.IntegerField(null=True, blank=True)
    passed = models.IntegerField(null=True, blank=True, db_column="pass")
    fail = models.IntegerField(null=True, blank=True)
    todo = models.IntegerField(null=True, blank=True)
    crit = models.IntegerField(null=True, blank=True)
    owner = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["id"]


class Defect(TenantOwned):
    tenant_source = ['project', 'owner']

    id = models.CharField(primary_key=True, max_length=20)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="defects")
    title = models.CharField(max_length=300)
    sev = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=30, blank=True)
    owner = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["id"]


class Document(TenantOwned):
    """documents : fiche du document. Le stockage réel des fichiers arrivera avec la GED (le scan est encore simulé)."""

    tenant_source = ['project', 'uploaded_by']

    id = models.CharField(primary_key=True, max_length=20)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="documents")
    name = models.CharField(max_length=255)
    ext = models.CharField(max_length=10, blank=True)
    size_mb = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    type = models.CharField(max_length=20, blank=True, help_text="cdc, sfd, hld, dat…")
    dstat = models.CharField(max_length=30, blank=True, help_text="Manquant, Brouillon, En revue, Validé")
    entity = models.CharField(max_length=120, blank=True)
    uploaded_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    uploaded_at = models.DateField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    scan_status = models.CharField(max_length=30, blank=True)
    client_visible = models.BooleanField(default=False)

    class Meta:
        ordering = ["id"]


class Meeting(TenantOwned):
    tenant_source = ['project', 'organizer', 'doc']

    id = models.CharField(primary_key=True, max_length=20)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="meetings")
    type = models.CharField(max_length=80, blank=True)
    title = models.CharField(max_length=300)
    date = models.DateField(null=True, blank=True)
    time = models.CharField(max_length=5, blank=True)
    dur = models.IntegerField(null=True, blank=True, help_text="Durée en minutes")
    organizer = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    attendees = models.ManyToManyField(USER, blank=True, related_name="meetings")
    external = models.JSONField(default=list, blank=True, help_text="Participants externes (noms)")
    agenda = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)
    decisions = models.JSONField(default=list, blank=True)
    actions = models.ManyToManyField(Action, blank=True, related_name="meetings")
    doc = models.ForeignKey(Document, on_delete=models.SET_NULL, null=True, blank=True, related_name="meetings")
    client_visible = models.BooleanField(default=False)
    status = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["id"]


# --------------------------------------------------------------------------- accès
class ProjectAccess(TenantOwned):
    """Projet affecté à un utilisateur. can_edit limite l'écriture, en plus de la matrice des droits."""

    tenant_source = ['user', 'project']

    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="project_accesses")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="accesses")
    can_edit = models.BooleanField(default=True)
    granted_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "project"], name="uniq_user_project")]


class ActionAccess(TenantOwned):
    """Tâche ouverte individuellement à un utilisateur, en plus de celles de ses projets."""

    tenant_source = ['user', 'action']

    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="action_accesses")
    action = models.ForeignKey(Action, on_delete=models.CASCADE, related_name="accesses")
    can_edit = models.BooleanField(default=False)
    granted_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "action"], name="uniq_user_action")]
