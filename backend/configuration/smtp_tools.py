"""Configuration SMTP par défaut et test détaillé (journal OK / KO avec l'erreur renvoyée par le serveur)."""
import smtplib
import socket

from django.conf import settings
from django.utils import timezone

from .models import NotificationChannel, NotificationDelivery, ServiceSecret

TEST_EVENT = "smtp_test"


def apply_defaults(tenant):
    """Complète le canal e-mail d'une entreprise avec la configuration par défaut (.env) sans écraser une saisie :
    serveur/identifiant si absents (ou identifiant de l'ancien défaut Brevo), clé SMTP chiffrée si aucune n'est enregistrée."""
    d = dict(getattr(settings, "DEFAULT_SMTP_SETTINGS", {}) or {})
    ch, _ = NotificationChannel.objects.get_or_create(tenant=tenant, kind="email", defaults={"enabled": False, "settings": {}})
    s = dict(ch.settings or {})
    changed = False
    has_secret = ServiceSecret.objects.filter(tenant=tenant, key="smtp_password").exists()
    if not s.get("host"):
        s.update({k: v for k, v in d.items() if v})
        changed = True
    elif (s.get("host") == d.get("host") and d.get("username") and s.get("username") != d.get("username")
          and (not has_secret or ServiceSecret.value_of(tenant, "smtp_password") == getattr(settings, "DEFAULT_SMTP_PASSWORD", ""))):
        s["username"] = d["username"]  # identifiant de connexion Brevo (≠ adresse d'expédition)
        changed = True
    for k in ("port", "security", "from_address"):
        if not s.get(k) and d.get(k):
            s[k] = d[k]
            changed = True
    if changed:
        ch.settings = s
        ch.save(update_fields=["settings"])
    pwd = getattr(settings, "DEFAULT_SMTP_PASSWORD", "")
    if pwd and not has_secret and s.get("host") == d.get("host"):
        row = ServiceSecret(tenant=tenant, key="smtp_password")
        row.set_value(pwd)
        row.save()
    return ch


def _conf(tenant_id):
    if tenant_id:
        ch = NotificationChannel.objects.filter(tenant_id=tenant_id, kind="email").first()
        c = (ch.settings if ch else {}) or {}
        return {"host": c.get("host"), "port": int(c.get("port") or 587), "security": c.get("security", "starttls"),
                "username": c.get("username") or "", "password": ServiceSecret.value_of(tenant_id, "smtp_password") or "",
                "from": c.get("from_address") or ""}
    from .mailer import platform_conf
    p = platform_conf(True)
    return {"host": p["host"], "port": p["port"], "security": p["security"], "username": p["username"], "password": p["password"],
            "from": p["from_address"]}


def _err(exc):
    code = getattr(exc, "smtp_code", None)
    msg = getattr(exc, "smtp_error", None)
    if isinstance(msg, bytes):
        msg = msg.decode("utf-8", "replace")
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        first = next(iter(exc.recipients.values()), (None, b""))
        code, msg = first[0], first[1].decode("utf-8", "replace") if isinstance(first[1], bytes) else first[1]
    text = f"{type(exc).__name__}" + (f" {code}" if code else "") + f" : {msg or exc}"
    return code, text[:300]


def test(tenant_id, to=None, by=None):
    """Connexion + authentification (+ envoi si `to`). Renvoie {ok, step, code, error, at} et l'enregistre dans le journal."""
    c = _conf(tenant_id)
    res = {"ok": False, "step": "configuration", "code": None, "error": "", "at": timezone.now(), "server": f"{c['host']}:{c['port']}"}
    try:
        if not c["host"]:
            raise ValueError("serveur SMTP non renseigné")
        res["step"] = "connexion"
        if c["security"] == "ssl":
            srv = smtplib.SMTP_SSL(c["host"], c["port"], timeout=12)
        else:
            srv = smtplib.SMTP(c["host"], c["port"], timeout=12)
        try:
            srv.ehlo()
            if c["security"] == "starttls":
                res["step"] = "chiffrement STARTTLS"
                srv.starttls()
                srv.ehlo()
            if c["username"]:
                res["step"] = "authentification"
                if not c["password"]:
                    raise ValueError("clé SMTP (mot de passe) non renseignée")
                srv.login(c["username"], c["password"])
            if to:
                res["step"] = "envoi"
                from email.message import EmailMessage
                from .mailer import app_url, render
                tname = "Project Control Tower"
                if tenant_id:
                    from tenants.models import Tenant
                    tname = getattr(Tenant.objects.filter(pk=tenant_id).first(), "name", tname)
                text, html = render("Notification de test — Project Control Tower",
                                    "Ceci est une notification envoyée par le socle de notifications, avec la même mise en page que les "
                                    "notifications réelles (actions, échéances, demandes de licence, récap hebdomadaire…).",
                                    {"Serveur": f"{c['host']}:{c['port']}", "Expéditeur": c["from"] or c["username"], "Destinataire": to},
                                    app_url(), tname, "action_assigned")
                m = EmailMessage()
                m["Subject"] = f"[{tname}] Notification de test — Project Control Tower"
                m["From"] = c["from"] or c["username"]
                m["To"] = to
                m.set_content(text)
                m.add_alternative(html, subtype="html")
                srv.send_message(m)
            res.update(ok=True, step="envoi" if to else "authentification", error="")
        finally:
            try:
                srv.quit()
            except Exception:  # noqa: BLE001
                pass
    except (smtplib.SMTPException, socket.error, OSError, ValueError) as exc:
        res["code"], res["error"] = _err(exc) if isinstance(exc, smtplib.SMTPException) else (None, f"{type(exc).__name__} : {exc}"[:300])
    NotificationDelivery.objects.create(tenant_id=tenant_id, event=TEST_EVENT, channel="email", recipient=to or "(test de connexion)",
                                        subject=f"Test SMTP {res['server']} · étape : {res['step']}" + (f" · par {by.display_name}" if by else ""),
                                        status="sent" if res["ok"] else "failed", error=res["error"], source="tenant" if tenant_id else "platform")
    return res


def history(tenant_id, limit=10):
    qs = NotificationDelivery.objects.filter(event=TEST_EVENT)
    qs = qs.filter(tenant_id=tenant_id) if tenant_id else qs.filter(tenant__isnull=True)
    return [{"at": d.at, "ok": d.status == "sent", "recipient": d.recipient, "subject": d.subject, "error": d.error} for d in qs.order_by("-at")[:limit]]
