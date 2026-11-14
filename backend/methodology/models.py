"""Pilotage méthodologique : Cycle en V (phases, Weekly Goals), Scrum (backlog, sprints, cérémonies), capacité,
rétrospectives et actions d'amélioration.

Réutilisation de l'existant, sans système parallèle :
- projets, actions, utilisateurs et documents : application `projects` ;
- échéances et cérémonies : événements du calendrier (`planning.CalendarEvent`) ;
- actions d'amélioration et actions de la semaine : des `projects.Action` ;
- notifications : `configuration.notify` (règles du tenant, préférences, PCT / e-mail / Teams).

Toutes les entités héritent de TenantOwned : tenant déduit du projet (ou de l'utilisateur), contrôlé à l'écriture.
"""
from django.conf import settings
from django.db import models
from django.db.models import F, Q

from tenants.models import TenantOwned

USER = settings.AUTH_USER_MODEL

KINDS = [("vcycle", "Cycle en V"), ("scrum", "Scrum"), ("hybrid", "Agile hybride"), ("custom", "Personnalisée")]
# Fonctionnalités activées par méthodologie (la méthodologie personnalisée choisit les siennes).
FEATURES = {
    "vcycle": ["phases", "weekly", "capacity", "retro"],
    "scrum": ["scrum", "capacity", "retro"],
    "hybrid": ["phases", "weekly", "scrum", "capacity", "retro"],
}
ALL_FEATURES = ["phases", "weekly", "scrum", "capacity", "retro"]
DEFAULT_COLUMNS = [
    {"key": "todo", "label": "À faire", "done": False},
    {"key": "doing", "label": "En cours", "done": False},
    {"key": "review", "label": "En revue", "done": False},
    {"key": "testing", "label": "En test", "done": False},
    {"key": "done", "label": "Terminé", "done": True},
]
DEFAULT_SETTINGS = {
    "productiveRatio": 1.0,          # part de la capacité disponible réellement productive (0,5 à 1)
    "sprintWeeks": 2,
    "boardColumns": DEFAULT_COLUMNS,
    "retroFrequency": "sprint",      # sprint | weekly | monthly | phase | milestone | project | none
    "reminderHours": [48, 24, 0],    # rappels de rétrospective (heures avant)
    "dailyTime": "09:30",
    "dailyMinutes": 15,
    "dailyInCalendar": True,
    "weeklyPlanningDay": 0,          # 0 = lundi
    "weeklyPlanningTime": "09:00",
    "timezone": "Europe/Paris",
}
DEFAULT_V_PHASES = [
    "Analyse des besoins", "Spécifications fonctionnelles", "Spécifications techniques", "Conception",
    "Développement / réalisation", "Tests unitaires", "Tests d'intégration", "Tests système", "Tests de validation",
    "Recette utilisateur", "Mise en production", "Stabilisation",
]


class ProjectMethodology(TenantOwned):
    tenant_source = "project"
    project = models.OneToOneField("projects.Project", on_delete=models.CASCADE, related_name="methodology")
    kind = models.CharField(max_length=10, choices=KINDS, default="vcycle")
    features = models.JSONField(default=list, blank=True, help_text="Méthodologie personnalisée : fonctionnalités choisies")
    settings = models.JSONField(default=dict, blank=True)
    history = models.JSONField(default=list, blank=True, help_text="Changements de méthodologie [{at, by, from, to, impact}]")
    updated_at = models.DateTimeField(auto_now=True)

    def enabled(self):
        return list(self.features) if self.kind == "custom" else FEATURES[self.kind]

    def conf(self, key):
        return {**DEFAULT_SETTINGS, **(self.settings or {})}.get(key)


STATUS = [("todo", "Non démarré"), ("doing", "En cours"), ("done", "Terminé"), ("late", "En retard"), ("skipped", "Sans objet")]


class VPhase(TenantOwned):
    """Phase configurable d'un projet Cycle en V. Jalons, tâches et dates : événements et actions existants."""

    tenant_source = ["project", "owner"]
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="v_phases")
    order = models.PositiveSmallIntegerField(default=0)
    name = models.CharField(max_length=120)
    start = models.DateField(null=True, blank=True)
    end = models.DateField(null=True, blank=True)
    forecast_end = models.DateField(null=True, blank=True)
    owner = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    status = models.CharField(max_length=8, choices=STATUS, default="todo")
    progress = models.PositiveSmallIntegerField(default=0)
    deliverables = models.JSONField(default=list, blank=True, help_text="[{title, done, document}]")
    validation_criteria = models.TextField(blank=True)
    risks = models.TextField(blank=True)
    depends_on = models.ManyToManyField("self", symmetrical=False, blank=True, related_name="successors")

    class Meta:
        ordering = ["project", "order", "id"]
        constraints = [models.CheckConstraint(condition=Q(progress__lte=100), name="vphase_progress_max_100")]


# --------------------------------------------------------------------------- capacité
SCRUM_ROLES = [("", "—"), ("po", "Product Owner"), ("sm", "Scrum Master"), ("dev", "Developer")]


class TeamMemberAllocation(TenantOwned):
    """Affectation d'un collaborateur à un projet : base du calcul de capacité. Rôles Scrum ≠ droits PCT."""

    tenant_source = ["project", "user"]
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="allocations")
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="allocations")
    project_role = models.CharField(max_length=80, blank=True)
    scrum_role = models.CharField(max_length=3, choices=SCRUM_ROLES, blank=True)
    allocation_pct = models.PositiveSmallIntegerField(default=100)
    hours_per_day = models.DecimalField(max_digits=4, decimal_places=2, default=7)
    days_per_week = models.PositiveSmallIntegerField(default=5)
    meeting_hours_per_week = models.DecimalField(max_digits=5, decimal_places=2, default=0,
                                                 help_text="Réunions récurrentes propres au projet")
    skills = models.JSONField(default=list, blank=True)
    start = models.DateField(null=True, blank=True)
    end = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["project", "user"]
        constraints = [
            models.UniqueConstraint(fields=["project", "user"], name="uniq_project_member"),
            models.CheckConstraint(condition=Q(allocation_pct__lte=100), name="allocation_max_100"),
            models.CheckConstraint(condition=Q(days_per_week__gte=1, days_per_week__lte=7), name="days_per_week_1_7"),
        ]


AVAILABILITY_KINDS = [("leave", "Congé"), ("absence", "Absence"), ("holiday", "Jour férié"),
                      ("unavailable", "Indisponibilité"), ("other", "Autre engagement")]


class TeamAvailability(TenantOwned):
    """Indisponibilité d'un collaborateur (ou de toute l'entreprise si `user` est vide : jour férié).

    `hours` vide = journée entière ; sinon heures retirées chaque jour de la période.
    """

    tenant_source = ["user"]
    user = models.ForeignKey(USER, on_delete=models.CASCADE, null=True, blank=True, related_name="availabilities")
    kind = models.CharField(max_length=12, choices=AVAILABILITY_KINDS)
    start = models.DateField()
    end = models.DateField()
    hours = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    note = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start", "id"]
        indexes = [models.Index(fields=["tenant", "start", "end"])]
        constraints = [models.CheckConstraint(condition=Q(end__gte=F("start")), name="availability_end_after_start")]


class TeamCapacity(TenantOwned):
    """Instantané de capacité enregistré à la validation d'une semaine ou au démarrage d'un sprint (historique)."""

    tenant_source = "project"
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="capacity_snapshots")
    start = models.DateField()
    end = models.DateField()
    sprint = models.ForeignKey("Sprint", on_delete=models.CASCADE, null=True, blank=True, related_name="capacity_snapshots")
    weekly_plan = models.ForeignKey("WeeklyPlan", on_delete=models.CASCADE, null=True, blank=True, related_name="capacity_snapshots")
    theoretical = models.DecimalField(max_digits=9, decimal_places=2)
    available = models.DecimalField(max_digits=9, decimal_places=2)
    planned = models.DecimalField(max_digits=9, decimal_places=2)
    details = models.JSONField(default=dict)
    computed_at = models.DateTimeField(auto_now_add=True)


# --------------------------------------------------------------------------- Cycle en V : semaine
GOAL_STATUS = [("not_started", "Non démarré"), ("in_progress", "En cours"), ("achieved", "Atteint"),
               ("partial", "Partiellement atteint"), ("missed", "Non atteint")]
PRIORITIES = [("low", "Basse"), ("normal", "Normale"), ("high", "Haute"), ("critical", "Critique")]


class WeeklyPlan(TenantOwned):
    tenant_source = "project"
    STATES = [("draft", "En préparation"), ("validated", "Validé"), ("closed", "Clôturé")]

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="weekly_plans")
    week_start = models.DateField(help_text="Lundi de la semaine")
    state = models.CharField(max_length=10, choices=STATES, default="draft")
    status = models.CharField(max_length=12, choices=GOAL_STATUS, default="not_started")
    validated_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    validated_at = models.DateTimeField(null=True, blank=True)
    meeting = models.JSONField(default=dict, blank=True, help_text="Réunion hebdomadaire : ordre du jour, décisions…")
    meeting_event = models.ForeignKey("planning.CalendarEvent", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    review = models.JSONField(default=dict, blank=True, help_text="Bilan automatique de fin de semaine")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["project", "-week_start"]
        constraints = [models.UniqueConstraint(fields=["project", "week_start"], name="uniq_project_week")]


class WeeklyGoal(TenantOwned):
    tenant_source = ["plan", "owner"]
    plan = models.ForeignKey(WeeklyPlan, on_delete=models.CASCADE, related_name="goals")
    title = models.CharField(max_length=300)
    expected_results = models.TextField(blank=True)
    deliverables = models.TextField(blank=True)
    phases = models.ManyToManyField(VPhase, blank=True, related_name="weekly_goals")
    owner = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    priority = models.CharField(max_length=8, choices=PRIORITIES, default="normal")
    risks = models.TextField(blank=True)
    success_criteria = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=GOAL_STATUS, default="not_started")
    result = models.TextField(blank=True, help_text="Résultat constaté en fin de semaine")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["plan", "order", "id"]


class WeeklyGoalAction(TenantOwned):
    tenant_source = ["goal", "action"]
    goal = models.ForeignKey(WeeklyGoal, on_delete=models.CASCADE, related_name="links")
    action = models.ForeignKey("projects.Action", on_delete=models.CASCADE, related_name="weekly_links")
    planned_hours = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    carried_over = models.BooleanField(default=False, help_text="Reportée de la semaine précédente")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["goal", "action"], name="uniq_goal_action")]


# --------------------------------------------------------------------------- Scrum
ITEM_KINDS = [("epic", "Epic"), ("feature", "Feature"), ("story", "User Story"), ("task", "Task"), ("bug", "Bug"),
              ("spike", "Spike")]
ITEM_STATUS = [("new", "Nouveau"), ("ready", "Prêt"), ("selected", "Dans un sprint"), ("done", "Terminé"),
               ("removed", "Retiré")]


class ProductBacklogItem(TenantOwned):
    tenant_source = ["project", "assignee"]
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="backlog")
    kind = models.CharField(max_length=8, choices=ITEM_KINDS, default="story")
    parent = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children",
                               help_text="Epic ou Feature parente")
    key = models.CharField(max_length=20, blank=True, help_text="Référence lisible, ex. US-34")
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    user_story = models.TextField(blank=True)
    acceptance = models.TextField(blank=True)
    rank = models.PositiveIntegerField(default=0, help_text="Ordre de priorité (1 = plus prioritaire)")
    priority = models.CharField(max_length=8, choices=PRIORITIES, default="normal")
    story_points = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    estimate_hours = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    assignee = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    team = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=9, choices=ITEM_STATUS, default="new")
    dependencies = models.ManyToManyField("self", symmetrical=False, blank=True, related_name="dependents")
    attachments = models.ManyToManyField("projects.Document", blank=True, related_name="backlog_items")
    source_story = models.OneToOneField("projects.UserStory", on_delete=models.SET_NULL, null=True, blank=True, related_name="backlog_item")
    history = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["project", "rank", "id"]
        indexes = [models.Index(fields=["project", "rank"])]


SPRINT_STATUS = [("preparing", "À préparer"), ("planned", "Planifié"), ("active", "En cours"), ("done", "Terminé"),
                 ("cancelled", "Annulé")]


class Sprint(TenantOwned):
    tenant_source = "project"
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="sprints")
    number = models.PositiveIntegerField()
    name = models.CharField(max_length=120, blank=True)
    start = models.DateField()
    end = models.DateField()
    team = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=10, choices=SPRINT_STATUS, default="preparing")
    capacity_hours = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, help_text="Figée au démarrage")
    committed_points = models.DecimalField(max_digits=7, decimal_places=1, null=True, blank=True)
    completed_points = models.DecimalField(max_digits=7, decimal_places=1, null=True, blank=True)
    po_validated_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    po_validated_at = models.DateTimeField(null=True, blank=True)
    team_validated_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    team_validated_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    events = models.JSONField(default=dict, blank=True, help_text="Événements du calendrier créés {sprint, planning, review, daily: []}")

    class Meta:
        ordering = ["project", "number"]
        constraints = [
            models.UniqueConstraint(fields=["project", "number"], name="uniq_sprint_number"),
            models.CheckConstraint(condition=Q(end__gte=F("start")), name="sprint_end_after_start"),
        ]

    @property
    def label(self):
        return self.name or f"Sprint {self.number}"


class SprintGoal(TenantOwned):
    """Suivi propre à l'objectif : jamais déduit automatiquement du pourcentage de tâches terminées."""

    tenant_source = ["sprint", "owner"]
    STATES = [("not_started", "Non démarré"), ("on_track", "En bonne voie"), ("at_risk", "À risque"),
              ("achieved", "Atteint"), ("partial", "Partiellement atteint"), ("missed", "Non atteint")]
    sprint = models.OneToOneField(Sprint, on_delete=models.CASCADE, related_name="goal")
    objective = models.TextField()
    value = models.TextField(blank=True, help_text="Valeur attendue")
    expected_results = models.TextField(blank=True)
    success_criteria = models.TextField(blank=True)
    risks = models.TextField(blank=True)
    owner = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    status = models.CharField(max_length=12, choices=STATES, default="not_started")
    progress = models.PositiveSmallIntegerField(default=0, help_text="Appréciation de l'atteinte de l'objectif")
    items = models.ManyToManyField(ProductBacklogItem, blank=True, related_name="sprint_goals")
    updated_at = models.DateTimeField(auto_now=True)


class SprintBacklogItem(TenantOwned):
    tenant_source = ["sprint", "item", "assignee"]
    sprint = models.ForeignKey(Sprint, on_delete=models.CASCADE, related_name="items")
    item = models.ForeignKey(ProductBacklogItem, on_delete=models.CASCADE, related_name="sprint_entries")
    column = models.CharField(max_length=30, default="todo")
    order = models.PositiveIntegerField(default=0)
    points = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    assignee = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    blocked = models.BooleanField(default=False)
    block_reason = models.CharField(max_length=300, blank=True)
    remaining_hours = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    added_at = models.DateTimeField()
    done_at = models.DateTimeField(null=True, blank=True)
    removed_at = models.DateTimeField(null=True, blank=True, help_text="Retiré du sprint en cours (traçabilité)")
    history = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["sprint", "column", "order", "id"]
        constraints = [models.UniqueConstraint(fields=["sprint", "item"], name="uniq_sprint_item")]


class ScrumDaily(TenantOwned):
    tenant_source = "sprint"
    sprint = models.ForeignKey(Sprint, on_delete=models.CASCADE, related_name="dailies")
    date = models.DateField()
    notes = models.TextField(blank=True, help_text="Adaptation du plan décidée par l'équipe")

    class Meta:
        ordering = ["sprint", "date"]
        constraints = [models.UniqueConstraint(fields=["sprint", "date"], name="uniq_sprint_daily")]


class ScrumDailyEntry(TenantOwned):
    tenant_source = ["daily", "user"]
    IMPEDIMENT = [("", "—"), ("open", "Ouvert"), ("in_progress", "En cours de résolution"), ("resolved", "Résolu")]
    daily = models.ForeignKey(ScrumDaily, on_delete=models.CASCADE, related_name="entries")
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="+")
    progress = models.TextField(blank=True, help_text="Ce qui a progressé vers l'objectif")
    plan = models.TextField(blank=True, help_text="Ce qui est prévu jusqu'au prochain Daily")
    impediment = models.TextField(blank=True)
    impediment_status = models.CharField(max_length=12, choices=IMPEDIMENT, blank=True)
    resolution = models.TextField(blank=True)
    resolution_owner = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    resolution_due = models.DateField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["daily", "user"], name="uniq_daily_user")]


class SprintReview(TenantOwned):
    tenant_source = "sprint"
    sprint = models.OneToOneField(Sprint, on_delete=models.CASCADE, related_name="review")
    increment = models.TextField(blank=True)
    demos = models.TextField(blank=True)
    feedback = models.TextField(blank=True, help_text="Retours des parties prenantes")
    decisions = models.TextField(blank=True)
    backlog_changes = models.TextField(blank=True)
    held_at = models.DateTimeField(null=True, blank=True)
    report = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)


# --------------------------------------------------------------------------- rétrospectives
RETRO_FORMATS = [("ssc", "Start / Stop / Continue"), ("msg", "Mad / Sad / Glad"),
                 ("wwi", "What went well / What could improve"), ("4ls", "4Ls"), ("free", "Format libre")]
RETRO_CATEGORIES = {
    "ssc": ["start", "stop", "continue"],
    "msg": ["mad", "sad", "glad"],
    "wwi": ["well", "improve"],
    "4ls": ["liked", "learned", "lacked", "longed"],
    "free": ["well", "less_well", "difficulties", "blockers", "proposals"],
}
RETRO_TRIGGERS = [("sprint", "Fin de sprint"), ("weekly", "Hebdomadaire"), ("monthly", "Mensuelle"),
                  ("phase", "Fin de phase"), ("milestone", "Fin de jalon"), ("project", "Fin de projet"),
                  ("adhoc", "Ponctuelle")]


class Retrospective(TenantOwned):
    tenant_source = ["project", "facilitator"]
    STATES = [("planned", "Programmée"), ("collecting", "Recueil des retours"), ("held", "Tenue"), ("closed", "Clôturée")]
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="retrospectives")
    sprint = models.ForeignKey(Sprint, on_delete=models.SET_NULL, null=True, blank=True, related_name="retrospectives")
    phase = models.ForeignKey(VPhase, on_delete=models.SET_NULL, null=True, blank=True, related_name="retrospectives")
    trigger = models.CharField(max_length=10, choices=RETRO_TRIGGERS, default="adhoc")
    period_label = models.CharField(max_length=120, blank=True)
    title = models.CharField(max_length=200)
    format = models.CharField(max_length=4, choices=RETRO_FORMATS, default="ssc")
    scheduled_at = models.DateTimeField()
    duration_minutes = models.PositiveSmallIntegerField(default=60)
    calendar_event = models.ForeignKey("planning.CalendarEvent", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    facilitator = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    anonymous_allowed = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=STATES, default="planned")
    report = models.TextField(blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    forced_close = models.BooleanField(default=False, help_text="Clôturée sans décisions complètes (autorisation explicite)")
    dedupe_key = models.CharField(max_length=120, blank=True, help_text="Création automatique idempotente")
    created_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["project", "-scheduled_at"]
        constraints = [models.UniqueConstraint(fields=["project", "dedupe_key"], condition=~Q(dedupe_key=""),
                                               name="uniq_retro_dedupe")]


class RetrospectiveParticipant(TenantOwned):
    tenant_source = ["retro", "user"]
    retro = models.ForeignKey(Retrospective, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="+")
    invited_at = models.DateTimeField(auto_now_add=True)
    contributed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["retro", "user"], name="uniq_retro_participant")]


class RetrospectiveFeedback(TenantOwned):
    """Retour d'un participant. Anonyme : l'auteur n'est pas enregistré (seule une empreinte évite les doublons)."""

    tenant_source = ["retro"]
    retro = models.ForeignKey(Retrospective, on_delete=models.CASCADE, related_name="feedback")
    author = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    anonymous = models.BooleanField(default=False)
    category = models.CharField(max_length=20)
    text = models.TextField()
    votes = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["retro", "category", "-votes", "id"]


class ImprovementAction(TenantOwned):
    """Décision de rétrospective, suivie comme une action PCT (`action`)."""

    tenant_source = ["retro", "action", "owner"]
    retro = models.ForeignKey(Retrospective, on_delete=models.CASCADE, related_name="improvements")
    action = models.OneToOneField("projects.Action", on_delete=models.SET_NULL, null=True, blank=True, related_name="improvement")
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    due = models.DateField(null=True, blank=True)
    priority = models.CharField(max_length=8, choices=PRIORITIES, default="normal")
    status = models.CharField(max_length=10, choices=[("todo", "À faire"), ("doing", "En cours"), ("done", "Réalisée"),
                                                      ("dropped", "Abandonnée")], default="todo")
    result_indicator = models.CharField(max_length=300, blank=True)
    target_sprint = models.ForeignKey(Sprint, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    target_period = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    done_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["retro", "id"]


# --------------------------------------------------------------------------- rappels
REMINDER_KINDS = [
    ("week_start", "Début de semaine"), ("weekly_planning", "Préparation de la semaine"),
    ("sprint_planning", "Sprint Planning"), ("daily", "Daily Scrum"), ("sprint_review", "Sprint Review"),
    ("retro", "Rétrospective"), ("retro_report", "Compte rendu de rétrospective"), ("sprint_close", "Clôture du sprint"),
    ("improvement_overdue", "Action d'amélioration en retard"),
]


class MethodologyReminder(TenantOwned):
    """Rappel planifié. `dedupe_key` unique : jamais deux fois le même rappel ; échecs retentés 3 fois."""

    tenant_source = "project"
    STATES = [("pending", "Prévu"), ("sent", "Envoyé"), ("failed", "Échec"), ("cancelled", "Annulé")]
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="methodology_reminders")
    kind = models.CharField(max_length=20, choices=REMINDER_KINDS)
    remind_at = models.DateTimeField()
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    users = models.ManyToManyField(USER, blank=True, related_name="+")
    sprint = models.ForeignKey(Sprint, on_delete=models.CASCADE, null=True, blank=True, related_name="reminders")
    retro = models.ForeignKey(Retrospective, on_delete=models.CASCADE, null=True, blank=True, related_name="reminders")
    weekly_plan = models.ForeignKey(WeeklyPlan, on_delete=models.CASCADE, null=True, blank=True, related_name="reminders")
    dedupe_key = models.CharField(max_length=160, unique=True)
    status = models.CharField(max_length=10, choices=STATES, default="pending")
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.CharField(max_length=300, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["remind_at", "id"]
        indexes = [models.Index(fields=["status", "remind_at"])]
