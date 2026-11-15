"""Espace client : contrats de support N1/N2/N3, CRA et factures mensuels par consultant et par client."""
from django.conf import settings
from django.db import models

from tenants.models import TenantOwned

USER = settings.AUTH_USER_MODEL
LEVELS = [("N1", "Support N1"), ("N2", "Support N2"), ("N3", "Support N3")]
LEVEL_ROLE = {"N1": "support_n1", "N2": "support_n2", "N3": "support_n3"}


class SupportContract(TenantOwned):
    """Licence de support d'un client : couvre tous ses projets (présents et futurs)."""

    tenant_source = "client"

    client = models.OneToOneField("projects.Client", on_delete=models.CASCADE, related_name="support_contract")
    enabled = models.BooleanField(default=False)
    levels = models.JSONField(default=list, help_text="Niveaux couverts : N1, N2, N3")
    rates = models.JSONField(default=dict, blank=True, help_text="TJM par niveau, ex. {\"N1\": 450}")
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    members = models.ManyToManyField(USER, blank=True, related_name="support_contracts")
    granted = models.JSONField(default=list, blank=True, help_text="Accès projet ouverts par le contrat : [[user, projet]]")
    updated_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)


class ClientDocument(TenantOwned):
    """Document de l'espace client. Lecture réservée aux `readers` (consultant, CP, commercial, client) et aux administrateurs."""

    tenant_source = "client"
    KINDS = [("cra", "Compte rendu d'activité"), ("invoice", "Facture"), ("other", "Autre")]

    id = models.CharField(primary_key=True, max_length=20)
    client = models.ForeignKey("projects.Client", on_delete=models.CASCADE, related_name="space_documents")
    kind = models.CharField(max_length=10, choices=KINDS)
    period = models.CharField(max_length=7, blank=True, help_text="AAAA-MM")
    person = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="client_documents")
    name = models.CharField(max_length=255)
    number = models.CharField(max_length=30, blank=True, help_text="Numéro de facture")
    content = models.BinaryField()
    mime = models.CharField(max_length=100, default="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    size_bytes = models.PositiveIntegerField(default=0)
    amount_ht = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    amount_ttc = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    days = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    readers = models.ManyToManyField(USER, blank=True, related_name="readable_client_documents")
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period", "person_id", "kind"]
        indexes = [models.Index(fields=["client", "period"], name="clientdoc_client_period")]


class InvoiceTemplate(TenantOwned):
    """Modèle .docx de facture déposé par l'administrateur, pour une personne, un groupe de personnes, une société
    (intervenants externes qui y sont rattachés) ou par défaut. Priorité : personne > groupe > société > défaut > modèle intégré."""

    SCOPES = [("person", "Personne"), ("group", "Groupe de personnes"), ("company", "Société"), ("default", "Par défaut")]

    name = models.CharField(max_length=120)
    scope = models.CharField(max_length=10, choices=SCOPES)
    persons = models.ManyToManyField(USER, blank=True, related_name="invoice_templates")
    company = models.CharField(max_length=120, blank=True)
    filename = models.CharField(max_length=255)
    content = models.BinaryField()
    size_bytes = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scope", "name"]
