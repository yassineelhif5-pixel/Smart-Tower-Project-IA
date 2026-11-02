"""API Collaboration (/api/v1/discussions…, /api/v1/teams/…, /api/v1/admin/teams, /api/v1/me/notification-preferences)."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAppAdmin, has_perm
from config.errors import ApiError
from configuration import audit
from configuration.models import CHANNELS, EVENTS, NotificationRule, ServiceSecret, UserNotificationPreference
from projects.access import in_active_tenant

from . import graph
from . import services as S
from .models import DiscussionMessage, TeamsConnector

User = get_user_model()


def fail(exc):
    return ApiError(exc.code, exc.message, exc.http_status, exc.details)


def require(user, verb="read"):
    if not in_active_tenant(user) or not has_perm(user, "collaboration", verb):
        raise ApiError("FORBIDDEN_PERMISSION", "La collaboration n'est pas accessible avec vos droits.", status.HTTP_403_FORBIDDEN)


def person(u):
    return {"id": u.pk, "username": u.username, "name": u.display_name} if u else None


def message_row(m, user):
    deleted = m.deleted_at is not None
    return {
        "id": m.pk, "kind": m.kind, "author": person(m.author), "externalAuthor": m.external_author,
        "body": "" if deleted else m.body, "deleted": deleted, "parent": m.parent_id, "origin": m.origin,
        "publicationStatus": m.publication_status, "publicationError": m.publication_error,
        "mentions": [person(u) for u in m.mentions.all()],
        "attachments": [{"id": d.pk, "name": d.name, "ext": d.ext} for d in m.attachments.all()],
        "createdAt": m.created_at, "editedAt": m.edited_at, "deletedAt": m.deleted_at,
        "historyCount": len(m.history or []),
        "mine": m.author_id == user.pk,
        "canEdit": m.author_id == user.pk and m.origin == "pct" and m.kind == "message" and not deleted,
        "canRetry": m.author_id == user.pk and m.publication_status == "failed",
    }


def discussion_row(d, user, with_counts=True):
    row = {
        "id": d.pk, "title": d.title, "project": {"id": d.project_id, "code": d.project.code, "name": d.project.name},
        "action": {"id": d.action_id, "title": d.action.title} if d.action_id else None,
        "destination": d.destination, "destinationLabel": d.get_destination_display(),
        "teamsKind": d.teams_kind, "teamsKindLabel": d.get_teams_kind_display(), "teamsUrl": d.teams_web_url,
        "status": d.status, "lastError": d.last_error, "createdBy": person(d.created_by), "createdAt": d.created_at,
        "lastMessageAt": d.last_message_at, "lastSyncedAt": d.last_synced_at, "private": d.is_private,
        "participants": [{**person(p.user), "role": p.role} for p in d.participants.select_related("user")],
        "canPost": S.can_post(user, d),
    }
    if with_counts:
        row["messageCount"] = d.messages.filter(deleted_at__isnull=True, kind="message").count()
        row["failedCount"] = d.messages.filter(publication_status="failed", author=user).count()
    return row


class DiscussionListView(APIView):
    def get(self, request):
        require(request.user)
        qs = S.visible_discussions(request.user).select_related("project", "action", "created_by")
        p = request.query_params
        if p.get("project"):
            qs = qs.filter(project_id=p["project"])
        if p.get("action"):
            qs = qs.filter(action_id=p["action"])
        if p.get("destination"):
            qs = qs.filter(destination=p["destination"])
        if p.get("mine") == "1":
            qs = qs.filter(participants__user=request.user)
        if p.get("q"):
            qs = qs.filter(title__icontains=p["q"])
        return Response([discussion_row(d, request.user) for d in qs[:200]])

    def post(self, request):
        require(request.user, "create")
        try:
            d = S.create_discussion(request.user, request.data)
        except S.CollabError as exc:
            raise fail(exc) from exc
        return Response(discussion_row(d, request.user), status=status.HTTP_201_CREATED)


class DiscussionDetailView(APIView):
    def get_discussion(self, request, pk):
        require(request.user)
        return get_object_or_404(S.visible_discussions(request.user).select_related("project", "action", "created_by"), pk=pk)

    def get(self, request, pk):
        d = self.get_discussion(request, pk)
        d.participants.filter(user=request.user).update(last_read_at=timezone.now())
        return Response(discussion_row(d, request.user))

    def patch(self, request, pk):
        d = self.get_discussion(request, pk)
        if d.created_by_id != request.user.pk and not has_perm(request.user, "collaboration", "approve"):
            raise ApiError("FORBIDDEN_PERMISSION", "Seul le créateur peut modifier la discussion.", status.HTTP_403_FORBIDDEN)
        if "title" in request.data:
            d.title = str(request.data["title"]).strip()[:200] or d.title
        if request.data.get("status") in ("active", "archived"):
            d.status = request.data["status"]
        d.save()
        audit.record(request.user, f"Projet {d.project.code}", "Discussion modifiée", "", f"{d.title} ({d.status})")
        return Response(discussion_row(d, request.user))


class MessageListView(APIView):
    def get(self, request, pk):
        require(request.user)
        d = get_object_or_404(S.visible_discussions(request.user), pk=pk)
        qs = d.messages.select_related("author").prefetch_related("mentions", "attachments")
        if request.query_params.get("before"):
            qs = qs.filter(pk__lt=request.query_params["before"])
        rows = list(qs.order_by("-id")[:100])[::-1]
        return Response([message_row(m, request.user) for m in rows])

    def post(self, request, pk):
        require(request.user, "create")
        d = get_object_or_404(S.visible_discussions(request.user).select_related("project"), pk=pk)
        try:
            m = S.post_message(request.user, d, request.data)
        except S.CollabError as exc:
            raise fail(exc) from exc
        return Response(message_row(m, request.user), status=status.HTTP_201_CREATED)


class MessageDetailView(APIView):
    def get_message(self, request, pk):
        require(request.user)
        return get_object_or_404(DiscussionMessage.objects.select_related("discussion"),
                                 pk=pk, discussion__in=S.visible_discussions(request.user))

    def get(self, request, pk):
        m = self.get_message(request, pk)
        if m.author_id != request.user.pk:
            raise ApiError("FORBIDDEN_PERMISSION", "Historique visible de l'auteur uniquement.", status.HTTP_403_FORBIDDEN)
        return Response({**message_row(m, request.user), "history": m.history})

    def patch(self, request, pk):
        m = self.get_message(request, pk)
        try:
            m = S.edit_message(request.user, m, request.data.get("body"))
        except S.CollabError as exc:
            raise fail(exc) from exc
        return Response(message_row(m, request.user))

    def delete(self, request, pk):
        m = self.get_message(request, pk)
        try:
            S.delete_message(request.user, m)
        except S.CollabError as exc:
            raise fail(exc) from exc
        return Response(status=status.HTTP_204_NO_CONTENT)


class MessageRetryView(APIView):
    def post(self, request, pk):
        require(request.user, "create")
        m = get_object_or_404(DiscussionMessage.objects.select_related("discussion"), pk=pk,
                              discussion__in=S.visible_discussions(request.user))
        try:
            m = S.retry(request.user, m)
        except S.CollabError as exc:
            raise fail(exc) from exc
        return Response(message_row(m, request.user))


class DiscussionDocumentsView(APIView):
    """Documents du projet de la discussion que l'utilisateur peut voir (pièces jointes)."""

    def get(self, request, pk):
        require(request.user)
        from projects.access import visible
        from projects.models import Document
        d = get_object_or_404(S.visible_discussions(request.user), pk=pk)
        docs = visible(request.user, Document).filter(project=d.project).order_by("name")[:200]
        return Response([{"id": doc.pk, "name": doc.name, "ext": doc.ext, "status": doc.dstat} for doc in docs])


class SynchronizeView(APIView):
    def post(self, request, pk):
        require(request.user)
        d = get_object_or_404(S.visible_discussions(request.user), pk=pk)
        try:
            counts = S.synchronize(d, by=request.user)
        except S.CollabError as exc:
            raise fail(exc) from exc
        return Response(counts)


# --------------------------------------------------------------------------- compte Teams de l'utilisateur
class ConnectionStatusView(APIView):
    def get(self, request):
        require(request.user)
        return Response(S.connection_status(request.user))


class OAuthStartView(APIView):
    def post(self, request):
        require(request.user)
        if request.auth is not None:
            raise ApiError("FORBIDDEN_PERMISSION", "Session interactive requise.", status.HTTP_403_FORBIDDEN)
        try:
            return Response({"url": S.oauth_start(request)})
        except S.CollabError as exc:
            raise fail(exc) from exc


class OAuthCallbackView(APIView):
    """Retour de Microsoft (navigateur de l'utilisateur, session PCT). Redirige vers la page Collaboration."""

    def get(self, request):
        target = f"{S.public_base(request)}/#collaboration"
        if request.query_params.get("error"):
            request.session.pop("teams_oauth", None)
            return HttpResponseRedirect(f"{target}?teams=refused")
        try:
            require(request.user)
            S.oauth_callback(request, request.query_params.get("code", ""), request.query_params.get("state", ""))
        except (S.CollabError, ApiError) as exc:
            code = getattr(exc, "code", "error")
            return HttpResponseRedirect(f"{target}?teams=error&code={code}")
        return HttpResponseRedirect(f"{target}?teams=linked")


class UnlinkView(APIView):
    def post(self, request):
        require(request.user)
        S.unlink(request.user)
        return Response(S.connection_status(request.user))


class JoinedTeamsView(APIView):
    def get(self, request):
        require(request.user)
        try:
            client = S.client_for(request.user)
            if not client.connector.allow_channels:
                raise S.CollabError("TEAMS_CHANNELS_DISABLED", "La publication dans les canaux n'est pas activée.", 409)
            return Response([{"id": t["id"], "name": t.get("displayName", "")} for t in client.joined_teams()])
        except graph.GraphError as exc:
            raise fail(S.from_graph(exc)) from exc
        except S.CollabError as exc:
            raise fail(exc) from exc


class ChannelsView(APIView):
    def get(self, request, team_id):
        require(request.user)
        try:
            client = S.client_for(request.user)
            if not client.connector.allow_channels:
                raise S.CollabError("TEAMS_CHANNELS_DISABLED", "La publication dans les canaux n'est pas activée.", 409)
            return Response([{"id": c["id"], "name": c.get("displayName", ""), "membership": c.get("membershipType", "")}
                             for c in client.channels(team_id)])
        except graph.GraphError as exc:
            raise fail(S.from_graph(exc)) from exc
        except S.CollabError as exc:
            raise fail(exc) from exc

    def post(self, request, team_id):
        require(request.user, "approve")
        try:
            c = S.create_channel(request.user, team_id, request.data.get("name"), request.data.get("description", ""))
        except S.CollabError as exc:
            raise fail(exc) from exc
        return Response({"id": c.get("id"), "name": c.get("displayName")}, status=status.HTTP_201_CREATED)


# --------------------------------------------------------------------------- notifications Microsoft Graph
class _GraphHook(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    handler = None

    def post(self, request):
        token = request.query_params.get("validationToken")
        if token is not None:
            # Poignée de main de création d'abonnement : renvoyer le jeton tel quel, en texte brut, sous 10 s.
            return HttpResponse(token[:1024], content_type="text/plain", status=200)
        if not isinstance(request.data, dict):
            return Response(status=status.HTTP_202_ACCEPTED)
        type(self).handler(request.data)
        return Response(status=status.HTTP_202_ACCEPTED)


class WebhookView(_GraphHook):
    handler = staticmethod(S.handle_notifications)


class LifecycleView(_GraphHook):
    handler = staticmethod(S.handle_lifecycle)


# --------------------------------------------------------------------------- administration du connecteur
def connector_row(c, tenant):
    secret = ServiceSecret.objects.filter(tenant=tenant, key="teams_client_secret").first()
    return {
        "directoryId": c.directory_id if c else "", "clientId": c.client_id if c else "",
        "enabled": bool(c and c.enabled), "allowChannels": bool(c and c.allow_channels),
        "allowChannelCreation": bool(c and c.allow_channel_creation), "allowEditInTeams": bool(c and c.allow_edit_in_teams),
        "status": c.status if c else "not_configured", "lastCheckAt": c.last_check_at if c else None,
        "lastError": c.last_error if c else "", "secretExpiresOn": c.secret_expires_on if c else None,
        "secretSet": secret is not None, "secretHint": secret.hint if secret else "",
        "scopes": graph.scopes_for(c) if c else graph.BASE_SCOPES,
        "redirectUri": f"{settings.PUBLIC_BASE_URL or ''}/api/v1/teams/oauth/callback",
        "webhookUrl": f"{settings.PUBLIC_BASE_URL}/api/v1/teams/webhook" if settings.PUBLIC_BASE_URL else "",
        "linkedUsers": c.tenant.users.filter(microsoft_token__revoked_at__isnull=True, microsoft_token__isnull=False).count() if c else 0,
    }


GUID = __import__("re").compile(r"^[0-9a-fA-F-]{36}$|^[a-z0-9.-]+\.onmicrosoft\.com$")


class TeamsAdminView(APIView):
    permission_classes = [IsAppAdmin]

    def get(self, request):
        return Response(connector_row(S.connector_of(request.user.tenant), request.user.tenant))

    @transaction.atomic
    def put(self, request):
        tenant = request.user.tenant
        c = S.connector_of(tenant) or TeamsConnector(tenant=tenant)
        data = request.data
        for field, key in (("directory_id", "directoryId"), ("client_id", "clientId")):
            if key in data:
                value = str(data[key] or "").strip()
                if value and not GUID.match(value):
                    raise ApiError("VALIDATION_ERROR", "Identifiant Microsoft invalide (GUID attendu).",
                                   details=[{"field": key, "message": "GUID attendu"}])
                setattr(c, field, value)
        for field, key in (("enabled", "enabled"), ("allow_channels", "allowChannels"),
                           ("allow_channel_creation", "allowChannelCreation"), ("allow_edit_in_teams", "allowEditInTeams")):
            if key in data:
                setattr(c, field, bool(data[key]))
        if "secretExpiresOn" in data:
            from django.utils.dateparse import parse_date
            c.secret_expires_on = parse_date(str(data["secretExpiresOn"] or "")) if data["secretExpiresOn"] else None
        secret = str(data.get("clientSecret") or "")
        if secret:
            row = ServiceSecret.objects.filter(tenant=tenant, key="teams_client_secret").first() or \
                ServiceSecret(tenant=tenant, key="teams_client_secret")
            row.set_value(secret)
            row.updated_by = request.user
            row.save()
            audit.record(request.user, "Secret Secret client de l'application Microsoft", "Secret défini")
        if c.enabled and not (c.directory_id and c.client_id):
            raise ApiError("VALIDATION_ERROR", "Renseignez l'annuaire et l'identifiant client avant d'activer le connecteur.")
        c.status = "configured" if c.directory_id and c.client_id else "not_configured"
        c.updated_by = request.user
        c.save()
        audit.record(request.user, "Connecteur Microsoft Teams", "Configuration modifiée", "",
                     f"activé={c.enabled} canaux={c.allow_channels} création={c.allow_channel_creation}")
        return Response(connector_row(c, tenant))


class TeamsAdminCheckView(APIView):
    permission_classes = [IsAppAdmin]

    def post(self, request):
        c = S.connector_of(request.user.tenant)
        if c is None or not (c.directory_id and c.client_id):
            raise ApiError("TEAMS_NOT_CONFIGURED", "Renseignez d'abord le connecteur.", status.HTTP_409_CONFLICT)
        c.last_check_at = timezone.now()
        try:
            graph.check_app_credentials(c)
        except graph.GraphError as exc:
            c.status, c.last_error = "error", exc.message[:300]
            c.save(update_fields=["status", "last_error", "last_check_at"])
            return Response({"ok": False, "message": exc.message, **connector_row(c, request.user.tenant)})
        c.status, c.last_error = "ok", ""
        c.save(update_fields=["status", "last_error", "last_check_at"])
        audit.record(request.user, "Connecteur Microsoft Teams", "Connexion vérifiée")
        return Response({"ok": True, "message": "Application Microsoft reconnue.", **connector_row(c, request.user.tenant)})


# --------------------------------------------------------------------------- préférences de notification
class NotificationPreferencesView(APIView):
    """Préférences personnelles : restreignent les règles de l'entreprise, sans pouvoir activer un canal coupé."""

    def get(self, request):
        user = request.user
        if not in_active_tenant(user):
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé aux utilisateurs d'une entreprise.", status.HTTP_403_FORBIDDEN)
        rules = {(r.event, r.channel): r.enabled for r in NotificationRule.objects.filter(tenant=user.tenant)}
        from configuration.models import NotificationChannel
        active = set(NotificationChannel.objects.filter(tenant=user.tenant, enabled=True).values_list("kind", flat=True))
        prefs = {(p.event, p.channel): p.enabled for p in UserNotificationPreference.objects.filter(user=user)}
        channels = [{"kind": k, "label": label} for k, label in CHANNELS if k in active]
        rows = []
        for event, label in EVENTS:
            cells = {}
            for ch in channels:
                allowed = rules.get((event, ch["kind"]), False)
                cells[ch["kind"]] = {"allowed": allowed, "enabled": allowed and prefs.get((event, ch["kind"]), True)}
            rows.append({"event": event, "label": label, "channels": cells})
        return Response({"channels": channels, "events": rows})

    def put(self, request):
        user = request.user
        if not in_active_tenant(user):
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé aux utilisateurs d'une entreprise.", status.HTTP_403_FORBIDDEN)
        events, kinds = dict(EVENTS), dict(CHANNELS)
        for item in request.data.get("preferences", []) if isinstance(request.data, dict) else []:
            event, kind = item.get("event"), item.get("channel")
            if event not in events or kind not in kinds:
                raise ApiError("VALIDATION_ERROR", "Événement ou canal inconnu.")
            UserNotificationPreference.objects.update_or_create(user=user, event=event, channel=kind,
                                                                defaults={"enabled": bool(item.get("enabled")), "tenant": user.tenant})
        return self.get(request)
