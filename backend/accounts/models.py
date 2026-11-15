from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.db import models

# Modules et verbes de la matrice des droits, repris de MODULES et VERBS de index.html.
# « collaboration » (discussions et Teams) a été ajouté en version 1.4.0 ; le calendrier relève de « planning ».
# « capacity » (capacité, disponibilités) et « methodology » (Cycle en V, Scrum, rétrospectives) : version 1.5.0.
MODULES = [
    ("project", "Projet"), ("client", "Client"), ("planning", "Planning"), ("action", "Action"),
    ("budget", "Budget"), ("resource", "Ressource"), ("document", "Document"), ("test", "Test"),
    ("risk", "Risque"), ("report", "Reporting"), ("user", "Utilisateur"), ("settings", "Paramétrage"),
    ("collaboration", "Collaboration"), ("capacity", "Capacité"), ("methodology", "Méthodologie"),
    ("timesheet", "Saisie de temps"),
]
VERBS = [("read", "Voir"), ("create", "Créer"), ("update", "Modifier"), ("delete", "Supprimer"), ("approve", "Valider")]
ADMIN_ROLE = "admin"
# Pilote (Super Admin Global) de la plateforme : sans tenant, il gère les entreprises (tenants) mais ne lit
# aucune donnée métier privée.
PLATFORM_ROLE = "superadmin"
SUPPORT_ROLE = "support"


class Role(models.Model):
    """Profil de l'application (ROLES dans index.html)."""

    code = models.CharField(primary_key=True, max_length=20)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, null=True, blank=True, related_name="roles")
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
    """Une ligne de la matrice des droits : un module, cinq verbes.

    tenant vide = matrice modèle de la plateforme, copiée à la création de chaque tenant.
    tenant renseigné = matrice propre à ce tenant, la seule appliquée à ses utilisateurs.
    """

    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="permissions")
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    module = models.CharField(max_length=20, choices=MODULES)
    can_read = models.BooleanField(default=False)
    can_create = models.BooleanField(default=False)
    can_update = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)
    can_approve = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["role", "module"], condition=models.Q(tenant__isnull=True),
                                    name="uniq_role_module_template"),
            models.UniqueConstraint(fields=["tenant", "role", "module"], condition=models.Q(tenant__isnull=False),
                                    name="uniq_tenant_role_module"),
        ]

    def as_list(self):
        return [self.can_read, self.can_create, self.can_update, self.can_delete, self.can_approve]


class User(AbstractUser):
    AUTH_MODES = [("standard", "Standard (identifiant et mot de passe)"), ("sso", "SSO"), ("both", "Standard et SSO")]
    # Tenant de l'utilisateur. Vide uniquement pour le super administrateur de la plateforme.
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, null=True, blank=True, related_name="users")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, null=True, blank=True, related_name="users")
    title = models.CharField(max_length=120, blank=True)
    team = models.CharField(max_length=120, blank=True)
    # Identifiant de la personne dans les données de démonstration (PEOPLE de index.html), ex. "sm".
    person_code = models.CharField(max_length=20, unique=True, null=True, blank=True)
    client = models.ForeignKey("projects.Client", on_delete=models.PROTECT, null=True, blank=True, related_name="users")
    must_change_password = models.BooleanField(default=False)
    auth_mode = models.CharField(max_length=10, choices=AUTH_MODES, default="both")
    # Facturation : société de rattachement (ex. société d'un consultant externe), statut externe et TJM par défaut.
    company = models.CharField(max_length=120, blank=True, help_text="Société de rattachement (ex. société du consultant externe)")
    external = models.BooleanField(default=False, help_text="Intervenant externe rattaché à une société")
    daily_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="TJM HT par défaut de la personne")

    @property
    def is_app_admin(self):
        """Administrateur de son tenant (module Configuration)."""
        return self.is_active and self.role_id == ADMIN_ROLE and self.tenant_id is not None

    @property
    def is_platform_admin(self):
        """Super administrateur de la plateforme (gestion des tenants), sans tenant."""
        return self.is_active and self.role_id == PLATFORM_ROLE and self.tenant_id is None

    @property
    def is_platform_support(self):
        return self.is_active and self.role_id == SUPPORT_ROLE and self.tenant_id is None

    @property
    def display_name(self):
        return self.get_full_name() or self.username


class SSOConnector(models.Model):
    """Connexion OpenID Connect propre à une entreprise ; son secret reste dans ServiceSecret."""

    tenant = models.OneToOneField("tenants.Tenant", on_delete=models.PROTECT, related_name="sso_connector")
    issuer = models.URLField(max_length=500)
    client_id = models.CharField(max_length=255)
    default_role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="sso_connectors")
    enabled = models.BooleanField(default=False)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)


class SSOIdentity(models.Model):
    """Lien stable entre une identité OIDC vérifiée et un compte PCT."""

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, related_name="sso_identities")
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sso_identity")
    issuer = models.URLField(max_length=500)
    subject = models.CharField(max_length=255)
    email = models.EmailField(max_length=254)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["issuer", "subject"], name="uniq_sso_issuer_subject")]


class SSOAccessRequest(models.Model):
    """Demande vérifiée par le fournisseur SSO, en attente de validation par le tenant."""

    PENDING, APPROVED, REJECTED = "pending", "approved", "rejected"
    STATUSES = [(PENDING, "En attente"), (APPROVED, "Acceptée"), (REJECTED, "Refusée")]
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="sso_access_requests")
    issuer = models.URLField(max_length=500)
    subject = models.CharField(max_length=255)
    email = models.EmailField(max_length=254)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="sso_requests_reviewed")
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="sso_access_request")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["issuer", "subject"], name="uniq_sso_access_request_subject")]
        ordering = ["requested_at"]


class UserAccessChangeRequest(models.Model):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="user_access_change_requests")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="access_change_requests")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="access_change_submissions")
    requested_role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="access_change_requests")
    reason = models.CharField(max_length=500)
    status = models.CharField(max_length=10, choices=[("pending", "En attente"), ("approved", "Acceptée"), ("rejected", "Refusée")], default="pending")
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="access_change_reviews")
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at"]


from .capabilities import RoleCapability, UserCapability  # noqa: E402,F401  (enregistrement des modèles)


class TenantMembership(models.Model):
    """Accès d'un utilisateur à une autre entreprise (tenant) : il peut basculer de l'une à l'autre.

    L'entreprise « active » reste celle de user.tenant ; basculer recopie ici le tenant, le profil et le client.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="memberships")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    client = models.ForeignKey("projects.Client", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "tenant"], name="uniq_user_tenant_membership")]
        ordering = ["tenant__name"]


class UserPhoto(models.Model):
    """Photo de profil (stockée en base, 256 px max., redimensionnée par le navigateur)."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, primary_key=True, on_delete=models.CASCADE, related_name="photo")
    content = models.BinaryField()
    mime = models.CharField(max_length=40, default="image/jpeg")
    updated_at = models.DateTimeField(auto_now=True)
