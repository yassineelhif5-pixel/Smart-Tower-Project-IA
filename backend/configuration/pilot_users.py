"""Le Pilote gère les utilisateurs de n'importe quelle entreprise, comme son administrateur :
création, modification (rôle, client, activation), réinitialisation du mot de passe et affectation aux
projets d'un client. Le rattachement au client se fait par le champ client (comptes externes) et/ou
par l'affectation à tous les projets du client (comptes internes ou externes)."""
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsPlatformAdmin, PasswordChangeNotRequired
from config.errors import ApiError
from projects.models import Client, Project, ProjectAccess
from tenants.models import Tenant

from . import audit
from .serializers import AdminUserSerializer
from .views import quota_guard, release_access, user_label

User = get_user_model()
PILOT = [permissions.IsAuthenticated, PasswordChangeNotRequired, IsPlatformAdmin]


def _assign_client_projects(by, user, client_code, tenant):
    """Affecte l'utilisateur à tous les projets du client (sans retirer ses autres affectations)."""
    client = get_object_or_404(Client, pk=client_code, tenant=tenant)
    n = 0
    for p in Project.objects.filter(client=client, tenant=tenant):
        _, created = ProjectAccess.objects.get_or_create(user=user, project=p, defaults={"tenant": tenant, "granted_by": by,
                                                                                          "can_edit": bool(user.role and user.role.internal)})
        n += int(created)
    audit.record(by, user_label(user), "Affecté aux projets du client (Pilote)", "", f"{client.name} : {n} projet(s)", tenant=tenant)
    return n


def _out(user, request, tenant):
    data = dict(AdminUserSerializer(user, context={"request": request, "tenant": tenant}).data)
    data["clientName"] = user.client.name if user.client_id else None
    data["projects"] = [{"id": a.project_id, "name": a.project.name, "client": a.project.client_id}
                        for a in user.project_accesses.select_related("project")]
    return data


class PilotTenantUsersView(APIView):
    """GET : utilisateurs, rôles et clients d'une entreprise. POST : crée un utilisateur (+ clientProjects)."""
    permission_classes = PILOT

    def get(self, request, tenant_id):
        from accounts.models import PLATFORM_ROLE, Role
        from django.db.models import Q
        tenant = get_object_or_404(Tenant, pk=tenant_id)
        users = User.objects.filter(tenant=tenant).select_related("role", "client").order_by("username")
        return Response({
            "tenant": {"id": tenant.id, "name": tenant.name},
            "users": [_out(u, request, tenant) for u in users],
            "roles": [{"code": r.code, "label": r.label, "internal": r.internal}
                      for r in Role.objects.filter(Q(tenant__isnull=True) | Q(tenant=tenant)).exclude(code=PLATFORM_ROLE).order_by("label")],
            "clients": [{"code": c.code, "name": c.name, "projects": c.projects.count()} for c in Client.objects.filter(tenant=tenant).order_by("name")],
        })

    def post(self, request, tenant_id):
        tenant = get_object_or_404(Tenant, pk=tenant_id)
        serializer = AdminUserSerializer(data=request.data, context={"request": request, "tenant": tenant})
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data.get("is_active", True):
            quota_guard(tenant)
        user = serializer.save(tenant=tenant)
        audit.record(request.user, user_label(user), "Compte créé par le Pilote", "", f"rôle {user.role_id}", tenant=tenant)
        n = 0
        target = request.data.get("clientProjects") or (user.client_id if request.data.get("assignClientProjects") else None)
        if target:
            n = _assign_client_projects(request.user, user, target, tenant)
        data = _out(user, request, tenant)
        data["temporaryPassword"] = user._temporary_password
        data["assigned"] = n
        return Response(data, status=status.HTTP_201_CREATED)


class PilotTenantUserDetailView(APIView):
    """PATCH : rôle, client, activation… ; POST {action: reset-password | assign-client, client}."""
    permission_classes = PILOT

    def get(self, request, tenant_id, pk):
        """Détail d'un compte : identité, profil, client, connexion, licence, SSO, projets et dernières actions."""
        from django.db.models import Count, Max, Q
        from configuration.models import AuditEvent
        from projects.models import Action, TimeEntry
        tenant = get_object_or_404(Tenant, pk=tenant_id)
        user = get_object_or_404(User.objects.select_related("role", "client"), pk=pk, tenant=tenant)
        lic = user.license_assignments.select_related("license").filter(released_at__isnull=True).first()
        try:
            sso = user.sso_identity
        except Exception:
            sso = None
        accesses = list(user.project_accesses.select_related("project", "project__client").order_by("project__name"))
        hours = dict(TimeEntry.objects.filter(person=user).values_list("project_id").annotate(h=Count("id")))
        tasks = dict(Action.objects.filter(owner=user).values_list("project_id").annotate(n=Count("id", filter=~Q(status="done"))))
        times = TimeEntry.objects.filter(person=user).aggregate(last=Max("work_date"), n=Count("id"))
        events = AuditEvent.objects.filter(Q(actor=user) | Q(entity=user_label(user))).order_by("-at")[:25]
        data = _out(user, request, tenant)
        data.update({
            "displayName": user.display_name, "roleLabel": user.role.label if user.role else "", "internal": bool(user.role and user.role.internal),
            "dateJoined": user.date_joined, "title": user.title, "team": user.team,
            "license": {"kind": lic.license.get_kind_display() if hasattr(lic.license, "get_kind_display") else "", "since": lic.assigned_at} if lic else None,
            "sso": {"email": sso.email, "since": sso.created_at, "issuer": sso.issuer} if sso else None,
            "projects": [{"id": a.project_id, "name": a.project.name, "client": a.project.client.name if a.project.client_id else "",
                          "canEdit": a.can_edit, "dailyRate": a.daily_rate, "since": a.granted_at,
                          "isPm": a.project.pm_id == user.id, "openTasks": tasks.get(a.project_id, 0), "entries": hours.get(a.project_id, 0)}
                         for a in accesses],
            "timesheet": {"entries": times["n"], "lastDate": times["last"]},
            "allProjects": [{"id": p.id, "code": p.code, "name": p.name, "client": p.client.name if p.client_id else ""}
                            for p in Project.objects.filter(tenant=tenant).select_related("client").order_by("client__name", "name")],
            "activity": [{"at": e.at, "event": e.event, "entity": e.entity, "by": e.actor.username if e.actor_id else "système",
                          "result": e.result} for e in events],
        })
        return Response(data)

    def patch(self, request, tenant_id, pk):
        tenant = get_object_or_404(Tenant, pk=tenant_id)
        user = get_object_or_404(User, pk=pk, tenant=tenant)
        before = {"role": user.role_id, "is_active": user.is_active, "client": user.client_id}
        serializer = AdminUserSerializer(user, data=request.data, partial=True, context={"request": request, "tenant": tenant})
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data.get("is_active") and not before["is_active"]:
            quota_guard(tenant)
        serializer.save()
        if before["is_active"] and not user.is_active:
            release_access(request.user, user)
        audit.record(request.user, user_label(user), "Compte modifié par le Pilote", str(before),
                     str({"role": user.role_id, "is_active": user.is_active, "client": user.client_id}), tenant=tenant)
        return Response(_out(user, request, tenant))

    def post(self, request, tenant_id, pk):
        from .serializers import temporary_password
        tenant = get_object_or_404(Tenant, pk=tenant_id)
        user = get_object_or_404(User, pk=pk, tenant=tenant)
        action = request.data.get("action")
        if action == "reset-password":
            pwd = temporary_password()
            user.set_password(pwd)
            user.must_change_password = True
            user.save(update_fields=["password", "must_change_password"])
            audit.record(request.user, user_label(user), "Mot de passe réinitialisé par le Pilote", tenant=tenant)
            return Response({"temporaryPassword": pwd})
        if action == "assign-client":
            n = _assign_client_projects(request.user, user, request.data.get("client"), tenant)
            out = _out(user, request, tenant)
            out["assigned"] = n
            return Response(out)
        raise ApiError("VALIDATION_ERROR", "Action inconnue.")


class PilotClientsView(APIView):
    """Liste des clients de toutes les entreprises (sélecteurs du Pilote)."""
    permission_classes = PILOT

    def get(self, request):
        return Response([{"code": c.code, "name": c.name, "tenant": c.tenant_id}
                         for c in Client.objects.order_by("tenant_id", "name")])


class PilotUserProjectsView(APIView):
    """PUT {projects: [{project, canEdit}]} : projets affectés à l'utilisateur (remplace la liste ; les tâches
    individuelles ne changent pas). Même règle que l'administrateur de l'entreprise."""
    permission_classes = PILOT

    def put(self, request, tenant_id, pk):
        from django.db import transaction
        from . import notify
        tenant = get_object_or_404(Tenant, pk=tenant_id)
        user = get_object_or_404(User, pk=pk, tenant=tenant)
        items = request.data.get("projects")
        if not isinstance(items, list):
            raise ApiError("VALIDATION_ERROR", "Liste de projets attendue.")
        wanted = {str(i.get("project")): bool(i.get("canEdit", True)) for i in items if isinstance(i, dict) and i.get("project")}
        known = set(Project.objects.filter(tenant=tenant, pk__in=wanted).values_list("pk", flat=True))
        if set(wanted) - known:
            raise ApiError("NOT_FOUND", "Projet introuvable dans cette entreprise.", status.HTTP_404_NOT_FOUND, sorted(set(wanted) - known))
        before = {a.project_id: a.can_edit for a in user.project_accesses.all()}
        with transaction.atomic():
            user.project_accesses.exclude(project_id__in=wanted).delete()
            for pid, edit in wanted.items():
                ProjectAccess.objects.update_or_create(user=user, project_id=pid, defaults={"tenant": tenant, "can_edit": edit, "granted_by": request.user})
        if before != wanted:
            fmt = lambda d: ", ".join(f"{k}{' (écriture)' if v else ''}" for k, v in sorted(d.items())) or "aucun"
            audit.record(request.user, user_label(user), "Projets affectés par le Pilote", fmt(before), fmt(wanted), tenant=tenant)
            try:
                notify.notify("scope_changed", [user], "Votre périmètre a changé", f"Projets : {fmt(wanted)}.")
            except Exception:
                pass
        return PilotTenantUserDetailView().get(request, tenant_id, pk)
