from django.contrib.auth.models import AbstractUser
from django.db import models

# Modules et verbes de la matrice des droits, identiques à MODULES et VERBS de index.html.
MODULES = [
    ("project", "Projet"), ("client", "Client"), ("planning", "Planning"), ("action", "Action"),
    ("budget", "Budget"), ("resource", "Ressource"), ("document", "Document"), ("test", "Test"),
    ("risk", "Risque"), ("report", "Reporting"), ("user", "Utilisateur"), ("settings", "Paramétrage"),
]
VERBS = [("read", "Voir"), ("create", "Créer"), ("update", "Modifier"), ("delete", "Supprimer"), ("approve", "Valider")]
ADMIN_ROLE = "admin"


class Role(models.Model):
    """Profil de l'application (ROLES dans index.html)."""

    code = models.CharField(primary_key=True, max_length=20)
    label = models.CharField(max_length=60)
    question = models.CharField(max_length=200, blank=True)
    money = models.BooleanField(default=False, help_text="Accès au budget, aux coûts et au forecast")
    margin = models.BooleanField(default=False, help_text="Accès aux marges et au chiffre d'affaires")
    internal = models.BooleanField(default=True, help_text="Faux pour le portail client")
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position"]

    def __str__(self):
        return self.label


class RolePermission(models.Model):
    """Une ligne de la matrice des droits : un module, cinq verbes."""

    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="permissions")
    module = models.CharField(max_length=20, choices=MODULES)
    can_read = models.BooleanField(default=False)
    can_create = models.BooleanField(default=False)
    can_update = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)
    can_approve = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["role", "module"], name="uniq_role_module")]

    def as_list(self):
        return [self.can_read, self.can_create, self.can_update, self.can_delete, self.can_approve]


class User(AbstractUser):
    role = models.ForeignKey(Role, on_delete=models.PROTECT, null=True, blank=True, related_name="users")
    title = models.CharField(max_length=120, blank=True)
    team = models.CharField(max_length=120, blank=True)
    # Identifiant de la personne dans les données de démonstration (PEOPLE de index.html), ex. "sm".
    person_code = models.CharField(max_length=20, unique=True, null=True, blank=True)
    client = models.ForeignKey("projects.Client", on_delete=models.PROTECT, null=True, blank=True, related_name="users")
    must_change_password = models.BooleanField(default=False)

    @property
    def is_app_admin(self):
        return self.is_active and self.role_id == ADMIN_ROLE

    @property
    def display_name(self):
        return self.get_full_name() or self.username
