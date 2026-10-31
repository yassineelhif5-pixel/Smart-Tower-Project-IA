"""Clients, projets et actions : uniquement les champs nécessaires à la gestion des accès.

Les autres champs métier (budget, planning, sprints…) arriveront avec la migration
des parcours correspondants depuis index.html.
"""
from django.conf import settings
from django.db import models

ACTION_STATUSES = [
    ("todo", "À faire"), ("planned", "Planifiée"), ("doing", "En cours"),
    ("review", "En revue"), ("blocked", "Bloquée"), ("done", "Terminée"),
]


class Client(models.Model):
    code = models.CharField(primary_key=True, max_length=20)
    name = models.CharField(max_length=120)
    sector = models.CharField(max_length=120, blank=True)
    city = models.CharField(max_length=120, blank=True)
    color = models.CharField(max_length=9, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Project(models.Model):
    id = models.CharField(primary_key=True, max_length=20)
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="projects")
    method = models.CharField(max_length=20, blank=True)
    pm = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    tl = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    progress = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} · {self.name}"


class Action(models.Model):
    id = models.CharField(primary_key=True, max_length=20)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="actions")
    title = models.CharField(max_length=300)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    status = models.CharField(max_length=10, choices=ACTION_STATUSES)
    type = models.CharField(max_length=40, blank=True)
    due = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["id"]


class ProjectAccess(models.Model):
    """Projet affecté à un utilisateur. can_edit limite l'écriture, en plus de la matrice des droits."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="project_accesses")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="accesses")
    can_edit = models.BooleanField(default=True)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "project"], name="uniq_user_project")]


class ActionAccess(models.Model):
    """Tâche ouverte individuellement à un utilisateur, en plus de celles de ses projets."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="action_accesses")
    action = models.ForeignKey(Action, on_delete=models.CASCADE, related_name="accesses")
    can_edit = models.BooleanField(default=False)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "action"], name="uniq_user_action")]
