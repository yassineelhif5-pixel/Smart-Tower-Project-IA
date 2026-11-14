"""Appel IA : un humain (ou plusieurs) échange en direct avec des assistants IA orchestrés par Maestro.

Lot 1 : un modèle unique. Tours de parole, cartes interactives, sections du document et fichiers lus sont
stockés en JSON sur l'appel ; ils seront éclatés en tables dédiées au lot 2 (voir le dossier de conception).
"""
from django.conf import settings
from django.db import models

from tenants.models import TenantOwned

USER = settings.AUTH_USER_MODEL


class AiCall(TenantOwned):
    tenant_source = "project"

    LIVE, CLOSED = "live", "closed"
    STATUSES = [(LIVE, "En cours"), (CLOSED, "Clôturé")]

    id = models.CharField(primary_key=True, max_length=20)
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="ai_calls")
    organizer = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, related_name="+")
    mode = models.CharField(max_length=10, default="audio", help_text="audio ou video")
    objective = models.CharField(max_length=300, blank=True)
    assistants = models.JSONField(default=list, help_text="Codes des assistants présents (Maestro toujours inclus)")
    lead = models.CharField(max_length=20, help_text="Assistant qui rédige le document principal")
    participants = models.JSONField(default=list, help_text="Humains présents : id, nom, rôle")
    doc_type = models.CharField(max_length=20, blank=True)
    doc_title = models.CharField(max_length=200, blank=True)
    sections = models.JSONField(default=list)
    turns = models.JSONField(default=list)
    cards = models.JSONField(default=list)
    files = models.JSONField(default=list)
    state = models.JSONField(default=dict, help_text="Curseur d'entretien, version du prompt, compteurs")
    status = models.CharField(max_length=10, choices=STATUSES, default=LIVE)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    document = models.ForeignKey("projects.Document", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["-started_at"]
