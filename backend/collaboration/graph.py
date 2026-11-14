"""Client Microsoft Graph minimal (v1.0), sans dépendance externe.

Tous les appels réseau passent par `transport()`, que les tests remplacent : aucun test n'appelle Microsoft.
Seuls deux hôtes sont joignables (login.microsoftonline.com, graph.microsoft.com) ; les messages d'erreur ne
contiennent jamais de jeton ni de secret.
"""
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

from django.utils import timezone

from configuration.models import ServiceSecret

logger = logging.getLogger("teams")

LOGIN = "https://login.microsoftonline.com"
GRAPH = "https://graph.microsoft.com/v1.0"
ALLOWED_HOSTS = {"login.microsoftonline.com", "graph.microsoft.com"}

# Permissions déléguées, au plus juste. Les permissions de canal ne sont demandées que si le tenant les active.
BASE_SCOPES = ["offline_access", "User.Read", "Chat.Create", "ChatMessage.Send", "Chat.Read"]
CHANNEL_SCOPES = ["Team.ReadBasic.All", "Channel.ReadBasic.All", "ChannelMessage.Send", "ChannelMessage.Read.All"]
CHANNEL_CREATE_SCOPES = ["Channel.Create"]
EDIT_SCOPES = ["ChatMessage.ReadWrite"]


class GraphError(Exception):
    def __init__(self, code, message, http_status=502, retry_after=None):
        super().__init__(message)
        self.code, self.message, self.http_status, self.retry_after = code, message, http_status, retry_after


def scopes_for(connector):
    scopes = list(BASE_SCOPES)
    if connector.allow_channels:
        scopes += CHANNEL_SCOPES
        if connector.allow_channel_creation:
            scopes += CHANNEL_CREATE_SCOPES
    if connector.allow_edit_in_teams:
        scopes += EDIT_SCOPES
    return scopes


def missing_scopes(connector, granted):
    have = {s.lower() for s in (granted or "").split()}
    return [s for s in scopes_for(connector) if s != "offline_access" and s.lower() not in have]


def transport(method, url, headers=None, body=None, form=None):
    """Seul point de sortie réseau. Renvoie (statut HTTP, en-têtes, corps JSON ou None)."""
    host = urllib.parse.urlparse(url).hostname
    if host not in ALLOWED_HOSTS or not url.startswith("https://"):
        raise GraphError("TEAMS_BAD_HOST", "Destination refusée.", 500)
    data = None
    headers = dict(headers or {})
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 (hôte vérifié)
            raw = response.read()
            return response.status, dict(response.headers), json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw) if raw else None
        except ValueError:
            payload = None
        return exc.code, dict(exc.headers or {}), payload
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GraphError("TEAMS_UNREACHABLE", f"Microsoft Graph est injoignable ({type(exc).__name__}).", 503) from exc


def _error(status, headers, payload):
    """Traduit une réponse d'erreur Microsoft en message compréhensible, sans détail sensible."""
    err = (payload or {}).get("error") if isinstance(payload, dict) else None
    code = err.get("code", "") if isinstance(err, dict) else (err or "")
    if status == 401 or code in ("invalid_grant", "InvalidAuthenticationToken"):
        return GraphError("TEAMS_RECONSENT_REQUIRED", "L'autorisation Microsoft a expiré ou a été retirée : reconnectez votre compte Teams.", 409)
    if status == 403:
        return GraphError("TEAMS_FORBIDDEN", "Microsoft refuse l'opération : permission manquante ou consentement administrateur requis.", 403)
    if status == 404:
        return GraphError("TEAMS_NOT_FOUND", "La conversation ou le canal Teams n'existe plus ou n'est pas accessible.", 404)
    if status == 429 or status == 503:
        retry = headers.get("Retry-After") or headers.get("retry-after")
        return GraphError("TEAMS_THROTTLED", "Microsoft Teams limite temporairement les envois : réessayez dans un instant.", 503,
                          retry_after=int(retry) if str(retry or "").isdigit() else None)
    if code == "invalid_client" or code == "unauthorized_client":
        return GraphError("TEAMS_BAD_CREDENTIALS", "Identifiant client ou secret de l'application Microsoft invalide (ou expiré).", 400)
    return GraphError("TEAMS_ERROR", f"Microsoft Graph a répondu {status}.", 502)


# --------------------------------------------------------------------------- OAuth
def _token_url(connector):
    return f"{LOGIN}/{urllib.parse.quote(connector.directory_id, safe='')}/oauth2/v2.0/token"


def _client_secret(connector):
    secret = ServiceSecret.value_of(connector.tenant_id, "teams_client_secret")
    if not secret:
        raise GraphError("TEAMS_NOT_CONFIGURED", "Le secret client de l'application Microsoft n'est pas renseigné.", 409)
    return secret


def authorize_url(connector, state, redirect_uri, code_challenge):
    query = urllib.parse.urlencode({
        "client_id": connector.client_id, "response_type": "code", "redirect_uri": redirect_uri, "response_mode": "query",
        "scope": " ".join(scopes_for(connector)), "state": state, "code_challenge": code_challenge,
        "code_challenge_method": "S256", "prompt": "select_account",
    })
    return f"{LOGIN}/{urllib.parse.quote(connector.directory_id, safe='')}/oauth2/v2.0/authorize?{query}"


def _token_request(connector, form):
    status, headers, payload = transport("POST", _token_url(connector), form={
        "client_id": connector.client_id, "client_secret": _client_secret(connector), **form})
    if status >= 300 or not payload or "access_token" not in payload:
        raise _error(status, headers, payload)
    return payload


def exchange_code(connector, code, redirect_uri, verifier):
    return _token_request(connector, {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                                      "code_verifier": verifier, "scope": " ".join(scopes_for(connector))})


def check_app_credentials(connector):
    """Vérifie l'annuaire, l'identifiant client et le secret (jeton d'application, sans aucune permission)."""
    _token_request(connector, {"grant_type": "client_credentials", "scope": "https://graph.microsoft.com/.default"})


def expiry(payload):
    return timezone.now() + timedelta(seconds=max(int(payload.get("expires_in", 3600)) - 60, 60))


def access_token(token, connector):
    """Jeton d'accès valide de l'utilisateur ; renouvelé (refresh token) s'il expire dans moins de 5 minutes."""
    if token.revoked_at:
        raise GraphError("TEAMS_RECONSENT_REQUIRED", "Votre compte Microsoft n'est plus relié : reconnectez-le.", 409)
    if token.expires_at - timezone.now() > timedelta(minutes=5):
        return token.access_token
    if not token.refresh_token:
        raise GraphError("TEAMS_RECONSENT_REQUIRED", "Votre autorisation Microsoft a expiré : reconnectez votre compte.", 409)
    try:
        payload = _token_request(connector, {"grant_type": "refresh_token", "refresh_token": token.refresh_token,
                                             "scope": " ".join(scopes_for(connector))})
    except GraphError as exc:
        if exc.code in ("TEAMS_RECONSENT_REQUIRED", "TEAMS_BAD_CREDENTIALS"):
            token.revoked_at = timezone.now()
            token.save(update_fields=["revoked_at"])
        raise
    token.store(payload["access_token"], payload.get("refresh_token"), expiry(payload), payload.get("scope"))
    token.refreshed_at = timezone.now()
    token.save()
    return token.access_token


# --------------------------------------------------------------------------- appels Graph
class Client:
    def __init__(self, token, connector):
        self.token, self.connector = token, connector

    def call(self, method, path, body=None, ok=(200, 201, 202, 204)):
        url = path if path.startswith("https://") else f"{GRAPH}{path}"
        status, headers, payload = transport(method, url, {"Authorization": f"Bearer {access_token(self.token, self.connector)}",
                                                           "Accept": "application/json"}, body=body)
        if status not in ok:
            logger.warning("Graph %s %s -> %s", method, path.split("?")[0], status)
            raise _error(status, headers, payload)
        return payload or {}

    def me(self):
        return self.call("GET", "/me?$select=id,displayName,userPrincipalName,mail")

    def create_chat(self, kind, member_upns, topic=""):
        members = [{"@odata.type": "#microsoft.graph.aadUserConversationMember", "roles": ["owner"],
                    "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{urllib.parse.quote(upn, safe='@.')}')"}
                   for upn in member_upns]
        body = {"chatType": kind, "members": members}
        if kind == "group" and topic:
            body["topic"] = topic[:250]
        return self.call("POST", "/chats", body)

    @staticmethod
    def _message(html, mentions=None):
        body = {"body": {"contentType": "html", "content": html}}
        if mentions:
            body["mentions"] = mentions
        return body

    def send_chat_message(self, chat_id, html, mentions=None):
        return self.call("POST", f"/chats/{urllib.parse.quote(chat_id, safe='')}/messages", self._message(html, mentions))

    def send_channel_message(self, team_id, channel_id, html, reply_to="", mentions=None):
        base = f"/teams/{urllib.parse.quote(team_id, safe='')}/channels/{urllib.parse.quote(channel_id, safe='')}/messages"
        if reply_to:
            base += f"/{urllib.parse.quote(reply_to, safe='')}/replies"
        return self.call("POST", base, self._message(html, mentions))

    def message_path(self, discussion, message_id):
        q = lambda v: urllib.parse.quote(v, safe="")  # noqa: E731
        if discussion.teams_kind == "channel":
            base = f"/teams/{q(discussion.teams_team_id)}/channels/{q(discussion.teams_channel_id)}/messages"
            if discussion.teams_root_message_id and message_id != discussion.teams_root_message_id:
                return f"{base}/{q(discussion.teams_root_message_id)}/replies/{q(message_id)}"
            return f"{base}/{q(message_id)}"
        return f"/chats/{q(discussion.teams_chat_id)}/messages/{q(message_id)}"

    def update_message(self, discussion, message_id, html):
        return self.call("PATCH", self.message_path(discussion, message_id), self._message(html))

    def delete_message(self, discussion, message_id):
        me = self.token.ms_user_id
        path = self.message_path(discussion, message_id).replace("/chats/", f"/users/{me}/chats/", 1) \
            if discussion.teams_kind != "channel" else self.message_path(discussion, message_id)
        return self.call("POST", f"{path}/softDelete")

    def get_message(self, discussion, message_id):
        return self.call("GET", self.message_path(discussion, message_id))

    def list_messages(self, discussion, top=50):
        q = lambda v: urllib.parse.quote(v, safe="")  # noqa: E731
        if discussion.teams_kind == "channel":
            if not discussion.teams_root_message_id:
                return []
            path = (f"/teams/{q(discussion.teams_team_id)}/channels/{q(discussion.teams_channel_id)}/messages/"
                    f"{q(discussion.teams_root_message_id)}/replies?$top={top}")
        else:
            path = f"/chats/{q(discussion.teams_chat_id)}/messages?$top={top}&$orderby=lastModifiedDateTime desc"
        return self.call("GET", path).get("value", [])

    def joined_teams(self):
        return self.call("GET", "/me/joinedTeams?$select=id,displayName,description").get("value", [])

    def channels(self, team_id):
        return self.call("GET", f"/teams/{urllib.parse.quote(team_id, safe='')}/channels?$select=id,displayName,membershipType").get("value", [])

    def create_channel(self, team_id, name, description=""):
        return self.call("POST", f"/teams/{urllib.parse.quote(team_id, safe='')}/channels",
                         {"displayName": name[:50], "description": description[:1024], "membershipType": "standard"})

    def create_subscription(self, resource, notification_url, lifecycle_url, client_state, expires_at):
        return self.call("POST", "/subscriptions", {
            "changeType": "created,updated,deleted", "notificationUrl": notification_url,
            "lifecycleNotificationUrl": lifecycle_url, "resource": resource, "includeResourceData": False,
            "expirationDateTime": expires_at.strftime("%Y-%m-%dT%H:%M:%S.0000000Z"), "clientState": client_state})

    def renew_subscription(self, subscription_id, expires_at):
        return self.call("PATCH", f"/subscriptions/{urllib.parse.quote(subscription_id, safe='')}",
                         {"expirationDateTime": expires_at.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")})

    def delete_subscription(self, subscription_id):
        return self.call("DELETE", f"/subscriptions/{urllib.parse.quote(subscription_id, safe='')}", ok=(200, 204, 404))
