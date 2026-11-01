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
from accounts.permissions import IsAppAdmin, PasswordChangeNotRequired
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
ADMIN = [permissions.IsAuthenticated, PasswordChangeNotRequired, IsAppAdmin]


class AdminView(APIView):
    permission_classes = ADMIN


def int_param(request, name, default, low, high):
    try:
        value = int(request.query_params.get(name, default))
    except (TypeError, ValueError):
        raise ApiError("VALIDATION_ERROR", f"Le paramètre {name} doit être un nombre.")
    return min(max(value, low), high)


def user_label(u):
    return f"Utilisateur {u.username}"


# --------------------------------------------------------------------- utilisateurs et droits
class UserListView(AdminView):
    def get(self, request):
        users = User.objects.select_related("role", "client").order_by("username")
        return Response(AdminUserSerializer(users, many=True, context={"request": request}).data)

    def post(self, request):
        serializer = AdminUserSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        audit.record(request.user, user_label(user), "Compte créé", "", f"rôle {user.role_id}")
        data = dict(serializer.data)
        data["temporaryPassword"] = user._temporary_password  # affiché une seule fois
        return Response(data, status=status.HTTP_201_CREATED)


class UserDetailView(AdminView):
    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        return Response(AdminUserSerializer(user, context={"request": request}).data)

    def patch(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        before = {"role": user.role_id, "is_active": user.is_active}
        serializer = AdminUserSerializer(user, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        if before["role"] != user.role_id:
            audit.record(request.user, user_label(user), "Rôle modifié", before["role"], user.role_id)
        if before["is_active"] != user.is_active:
            audit.record(request.user, user_label(user), "Compte réactivé" if user.is_active else "Compte désactivé")
        if set(request.data) - {"role", "isActive"}:
            audit.record(request.user, user_label(user), "Profil modifié")
        return Response(serializer.data)


class UserResetPasswordView(AdminView):
    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        password = temporary_password()
        user.set_password(password)  # invalide aussi les sessions ouvertes de ce compte
        user.must_change_password = True
        user.save(update_fields=["password", "must_change_password"])
        audit.record(request.user, user_label(user), "Mot de passe réinitialisé")
        return Response({"temporaryPassword": password})


class UserAccessView(AdminView):
    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        return Response({
            "projects": [{"project": a.project_id, "canEdit": a.can_edit} for a in user.project_accesses.all()],
            "actions": [{"action": a.action_id, "canEdit": a.can_edit} for a in user.action_accesses.all()],
        })

    def put(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        serializer = AccessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        wanted_p = {i["project"]: i["canEdit"] for i in serializer.validated_data["projects"]}
        wanted_a = {i["action"]: i["canEdit"] for i in serializer.validated_data["actions"]}
        unknown = (set(wanted_p) - set(Project.objects.filter(pk__in=wanted_p).values_list("pk", flat=True))) | (
            set(wanted_a) - set(Action.objects.filter(pk__in=wanted_a).values_list("pk", flat=True)))
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
        projects = Project.objects.select_related("client").prefetch_related("actions")
        return Response([{
            "id": p.id, "code": p.code, "name": p.name, "client": {"code": p.client_id, "name": p.client.name},
            "actions": [{"id": a.id, "title": a.title, "status": a.status} for a in p.actions.all()],
        } for p in projects])


class RoleListView(AdminView):
    def get(self, request):
        roles = Role.objects.annotate(userCount=Count("users", filter=Q(users__is_active=True))).order_by("position")
        return Response({
            "modules": [{"code": c, "label": l} for c, l in MODULES],
            "verbs": [{"code": c, "label": l} for c, l in VERBS],
            "roles": [{"code": r.code, "label": r.label, "internal": r.internal, "money": r.money, "margin": r.margin,
                       "userCount": r.userCount, "permissions": permissions_of(r.code)} for r in roles],
        })


class RolePermissionsView(AdminView):
    def put(self, request, code):
        role = get_object_or_404(Role, pk=code)
        serializer = PermissionsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        wanted = serializer.validated_data["permissions"]
        modules = {c for c, _ in MODULES}
        if set(wanted) - modules:
            raise ApiError("VALIDATION_ERROR", "Module inconnu.", details=sorted(set(wanted) - modules))
        before = permissions_of(code)
        with transaction.atomic():
            for module, flags in wanted.items():
                RolePermission.objects.update_or_create(role=role, module=module, defaults={
                    f"can_{v}": flags[i] for i, (v, _) in enumerate(VERBS)})
        for module, flags in wanted.items():
            if before.get(module) != flags:
                diff = lambda f: "".join("1" if x else "0" for x in f)
                audit.record(request.user, f"Rôle {role.label}", f"Droits « {dict(MODULES)[module]} »", diff(before.get(module, [False] * 5)), diff(flags))
        return Response({"code": code, "permissions": permissions_of(code)})


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


class DatabaseView(AdminView):
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


class DatabaseTestView(AdminView):
    def post(self, request):
        result = database_status()
        audit.record(request.user, "Base de données", "Test de connexion", "", "réussi" if result["connected"] else "échec")
        return Response(result, status=status.HTTP_200_OK if result["connected"] else status.HTTP_503_SERVICE_UNAVAILABLE)


# --------------------------------------------------------------------- API : état, journal, jetons, secrets
def _access_of(callback):
    cls = getattr(callback, "cls", None)
    perms = getattr(cls, "permission_classes", []) if cls else []
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
    def get(self, request):
        # Seule la version courante est listée : l'ancien chemin /api/ sans version en est un alias exact.
        return Response([e for e in _walk(get_resolver().url_patterns) if e["path"].startswith("/api/v1/")])


class ApiStatsView(AdminView):
    def get(self, request):
        hours = int_param(request, "hours", 24, 1, 24 * 30)
        logs = ApiRequestLog.objects.filter(at__gte=timezone.now() - timedelta(hours=hours))
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
        logs = ApiRequestLog.objects.select_related("user", "token")
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
        return Response([token_row(t) for t in ApiToken.objects.select_related("user")])

    def post(self, request):
        serializer = TokenCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        expires = timezone.now() + timedelta(days=d["expiresInDays"]) if d.get("expiresInDays") else None
        token, raw = ApiToken.issue(name=d["name"], user=d["user"], read_only=d["readOnly"], created_by=request.user, expires_at=expires)
        audit.record(request.user, f"Jeton API {token.name}", "Jeton créé", "", f"{token.prefix}… · {d['user'].username} · {'lecture' if token.read_only else 'lecture/écriture'}")
        return Response({**token_row(token), "token": raw}, status=status.HTTP_201_CREATED)


class TokenRevokeView(AdminView):
    def post(self, request, pk):
        token = get_object_or_404(ApiToken, pk=pk)
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
        rows = {s.key: s for s in ServiceSecret.objects.all()}
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
        row = ServiceSecret.objects.filter(key=key).first()
        existed = row is not None
        row = row or ServiceSecret(key=key)
        row.set_value(value)
        row.updated_by = request.user
        row.save()
        audit.record(request.user, f"Secret {SECRET_CATALOG[key]['label']}", "Secret remplacé" if existed else "Secret défini")
        return Response(secret_row(key, row))

    def delete(self, request, key):
        if key not in SECRET_CATALOG:
            raise ApiError("NOT_FOUND", "Secret inconnu.", status.HTTP_404_NOT_FOUND)
        deleted, _ = ServiceSecret.objects.filter(key=key).delete()
        if deleted:
            audit.record(request.user, f"Secret {SECRET_CATALOG[key]['label']}", "Secret supprimé")
        return Response(secret_row(key, None))


# --------------------------------------------------------------------- notifications
def notifications_state():
    channels = {c.kind: c for c in NotificationChannel.objects.all()}
    secrets_set = set(ServiceSecret.objects.values_list("key", flat=True))
    rules = {}
    for r in NotificationRule.objects.all():
        rules.setdefault(r.event, {})[r.channel_id] = r.enabled
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
        return Response(notifications_state())


class ChannelView(AdminView):
    def put(self, request, kind):
        if kind not in dict(CHANNELS):
            raise ApiError("NOT_FOUND", "Canal inconnu.", status.HTTP_404_NOT_FOUND)
        serializer = ChannelSerializer(data=request.data, context={"kind": kind})
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        if d["enabled"] and kind in ("teams", "slack") and not ServiceSecret.objects.filter(key=CHANNEL_SECRET[kind]).exists():
            raise ApiError("VALIDATION_ERROR", "Renseignez l'URL du webhook avant d'activer ce canal.")
        channel, _ = NotificationChannel.objects.get_or_create(kind=kind)
        before = (channel.enabled, channel.settings)
        channel.enabled, channel.settings = d["enabled"], d["settings"]
        channel.save()
        if before[0] != channel.enabled:
            audit.record(request.user, f"Canal {dict(CHANNELS)[kind]}", "Canal activé" if channel.enabled else "Canal désactivé")
        if before[1] != channel.settings:
            audit.record(request.user, f"Canal {dict(CHANNELS)[kind]}", "Paramètres du canal modifiés")
        return Response(notifications_state())


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
                    channel, _ = NotificationChannel.objects.get_or_create(kind=kind)
                    rule, _ = NotificationRule.objects.get_or_create(event=event, channel=channel)
                    if rule.enabled != enabled:
                        rule.enabled = enabled
                        rule.save(update_fields=["enabled"])
                        changes.append(f"{events[event]} · {kinds[kind]} : {'oui' if enabled else 'non'}")
        if changes:
            audit.record(request.user, "Règles de notification", "Règles modifiées", "", " ; ".join(changes))
        return Response(notifications_state())


class ChannelTestView(AdminView):
    def post(self, request, kind):
        if kind not in ("email", "teams", "slack"):
            raise ApiError("VALIDATION_ERROR", "Ce canal ne s'envoie pas vers l'extérieur.")
        channel = NotificationChannel.objects.filter(kind=kind).first()
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
                notify.send_webhook(kind, text)
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
        rows = AuditEvent.objects.select_related("actor")[:limit]
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
