"""Règles des discussions et du connecteur Teams.

Visibilité d'une discussion (module « collaboration », droit « Voir ») :
- discussion interne ou de canal : toute personne qui voit le projet (et l'action, si la discussion en dépend) ;
- conversation individuelle ou de groupe : ses seuls participants.
Le Pilote (sans tenant) n'a accès à aucune discussion : `in_active_tenant` est faux pour lui.

Synchronisation Teams → PCT : par notification de modification (webhook) et, en secours, par relecture
périodique. Chaque message Teams est enregistré une seule fois (identifiant Teams unique par discussion) ;
un message publié depuis PCT est reconnu à son retour (identifiant ou empreinte du texte) : pas de doublon, pas
de boucle.
"""
import hashlib
import hmac
import html
import logging
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from accounts.permissions import has_perm
from configuration import audit
from configuration.notify import notify
from projects.access import in_active_tenant, visible, visible_actions, visible_projects
from projects.models import Document

from . import graph
from .models import (DiscussionMessage, DiscussionParticipant, GraphNotificationReceipt, GraphSubscription,
                     MicrosoftToken, ProjectDiscussion, TeamsConnector)

logger = logging.getLogger("teams")
User = get_user_model()

SUBSCRIPTION_MINUTES = 4200          # maximum Microsoft pour les messages Teams : 4 320 min (3 jours)
RENEW_BEFORE = timedelta(hours=12)
MAX_BODY = 8000


class CollabError(Exception):
    def __init__(self, code, message, http_status=400, details=None):
        super().__init__(message)
        self.code, self.message, self.http_status, self.details = code, message, http_status, details or []


def from_graph(exc):
    return CollabError(exc.code, exc.message, exc.http_status)


# --------------------------------------------------------------------------- connecteur
def connector_of(tenant):
    return TeamsConnector.objects.filter(tenant=tenant).first()


def ready_connector(tenant):
    c = connector_of(tenant)
    if c is None or not c.enabled or not c.directory_id or not c.client_id:
        raise CollabError("TEAMS_NOT_CONFIGURED", "Le connecteur Microsoft Teams n'est pas activé pour votre entreprise.", 409)
    return c


def token_of(user):
    t = MicrosoftToken.objects.filter(user=user, tenant=user.tenant).first()
    return t if t and not t.revoked_at else None


def client_for(user):
    connector = ready_connector(user.tenant)
    token = token_of(user)
    if token is None:
        raise CollabError("TEAMS_NOT_LINKED", "Reliez d'abord votre compte Microsoft Teams (page Collaboration).", 409)
    return graph.Client(token, connector)


def connection_status(user):
    c = connector_of(user.tenant)
    t = MicrosoftToken.objects.filter(user=user, tenant=user.tenant).first()
    configured = bool(c and c.enabled and c.directory_id and c.client_id)
    linked = bool(t and not t.revoked_at)
    return {
        "configured": configured,
        "channels": bool(c and c.allow_channels),
        "channelCreation": bool(c and c.allow_channels and c.allow_channel_creation),
        "linked": linked,
        "account": {"name": t.ms_display_name, "upn": t.ms_upn} if t else None,
        "needsReconsent": bool(t and t.revoked_at),
        "missingScopes": graph.missing_scopes(c, t.scopes) if (c and linked) else [],
        "tokenExpiresAt": t.expires_at if linked else None,
        "webhooks": public_base().startswith("https://"),
    }


def public_base(request=None):
    if settings.PUBLIC_BASE_URL:
        return settings.PUBLIC_BASE_URL
    return request.build_absolute_uri("/").rstrip("/") if request is not None else ""


# --------------------------------------------------------------------------- OAuth (PKCE, état en session)
def oauth_start(request):
    connector = ready_connector(request.user.tenant)
    verifier = secrets.token_urlsafe(64)
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    state = secrets.token_urlsafe(32)
    request.session["teams_oauth"] = {"state": state, "verifier": verifier, "at": timezone.now().isoformat()}
    return graph.authorize_url(connector, state, redirect_uri(request), challenge)


def _b64(raw):
    import base64
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def redirect_uri(request):
    return f"{public_base(request)}/api/v1/teams/oauth/callback"


def oauth_callback(request, code, state):
    pending = request.session.pop("teams_oauth", None)
    if not pending or not state or not hmac.compare_digest(pending["state"], state):
        raise CollabError("TEAMS_OAUTH_STATE", "Lien de connexion expiré ou invalide : recommencez depuis PCT.", 400)
    started = parse_datetime(pending["at"])
    if started and timezone.now() - started > timedelta(minutes=15):
        raise CollabError("TEAMS_OAUTH_STATE", "La connexion à Microsoft a pris trop de temps : recommencez.", 400)
    user = request.user
    connector = ready_connector(user.tenant)
    try:
        payload = graph.exchange_code(connector, code, redirect_uri(request), pending["verifier"])
    except graph.GraphError as exc:
        raise from_graph(exc) from exc
    token = MicrosoftToken.objects.filter(user=user).first() or MicrosoftToken(user=user, tenant=user.tenant)
    token.store(payload["access_token"], payload.get("refresh_token", ""), graph.expiry(payload), payload.get("scope", ""))
    token.save()
    try:
        me = graph.Client(token, connector).me()
    except graph.GraphError as exc:
        raise from_graph(exc) from exc
    token.ms_user_id = me.get("id", "")
    token.ms_display_name = me.get("displayName", "")[:200]
    token.ms_upn = (me.get("userPrincipalName") or me.get("mail") or "")[:254]
    token.save()
    audit.record(user, f"Utilisateur {user.username}", "Compte Microsoft Teams relié", "", token.ms_upn)
    return token


def unlink(user):
    deleted, _ = MicrosoftToken.objects.filter(user=user).delete()
    if deleted:
        audit.record(user, f"Utilisateur {user.username}", "Compte Microsoft Teams délié")


# --------------------------------------------------------------------------- visibilité et droits
def visible_discussions(user):
    if not in_active_tenant(user) or not has_perm(user, "collaboration", "read"):
        return ProjectDiscussion.objects.none()
    base = ProjectDiscussion.objects.filter(tenant_id=user.tenant_id)
    public = Q(project__in=visible_projects(user)) & ~Q(teams_kind__in=("oneOnOne", "group")) \
        & (Q(action__isnull=True) | Q(action__in=visible_actions(user)))
    private = Q(teams_kind__in=("oneOnOne", "group"), participants__user=user)
    return base.filter(public | private).distinct()


def can_post(user, discussion):
    return discussion.status == "active" and has_perm(user, "collaboration", "create") \
        and visible_discussions(user).filter(pk=discussion.pk).exists()


def _member_sees_project(member, project):
    return member.is_active and member.tenant_id == project.tenant_id and visible_projects(member).filter(pk=project.pk).exists()


# --------------------------------------------------------------------------- contenu
def to_html(text):
    return html.escape(text).replace("\n", "<br>")


TAG = re.compile(r"<[^>]+>")


def to_text(content, content_type="html"):
    if content_type != "html":
        return content or ""
    text = re.sub(r"<br\s*/?>|</p>|</div>", "\n", content or "", flags=re.I)
    text = html.unescape(TAG.sub("", text))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def app_link(discussion):
    base = public_base()
    return f"{base}/#collaboration/{discussion.pk}" if base else ""


def initial_html(discussion, by, message):
    p = discussion.project
    lines = [f"<b>{html.escape(discussion.title)}</b>",
             f"Projet : {html.escape(p.code)} — {html.escape(p.name)}"]
    if discussion.action_id:
        lines.append(f"Action : {html.escape(discussion.action.title)}")
    lines.append(f"Ouverte par {html.escape(by.display_name)} depuis Project Control Tower")
    if message:
        lines += ["", to_html(message)]
    link = app_link(discussion)
    if link:
        lines.append(f'<a href="{html.escape(link)}">Ouvrir dans PCT</a>')
    return "<br>".join(lines)


def _mentions_payload(users, text):
    """Mentions Teams pour les personnes dont le compte Microsoft est relié ; les autres restent en « @Nom »."""
    tokens = {t.user_id: t for t in MicrosoftToken.objects.filter(user__in=users, revoked_at__isnull=True)}
    out, extra = [], []
    for i, u in enumerate(users):
        t = tokens.get(u.pk)
        if t and t.ms_user_id:
            out.append({"id": len(out), "mentionText": u.display_name,
                        "mentioned": {"user": {"id": t.ms_user_id, "displayName": u.display_name}}})
            extra.append(f'<at id="{len(out) - 1}">{html.escape(u.display_name)}</at>')
        else:
            extra.append(f"@{html.escape(u.display_name)}")
    prefix = " ".join(extra)
    return (f"{prefix} " if prefix else "") + to_html(text), out


# --------------------------------------------------------------------------- création
def create_discussion(by, data):
    try:
        with transaction.atomic():
            return _create_discussion(by, data)
    except CollabError as exc:
        if exc.code == "TEAMS_RECONSENT_REQUIRED":
            # Annulation de la création, mais l'autorisation retirée par Microsoft reste constatée.
            MicrosoftToken.objects.filter(user=by, revoked_at__isnull=True).update(revoked_at=timezone.now())
        raise


def _create_discussion(by, data):
    if not in_active_tenant(by) or not has_perm(by, "collaboration", "create"):
        raise CollabError("FORBIDDEN_PERMISSION", "Vous ne pouvez pas créer de discussion.", 403)
    project = visible_projects(by).filter(pk=data.get("project")).first()
    if project is None:
        raise CollabError("NOT_FOUND", "Projet introuvable.", 404)
    action = None
    if data.get("action"):
        action = visible_actions(by).filter(pk=data["action"], project=project).first()
        if action is None:
            raise CollabError("NOT_FOUND", "Action introuvable dans ce projet.", 404)
    title = (data.get("title") or "").strip()[:200] or (action.title if action else f"Discussion {project.code}")
    destination = data.get("destination", "internal")
    if destination not in ("internal", "teams", "both"):
        raise CollabError("VALIDATION_ERROR", "Destination inconnue (internal, teams, both).")
    kind = data.get("teamsKind") or ("none" if destination == "internal" else "group")
    if destination == "internal":
        kind = "none"
    elif kind not in ("oneOnOne", "group", "channel"):
        raise CollabError("VALIDATION_ERROR", "Type de conversation Teams inconnu (oneOnOne, group, channel).")

    members = {by.pk: by}
    for uid in data.get("participants") or []:
        u = User.objects.filter(pk=uid, tenant=by.tenant).first()
        if u is None or not _member_sees_project(u, project):
            raise CollabError("VALIDATION_ERROR", "Un participant n'a pas accès à ce projet.",
                              details=[{"field": "participants", "message": f"Utilisateur {uid}"}])
        members[u.pk] = u
    if kind == "oneOnOne" and len(members) != 2:
        raise CollabError("VALIDATION_ERROR", "Une conversation individuelle réunit exactement deux personnes.")
    if kind == "group" and len(members) < 3:
        raise CollabError("VALIDATION_ERROR", "Une conversation de groupe réunit au moins trois personnes (sinon, choisissez « individuelle »).")

    discussion = ProjectDiscussion.objects.create(
        tenant=by.tenant, project=project, action=action, title=title, destination=destination, teams_kind=kind,
        created_by=by, last_message_at=timezone.now())
    for u in members.values():
        DiscussionParticipant.objects.create(tenant=by.tenant, discussion=discussion, user=u,
                                             role="owner" if u.pk == by.pk else "member")
    first = (data.get("message") or "").strip()[:MAX_BODY]
    if first:
        _create_message(discussion, by, first, origin="pct",
                        status="internal" if destination == "internal" else "pending")
    if discussion.uses_teams:
        _open_in_teams(by, discussion, list(members.values()), data, first)
    audit.record(by, f"Projet {project.code}", "Discussion créée", "", f"{title} ({discussion.get_destination_display()})")
    notify("discussion_message", [u for u in members.values() if u.pk != by.pk],
           f"Nouvelle discussion : {title}", f"{by.display_name} vous a ajouté à une discussion du projet {project.code}.")
    return discussion


def _open_in_teams(by, discussion, members, data, first):
    client = client_for(by)
    connector = client.connector
    try:
        if discussion.teams_kind == "channel":
            if not connector.allow_channels:
                raise CollabError("TEAMS_CHANNELS_DISABLED", "La publication dans les canaux n'est pas activée pour votre entreprise.", 409)
            team_id, channel_id = data.get("teamId", ""), data.get("channelId", "")
            if not team_id or not channel_id:
                raise CollabError("VALIDATION_ERROR", "Choisissez l'équipe et le canal Teams.")
            discussion.teams_team_id, discussion.teams_channel_id = team_id, channel_id
            root = client.send_channel_message(team_id, channel_id, initial_html(discussion, by, first))
            discussion.teams_root_message_id = root.get("id", "")
            discussion.teams_web_url = (root.get("webUrl") or "")[:1000]
        else:
            upns = []
            for u in members:
                t = token_of(u)
                upn = (t.ms_upn if t and t.ms_upn else u.email)
                if not upn:
                    raise CollabError("VALIDATION_ERROR", f"{u.display_name} n'a ni compte Teams relié ni adresse e-mail.")
                upns.append(upn)
            chat = client.create_chat(discussion.teams_kind, upns, discussion.title)
            discussion.teams_chat_id = chat.get("id", "")
            discussion.teams_web_url = (chat.get("webUrl") or "")[:1000]
            root = client.send_chat_message(discussion.teams_chat_id, initial_html(discussion, by, first))
        discussion.last_synced_at = timezone.now()
        discussion.save()
        if first:
            msg = discussion.messages.filter(author=by).order_by("id").first()
            if msg:
                msg.teams_message_id = root.get("id", "")
                msg.publication_status = "published"
                msg.save(update_fields=["teams_message_id", "publication_status"])
        else:
            DiscussionMessage.objects.get_or_create(
                discussion=discussion, teams_message_id=root.get("id", "") or "-", defaults={
                    "tenant": discussion.tenant, "author": by, "kind": "system", "origin": "pct",
                    "body": f"Discussion ouverte dans Teams par {by.display_name}.", "publication_status": "published"})
    except graph.GraphError as exc:
        raise from_graph(exc) from exc
    ensure_subscription(discussion, by)


# --------------------------------------------------------------------------- messages
def _create_message(discussion, author, body, origin="pct", status="internal", parent=None, mentions=(), attachments=(),
                    teams_id="", client_key="", external_author="", kind="message", modified=None):
    msg = DiscussionMessage.objects.create(
        tenant=discussion.tenant, discussion=discussion, author=author, external_author=external_author[:200], kind=kind,
        body=body, body_hash=DiscussionMessage.hash_body(body), parent=parent, origin=origin, publication_status=status,
        teams_message_id=teams_id, client_key=client_key[:64], teams_modified_at=modified)
    if mentions:
        msg.mentions.set(mentions)
    if attachments:
        msg.attachments.set(attachments)
    ProjectDiscussion.objects.filter(pk=discussion.pk).update(last_message_at=timezone.now())
    return msg


def post_message(by, discussion, data):
    if not can_post(by, discussion):
        raise CollabError("FORBIDDEN_PERMISSION", "Vous ne pouvez pas écrire dans cette discussion.", 403)
    body = (data.get("body") or "").strip()
    if not body:
        raise CollabError("VALIDATION_ERROR", "Le message est vide.")
    if len(body) > MAX_BODY:
        raise CollabError("VALIDATION_ERROR", f"Message trop long ({MAX_BODY} caractères au plus).")
    client_key = str(data.get("clientKey") or "")[:64]
    if client_key:
        existing = discussion.messages.filter(author=by, client_key=client_key).first()
        if existing:
            return existing  # double clic, réseau instable : même message
    parent = None
    if data.get("parent"):
        parent = discussion.messages.filter(pk=data["parent"], deleted_at__isnull=True).first()
        if parent is None:
            raise CollabError("NOT_FOUND", "Message d'origine introuvable.", 404)
    mentions = list(User.objects.filter(pk__in=data.get("mentions") or [], tenant=by.tenant, is_active=True))
    mentions = [u for u in mentions if _member_sees_project(u, discussion.project)]
    attachments = list(visible(by, Document).filter(pk__in=data.get("attachments") or [], project=discussion.project))
    status = "pending" if discussion.uses_teams else "internal"
    try:
        msg = _create_message(discussion, by, body, status=status, parent=parent, mentions=mentions,
                              attachments=attachments, client_key=client_key)
    except IntegrityError:
        return discussion.messages.get(author=by, client_key=client_key)
    if discussion.uses_teams:
        publish(by, msg)
    recipients = {u.pk: u for u in User.objects.filter(discussion_participations__discussion=discussion)}
    for u in mentions:
        recipients[u.pk] = u
    recipients.pop(by.pk, None)
    if mentions:
        notify("comment_mention", [u for u in mentions if u.pk != by.pk], f"{by.display_name} vous a mentionné",
               f"{discussion.title} : {body[:200]}")
    notify("discussion_message", [u for u in recipients.values() if u not in mentions],
           f"Nouveau message : {discussion.title}", f"{by.display_name} : {body[:200]}")
    return msg


def _attachments_html(msg):
    docs = list(msg.attachments.all())
    if not docs:
        return ""
    names = ", ".join(html.escape(f"{d.name}{('.' + d.ext) if d.ext and not d.name.endswith(d.ext) else ''}") for d in docs)
    link = app_link(msg.discussion)
    return f"<br>Pièces jointes (dans PCT) : {names}" + (f' — <a href="{html.escape(link)}">ouvrir</a>' if link else "")


def publish(by, msg):
    """Publie un message dans Teams. En cas d'échec : statut « failed » et raison ; le message reste dans PCT."""
    discussion = msg.discussion
    try:
        client = client_for(by)
        content, mentions = _mentions_payload(list(msg.mentions.all()), msg.body)
        content += _attachments_html(msg)
        if discussion.teams_kind == "channel":
            reply_to = discussion.teams_root_message_id
            result = client.send_channel_message(discussion.teams_team_id, discussion.teams_channel_id, content,
                                                 reply_to=reply_to, mentions=mentions)
        else:
            result = client.send_chat_message(discussion.teams_chat_id, content, mentions=mentions)
    except (graph.GraphError, CollabError) as exc:
        msg.publication_status = "failed"
        msg.publication_error = exc.message[:300]
        msg.save(update_fields=["publication_status", "publication_error"])
        return msg
    msg.teams_message_id = result.get("id", "")
    msg.teams_modified_at = parse_datetime(result.get("lastModifiedDateTime") or "") or timezone.now()
    msg.publication_status = "published"
    msg.publication_error = ""
    msg.save(update_fields=["teams_message_id", "teams_modified_at", "publication_status", "publication_error"])
    return msg


def retry(by, msg):
    if msg.author_id != by.pk:
        raise CollabError("FORBIDDEN_PERMISSION", "Seul l'auteur peut renvoyer son message.", 403)
    if msg.publication_status != "failed":
        raise CollabError("CONFLICT", "Ce message n'est pas en échec de publication.", 409)
    return publish(by, msg)


def edit_message(by, msg, body):
    if msg.author_id != by.pk or msg.origin != "pct" or msg.kind != "message":
        raise CollabError("FORBIDDEN_PERMISSION", "Vous ne pouvez modifier que vos propres messages.", 403)
    if msg.deleted_at:
        raise CollabError("CONFLICT", "Ce message a été supprimé.", 409)
    body = (body or "").strip()
    if not body or len(body) > MAX_BODY:
        raise CollabError("VALIDATION_ERROR", "Message vide ou trop long.")
    if body == msg.body:
        return msg
    msg.history = (msg.history or []) + [{"at": timezone.now().isoformat(), "body": msg.body}]
    msg.body, msg.body_hash, msg.edited_at = body, DiscussionMessage.hash_body(body), timezone.now()
    msg.publication_error = ""
    if msg.teams_message_id and msg.publication_status == "published":
        _mirror(by, msg, lambda c: c.update_message(msg.discussion, msg.teams_message_id, to_html(body)))
    msg.save()
    return msg


def delete_message(by, msg):
    if msg.author_id != by.pk or msg.kind != "message":
        raise CollabError("FORBIDDEN_PERMISSION", "Vous ne pouvez supprimer que vos propres messages.", 403)
    if msg.deleted_at:
        return msg
    msg.history = (msg.history or []) + [{"at": timezone.now().isoformat(), "body": msg.body, "deleted": True}]
    msg.deleted_at = timezone.now()
    msg.body = ""
    if msg.teams_message_id and msg.publication_status == "published":
        _mirror(by, msg, lambda c: c.delete_message(msg.discussion, msg.teams_message_id))
    msg.save()
    return msg


def _mirror(by, msg, operation):
    """Modification/suppression côté Teams si le tenant l'autorise ; sinon, PCT seulement (indiqué au message)."""
    connector = connector_of(by.tenant)
    if not (connector and connector.allow_edit_in_teams):
        msg.publication_error = "Modifié dans PCT uniquement (répercussion dans Teams non activée)."
        return
    try:
        operation(client_for(by))
        msg.teams_modified_at = timezone.now()
    except (graph.GraphError, CollabError) as exc:
        msg.publication_error = f"Modifié dans PCT uniquement : {exc.message}"[:300]


# --------------------------------------------------------------------------- synchronisation Teams -> PCT
def _sync_owner(discussion):
    """Compte dont l'autorisation sert à relire la discussion : créateur, sinon un participant relié."""
    candidates = [discussion.created_by_id] + list(discussion.participants.values_list("user_id", flat=True))
    for uid in candidates:
        t = MicrosoftToken.objects.filter(user_id=uid, revoked_at__isnull=True, tenant=discussion.tenant).first()
        if t:
            return t
    return None


def _ingest(discussion, item):
    """Enregistre ou met à jour un message Teams. Renvoie 'created', 'updated', 'deleted' ou None (rien à faire)."""
    if item.get("messageType") != "message":
        return None
    mid = item.get("id", "")
    if not mid or mid == discussion.teams_root_message_id:
        return None
    modified = parse_datetime(item.get("lastModifiedDateTime") or item.get("createdDateTime") or "") or timezone.now()
    body = to_text((item.get("body") or {}).get("content", ""), (item.get("body") or {}).get("contentType", "html"))
    existing = discussion.messages.filter(teams_message_id=mid).first()
    if existing:
        if item.get("deletedDateTime"):
            if existing.deleted_at:
                return None
            existing.deleted_at = parse_datetime(item["deletedDateTime"]) or timezone.now()
            existing.body = ""
            existing.save(update_fields=["deleted_at", "body"])
            return "deleted"
        # Boucle évitée : on ignore un état Teams plus ancien que (ou identique à) l'état connu.
        if existing.teams_modified_at and modified <= existing.teams_modified_at:
            return None
        if existing.origin == "teams":
            existing.history = (existing.history or []) + [{"at": timezone.now().isoformat(), "body": existing.body}]
            existing.body, existing.body_hash = body, DiscussionMessage.hash_body(body)
            existing.edited_at = modified
        existing.teams_modified_at = modified
        existing.save()
        return "updated" if existing.origin == "teams" else None
    if item.get("deletedDateTime"):
        return None
    sender = ((item.get("from") or {}).get("user") or {})
    token = MicrosoftToken.objects.filter(ms_user_id=sender.get("id") or "-", tenant=discussion.tenant).first()
    author = token.user if token else None
    # Message envoyé depuis PCT dont l'identifiant n'est pas encore enregistré (notification arrivée avant la réponse).
    if author:
        pending = _pending_match(discussion, author, body)
        if pending:
            pending.teams_message_id, pending.teams_modified_at = mid, modified
            pending.publication_status, pending.publication_error = "published", ""
            pending.save()
            return None
    try:
        with transaction.atomic():
            _create_message(discussion, author, body or "(message sans texte)", origin="teams", status="published",
                            teams_id=mid, external_author="" if author else sender.get("displayName", "Utilisateur Teams"),
                            modified=modified)
    except IntegrityError:
        return None  # reçu en parallèle par une autre notification
    return "created"


def _norm(text):
    return " ".join((text or "").split())


def _pending_match(discussion, author, body):
    """Message PCT en attente dont le texte correspond (les mentions Teams ajoutent les noms en tête)."""
    incoming = _norm(body)
    recent = timezone.now() - timedelta(minutes=10)
    for m in discussion.messages.filter(author=author, origin="pct", teams_message_id="", created_at__gte=recent,
                                        publication_status__in=("pending", "failed")).order_by("-id")[:20]:
        mine = _norm(m.body)
        if mine and (incoming == mine or incoming.endswith(mine) or incoming.startswith(mine)):
            return m
    return None


def synchronize(discussion, by=None):
    """Relit les derniers messages Teams de la discussion (secours des notifications). Idempotent."""
    if not discussion.uses_teams or not (discussion.teams_chat_id or discussion.teams_root_message_id):
        return {"created": 0, "updated": 0, "deleted": 0}
    token = token_of(by) if by else None
    token = token or _sync_owner(discussion)
    if token is None:
        raise CollabError("TEAMS_NOT_LINKED", "Aucun participant n'a relié son compte Teams : synchronisation impossible.", 409)
    client = graph.Client(token, ready_connector(discussion.tenant))
    try:
        items = client.list_messages(discussion)
    except graph.GraphError as exc:
        ProjectDiscussion.objects.filter(pk=discussion.pk).update(last_error=exc.message[:300])
        raise from_graph(exc) from exc
    counts = {"created": 0, "updated": 0, "deleted": 0}
    for item in sorted(items, key=lambda i: i.get("createdDateTime") or ""):
        result = _ingest(discussion, item)
        if result:
            counts[result] += 1
    ProjectDiscussion.objects.filter(pk=discussion.pk).update(last_synced_at=timezone.now(), last_error="")
    if counts["created"]:
        _notify_incoming(discussion, counts["created"])
    return counts


def _notify_incoming(discussion, count):
    users = list(User.objects.filter(discussion_participations__discussion=discussion))
    notify("discussion_message", users, f"{count} nouveau(x) message(s) Teams : {discussion.title}",
           f"Projet {discussion.project.code}")


# --------------------------------------------------------------------------- abonnements et webhook
def ensure_subscription(discussion, by):
    base = public_base()
    if not base.startswith("https://"):
        return None  # pas d'adresse publique : la relecture périodique prend le relais
    token = token_of(by) or _sync_owner(discussion)
    if token is None:
        return None
    if discussion.teams_kind == "channel":
        resource = f"/teams/{discussion.teams_team_id}/channels/{discussion.teams_channel_id}/messages"
    else:
        resource = f"/chats/{discussion.teams_chat_id}/messages"
    state = secrets.token_urlsafe(32)
    expires = timezone.now() + timedelta(minutes=SUBSCRIPTION_MINUTES)
    client = graph.Client(token, ready_connector(discussion.tenant))
    try:
        sub = client.create_subscription(resource, f"{base}/api/v1/teams/webhook", f"{base}/api/v1/teams/lifecycle", state, expires)
    except graph.GraphError as exc:
        logger.warning("Abonnement Graph impossible pour la discussion %s : %s", discussion.pk, exc.code)
        return None
    return GraphSubscription.objects.create(tenant=discussion.tenant, discussion=discussion, owner=token.user,
                                            subscription_id=sub["id"], resource=resource,
                                            client_state_hash=GraphSubscription.hash_state(state), expires_at=expires)


def renew_subscriptions(now=None):
    now = now or timezone.now()
    report = {"renewed": 0, "failed": 0}
    for sub in GraphSubscription.objects.filter(status="active", expires_at__lt=now + RENEW_BEFORE).select_related("discussion"):
        report["renewed" if renew(sub, now) else "failed"] += 1
    return report


def renew(sub, now=None):
    now = now or timezone.now()
    token = token_of(sub.owner)
    try:
        if token is None:
            raise graph.GraphError("TEAMS_RECONSENT_REQUIRED", "Autorisation du propriétaire de l'abonnement retirée.", 409)
        expires = now + timedelta(minutes=SUBSCRIPTION_MINUTES)
        graph.Client(token, ready_connector(sub.tenant)).renew_subscription(sub.subscription_id, expires)
    except (graph.GraphError, CollabError) as exc:
        sub.status, sub.last_error = "error", exc.message[:300]
        sub.save(update_fields=["status", "last_error"])
        return False
    sub.expires_at, sub.renewed_at, sub.last_error = expires, now, ""
    sub.save(update_fields=["expires_at", "renewed_at", "last_error"])
    return True


def _receipt(key_parts, tenant):
    key = hashlib.sha256("|".join(key_parts).encode()).hexdigest()
    try:
        with transaction.atomic():
            GraphNotificationReceipt.objects.create(key=key, tenant=tenant)
        return True
    except IntegrityError:
        return False


MESSAGE_ID = re.compile(r"messages\('?([^')/]+)'?\)(?:/replies\('?([^')/]+)'?\))?$|messages/([^/]+)(?:/replies/([^/]+))?$")


def handle_notifications(payload):
    """Traite un lot de notifications Microsoft Graph. Toute notification non authentifiée est ignorée."""
    report = {"accepted": 0, "ignored": 0}
    for n in (payload or {}).get("value", [])[:100]:
        sub = GraphSubscription.objects.filter(subscription_id=str(n.get("subscriptionId", ""))).select_related("discussion").first()
        state = str(n.get("clientState") or "")
        if sub is None or not hmac.compare_digest(sub.client_state_hash, GraphSubscription.hash_state(state)):
            report["ignored"] += 1
            continue
        resource = str(n.get("resource") or "")
        change = str(n.get("changeType") or "")
        stamp = str((n.get("resourceData") or {}).get("@odata.etag") or n.get("subscriptionExpirationDateTime") or "")
        if not _receipt([sub.subscription_id, change, resource, stamp], sub.tenant):
            report["ignored"] += 1  # rejeu ou doublon
            continue
        report["accepted"] += 1
        _process_change(sub, resource)
    return report


def _process_change(sub, resource):
    discussion = sub.discussion
    if discussion.status != "active":
        return
    m = MESSAGE_ID.search(resource)
    token = token_of(sub.owner) or _sync_owner(discussion)
    if token is None:
        return
    try:
        client = graph.Client(token, ready_connector(discussion.tenant))
        if m:
            parts = [p for p in m.groups() if p]
            mid = parts[-1]
            try:
                item = client.get_message(discussion, mid)
            except graph.GraphError as exc:
                if exc.code != "TEAMS_NOT_FOUND":
                    raise
                item = {"id": mid, "messageType": "message", "deletedDateTime": timezone.now().isoformat()}
            if _ingest(discussion, item) == "created":
                _notify_incoming(discussion, 1)
        else:
            synchronize(discussion)
    except (graph.GraphError, CollabError) as exc:
        logger.warning("Notification Teams non traitée (discussion %s) : %s", discussion.pk, getattr(exc, "code", ""))


def handle_lifecycle(payload):
    report = {"renewed": 0, "resynced": 0, "ignored": 0}
    for n in (payload or {}).get("value", [])[:100]:
        sub = GraphSubscription.objects.filter(subscription_id=str(n.get("subscriptionId", ""))).first()
        if sub is None or not hmac.compare_digest(sub.client_state_hash, GraphSubscription.hash_state(str(n.get("clientState") or ""))):
            report["ignored"] += 1
            continue
        event = n.get("lifecycleEvent")
        if event == "reauthorizationRequired":
            report["renewed"] += int(renew(sub))
        elif event == "subscriptionRemoved":
            sub.status = "removed"
            sub.save(update_fields=["status"])
            ensure_subscription(sub.discussion, sub.owner)
            report["renewed"] += 1
        elif event == "missed":
            try:
                synchronize(sub.discussion)
                report["resynced"] += 1
            except CollabError:
                report["ignored"] += 1
    return report


def fallback_sync(now=None, stale_minutes=30, limit=50):
    """Relecture périodique des discussions Teams sans abonnement actif, ou non relues depuis longtemps."""
    now = now or timezone.now()
    qs = ProjectDiscussion.objects.filter(status="active", destination__in=("teams", "both")).filter(
        Q(last_synced_at__isnull=True) | Q(last_synced_at__lt=now - timedelta(minutes=stale_minutes)))
    report = {"synced": 0, "failed": 0}
    for d in qs[:limit]:
        try:
            synchronize(d)
            report["synced"] += 1
        except CollabError:
            report["failed"] += 1
    return report


def purge_receipts(now=None):
    now = now or timezone.now()
    deleted, _ = GraphNotificationReceipt.objects.filter(received_at__lt=now - timedelta(days=3)).delete()
    return deleted


# --------------------------------------------------------------------------- canaux
def create_channel(by, team_id, name, description=""):
    if not has_perm(by, "collaboration", "approve"):
        raise CollabError("FORBIDDEN_PERMISSION", "La création de canal demande le droit « Collaboration · Valider ».", 403)
    client = client_for(by)
    if not (client.connector.allow_channels and client.connector.allow_channel_creation):
        raise CollabError("TEAMS_CHANNELS_DISABLED", "La création de canaux n'est pas activée pour votre entreprise.", 409)
    name = (name or "").strip()
    if not name:
        raise CollabError("VALIDATION_ERROR", "Nom du canal obligatoire.")
    try:
        channel = client.create_channel(team_id, name, description)
    except graph.GraphError as exc:
        raise from_graph(exc) from exc
    audit.record(by, "Microsoft Teams", "Canal créé", "", name)
    return channel


# --------------------------------------------------------------------------- reprise des commentaires
def import_action_comments(tenant):
    """Reprend les commentaires d'actions existants dans une discussion interne par action (une seule fois)."""
    from projects.models import ActionComment
    created = 0
    by_action = {}
    for c in ActionComment.objects.filter(tenant=tenant).select_related("action__project", "author").order_by("id"):
        by_action.setdefault(c.action, []).append(c)
    for action, comments in by_action.items():
        if ProjectDiscussion.objects.filter(action=action, title__startswith="Commentaires · ").exists():
            continue
        d = ProjectDiscussion.objects.create(tenant=tenant, project=action.project, action=action,
                                             title=f"Commentaires · {action.title}"[:200], destination="internal",
                                             created_by=comments[0].author, last_message_at=timezone.now())
        for c in comments:
            _create_message(d, c.author, c.body)
        created += 1
    return created

