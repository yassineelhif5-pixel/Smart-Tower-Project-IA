"""API du module Configuration (réservée aux administrateurs) et notifications de l'utilisateur."""
import secrets
import time
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404
from django.urls import URLPattern, URLResolver, get_resolver
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import MODULES, VERBS, Role, RolePermission, SSOAccessRequest, SSOConnector, SSOIdentity, UserAccessChangeRequest
from accounts.capabilities import has_capability
from accounts.models import PLATFORM_ROLE
from accounts.permissions import IsAppAdmin, IsPlatformAdmin, IsPlatformSupport, LicenseIsValid, PasswordChangeNotRequired, TenantIsActive, has_perm
from accounts.serializers import permissions_of
from config.errors import ApiError
from projects.access import in_active_tenant
from projects.models import Action, ActionAccess, Client, Project, ProjectAccess
from tenants.models import TenantDomain

from . import audit, notify
from .models import (CHANNEL_SECRET, CHANNELS, EVENTS, SECRET_CATALOG, ApiRequestLog, ApiToken, AppSetting, AuditEvent,
                     Notification, NotificationChannel, NotificationRule, ServiceSecret)
from .serializers import (AccessSerializer, AdminUserSerializer, ChannelSerializer, ChannelTestSerializer,
                          PermissionsSerializer, RoleCreateSerializer, RulesSerializer, SSOConnectorSerializer, SecretSerializer, TokenCreateSerializer,
                          temporary_password)

User = get_user_model()
ADMIN = [permissions.IsAuthenticated, TenantIsActive, LicenseIsValid, PasswordChangeNotRequired, IsAppAdmin]
PLATFORM = [permissions.IsAuthenticated, PasswordChangeNotRequired, IsPlatformAdmin]


class AdminView(APIView):
    """Administration d'UN tenant : chaque requête est limitée au tenant de l'administrateur connecté."""

    permission_classes = ADMIN

    @property
    def tenant(self):
        return self.request.user.tenant

    def tenant_users(self):
        return User.objects.filter(tenant=self.tenant)

    def get_user(self, pk):
        # 404 (et non 403) pour un compte d'un autre tenant : son existence n'est pas révélée.
        return get_object_or_404(self.tenant_users(), pk=pk)


class PlatformView(APIView):
    """Administration de la plateforme : Pilote uniquement."""

    permission_classes = PLATFORM


class PlatformTenantRightsView(PlatformView):
    """Pilotage des permissions de création projet et d'administration par profil d'un tenant."""
    permission_classes = [permissions.IsAuthenticated, PasswordChangeNotRequired, IsPlatformSupport]

    def get(self, request, pk):
        from accounts.capabilities import CATALOG, RoleCapability
        from tenants.models import Tenant
        tenant = get_object_or_404(Tenant, pk=pk)
        roles = Role.objects.filter(Q(tenant__isnull=True) | Q(tenant=tenant)).exclude(code__in=[PLATFORM_ROLE, "support"]).order_by("position", "label")
        policy_row = AppSetting.objects.filter(tenant=tenant, key="pilot_access_policy").first()
        policy = policy_row.value if policy_row and isinstance(policy_row.value, dict) else {}
        result = []
        for role in roles:
            row = RolePermission.objects.filter(tenant=tenant, role=role, module="project").first()
            caps = set(RoleCapability.objects.filter(tenant=tenant, role=role).values_list("code", flat=True))
            project_roles = policy.get("projectCreateRoles")
            cap_roles = policy.get("capabilityRoles", {})
            if role.code != "admin" and isinstance(project_roles, list):
                project_create = role.code in project_roles
            else:
                project_create = True if role.code == "admin" else bool(row and row.can_create)
            if role.code != "admin":
                caps = {code for code, allowed in cap_roles.items() if isinstance(allowed, list) and role.code in allowed} if cap_roles else caps
            result.append({"code": role.code, "label": role.label, "locked": role.code == "admin",
                           "projectCreate": project_create,
                           "capabilities": sorted({c for c, _, _ in CATALOG} if role.code == "admin" else caps)})
        return Response({"catalog": [{"code": c, "domain": d, "action": a, "delegable": c not in {"roles.administer"}} for c, d, a in CATALOG],
                         "roles": result})

    def put(self, request, pk):
        from accounts.capabilities import CATALOG, CODES, NOT_DELEGABLE, RoleCapability
        from tenants.models import Tenant
        tenant = get_object_or_404(Tenant, pk=pk)
        wanted = request.data.get("roles")
        if not isinstance(wanted, dict) or "admin" in wanted or PLATFORM_ROLE in wanted:
            raise ApiError("VALIDATION_ERROR", "Fournissez les droits modifiables par profil ; le profil Administrateur reste verrouillé.")
        roles = {r.code: r for r in Role.objects.filter(Q(tenant__isnull=True) | Q(tenant=tenant)).exclude(code__in=[PLATFORM_ROLE, "support"])}
        for code, values in wanted.items():
            if code not in roles or not isinstance(values, dict) or not isinstance(values.get("projectCreate"), bool):
                raise ApiError("VALIDATION_ERROR", "Profil ou règle de création projet invalide.", details=[code])
            caps = values.get("capabilities", [])
            if not isinstance(caps, list) or set(caps) - CODES or set(caps) & NOT_DELEGABLE:
                raise ApiError("VALIDATION_ERROR", "Une permission d'administration est inconnue ou réservée.", details=[code])
        with transaction.atomic():
            project_roles = ["admin"] + [code for code, values in wanted.items() if values["projectCreate"]]
            capability_roles = {cap: ["admin"] + [code for code, values in wanted.items() if cap in values.get("capabilities", [])]
                                for cap, _, _ in CATALOG}
            for code, values in wanted.items():
                role = roles[code]
                row, _ = RolePermission.objects.get_or_create(tenant=tenant, role=role, module="project", defaults={
                    "can_read": False, "can_create": False, "can_update": False, "can_delete": False, "can_approve": False})
                if row.can_create != values["projectCreate"]:
                    before = row.can_create
                    row.can_create = values["projectCreate"]
                    row.save(update_fields=["can_create"])
                    audit.record(request.user, f"Entreprise {tenant.name} · {role.label}", "Droit de création projet modifié",
                                 "accordé" if before else "refusé", "accordé" if row.can_create else "refusé", tenant=None)
                caps = set(values.get("capabilities", []))
                before = set(RoleCapability.objects.filter(tenant=tenant, role=role).values_list("code", flat=True))
                RoleCapability.objects.filter(tenant=tenant, role=role).exclude(code__in=caps).delete()
                for cap in caps - before:
                    RoleCapability.objects.create(tenant=tenant, role=role, code=cap)
                if before != caps:
                    audit.record(request.user, f"Entreprise {tenant.name} · {role.label}", "Droits d'administration modifiés",
                                 ", ".join(sorted(before)) or "aucun", ", ".join(sorted(caps)) or "aucun", tenant=None)
            AppSetting.objects.update_or_create(tenant=tenant, key="pilot_access_policy", defaults={
                "value": {"projectCreateRoles": project_roles, "capabilityRoles": capability_roles}})
            audit.record(request.user, f"Entreprise {tenant.name}", "Politique d'accès Pilotée modifiée", "", "Droits d'accès définis par profil", tenant=None)
        return self.get(request, pk)


def int_param(request, name, default, low, high):
    try:
        value = int(request.query_params.get(name, default))
    except (TypeError, ValueError):
        raise ApiError("VALIDATION_ERROR", f"Le paramètre {name} doit être un nombre.")
    return min(max(value, low), high)


def user_label(u):
    return f"Utilisateur {u.username}"


def quota_guard(tenant):
    """Nombre maximal d'utilisateurs actifs de l'offre souscrite (vérifié côté serveur)."""
    from licensing import services as licensing
    try:
        licensing.check_user_quota(tenant)
    except licensing.LicenseError as exc:
        raise ApiError(exc.code, exc.message) from exc


def release_access(by, user):
    """Un compte désactivé rend sa licence nominative au stock et perd ses sessions."""
    from licensing import models as L
    from licensing import services as licensing
    lic = licensing.named_license_of(user)
    if lic is not None:
        licensing.release(by=by, license=lic, reason="Compte désactivé")
    for s in L.ConcurrentSession.objects.filter(user=user, ended_at__isnull=True):
        licensing.close_session(s, "revoked")


# --------------------------------------------------------------------- utilisateurs et droits
class UserListView(AdminView):
    def get(self, request):
        users = self.tenant_users().select_related("role", "client").order_by("username")
        return Response(AdminUserSerializer(users, many=True, context={"request": request}).data)

    def post(self, request):
        serializer = AdminUserSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data.get("is_active", True):
            quota_guard(self.tenant)
        user = serializer.save(tenant=self.tenant)
        audit.record(request.user, user_label(user), "Compte créé", "", f"rôle {user.role_id}")
        data = dict(serializer.data)
        data["temporaryPassword"] = user._temporary_password  # affiché une seule fois
        return Response(data, status=status.HTTP_201_CREATED)


class UserDetailView(AdminView):
    def get(self, request, pk):
        user = self.get_user(pk)
        return Response(AdminUserSerializer(user, context={"request": request}).data)

    def patch(self, request, pk):
        user = self.get_user(pk)
        before = {"role": user.role_id, "is_active": user.is_active}
        serializer = AdminUserSerializer(user, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data.get("is_active") and not before["is_active"]:
            quota_guard(self.tenant)
        serializer.save()
        if before["is_active"] and not user.is_active:
            release_access(request.user, user)
        if before["role"] != user.role_id:
            audit.record(request.user, user_label(user), "Rôle modifié", before["role"], user.role_id)
        if before["is_active"] != user.is_active:
            audit.record(request.user, user_label(user), "Compte réactivé" if user.is_active else "Compte désactivé")
        if set(request.data) - {"role", "isActive"}:
            audit.record(request.user, user_label(user), "Profil modifié")
        return Response(serializer.data)


class UserResetPasswordView(AdminView):
    def post(self, request, pk):
        user = self.get_user(pk)
        password = temporary_password()
        user.set_password(password)  # invalide aussi les sessions ouvertes de ce compte
        user.must_change_password = True
        user.save(update_fields=["password", "must_change_password"])
        audit.record(request.user, user_label(user), "Mot de passe réinitialisé")
        return Response({"temporaryPassword": password})


class UserAccessView(AdminView):
    def get(self, request, pk):
        user = self.get_user(pk)
        return Response({
            "projects": [{"project": a.project_id, "canEdit": a.can_edit} for a in user.project_accesses.all()],
            "actions": [{"action": a.action_id, "canEdit": a.can_edit} for a in user.action_accesses.all()],
        })

    def put(self, request, pk):
        user = self.get_user(pk)
        serializer = AccessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        wanted_p = {i["project"]: i["canEdit"] for i in serializer.validated_data["projects"]}
        wanted_a = {i["action"]: i["canEdit"] for i in serializer.validated_data["actions"]}
        # Seuls les projets et tâches du tenant existent pour cet administrateur.
        unknown = (set(wanted_p) - set(Project.objects.filter(tenant=self.tenant, pk__in=wanted_p).values_list("pk", flat=True))) | (
            set(wanted_a) - set(Action.objects.filter(tenant=self.tenant, pk__in=wanted_a).values_list("pk", flat=True)))
        if unknown:
            raise ApiError("NOT_FOUND", "Projet ou tâche introuvable.", status.HTTP_404_NOT_FOUND, sorted(unknown))
        before_p = {a.project_id: a.can_edit for a in user.project_accesses.all()}
        before_a = {a.action_id: a.can_edit for a in user.action_accesses.all()}
        with transaction.atomic():
            user.project_accesses.exclude(project_id__in=wanted_p).delete()
            user.action_accesses.exclude(action_id__in=wanted_a).delete()
            for pid, edit in wanted_p.items():
                ProjectAccess.objects.update_or_create(user=user, project_id=pid, defaults={"can_edit": edit, "granted_by": request.user})
            for aid, edit in wanted_a.items():
                ActionAccess.objects.update_or_create(user=user, action_id=aid, defaults={"can_edit": edit, "granted_by": request.user})
        fmt = lambda d: ", ".join(f"{k}{' (écriture)' if v else ''}" for k, v in sorted(d.items())) or "aucun"
        changed = before_p != wanted_p or before_a != wanted_a
        if changed:
            audit.record(request.user, user_label(user), "Accès projets et tâches", f"{fmt(before_p)} | {fmt(before_a)}", f"{fmt(wanted_p)} | {fmt(wanted_a)}")
            notify.notify("scope_changed", [user], "Votre périmètre a changé",
                          f"Projets : {fmt(wanted_p)}. Tâches individuelles : {fmt(wanted_a)}.")
        return self.get(request, pk)


class TenantCompanyProfileView(AdminView):
    """Fiche de l'entreprise visible et modifiable par son propre administrateur."""
    FIELDS = {"industry": "industry", "website": "website", "phone": "phone", "address": "address",
              "city": "city", "country": "country", "contactName": "contact_name", "contactEmail": "contact_email",
              "contactPhone": "contact_phone", "description": "description"}

    def get(self, request):
        from tenants.views import tenant_row
        return Response(tenant_row(self.tenant))

    def patch(self, request):
        from tenants.views import TenantUpdateSerializer, tenant_row
        serializer = TenantUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        if set(values) - set(self.FIELDS):
            raise ApiError("VALIDATION_ERROR", "Cette fiche accepte uniquement les coordonnées de l'entreprise.")
        changed = []
        for external, field in self.FIELDS.items():
            if external in values and getattr(self.tenant, field) != values[external]:
                setattr(self.tenant, field, values[external])
                changed.append(field)
        if changed:
            self.tenant.save(update_fields=changed)
            audit.record(request.user, f"Entreprise {self.tenant.name}", "Fiche entreprise modifiée", "", ", ".join(changed))
        return Response(tenant_row(self.tenant))


PROJECT_ROLES = {"pm": ({"cdp"}, ("chef de projet",)), "tl": ({"techlead"}, ("tech lead", "techlead"))}


def has_project_role(user, key):
    """Le chef de projet / Tech Lead d'un projet doit avoir le profil correspondant (code ou libellé)."""
    codes, labels = PROJECT_ROLES[key]
    role = user.role
    return bool(role) and (role.code in codes or any(l in role.label.lower() for l in labels))


def new_client_code(name):
    """La clé d'un client est unique sur toute la plateforme : code lisible + suffixe aléatoire."""
    stem = (slugify(name).replace("-", "").upper() or "CLIENT")[:13]
    code = f"{stem}-{secrets.token_hex(3).upper()}"
    while Client.objects.filter(pk=code).exists():
        code = f"{stem}-{secrets.token_hex(3).upper()}"
    return code


def own_company_client(tenant, user):
    """Client qui représente l'entreprise connectée elle-même (projets internes)."""
    client = Client.objects.filter(tenant=tenant, name__iexact=tenant.name).first()
    if client is None:
        client = Client.objects.create(tenant=tenant, code=new_client_code(tenant.name), name=tenant.name, label="Interne")
        audit.record(user, f"Client {client.name}", "Client créé (entreprise connectée)")
    return client


class AdminProjectsView(AdminView):
    """Tous les projets et leurs tâches, pour choisir les accès à affecter."""

    def get(self, request):
        projects = Project.objects.filter(tenant=self.tenant).select_related("client", "pm", "tl").prefetch_related("actions")
        return Response([admin_project_row(p) for p in projects])

    def post(self, request):
        from django.utils.text import slugify

        if not in_active_tenant(request.user) or not has_perm(request.user, "project", "create"):
            raise ApiError("FORBIDDEN_PERMISSION", "Vous n'avez pas le droit de créer un projet.", status.HTTP_403_FORBIDDEN)
        code = str(request.data.get("code", "")).strip().upper()
        name = str(request.data.get("name", "")).strip()
        client_code = str(request.data.get("client", "")).strip()
        if not code or len(code) > 20 or not name or len(name) > 200:
            raise ApiError("VALIDATION_ERROR", "Indiquez un code (20 caractères maximum) et un nom.")
        if Project.objects.filter(tenant=self.tenant, code__iexact=code).exists():
            raise ApiError("VALIDATION_ERROR", "Ce code projet existe déjà dans votre entreprise.")
        # Sans client choisi, le projet est rattaché à l'entreprise connectée (client créé au premier usage).
        client = (get_object_or_404(Client, tenant=self.tenant, code=client_code) if client_code
                  else own_company_client(self.tenant, request.user))
        project_id = slugify(code).replace("-", "")[:20].upper()
        if not project_id or Project.objects.filter(pk=project_id).exists():
            raise ApiError("VALIDATION_ERROR", "Le code ne permet pas de créer un identifiant projet unique.")
        from django.utils.dateparse import parse_date
        dates = {}
        for key, field in (("startDate", "start_date"), ("endDate", "end_date")):
            raw = request.data.get(key) or ""
            parsed = parse_date(str(raw)) if raw else None
            if raw and parsed is None:
                raise ApiError("VALIDATION_ERROR", f"La date {key} est invalide.")
            dates[field] = parsed
        if dates["start_date"] and dates["end_date"] and dates["end_date"] < dates["start_date"]:
            raise ApiError("VALIDATION_ERROR", "La date de fin doit être postérieure à la date de début.")
        members = []
        for key, field in (("pm", "pm"), ("tl", "tl")):
            value = request.data.get(key)
            user = get_object_or_404(self.tenant_users(), pk=value) if value else None
            if user and not has_project_role(user, key):
                label = "chef de projet" if key == "pm" else "Tech Lead"
                raise ApiError("VALIDATION_ERROR", f"{user.get_full_name() or user.username} n'a pas le profil {label}.")
            dates[field] = user
            if user:
                members.append(user)
        project = Project(tenant=self.tenant, id=project_id, code=code, name=name,
                          client=client, method=str(request.data.get("method", ""))[:20],
                          descr=str(request.data.get("description", "")), **dates)
        from projects.workspace import set_project_type
        set_project_type(project, request.data)
        project.save()
        for member in {request.user.pk: request.user, **{u.pk: u for u in members}}.values():
            ProjectAccess.objects.get_or_create(tenant=self.tenant, project=project, user=member,
                                                 defaults={"can_edit": True, "granted_by": request.user})
        audit.record(request.user, f"Projet {project.code}", "Projet créé", "", f"{project.name} · {client.name}")
        project = Project.objects.select_related("client", "pm", "tl").prefetch_related("actions").get(pk=project.pk)
        return Response(admin_project_row(project), status=status.HTTP_201_CREATED)

def admin_project_row(p):
    person = lambda u: {"id": u.id, "name": u.get_full_name() or u.username} if u else None  # noqa: E731
    return {
        "id": p.id, "code": p.code, "name": p.name, "client": {"code": p.client_id, "name": p.client.name},
        "method": p.method, "description": p.descr, "startDate": p.start_date, "endDate": p.end_date,
        "pm": person(p.pm), "tl": person(p.tl),
        "projectType": p.project_type, "projectTypeLabel": p.get_project_type_display(),
        "baseProject": p.base_project_id, "baseVersion": p.base_version, "targetVersion": p.target_version,
        "actions": [{"id": a.id, "title": a.title, "status": a.status} for a in p.actions.all()],
    }


class AdminProjectDetailView(AdminView):
    """Modification d'un projet par l'administrateur, notamment l'affectation du chef de projet et du Tech Lead."""

    def patch(self, request, pk):
        from django.utils.dateparse import parse_date

        project = get_object_or_404(Project.objects.select_related("client", "pm", "tl"), tenant=self.tenant, pk=pk)
        data, changes = request.data, []
        if "name" in data:
            name = str(data.get("name", "")).strip()
            if not name or len(name) > 200:
                raise ApiError("VALIDATION_ERROR", "Le nom du projet est obligatoire (200 caractères maximum).")
            if name != project.name:
                changes.append(f"nom : {name}")
                project.name = name
        if "client" in data:
            code = str(data.get("client") or "").strip()
            client = get_object_or_404(Client, tenant=self.tenant, code=code) if code else own_company_client(self.tenant, request.user)
            if client.pk != project.client_id:
                changes.append(f"client : {client.name}")
                project.client = client
        if "method" in data:
            project.method = str(data.get("method") or "")[:20]
        if "description" in data:
            project.descr = str(data.get("description") or "")
        for key, field in (("startDate", "start_date"), ("endDate", "end_date")):
            if key in data:
                raw = data.get(key) or ""
                parsed = parse_date(str(raw)) if raw else None
                if raw and parsed is None:
                    raise ApiError("VALIDATION_ERROR", "Date invalide.")
                setattr(project, field, parsed)
        if project.start_date and project.end_date and project.end_date < project.start_date:
            raise ApiError("VALIDATION_ERROR", "La date de fin doit être postérieure à la date de début.")
        if any(k in data for k in ("projectType", "baseProject", "baseVersion", "targetVersion")):
            from projects.workspace import set_project_type
            before = project.get_project_type_display()
            set_project_type(project, data)
            if before != project.get_project_type_display():
                changes.append(f"type : {project.get_project_type_display()}")
        new_members = []
        for key, label in (("pm", "chef de projet"), ("tl", "Tech Lead")):
            if key not in data:
                continue
            value = data.get(key)
            user = get_object_or_404(self.tenant_users().filter(is_active=True), pk=value) if value else None
            if user and not has_project_role(user, key):
                raise ApiError("VALIDATION_ERROR", f"{user.get_full_name() or user.username} n'a pas le profil {label}.")
            if getattr(project, f"{key}_id") != (user.pk if user else None):
                changes.append(f"{label} : {(user.get_full_name() or user.username) if user else 'non affecté'}")
                setattr(project, key, user)
                if user:
                    new_members.append(user)
        project.save()
        for member in new_members:
            ProjectAccess.objects.get_or_create(tenant=self.tenant, project=project, user=member,
                                                 defaults={"can_edit": True, "granted_by": request.user})
        if changes:
            audit.record(request.user, f"Projet {project.code}", "Projet modifié", "", " ; ".join(changes))
        project = Project.objects.select_related("client", "pm", "tl").prefetch_related("actions").get(pk=project.pk)
        return Response(admin_project_row(project))


class AdminProjectClientsView(AdminView):
    def get(self, request):
        if not in_active_tenant(request.user) or not has_perm(request.user, "project", "create"):
            raise ApiError("FORBIDDEN_PERMISSION", "Vous n'avez pas le droit de créer un projet.", status.HTTP_403_FORBIDDEN)
        return Response([{"code": c.code, "name": c.name} for c in Client.objects.filter(tenant=self.tenant).order_by("name")])

    def post(self, request):
        """Ajoute un client au référentiel de l'entreprise (nécessaire avant de créer un projet)."""
        if not in_active_tenant(request.user) or not (
                has_perm(request.user, "project", "create") or has_perm(request.user, "client", "create")):
            raise ApiError("FORBIDDEN_PERMISSION", "Vous n'avez pas le droit d'ajouter un client.", status.HTTP_403_FORBIDDEN)
        name = str(request.data.get("name", "")).strip()
        if not name or len(name) > 120:
            raise ApiError("VALIDATION_ERROR", "Indiquez le nom du client (120 caractères maximum).")
        if Client.objects.filter(tenant=self.tenant, name__iexact=name).exists():
            raise ApiError("VALIDATION_ERROR", "Un client porte déjà ce nom dans votre entreprise.")
        client = Client.objects.create(tenant=self.tenant, code=new_client_code(name), name=name,
                                       sector=str(request.data.get("sector", "")).strip()[:120],
                                       city=str(request.data.get("city", "")).strip()[:120])
        audit.record(request.user, f"Client {client.name}", "Client créé")
        return Response({"code": client.code, "name": client.name}, status=status.HTTP_201_CREATED)


class RoleListView(AdminView):
    def get(self, request):
        visible_roles = Role.objects.filter(Q(tenant__isnull=True) | Q(tenant=self.tenant)).exclude(code=PLATFORM_ROLE)
        roles = visible_roles.annotate(userCount=Count(
            "users", filter=Q(users__is_active=True, users__tenant=self.tenant))).order_by("position", "label")
        return Response({
            "modules": [{"code": c, "label": l} for c, l in MODULES],
            "verbs": [{"code": c, "label": l} for c, l in VERBS],
            "roles": [{"code": r.code, "label": r.label, "internal": r.internal, "money": r.money, "margin": r.margin,
                       "userCount": r.userCount, "permissions": permissions_of(r.code, self.tenant)} for r in roles],
        })

    def post(self, request):
        serializer = RoleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from accounts.models import RolePermission
        from django.db import transaction
        data = serializer.validated_data
        stem = slugify(data["label"])[:9] or "profil"
        with transaction.atomic():
            code = None
            for _ in range(12):
                candidate = f"p-{stem}-{secrets.token_hex(3)}"[:20]
                if not Role.objects.filter(code=candidate).exists():
                    code = candidate
                    break
            if code is None:
                raise ApiError("VALIDATION_ERROR", "Impossible de générer un identifiant de profil unique.")
            role = Role.objects.create(code=code, tenant=self.tenant, label=data["label"],
                                       question=data["question"], internal=data["internal"],
                                       money=data["money"], margin=data["margin"],
                                       position=(Role.objects.filter(Q(tenant__isnull=True) | Q(tenant=self.tenant))
                                                 .order_by("-position").values_list("position", flat=True).first() or 0) + 1)
            RolePermission.objects.bulk_create([
                RolePermission(role=role, tenant=self.tenant, module=module)
                for module, _ in MODULES
            ])
        audit.record(request.user, f"Profil {role.label}", "Profil créé", "", "Droits métier refusés par défaut")
        return Response({"code": role.code, "label": role.label, "internal": role.internal, "money": role.money,
                         "margin": role.margin, "userCount": 0, "permissions": permissions_of(role.code, self.tenant)},
                        status=status.HTTP_201_CREATED)


class RolePermissionsView(AdminView):
    def put(self, request, code):
        role = get_object_or_404(Role.objects.filter(Q(tenant__isnull=True) | Q(tenant=self.tenant)).exclude(code=PLATFORM_ROLE), pk=code)
        serializer = PermissionsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        wanted = serializer.validated_data["permissions"]
        modules = {c for c, _ in MODULES}
        if set(wanted) - modules:
            raise ApiError("VALIDATION_ERROR", "Module inconnu.", details=sorted(set(wanted) - modules))
        before = permissions_of(code, self.tenant)
        with transaction.atomic():
            for module, flags in wanted.items():
                RolePermission.objects.update_or_create(role=role, module=module, tenant=self.tenant, defaults={
                    f"can_{v}": flags[i] for i, (v, _) in enumerate(VERBS)})
        for module, flags in wanted.items():
            if before.get(module) != flags:
                diff = lambda f: "".join("1" if x else "0" for x in f)
                audit.record(request.user, f"Rôle {role.label}", f"Droits « {dict(MODULES)[module]} »", diff(before.get(module, [False] * 5)), diff(flags))
        return Response({"code": code, "permissions": permissions_of(code, self.tenant)})


# --------------------------------------------------------------------- connexion SSO OpenID Connect
class SSOSettingsView(AdminView):
    """Le tenant configure son fournisseur ; les domaines restent attribués exclusivement par le Pilote."""

    def get(self, request):
        from accounts.models import Role
        from tenants.models import TenantDomain
        connector = SSOConnector.objects.filter(tenant=self.tenant).first()
        secret = ServiceSecret.objects.filter(tenant=self.tenant, key="sso_client_secret").first()
        roles = Role.objects.filter(internal=True).filter(Q(tenant__isnull=True) | Q(tenant=self.tenant)).exclude(code__in=["admin", PLATFORM_ROLE]).order_by("position", "label")
        return Response({
            "enabled": bool(connector and connector.enabled),
            "issuer": connector.issuer if connector else "",
            "clientId": connector.client_id if connector else "",
            "defaultRole": connector.default_role_id if connector else "",
            "secretSet": bool(secret),
            "secretHint": secret.hint if secret else "",
            "domains": list(TenantDomain.objects.filter(tenant=self.tenant, enabled=True).values_list("domain", flat=True)),
            "roles": [{"code": role.code, "label": role.label} for role in roles],
        })

    def put(self, request):
        serializer = SSOConnectorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        issuer = data["issuer"].strip().rstrip("/")
        from urllib.parse import urlparse
        parsed = urlparse(issuer)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ApiError("VALIDATION_ERROR", "L’émetteur OIDC doit être une URL HTTPS publique, sans paramètres.")
        role = get_object_or_404(
            Role.objects.filter(internal=True).filter(Q(tenant__isnull=True) | Q(tenant=self.tenant))
                .exclude(code__in=["admin", PLATFORM_ROLE]), pk=data["defaultRole"])
        if data["enabled"] and not TenantDomain.objects.filter(tenant=self.tenant, enabled=True).exists():
            raise ApiError("VALIDATION_ERROR", "Le Pilote doit d’abord attribuer un domaine à cette entreprise.")
        secret_row = ServiceSecret.objects.filter(tenant=self.tenant, key="sso_client_secret").first()
        client_secret = data.get("clientSecret", "")
        if data["enabled"] and not (client_secret or secret_row):
            raise ApiError("VALIDATION_ERROR", "Enregistrez le secret du fournisseur avant d’activer le SSO.")
        before = "activé" if SSOConnector.objects.filter(tenant=self.tenant, enabled=True).exists() else "désactivé"
        if client_secret:
            secret_row = secret_row or ServiceSecret(tenant=self.tenant, key="sso_client_secret")
            secret_row.set_value(client_secret)
            secret_row.updated_by = request.user
            secret_row.save()
        connector, _ = SSOConnector.objects.update_or_create(
            tenant=self.tenant,
            defaults={"issuer": issuer, "client_id": data["clientId"], "default_role": role,
                      "enabled": data["enabled"], "updated_by": request.user},
        )
        audit.record(request.user, "Connexion SSO", "Configuration modifiée", before,
                     "activée" if connector.enabled else "désactivée", tenant=self.tenant)
        return self.get(request)


class TimeTrackingSettingsView(AdminView):
    def get(self, request):
        row = AppSetting.objects.filter(tenant=self.tenant, key="time").first()
        value = row.value if row and isinstance(row.value, dict) else {}
        from projects.time_approval import DEFAULT_MODE, MODES
        return Response({"unit": value.get("entryUnit", "hour"), "hoursPerDay": value.get("hpd", 8),
                         "clientVisible": value.get("clientVisible", True),
                         "approval": value.get("approval", DEFAULT_MODE) if value.get("approval") in MODES else DEFAULT_MODE,
                         "approvalModes": [{"code": c, "label": l} for c, l in MODES.items()],
                         "clientApproval": bool(value.get("clientApproval", False))})

    def put(self, request):
        unit = request.data.get("unit")
        client_visible = request.data.get("clientVisible", True)
        try:
            hours_per_day = float(request.data.get("hoursPerDay", 8))
        except (TypeError, ValueError):
            raise ApiError("VALIDATION_ERROR", "Le nombre d'heures par journée est invalide.")
        if unit not in {"hour", "day"} or not isinstance(client_visible, bool) or not 1 <= hours_per_day <= 24:
            raise ApiError("VALIDATION_ERROR", "Choisissez une unité valide et entre 1 et 24 heures par jour.")
        from projects.time_approval import DEFAULT_MODE, MODES
        row = AppSetting.objects.filter(tenant=self.tenant, key="time").first()
        value = row.value.copy() if row and isinstance(row.value, dict) else {}
        approval = request.data.get("approval", value.get("approval", DEFAULT_MODE))
        if approval not in MODES:
            raise ApiError("VALIDATION_ERROR", "Circuit de validation inconnu.")
        if approval != value.get("approval", DEFAULT_MODE):
            audit.record(request.user, "Saisie de temps", "Circuit de validation modifié",
                         MODES.get(value.get("approval", DEFAULT_MODE), ""), MODES[approval], tenant=self.tenant)
        client_approval = bool(request.data.get("clientApproval", value.get("clientApproval", False)))
        if client_approval != bool(value.get("clientApproval", False)):
            audit.record(request.user, "Saisie de temps", "Validation client des temps",
                         str(bool(value.get("clientApproval", False))), str(client_approval), tenant=self.tenant)
        value.update({"entryUnit": unit, "hpd": hours_per_day, "clientVisible": client_visible, "approval": approval,
                      "clientApproval": client_approval})
        AppSetting.objects.update_or_create(tenant=self.tenant, key="time", defaults={"value": value})
        audit.record(request.user, "Saisie de temps", "Règles de saisie modifiées", "", f"{unit} · {hours_per_day} h/jour · client {'visible' if client_visible else 'masqué'}", tenant=self.tenant)
        return self.get(request)


class SSOAccessRequestView(APIView):
    permission_classes = [permissions.IsAuthenticated, TenantIsActive, LicenseIsValid, PasswordChangeNotRequired]

    def _allowed(self, request):
        return bool(request.user.tenant_id and has_capability(request.user, "users.approve_sso"))

    def get(self, request):
        if not self._allowed(request):
            return Response({"detail": "Vous n'êtes pas habilité à traiter les demandes SSO."}, status=status.HTTP_403_FORBIDDEN)
        rows = SSOAccessRequest.objects.filter(tenant=request.user.tenant).select_related("reviewed_by")
        roles = Role.objects.filter(internal=True).filter(Q(tenant__isnull=True) | Q(tenant=request.user.tenant)).exclude(code__in=["admin", PLATFORM_ROLE]).order_by("position", "label")
        from .client_domains import client_for_email
        ext = Role.objects.filter(internal=False).filter(Q(tenant__isnull=True) | Q(tenant=request.user.tenant)).order_by("position", "label")
        out = []
        for row in rows:
            c = client_for_email(request.user.tenant, row.email)
            out.append({"id": row.pk, "email": row.email, "firstName": row.first_name, "lastName": row.last_name,
                        "status": row.status, "requestedAt": row.requested_at, "reviewedAt": row.reviewed_at,
                        "reviewedBy": row.reviewed_by.username if row.reviewed_by else None,
                        "client": c.code if c else None, "clientName": c.name if c else None})
        return Response({"requests": out,
                         "roles": [{"code": role.code, "label": role.label} for role in roles]
                         + [{"code": role.code, "label": f"{role.label} (externe)", "external": True} for role in ext]})

    @transaction.atomic
    def post(self, request, pk=None):
        if not self._allowed(request):
            return Response({"detail": "Vous n'êtes pas habilité à traiter les demandes SSO."}, status=status.HTTP_403_FORBIDDEN)
        try:
            item = SSOAccessRequest.objects.select_for_update().get(pk=pk, tenant=request.user.tenant)
        except SSOAccessRequest.DoesNotExist:
            from django.http import Http404
            raise Http404
        if item.status != SSOAccessRequest.PENDING:
            return Response({"detail": "Cette demande a déjà été traitée."}, status=status.HTTP_409_CONFLICT)
        action = request.data.get("action")
        if action not in {"approve", "reject"}:
            return Response({"detail": "Choisissez accepter ou refuser."}, status=status.HTTP_400_BAD_REQUEST)
        if action == "approve":
            from .client_domains import client_for_email
            domain_client = client_for_email(request.user.tenant, item.email)
            roles_qs = Role.objects.filter(Q(tenant__isnull=True) | Q(tenant=request.user.tenant))
            role = get_object_or_404(roles_qs if domain_client else roles_qs.filter(internal=True), code=request.data.get("role"))
            if role.code in {"admin", PLATFORM_ROLE}:
                return Response({"detail": "Un profil administrateur ne peut pas être attribué par cette demande."}, status=status.HTTP_400_BAD_REQUEST)
            if not TenantDomain.objects.filter(tenant=request.user.tenant, enabled=True,
                                               domain=item.email.rsplit("@", 1)[-1].lower()).exists():
                return Response({"detail": "Le domaine n'est plus autorisé par le Pilote."}, status=status.HTTP_409_CONFLICT)
            user = User.objects.filter(email__iexact=item.email).first()
            if user and (user.tenant_id != request.user.tenant_id or not user.is_active):
                return Response({"detail": "Cette adresse est déjà rattachée à un autre compte."}, status=status.HTTP_409_CONFLICT)
            if user is None:
                from accounts.sso import _username
                user = User(username=_username(item.email, request.user.tenant), email=item.email,
                            first_name=item.first_name, last_name=item.last_name,
                            tenant=request.user.tenant, role=role, is_active=True, must_change_password=False,
                            client=None if role.internal else domain_client)
                user.set_unusable_password()
                user.save()
            else:
                user.role = role
                user.client = None if role.internal else (domain_client or user.client)
                user.save(update_fields=["role", "client"])
            identity, created = SSOIdentity.objects.get_or_create(
                issuer=item.issuer, subject=item.subject,
                defaults={"tenant": request.user.tenant, "user": user, "email": item.email},
            )
            if not created and (identity.user_id != user.pk or identity.tenant_id != request.user.tenant_id):
                return Response({"detail": "Cette identité SSO est déjà rattachée à un autre compte."}, status=status.HTTP_409_CONFLICT)
            item.user = user
            item.status = SSOAccessRequest.APPROVED
        else:
            item.status = SSOAccessRequest.REJECTED
        item.reviewed_by = request.user
        item.reviewed_at = timezone.now()
        item.save(update_fields=["user", "status", "reviewed_by", "reviewed_at"])
        audit.record(request.user, f"Demande SSO {item.email}", "Demande d'accès acceptée" if action == "approve" else "Demande d'accès refusée",
                     "En attente", item.status, tenant=request.user.tenant)
        return Response({"id": item.pk, "email": item.email, "status": item.status,
                         "reviewedAt": item.reviewed_at, "reviewedBy": request.user.username})


class UserAccessChangeRequestView(APIView):
    permission_classes = [permissions.IsAuthenticated, TenantIsActive, LicenseIsValid, PasswordChangeNotRequired]

    def get(self, request):
        is_admin = request.user.is_app_admin
        if not is_admin and not has_capability(request.user, "users.request_access_change"):
            return Response({"detail": "Vous n'êtes pas habilité à consulter les demandes d'accès."}, status=403)
        rows = UserAccessChangeRequest.objects.filter(tenant=request.user.tenant)
        if not is_admin:
            rows = rows.filter(requested_by=request.user)
        rows = rows.select_related("user", "requested_by", "requested_role", "reviewed_by")[:100]
        roles = Role.objects.filter(internal=True).filter(Q(tenant__isnull=True) | Q(tenant=request.user.tenant)).exclude(code__in=["admin", PLATFORM_ROLE]).order_by("position", "label")
        return Response({"requests": [{"id": row.pk, "user": row.user_id, "username": row.user.username,
            "email": row.user.email, "requestedBy": row.requested_by.username, "requestedRole": row.requested_role_id,
            "reason": row.reason, "status": row.status, "requestedAt": row.requested_at,
            "reviewedBy": row.reviewed_by.username if row.reviewed_by else None} for row in rows],
            "roles": [{"code": role.code, "label": role.label} for role in roles],
            "users": list(User.objects.filter(tenant=request.user.tenant, is_active=True).order_by("username").values("id", "username", "email")) if not is_admin else []})

    def post(self, request, pk=None):
        if pk is None:
            if request.user.is_app_admin or not has_capability(request.user, "users.request_access_change"):
                return Response({"detail": "Vous n'êtes pas habilité à déposer une demande."}, status=403)
            user = get_object_or_404(User.objects.filter(tenant=request.user.tenant, is_active=True), pk=request.data.get("user"))
            role = get_object_or_404(Role.objects.filter(internal=True).filter(Q(tenant__isnull=True) | Q(tenant=request.user.tenant)).exclude(code__in=["admin", PLATFORM_ROLE]), pk=request.data.get("role"))
            reason = str(request.data.get("reason", "")).strip()[:500]
            if not reason:
                return Response({"detail": "Expliquez la raison du changement demandé."}, status=400)
            item = UserAccessChangeRequest.objects.create(tenant=request.user.tenant, user=user,
                requested_by=request.user, requested_role=role, reason=reason)
            audit.record(request.user, f"Accès de {user.username}", "Demande de changement d'accès", user.role_id, role.code, tenant=request.user.tenant)
            return Response({"id": item.pk, "status": item.status}, status=201)
        if not request.user.is_app_admin:
            return Response({"detail": "Seul un administrateur peut valider ces changements."}, status=403)
        with transaction.atomic():
            item = get_object_or_404(UserAccessChangeRequest.objects.select_for_update().filter(tenant=request.user.tenant), pk=pk)
            if item.status != "pending":
                return Response({"detail": "Cette demande a déjà été traitée."}, status=409)
            action = request.data.get("action")
            if action not in {"approve", "reject"}:
                return Response({"detail": "Choisissez accepter ou refuser."}, status=400)
            if action == "approve":
                role = get_object_or_404(Role.objects.filter(internal=True).filter(Q(tenant__isnull=True) | Q(tenant=request.user.tenant)).exclude(code__in=["admin", PLATFORM_ROLE]), pk=request.data.get("role", item.requested_role_id))
                item.user.role = role
                item.user.save(update_fields=["role"])
                item.status = "approved"
            else:
                item.status = "rejected"
            item.reviewed_by, item.reviewed_at = request.user, timezone.now()
            item.save(update_fields=["status", "reviewed_by", "reviewed_at"])
            audit.record(request.user, f"Accès de {item.user.username}", "Demande de changement acceptée" if action == "approve" else "Demande de changement refusée",
                         item.user.role_id, item.status, tenant=request.user.tenant)
        return Response({"id": item.pk, "status": item.status})


# --------------------------------------------------------------------- base de données
def database_status():
    started = time.perf_counter()
    try:
        with connection.cursor() as cursor:
            cursor.execute("select current_setting('server_version')")
            version = cursor.fetchone()[0]
            ssl = None
            try:
                cursor.execute("select ssl from pg_stat_ssl where pid = pg_backend_pid()")
                row = cursor.fetchone()
                ssl = bool(row[0]) if row else None
            except Exception:
                ssl = None
        latency = round((time.perf_counter() - started) * 1000, 1)
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        applied = len(executor.loader.applied_migrations)
        return {
            "connected": True, "serverVersion": version, "latencyMs": latency, "ssl": ssl,
            "migrations": {"applied": applied, "pending": [f"{m.app_label}.{m.name}" for m, _ in plan]},
        }
    except Exception as exc:
        return {"connected": False, "error": type(exc).__name__}


class DatabaseView(PlatformView):
    def get(self, request):
        host = connection.settings_dict.get("HOST", "")
        data = {
            "provider": "Supabase (PostgreSQL)" if "supabase" in host else "PostgreSQL",
            "engine": connection.vendor,
            "configuredBy": "DATABASE_URL",
            "location": "local" if host in ("", "localhost", "127.0.0.1") or host.startswith("/") else "distant",
        }
        data.update(database_status())
        return Response(data)


class DatabaseTestView(PlatformView):
    def post(self, request):
        result = database_status()
        audit.record(request.user, "Base de données", "Test de connexion", "", "réussi" if result["connected"] else "échec", tenant=None)
        return Response(result, status=status.HTTP_200_OK if result["connected"] else status.HTTP_503_SERVICE_UNAVAILABLE)


class SupportSaaSReportView(APIView):
    """Supervision globale en lecture seule, accessible au Pilote et au support Control Tower."""
    permission_classes = [permissions.IsAuthenticated, PasswordChangeNotRequired, IsPlatformSupport]

    def get(self, request):
        from tenants.models import Tenant
        from django.conf import settings
        since = timezone.now() - timedelta(hours=24)
        logs = ApiRequestLog.objects.filter(at__gte=since)
        totals = logs.aggregate(requests=Count("id"), errors=Count("id", filter=Q(status__gte=500)),
                                clientErrors=Count("id", filter=Q(status__gte=400, status__lt=500)), avg=Avg("duration_ms"))
        tenants = Tenant.objects.all()
        return Response({"database": database_status(), "tenants": {"total": tenants.count(), "active": tenants.filter(status="active").count(),
                         "suspended": tenants.filter(status="suspended").count()},
                         "api24h": {"requests": totals["requests"] or 0, "serverErrors": totals["errors"] or 0,
                                    "clientErrors": totals["clientErrors"] or 0, "avgMs": round(totals["avg"] or 0, 1)},
                         "deployment": "serverless" if getattr(settings, "ON_VERCEL", False) else "process",
                         "restartAvailable": False,
                         "restartMessage": "Le redémarrage doit être effectué depuis l’hébergeur du service; cette application ne dispose pas d’une commande d’exploitation sécurisée."})


class SupportTenantListView(APIView):
    permission_classes = [permissions.IsAuthenticated, PasswordChangeNotRequired, IsPlatformSupport]

    def get(self, request):
        from tenants.models import Tenant
        return Response([{"id": t.pk, "name": t.name, "status": t.status} for t in Tenant.objects.order_by("name")])


class AdminSaaSReportView(AdminView):
    def get(self, request):
        since = timezone.now() - timedelta(hours=24)
        logs = ApiRequestLog.objects.filter(tenant=self.tenant, at__gte=since)
        totals = logs.aggregate(requests=Count("id"), errors=Count("id", filter=Q(status__gte=500)),
                                clientErrors=Count("id", filter=Q(status__gte=400, status__lt=500)), avg=Avg("duration_ms"))
        return Response({"tenant": self.tenant.name,
                         "api24h": {"requests": totals["requests"] or 0, "serverErrors": totals["errors"] or 0,
                                    "clientErrors": totals["clientErrors"] or 0, "avgMs": round(totals["avg"] or 0, 1)},
                         "restartAvailable": False,
                         "restartMessage": "Le redémarrage des services est réservé à l’exploitation de la plateforme."})


# --------------------------------------------------------------------- API : état, journal, jetons, secrets
def _access_of(callback):
    cls = getattr(callback, "cls", None)
    perms = getattr(cls, "permission_classes", []) if cls else []
    capabilities = getattr(cls, "capabilities", None)
    if capabilities:
        return "droit : " + ", ".join(f"{m} {c}" for m, c in sorted(capabilities.items()))
    if cls is not None and cls.__name__ in ("EndpointListView", "SpectacularAPIView", "SpectacularSwaggerView"):
        return "admin ou pilote"
    if IsPlatformAdmin in perms:
        return "pilote"
    if IsAppAdmin in perms:
        return "admin"
    if permissions.AllowAny in perms:
        return "public"
    return "connecté"


def _walk(patterns, prefix=""):
    for p in patterns:
        if isinstance(p, URLResolver):
            yield from _walk(p.url_patterns, prefix + str(p.pattern))
        elif isinstance(p, URLPattern):
            cls = getattr(p.callback, "cls", None)
            methods = [m.upper() for m in ("get", "post", "put", "patch", "delete") if cls and hasattr(cls, m)]
            yield {"path": "/" + prefix + str(p.pattern), "methods": methods, "access": _access_of(p.callback)}


class EndpointListView(AdminView):
    permission_classes = [permissions.IsAuthenticated, PasswordChangeNotRequired]

    def check_permissions(self, request):
        # Catalogue des routes : lisible par un administrateur de tenant comme par le Pilote.
        super().check_permissions(request)
        if not (request.user.is_app_admin or request.user.is_platform_admin) or request.auth is not None:
            self.permission_denied(request, message=IsAppAdmin.message)

    def get(self, request):
        # Seule la version courante est listée : l'ancien chemin /api/ sans version en est un alias exact.
        return Response([e for e in _walk(get_resolver().url_patterns) if e["path"].startswith("/api/v1/")])


class ApiStatsView(AdminView):
    def get(self, request):
        hours = int_param(request, "hours", 24, 1, 24 * 30)
        logs = ApiRequestLog.objects.filter(tenant=self.tenant, at__gte=timezone.now() - timedelta(hours=hours))
        total = logs.aggregate(n=Count("id"), avg=Avg("duration_ms"), err4=Count("id", filter=Q(status__gte=400, status__lt=500)),
                               err5=Count("id", filter=Q(status__gte=500)))
        top = logs.values("method", "path").annotate(n=Count("id"), avg=Avg("duration_ms"),
                                                     errors=Count("id", filter=Q(status__gte=400))).order_by("-n")[:10]
        return Response({
            "hours": hours, "requests": total["n"], "avgMs": round(total["avg"] or 0, 1),
            "clientErrors": total["err4"], "serverErrors": total["err5"],
            "top": [{"method": t["method"], "path": t["path"], "requests": t["n"], "avgMs": round(t["avg"], 1), "errors": t["errors"]} for t in top],
        })


class ApiLogView(AdminView):
    def get(self, request):
        limit = int_param(request, "limit", 100, 1, 500)
        logs = ApiRequestLog.objects.filter(tenant=self.tenant).select_related("user", "token")
        if request.query_params.get("errors") == "1":
            logs = logs.filter(status__gte=400)
        return Response([{"at": l.at, "method": l.method, "path": l.path, "status": l.status, "durationMs": l.duration_ms,
                          "user": l.user.username if l.user else None, "token": l.token.name if l.token else None} for l in logs[:limit]])


def token_row(t):
    return {"id": t.id, "name": t.name, "prefix": t.prefix, "user": {"id": t.user_id, "username": t.user.username},
            "readOnly": t.read_only, "createdAt": t.created_at, "expiresAt": t.expires_at, "lastUsedAt": t.last_used_at,
            "revokedAt": t.revoked_at, "active": t.is_valid}


class TokenListView(AdminView):
    def get(self, request):
        return Response([token_row(t) for t in ApiToken.objects.filter(tenant=self.tenant).select_related("user")])

    def post(self, request):
        serializer = TokenCreateSerializer(data=request.data, context={"tenant": self.tenant})
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        expires = timezone.now() + timedelta(days=d["expiresInDays"]) if d.get("expiresInDays") else None
        token, raw = ApiToken.issue(name=d["name"], user=d["user"], read_only=d["readOnly"], created_by=request.user, expires_at=expires)
        audit.record(request.user, f"Jeton API {token.name}", "Jeton créé", "", f"{token.prefix}… · {d['user'].username} · {'lecture' if token.read_only else 'lecture/écriture'}")
        return Response({**token_row(token), "token": raw}, status=status.HTTP_201_CREATED)


class TokenRevokeView(AdminView):
    def post(self, request, pk):
        token = get_object_or_404(ApiToken, pk=pk, tenant=self.tenant)
        if token.revoked_at is None:
            token.revoked_at = timezone.now()
            token.save(update_fields=["revoked_at"])
            audit.record(request.user, f"Jeton API {token.name}", "Jeton révoqué", f"{token.prefix}…", "")
        return Response(token_row(token))


def secret_row(key, row):
    return {"key": key, **SECRET_CATALOG[key], "isSet": row is not None,
            "hint": f"••••{row.hint}" if row and row.hint else ("••••" if row else None),
            "updatedAt": row.updated_at if row else None}


class SecretListView(AdminView):
    def get(self, request):
        rows = {s.key: s for s in ServiceSecret.objects.filter(tenant=self.tenant)}
        return Response([secret_row(k, rows.get(k)) for k in SECRET_CATALOG])


class SecretDetailView(AdminView):
    def put(self, request, key):
        if key not in SECRET_CATALOG:
            raise ApiError("NOT_FOUND", "Secret inconnu.", status.HTTP_404_NOT_FOUND)
        serializer = SecretSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        value = serializer.validated_data["value"]
        kind = next((k for k, s in CHANNEL_SECRET.items() if s == key and k in ("teams", "slack")), None)
        if kind:
            try:
                notify.validate_webhook_url(kind, value)
            except notify.ChannelError as exc:
                raise ApiError("VALIDATION_ERROR", str(exc), details=[{"field": "value", "message": str(exc)}]) from exc
        row = ServiceSecret.objects.filter(tenant=self.tenant, key=key).first()
        existed = row is not None
        row = row or ServiceSecret(tenant=self.tenant, key=key)
        row.set_value(value)
        row.updated_by = request.user
        row.save()
        audit.record(request.user, f"Secret {SECRET_CATALOG[key]['label']}", "Secret remplacé" if existed else "Secret défini")
        return Response(secret_row(key, row))

    def delete(self, request, key):
        if key not in SECRET_CATALOG:
            raise ApiError("NOT_FOUND", "Secret inconnu.", status.HTTP_404_NOT_FOUND)
        deleted, _ = ServiceSecret.objects.filter(tenant=self.tenant, key=key).delete()
        if deleted:
            audit.record(request.user, f"Secret {SECRET_CATALOG[key]['label']}", "Secret supprimé")
        return Response(secret_row(key, None))


# --------------------------------------------------------------------- notifications
def notifications_state(tenant):
    channels = {c.kind: c for c in NotificationChannel.objects.filter(tenant=tenant)}
    secrets_set = set(ServiceSecret.objects.filter(tenant=tenant).values_list("key", flat=True))
    rules = {}
    for r in NotificationRule.objects.filter(tenant=tenant):
        rules.setdefault(r.event, {})[r.channel] = r.enabled
    return {
        "channels": [{
            "kind": kind, "label": label, "enabled": channels[kind].enabled if kind in channels else False,
            "settings": channels[kind].settings if kind in channels else {},
            "secret": ({"key": CHANNEL_SECRET[kind], "isSet": CHANNEL_SECRET[kind] in secrets_set} if kind in CHANNEL_SECRET else None),
        } for kind, label in CHANNELS],
        "events": [{"code": c, "label": l} for c, l in EVENTS],
        # Sans règle enregistrée : valeur par défaut du socle (application oui ; e-mail pour les événements importants).
        "rules": {code: {kind: rules.get(code, {}).get(kind, _rule_default(code, kind)) for kind, _ in CHANNELS} for code, _ in EVENTS},
    }


def _rule_default(event, kind):
    from .mailer import DEFAULT_EMAIL_EVENTS, SOCLE_EVENTS
    if kind == "email":
        return event in DEFAULT_EMAIL_EVENTS
    if kind == "inapp":
        return event in SOCLE_EVENTS
    return False


class NotificationSettingsView(AdminView):
    def get(self, request):
        return Response(notifications_state(self.tenant))


class ChannelView(AdminView):
    def put(self, request, kind):
        if kind not in dict(CHANNELS):
            raise ApiError("NOT_FOUND", "Canal inconnu.", status.HTTP_404_NOT_FOUND)
        serializer = ChannelSerializer(data=request.data, context={"kind": kind})
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        if d["enabled"] and kind in ("teams", "slack") and not ServiceSecret.objects.filter(tenant=self.tenant, key=CHANNEL_SECRET[kind]).exists():
            raise ApiError("VALIDATION_ERROR", "Renseignez l'URL du webhook avant d'activer ce canal.")
        channel, _ = NotificationChannel.objects.get_or_create(tenant=self.tenant, kind=kind)
        before = (channel.enabled, channel.settings)
        channel.enabled, channel.settings = d["enabled"], d["settings"]
        channel.save()
        if before[0] != channel.enabled:
            audit.record(request.user, f"Canal {dict(CHANNELS)[kind]}", "Canal activé" if channel.enabled else "Canal désactivé")
        if before[1] != channel.settings:
            audit.record(request.user, f"Canal {dict(CHANNELS)[kind]}", "Paramètres du canal modifiés")
        return Response(notifications_state(self.tenant))


class RulesView(AdminView):
    def put(self, request):
        serializer = RulesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        events, kinds = dict(EVENTS), dict(CHANNELS)
        changes = []
        with transaction.atomic():
            for event, per_channel in serializer.validated_data["rules"].items():
                if event not in events or set(per_channel) - set(kinds):
                    raise ApiError("VALIDATION_ERROR", "Événement ou canal inconnu.", details=[event])
                for kind, enabled in per_channel.items():
                    rule, _ = NotificationRule.objects.get_or_create(tenant=self.tenant, event=event, channel=kind)
                    if rule.enabled != enabled:
                        rule.enabled = enabled
                        rule.save(update_fields=["enabled"])
                        changes.append(f"{events[event]} · {kinds[kind]} : {'oui' if enabled else 'non'}")
        if changes:
            audit.record(request.user, "Règles de notification", "Règles modifiées", "", " ; ".join(changes))
        return Response(notifications_state(self.tenant))


class ChannelTestView(AdminView):
    def post(self, request, kind):
        if kind not in ("email", "teams", "slack"):
            raise ApiError("VALIDATION_ERROR", "Ce canal ne s'envoie pas vers l'extérieur.")
        channel = NotificationChannel.objects.filter(tenant=self.tenant, kind=kind).first()
        if channel is None or (kind == "email" and not channel.settings.get("host")):
            raise ApiError("VALIDATION_ERROR", "Enregistrez d'abord les paramètres du canal.")
        serializer = ChannelTestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        text = "Message de test envoyé depuis le module Configuration de Project Control Tower."
        try:
            if kind == "email":
                to = serializer.validated_data.get("to") or request.user.email
                if not to:
                    raise notify.ChannelError("Indiquez une adresse de destination.")
                notify.send_email(channel, [to], "Test de notification", text)
            else:
                notify.send_webhook(self.tenant, kind, text)
        except notify.ChannelError as exc:
            audit.record(request.user, f"Canal {dict(CHANNELS)[kind]}", "Test d'envoi", "", "échec")
            raise ApiError("CHANNEL_TEST_FAILED", str(exc), status.HTTP_502_BAD_GATEWAY) from exc
        audit.record(request.user, f"Canal {dict(CHANNELS)[kind]}", "Test d'envoi", "", "réussi")
        return Response({"sent": True})


class MyNotificationsView(APIView):
    """Notifications « dans l'application » de l'utilisateur connecté."""

    def get(self, request):
        items = Notification.objects.filter(user=request.user)[:50]
        return Response([{"id": n.id, "event": n.event, "title": n.title, "body": n.body, "createdAt": n.created_at,
                          "read": n.read_at is not None} for n in items])

    def post(self, request):
        Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
        return Response(status=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------- audit et santé
class AuditView(AdminView):
    def get(self, request):
        limit = int_param(request, "limit", 200, 1, 1000)
        rows = AuditEvent.objects.filter(tenant=self.tenant).select_related("actor")[:limit]
        return Response([{"at": r.at, "actor": r.actor.username if r.actor else None, "entity": r.entity, "event": r.event,
                          "old": r.old_value, "new": r.new_value, "trace": r.trace} for r in rows])


class HealthView(APIView):
    """Contrôle public de disponibilité : aucun détail technique."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
            return Response({"status": "ok"})
        except Exception:
            return Response({"status": "unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


# --------------------------------------------------------------------- délégation des droits d'administration (phase 3)
class CapabilityMatrixView(AdminView):
    """Droits d'administration par rôle, dans le tenant. Le rôle Administrateur garde tous les droits (non modifiable)."""

    def get(self, request):
        from accounts.capabilities import CATALOG, NOT_DELEGABLE, RoleCapability
        granted = {}
        for rc in RoleCapability.objects.filter(tenant=self.tenant):
            granted.setdefault(rc.role_id, set()).add(rc.code)
        roles = Role.objects.filter(Q(tenant__isnull=True) | Q(tenant=self.tenant)).exclude(code=PLATFORM_ROLE).order_by("position", "label")
        return Response({
            "catalog": [{"code": c, "domain": d, "action": a, "delegable": c not in NOT_DELEGABLE} for c, d, a in CATALOG],
            "roles": [{"code": r.code, "label": r.label, "locked": r.code == "admin",
                       "capabilities": sorted(c for c, _, _ in CATALOG) if r.code == "admin" else sorted(granted.get(r.code, set()))}
                      for r in roles],
        })

    def put(self, request):
        from accounts.capabilities import CODES, NOT_DELEGABLE, RoleCapability
        from licensing import services as licensing
        wanted = request.data.get("roles")
        if not isinstance(wanted, dict):
            raise ApiError("VALIDATION_ERROR", "Format attendu : {\"roles\": {code_du_rôle: [droits]}}.")
        if "admin" in wanted or PLATFORM_ROLE in wanted:
            raise ApiError("VALIDATION_ERROR", "Les droits de l'administrateur et du Pilote ne se modifient pas.")
        roles = set(Role.objects.filter(Q(tenant__isnull=True) | Q(tenant=self.tenant)).exclude(code__in=["admin", PLATFORM_ROLE]).values_list("code", flat=True))
        for role, codes in wanted.items():
            if role not in roles or not isinstance(codes, list) or set(codes) - CODES:
                raise ApiError("VALIDATION_ERROR", "Rôle ou droit inconnu.", details=[role])
            if set(codes) & NOT_DELEGABLE:
                raise ApiError("VALIDATION_ERROR", "Le droit « Rôles et permissions · Administrer » reste réservé à l'administrateur.")
        if any(wanted.values()) and not licensing.module_enabled(self.tenant, "delegation"):
            raise ApiError("FEATURE_NOT_IN_OFFER", "La délégation des droits n'est pas comprise dans l'offre souscrite.")
        with transaction.atomic():
            for role, codes in wanted.items():
                before = set(RoleCapability.objects.filter(tenant=self.tenant, role_id=role).values_list("code", flat=True))
                RoleCapability.objects.filter(tenant=self.tenant, role_id=role).exclude(code__in=codes).delete()
                for code in set(codes) - before:
                    RoleCapability.objects.create(tenant=self.tenant, role_id=role, code=code)
                if before != set(codes):
                    audit.record(request.user, f"Rôle {role}", "Droits d'administration délégués",
                                 ", ".join(sorted(before)) or "aucun", ", ".join(sorted(codes)) or "aucun")
        return self.get(request)


class UserCapabilityView(AdminView):
    """Exceptions individuelles : accorder ou retirer un droit d'administration à un utilisateur précis."""

    def get(self, request, pk):
        from accounts.capabilities import capabilities_of
        user = self.get_user(pk)
        return Response({"overrides": [{"code": o.code, "granted": o.granted} for o in user.capability_overrides.filter(tenant=self.tenant)],
                         "effective": capabilities_of(user)})

    def put(self, request, pk):
        from accounts.capabilities import CODES, NOT_DELEGABLE, UserCapability
        from licensing import services as licensing
        user = self.get_user(pk)
        if user.pk == request.user.pk:
            raise ApiError("VALIDATION_ERROR", "Vous ne pouvez pas modifier vos propres droits.")
        items = request.data.get("overrides")
        if not isinstance(items, list) or any(not isinstance(i, dict) or i.get("code") not in CODES or
                                              not isinstance(i.get("granted"), bool) for i in items):
            raise ApiError("VALIDATION_ERROR", "Format attendu : {\"overrides\": [{\"code\", \"granted\"}]}.")
        if any(i["granted"] and i["code"] in NOT_DELEGABLE for i in items):
            raise ApiError("VALIDATION_ERROR", "Le droit « Rôles et permissions · Administrer » reste réservé à l'administrateur.")
        if any(i["granted"] for i in items) and not licensing.module_enabled(self.tenant, "delegation"):
            raise ApiError("FEATURE_NOT_IN_OFFER", "La délégation des droits n'est pas comprise dans l'offre souscrite.")
        with transaction.atomic():
            before = {o.code: o.granted for o in user.capability_overrides.filter(tenant=self.tenant)}
            user.capability_overrides.filter(tenant=self.tenant).delete()
            for i in items:
                UserCapability.objects.create(tenant=self.tenant, user=user, code=i["code"], granted=i["granted"], granted_by=request.user)
            after = {i["code"]: i["granted"] for i in items}
            if before != after:
                fmt = lambda d: ", ".join(f"{'+' if g else '−'}{c}" for c, g in sorted(d.items())) or "aucune"
                audit.record(request.user, user_label(user), "Exceptions de droits modifiées", fmt(before), fmt(after))
        return self.get(request, pk)


# --------------------------------------------------------------------- maintenance planifiée (Vercel Cron)
class CronMaintenanceView(APIView):
    """Appelée par le planificateur (Vercel Cron) : sessions inactives, abonnements échus, purge des journaux.

    Protégée par le jeton partagé CRON_SECRET (en-tête « Authorization: Bearer … ») ; sans ce réglage, la route
    répond 404. Idempotente, sans paramètre, ne supprime que des journaux plus anciens que leur durée de conservation.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        import hmac
        from io import StringIO

        from django.conf import settings
        from django.core.management import call_command
        from django.http import Http404

        expected = settings.CRON_SECRET
        given = request.headers.get("Authorization", "")
        if not expected:
            raise Http404()
        if not hmac.compare_digest(given.encode(), f"Bearer {expected}".encode()):
            raise ApiError("UNAUTHENTICATED", "Jeton de planification invalide.", status.HTTP_401_UNAUTHORIZED)
        out = StringIO()
        call_command("expire_licenses", stdout=out)
        call_command("purge_logs", stdout=out)
        call_command("process_calendar", stdout=out)
        call_command("sync_teams", stdout=out)
        call_command("process_methodology", stdout=out)
        call_command("remind_timesheets", stdout=out)
        call_command("send_notifications", stdout=out)
        call_command("generate_cra", stdout=out)
        return Response({"done": True, "report": out.getvalue().strip().splitlines()})
