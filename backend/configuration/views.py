"""API du module Configuration (réservée aux administrateurs) et notifications de l'utilisateur."""
import time
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404
from django.urls import URLPattern, URLResolver, get_resolver
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import MODULES, VERBS, Role, RolePermission
from accounts.models import PLATFORM_ROLE
from accounts.permissions import IsAppAdmin, IsPlatformAdmin, LicenseIsValid, PasswordChangeNotRequired, TenantIsActive
from accounts.serializers import permissions_of
from config.errors import ApiError
from projects.models import Action, ActionAccess, Project, ProjectAccess

from . import audit, notify
from .models import (CHANNEL_SECRET, CHANNELS, EVENTS, SECRET_CATALOG, ApiRequestLog, ApiToken, AuditEvent,
                     Notification, NotificationChannel, NotificationRule, ServiceSecret)
from .serializers import (AccessSerializer, AdminUserSerializer, ChannelSerializer, ChannelTestSerializer,
                          PermissionsSerializer, RulesSerializer, SecretSerializer, TokenCreateSerializer,
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


class AdminProjectsView(AdminView):
    """Tous les projets et leurs tâches, pour choisir les accès à affecter."""

    def get(self, request):
        projects = Project.objects.filter(tenant=self.tenant).select_related("client").prefetch_related("actions")
        return Response([{
            "id": p.id, "code": p.code, "name": p.name, "client": {"code": p.client_id, "name": p.client.name},
            "actions": [{"id": a.id, "title": a.title, "status": a.status} for a in p.actions.all()],
        } for p in projects])


class RoleListView(AdminView):
    def get(self, request):
        roles = Role.objects.exclude(code=PLATFORM_ROLE).annotate(userCount=Count(
            "users", filter=Q(users__is_active=True, users__tenant=self.tenant))).order_by("position")
        return Response({
            "modules": [{"code": c, "label": l} for c, l in MODULES],
            "verbs": [{"code": c, "label": l} for c, l in VERBS],
            "roles": [{"code": r.code, "label": r.label, "internal": r.internal, "money": r.money, "margin": r.margin,
                       "userCount": r.userCount, "permissions": permissions_of(r.code, self.tenant)} for r in roles],
        })


class RolePermissionsView(AdminView):
    def put(self, request, code):
        role = get_object_or_404(Role.objects.exclude(code=PLATFORM_ROLE), pk=code)
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
        "rules": {code: {kind: rules.get(code, {}).get(kind, False) for kind, _ in CHANNELS} for code, _ in EVENTS},
    }


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
        roles = Role.objects.exclude(code=PLATFORM_ROLE).order_by("position")
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
        roles = set(Role.objects.exclude(code__in=["admin", PLATFORM_ROLE]).values_list("code", flat=True))
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
        return Response({"done": True, "report": out.getvalue().strip().splitlines()})
