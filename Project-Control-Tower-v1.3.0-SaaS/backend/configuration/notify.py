"""Envoi des notifications selon les canaux et règles définis dans le module Configuration."""
import json
import logging
import urllib.request
from urllib.parse import urlparse

from django.core.mail import EmailMessage, get_connection

from .models import CHANNEL_SECRET, Notification, NotificationChannel, NotificationRule, ServiceSecret

logger = logging.getLogger("notifications")

# Domaines acceptés pour les webhooks : évite qu'une URL saisie fasse appeler un serveur interne.
WEBHOOK_HOSTS = {
    "teams": (".webhook.office.com", ".logic.azure.com", ".powerplatform.com"),
    "slack": ("hooks.slack.com",),
}


class ChannelError(Exception):
    """Erreur d'envoi, sans aucun secret dans le message."""


def validate_webhook_url(kind, url):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    allowed = WEBHOOK_HOSTS[kind]
    if parsed.scheme != "https" or not any(host == a.lstrip(".") or host.endswith(a) for a in allowed):
        raise ChannelError(f"L'URL doit être en https et viser {', '.join(a.lstrip('.') for a in allowed)}.")


def send_email(channel, to, subject, body):
    conf = channel.settings
    security = conf.get("security", "starttls")
    try:
        connection = get_connection(
            "django.core.mail.backends.smtp.EmailBackend",
            host=conf.get("host"),
            port=int(conf.get("port") or 587),
            username=conf.get("username") or None,
            password=ServiceSecret.value_of(channel.tenant_id, "smtp_password"),
            use_tls=security == "starttls",
            use_ssl=security == "ssl",
            timeout=10,
        )
        EmailMessage(subject, body, conf.get("from_address"), to, connection=connection).send()
    except Exception as exc:
        logger.warning("Envoi SMTP impossible : %s", type(exc).__name__)
        raise ChannelError(f"Envoi SMTP impossible ({type(exc).__name__}). Vérifiez le serveur, le port et les identifiants.") from exc


def send_webhook(tenant, kind, text):
    url = ServiceSecret.value_of(tenant, CHANNEL_SECRET[kind])
    if not url:
        raise ChannelError("L'URL du webhook n'est pas renseignée.")
    validate_webhook_url(kind, url)
    payload = json.dumps({"text": text}).encode()
    request = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 (URL validée ci-dessus)
            if response.status >= 300:
                raise ChannelError(f"Le webhook a répondu {response.status}.")
    except ChannelError:
        raise
    except Exception as exc:
        logger.warning("Envoi webhook %s impossible : %s", kind, type(exc).__name__)
        raise ChannelError(f"Envoi vers {kind.capitalize()} impossible ({type(exc).__name__}).") from exc


def notify(event, users, title, body=""):
    """Diffuse un événement aux utilisateurs, sur chaque canal actif dont la règle est activée.

    Une panne d'un canal externe n'empêche ni les autres canaux ni l'opération métier.
    """
    # Chaque tenant applique ses propres canaux et règles, à ses seuls utilisateurs.
    by_tenant = {}
    for u in users:
        if u.tenant_id:
            by_tenant.setdefault(u.tenant_id, []).append(u)
    for tenant_id, members in by_tenant.items():
        enabled = set(NotificationRule.objects.filter(tenant_id=tenant_id, event=event, enabled=True).values_list("channel", flat=True))
        for channel in NotificationChannel.objects.filter(tenant_id=tenant_id, enabled=True, kind__in=enabled):
            try:
                if channel.kind == "inapp":
                    Notification.objects.bulk_create(Notification(user=u, event=event, title=title, body=body) for u in members)
                elif channel.kind == "email":
                    recipients = [u.email for u in members if u.email]
                    if recipients:
                        send_email(channel, recipients, title, body)
                else:
                    send_webhook(tenant_id, channel.kind, f"{title}\n{body}".strip())
            except ChannelError:
                logger.warning("Notification %s non envoyée sur %s", event, channel.kind)
