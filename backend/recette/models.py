"""Module Recette : user stories de test, bugs liés et discussions.

Cycle : une US est « À tester » ; le testeur la passe « En test » puis « Validée » ou « En échec ». Un bug
déclaré sur une US la met « En échec ». Quand tous les bugs ouverts d'une US sont clôturés, l'US passe
automatiquement « Prête à retester ».
"""
from django.conf import settings
from django.db import models

from tenants.models import TenantOwned

USER = settings.AUTH_USER_MODEL

PRIORITIES = [("bloquante", "Bloquante"), ("critique", "Critique"), ("majeure", "Majeure"),
              ("mineure", "Mineure"), ("autre", "Autre")]
STORY_STATUSES = [("a_tester", "À tester"), ("en_test", "En test"), ("validee", "Validée"), ("echec", "En échec"),
                  ("a_retester", "Prête à retester"), ("bloquee", "Bloquée")]
BUG_STATUSES = [("nouveau", "Nouveau"), ("assigne", "Assigné"), ("en_cours", "En cours"), ("cloture", "Clôturé"),
                ("rejete", "Rejeté"), ("rouvert", "Rouvert")]
OPEN_BUG = ("nouveau", "assigne", "en_cours", "rouvert")


class TestStory(TenantOwned):
    tenant_source = "project"

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="test_stories")
    code = models.CharField(max_length=20)
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True, help_text="En tant que… je veux… afin de…")
    acceptance = models.TextField(blank=True, help_text="Critères d'acceptation")
    scenario = models.TextField(blank=True, help_text="Étapes de test")
    expected = models.TextField(blank=True, help_text="Résultat attendu")
    feature = models.CharField(max_length=120, blank=True, help_text="Lot / fonctionnalité")
    priority = models.CharField(max_length=10, choices=PRIORITIES, default="majeure")
    status = models.CharField(max_length=12, choices=STORY_STATUSES, default="a_tester")
    tester = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tested_at = models.DateTimeField(null=True, blank=True)
    tested_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["project_id", "id"]
        constraints = [models.UniqueConstraint(fields=["project", "code"], name="uniq_test_story_code")]


class Bug(TenantOwned):
    tenant_source = "project"

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="bugs")
    story = models.ForeignKey(TestStory, on_delete=models.CASCADE, related_name="bugs")
    code = models.CharField(max_length=20)
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    steps = models.TextField(blank=True, help_text="Étapes pour reproduire")
    severity = models.CharField(max_length=10, choices=PRIORITIES, default="majeure")
    status = models.CharField(max_length=10, choices=BUG_STATUSES, default="nouveau")
    assignee = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    reported_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    resolution = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["project_id", "id"]
        constraints = [models.UniqueConstraint(fields=["project", "code"], name="uniq_bug_code")]


class TestComment(TenantOwned):
    """Discussion (ou trace d'un changement d'état) sur une US ou un bug."""

    tenant_source = "project"

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="+")
    story = models.ForeignKey(TestStory, on_delete=models.CASCADE, null=True, blank=True, related_name="comments")
    bug = models.ForeignKey(Bug, on_delete=models.CASCADE, null=True, blank=True, related_name="comments")
    author = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    body = models.TextField()
    kind = models.CharField(max_length=8, default="comment", help_text="comment ou event")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
