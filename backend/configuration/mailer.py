"""Socle de notifications système : un seul point d'entrée pour la cloche de l'application et l'e-mail.

    dispatch(event, users, title, body, project=..., details={...}, link=..., actor=...)

- Notification dans l'application pour chaque destinataire (sauf l'auteur de l'action).
- E-mail si le canal e-mail de l'entreprise est actif (Configuration › Notifications) et que la règle de l'événement
  l'autorise. Sans règle enregistrée, les événements de DEFAULT_EMAIL_EVENTS partent par e-mail. Les préférences de
  l'utilisateur ne peuvent que restreindre.
- Envois de la plateforme (Pilote, tenant vide) : serveur SMTP PLATFORM_EMAIL_* (fichier .env).
- Chaque envoi est tracé dans NotificationDelivery (journal visible par l'administrateur et le Pilote).
- Envoi des e-mails en arrière-plan : l'écran de l'utilisateur n'attend jamais le serveur SMTP.
"""
import logging
import threading
from html import escape

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.db import close_old_connections
from django.utils import timezone

from .models import (EVENTS, Notification, NotificationChannel, NotificationDelivery, NotificationRule, ServiceSecret,
                     UserNotificationPreference)

logger = logging.getLogger("notifications")
EVENT_LABEL = dict(EVENTS)
SOCLE_EVENTS = {"licence_request", "action_created", "action_updated", "action_assigned", "action_due", "weekly_recap", "project_alert"}
DEFAULT_EMAIL_EVENTS = {"licence_request", "action_assigned", "action_due", "weekly_recap", "validation_requested", "action_late"}


# --------------------------------------------------------------------------- configuration
LOCAL_URL = "http://localhost:5173"
APP_URL_KEY = "app_public_url"


def valid_url(u):
    from urllib.parse import urlparse
    u = str(u or "").strip().rstrip("/")
    p = urlparse(u)
    return u if p.scheme in ("http", "https") and p.netloc and " " not in u else ""


def app_url():
    """URL publique de l'application pour les liens des e-mails : réglage du Pilote s'il est valide, sinon APP_PUBLIC_URL
    (.env), sinon http://localhost:5173."""
    try:
        from .models import PlatformSetting
        row = PlatformSetting.objects.filter(key=APP_URL_KEY).first()
        u = valid_url((row.value or {}).get("url")) if row else ""
        if u:
            return u
    except Exception:  # noqa: BLE001
        pass
    return valid_url(getattr(settings, "APP_PUBLIC_URL", "")) or LOCAL_URL


def app_url_source():
    from .models import PlatformSetting
    row = PlatformSetting.objects.filter(key=APP_URL_KEY).first()
    if row and valid_url((row.value or {}).get("url")):
        return "pilote"
    return "env" if valid_url(getattr(settings, "APP_PUBLIC_URL", "")) else "localhost"


PLATFORM_SMTP_KEY = "platform_smtp"


def platform_conf(with_password=False):
    """Serveur SMTP de la plateforme : réglage du Pilote (Pilote › Configuration) s'il est renseigné, sinon fichier .env."""
    row = None
    try:
        from .models import PlatformSetting
        row = PlatformSetting.objects.filter(key=PLATFORM_SMTP_KEY).first()
    except Exception:  # noqa: BLE001
        pass
    v = (row.value or {}) if row else {}
    if v.get("host"):
        pwd = ""
        if v.get("password"):
            try:
                from . import crypto
                pwd = crypto.decrypt(v["password"])
            except Exception:  # noqa: BLE001
                pwd = ""
        c = {"host": v.get("host"), "port": int(v.get("port") or 587), "security": v.get("security") or "starttls",
             "username": v.get("username") or "", "from_address": v.get("from_address") or v.get("username") or "",
             "password": pwd or getattr(settings, "PLATFORM_EMAIL_PASSWORD", ""), "source": "pilote", "passwordHint": v.get("hint", "")}
    else:
        c = {"host": getattr(settings, "PLATFORM_EMAIL_HOST", ""), "port": int(getattr(settings, "PLATFORM_EMAIL_PORT", 587) or 587),
             "security": getattr(settings, "PLATFORM_EMAIL_SECURITY", "starttls"), "username": getattr(settings, "PLATFORM_EMAIL_USER", ""),
             "from_address": getattr(settings, "PLATFORM_EMAIL_FROM", "") or getattr(settings, "PLATFORM_EMAIL_USER", ""),
             "password": getattr(settings, "PLATFORM_EMAIL_PASSWORD", ""), "source": "env",
             "passwordHint": (getattr(settings, "PLATFORM_EMAIL_PASSWORD", "") or "")[-4:]}
    if not with_password:
        c["passwordSet"] = bool(c.pop("password"))
    c["configured"] = bool(c["host"])
    return c


def platform_smtp():
    """Serveur SMTP de la plateforme (Pilote), sans secret."""
    return platform_conf(False)


def tenant_channel(tenant_id):
    return NotificationChannel.objects.filter(tenant_id=tenant_id, kind="email", enabled=True).first()


def inapp_allowed(tenant_id, event):
    rule = NotificationRule.objects.filter(tenant_id=tenant_id, event=event, channel="inapp").first() if tenant_id else None
    return rule.enabled if rule is not None else True


def email_allowed(tenant_id, event):
    rule = NotificationRule.objects.filter(tenant_id=tenant_id, event=event, channel="email").first()
    return rule.enabled if rule is not None else event in DEFAULT_EMAIL_EVENTS


def _connection(tenant_id):
    """(connexion, adresse d'expédition, source) ou (None, None, raison)."""
    if tenant_id:
        ch = tenant_channel(tenant_id)
        if ch is None:
            return None, None, "canal e-mail de l'entreprise désactivé"
        c = ch.settings or {}
        sec = c.get("security", "starttls")
        conn = get_connection("django.core.mail.backends.smtp.EmailBackend", host=c.get("host"), port=int(c.get("port") or 587),
                              username=c.get("username") or None, password=ServiceSecret.value_of(tenant_id, "smtp_password"),
                              use_tls=sec == "starttls", use_ssl=sec == "ssl", timeout=12)
        return conn, c.get("from_address"), "tenant"
    p = platform_conf(True)
    if not p["configured"]:
        return None, None, "serveur SMTP de la plateforme non configuré (Pilote › Configuration ou PLATFORM_EMAIL_HOST)"
    conn = get_connection("django.core.mail.backends.smtp.EmailBackend", host=p["host"], port=int(p["port"] or 587),
                          username=p["username"] or None, password=p["password"] or None,
                          use_tls=p["security"] == "starttls", use_ssl=p["security"] == "ssl", timeout=12)
    return conn, p["from_address"], "platform"


def log(tenant_id, event, channel, recipient, subject, status, error="", source=""):
    try:
        NotificationDelivery.objects.create(tenant_id=tenant_id, event=event[:30], channel=channel, recipient=str(recipient)[:254],
                                            subject=str(subject)[:200], status=status, error=str(error)[:300], source=source[:40])
    except Exception:  # le journal ne doit jamais bloquer un envoi
        logger.warning("Journal des notifications indisponible", exc_info=True)


# --------------------------------------------------------------------------- mise en forme
def render(title, body="", details=None, link=None, tenant_name="", event=""):
    """(texte, html) : en-tête, corps, détails clé/valeur, lien, pied de page."""
    details = [(k, v) for k, v in (details or {}).items() if v not in (None, "")]
    when = timezone.localtime().strftime("%d/%m/%Y %H:%M")
    text = [title, "=" * min(60, len(title)), ""]
    if body:
        text += [body, ""]
    text += [f"{k} : {v}" for k, v in details]
    if link:
        text += ["", f"Ouvrir : {link}"]
    text += ["", f"— {tenant_name or 'Project Control Tower'} · {EVENT_LABEL.get(event, 'Notification')} · {when}",
             "Vous recevez ce message selon vos préférences de notification (Mon accès › Notifications).",
             "Project Control Tower — © ZirconAI (https://zirconai.fr/)"]
    rows = "".join(f"<tr><td style='padding:4px 12px 4px 0;color:#64748b;white-space:nowrap;vertical-align:top'>{escape(str(k))}</td>"
                   f"<td style='padding:4px 0'>{escape(str(v))}</td></tr>" for k, v in details)
    body_html = "".join(f"<p style='margin:0 0 8px'>{escape(line)}</p>" for line in str(body).split("\n") if line.strip())
    html = (f"<div style='font-family:Segoe UI,Arial,sans-serif;background:#f1f5f9;padding:24px'>"
            f"<div style='max-width:620px;margin:auto;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #e2e8f0'>"
            f"<div style='background:#312e81;color:#fff;padding:14px 20px;font-size:13px'>{escape(tenant_name or 'Project Control Tower')}"
            f" · {escape(EVENT_LABEL.get(event, 'Notification'))}</div>"
            f"<div style='padding:20px'><h2 style='margin:0 0 12px;font-size:18px;color:#0f172a'>{escape(title)}</h2>{body_html}"
            + (f"<table style='font-size:13px;border-collapse:collapse;margin-top:8px'>{rows}</table>" if rows else "")
            + (f"<p style='margin:18px 0 0'><a href='{escape(link)}' style='background:#4f46e5;color:#fff;padding:9px 16px;border-radius:8px;"
               f"text-decoration:none;font-size:13px'>Ouvrir dans Project Control Tower</a></p>" if link else "")
            + f"</div><div style='padding:12px 20px;font-size:11px;color:#94a3b8;border-top:1px solid #f1f5f9'>{when} · Vous recevez ce message "
            f"selon vos préférences de notification.<br>Project Control Tower — © <a href='https://zirconai.fr/' style='color:#94a3b8'>ZirconAI</a></div>"
            f"</div></div>")
    return "\n".join(text), html


# --------------------------------------------------------------------------- envoi
def send_mail(tenant_id, recipients, subject, text, html=None, event="", wait=False):
    """Envoie un e-mail (un message par destinataire) et trace chaque envoi. `wait` : envoi synchrone (test)."""
    recipients = [r for r in dict.fromkeys(recipients or []) if r]
    if not recipients:
        return {"sent": 0, "failed": 0, "skipped": 0}

    def run():
        res = {"sent": 0, "failed": 0, "skipped": 0, "error": ""}
        try:
            conn, sender, source = _connection(tenant_id)
            if conn is None:
                for r in recipients:
                    log(tenant_id, event, "email", r, subject, "skipped", source, "tenant" if tenant_id else "platform")
                res["skipped"] = len(recipients)
                res["error"] = source
                return res
            for r in recipients:
                try:
                    msg = EmailMultiAlternatives(subject[:200], text, sender, [r], connection=conn)
                    if html:
                        msg.attach_alternative(html, "text/html")
                    msg.send()
                    log(tenant_id, event, "email", r, subject, "sent", "", source)
                    res["sent"] += 1
                except Exception as exc:  # noqa: BLE001
                    log(tenant_id, event, "email", r, subject, "failed", f"{type(exc).__name__}: {exc}"[:300], source)
                    res["failed"] += 1
                    res["error"] = f"{type(exc).__name__}"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Envoi e-mail impossible : %s", type(exc).__name__)
            res["error"] = type(exc).__name__
        finally:
            if not wait:
                close_old_connections()
        return res

    if wait:
        return run()
    threading.Thread(target=run, daemon=True).start()
    return {"queued": len(recipients)}


def _refused(users, event, channel):
    return set(UserNotificationPreference.objects.filter(user__in=users, event=event, channel=channel, enabled=False)
               .values_list("user_id", flat=True))


def dispatch(event, users, title, body="", *, project=None, details=None, link=None, actor=None, email=True, inapp=True):
    """Diffuse un événement système. Renvoie {inapp, email}. Ne lève jamais d'exception vers l'appelant."""
    try:
        actor_id = getattr(actor, "pk", None)
        people = {u.pk: u for u in users if u is not None and getattr(u, "is_active", False) and u.pk != actor_id}.values()
        people = list(people)
        if not people:
            return {"inapp": 0, "email": 0}
        prefix = f"[{project.code}] " if project is not None and not title.startswith("[") else ""
        full = f"{prefix}{title}"[:200]
        det = dict(details or {})
        if project is not None:
            det.setdefault("Projet", f"{project.name} ({project.code})")
        if actor is not None:
            det.setdefault("Par", actor.display_name)
        n_in = n_mail = 0
        if inapp:
            refused = _refused(people, event, "inapp")
            allowed = {t: inapp_allowed(t, event) for t in {u.tenant_id for u in people}}
            rows = [Notification(user=u, event=event, title=full, body=(body or "")[:1900] + (f" · {project.id}" if project is not None else ""))
                    for u in people if u.pk not in refused and allowed.get(u.tenant_id, True)]
            Notification.objects.bulk_create(rows)
            n_in = len(rows)
        if email:
            by_tenant = {}
            for u in people:
                by_tenant.setdefault(u.tenant_id, []).append(u)
            for tenant_id, members in by_tenant.items():
                if tenant_id and not email_allowed(tenant_id, event):
                    continue
                refused = _refused(members, event, "email")
                to = [u.email for u in members if u.email and u.pk not in refused]
                if not to:
                    continue
                tname = members[0].tenant.name if tenant_id and members[0].tenant_id else "Project Control Tower · Plateforme"
                text, html = render(full, body, det, link, tname, event)
                send_mail(tenant_id, to, full, text, html, event)
                n_mail += len(to)
        return {"inapp": n_in, "email": n_mail}
    except Exception:  # noqa: BLE001
        logger.warning("Notification %s non diffusée", event, exc_info=True)
        return {"inapp": 0, "email": 0}
