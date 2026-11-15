"""Socle de notifications : configuration d'envoi visible par l'administrateur (son entreprise) et le Pilote (toutes).

GET  /admin/notifications/deliveries                 journal des envois de l'entreprise (?status=failed)
GET  /platform/notifications                         serveur SMTP de la plateforme + journal des envois plateforme
POST /platform/notifications/test                    {to} e-mail de test via le SMTP plateforme
GET  /platform/tenants/<id>/notifications            configuration e-mail, règles et journal d'une entreprise
PUT  /platform/tenants/<id>/notifications/email      {enabled, settings{host,port,security,username,from_address}, password?}
POST /platform/tenants/<id>/notifications/test       {to} e-mail de test via le SMTP de l'entreprise
"""
from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from config.errors import ApiError

from . import audit
from .mailer import DEFAULT_EMAIL_EVENTS, EVENT_LABEL, platform_smtp, render, send_mail
from .models import NotificationChannel, NotificationDelivery, ServiceSecret
from .views import AdminView, PlatformView, notifications_state


def deliveries(tenant_id, request, platform=False):
    qs = NotificationDelivery.objects.filter(tenant__isnull=True) if platform else NotificationDelivery.objects.filter(tenant_id=tenant_id)
    st = request.query_params.get("status")
    if st in ("sent", "failed", "skipped"):
        qs = qs.filter(status=st)
    since = timezone.now() - timedelta(days=7)
    base = NotificationDelivery.objects.filter(tenant__isnull=True) if platform else NotificationDelivery.objects.filter(tenant_id=tenant_id)
    stats = {s: base.filter(at__gte=since, status=s).count() for s in ("sent", "failed", "skipped")}
    return {"stats7d": stats, "rows": [{"at": d.at, "event": d.event, "eventLabel": EVENT_LABEL.get(d.event, d.event or "—"), "channel": d.channel,
                                        "recipient": d.recipient, "subject": d.subject, "status": d.status, "error": d.error, "source": d.source}
                                       for d in qs[:150]]}


def email_conf(tenant):
    ch = NotificationChannel.objects.filter(tenant=tenant, kind="email").first()
    sec = ServiceSecret.objects.filter(tenant=tenant, key="smtp_password").first()
    s = (ch.settings if ch else {}) or {}
    return {"enabled": bool(ch and ch.enabled), "host": s.get("host", ""), "port": s.get("port", 587), "security": s.get("security", "starttls"),
            "username": s.get("username", ""), "from_address": s.get("from_address", ""), "passwordSet": bool(sec),
            "passwordHint": sec.hint if sec else "", "updatedAt": ch.updated_at if ch else None}


class AdminDeliveriesView(AdminView):
    def get(self, request):
        return Response({**deliveries(self.tenant.pk, request), "email": email_conf(self.tenant),
                         "platform": {"configured": platform_smtp()["configured"]}, "defaultEmailEvents": sorted(DEFAULT_EMAIL_EVENTS)})


class PlatformNotificationsView(PlatformView):
    def get(self, request):
        return Response({"smtp": platform_smtp(), **deliveries(None, request, platform=True)})


class PlatformTestView(PlatformView):
    """Test du SMTP plateforme : connexion + authentification, et envoi si une adresse est fournie. Résultat détaillé."""

    def post(self, request):
        from . import smtp_tools
        to = str((request.data or {}).get("to") or "").strip()
        if to and "@" not in to:
            raise ApiError("VALIDATION_ERROR", "Adresse e-mail invalide.")
        res = smtp_tools.test(None, to or None, request.user)
        audit.record(request.user, "Notifications plateforme", "Test SMTP", "", f"{'OK' if res['ok'] else 'KO'} · {res['step']} {res['error']}", tenant=None)
        return Response({**res, "history": smtp_tools.history(None)})


def _tenant(pk):
    from tenants.models import Tenant
    return get_object_or_404(Tenant, pk=pk)


class PilotTenantNotificationsView(PlatformView):
    def get(self, request, tenant_id):
        t = _tenant(tenant_id)
        st = notifications_state(t)
        from . import smtp_tools
        smtp_tools.apply_defaults(t)
        return Response({"tenant": {"id": t.pk, "name": t.name}, "email": email_conf(t), "events": st["events"], "rules": st["rules"],
                         "smtpTests": smtp_tools.history(t.pk), **deliveries(t.pk, request)})


class PilotTenantEmailView(PlatformView):
    def put(self, request, tenant_id):
        t = _tenant(tenant_id)
        d = request.data or {}
        s = d.get("settings") or {}
        host = str(s.get("host") or "").strip()
        sender = str(s.get("from_address") or "").strip()
        if d.get("enabled") and (not host or "@" not in sender):
            raise ApiError("VALIDATION_ERROR", "Serveur SMTP et adresse d'expédition obligatoires pour activer l'envoi.")
        try:
            port = int(s.get("port") or 587)
        except (TypeError, ValueError):
            raise ApiError("VALIDATION_ERROR", "Port invalide.")
        sec = s.get("security") if s.get("security") in ("starttls", "ssl", "none") else "starttls"
        ch, _ = NotificationChannel.objects.get_or_create(tenant=t, kind="email")
        ch.settings = {"host": host, "port": port, "security": sec, "username": str(s.get("username") or "").strip(), "from_address": sender}
        ch.enabled = bool(d.get("enabled"))
        ch.save()
        if d.get("password"):
            row = ServiceSecret.objects.filter(tenant=t, key="smtp_password").first() or ServiceSecret(tenant=t, key="smtp_password")
            row.set_value(str(d["password"]))
            row.updated_by = request.user
            row.save()
        audit.record(request.user, f"Entreprise {t.name}", "Configuration e-mail modifiée par le Pilote", "",
                     f"{host}:{port} · {'active' if ch.enabled else 'inactive'}" + (" · clé SMTP mise à jour" if d.get("password") else ""), tenant=t)
        return PilotTenantNotificationsView().get(request, tenant_id)


class PilotTenantTestView(PlatformView):
    def post(self, request, tenant_id):
        from . import smtp_tools
        t = _tenant(tenant_id)
        to = str((request.data or {}).get("to") or "").strip()
        if to and "@" not in to:
            raise ApiError("VALIDATION_ERROR", "Adresse e-mail invalide.")
        res = smtp_tools.test(t.pk, to or None, request.user)
        audit.record(request.user, f"Entreprise {t.name}", "Test SMTP (Pilote)", "", f"{'OK' if res['ok'] else 'KO'} · {res['step']} {res['error']}", tenant=t)
        return Response({**res, "history": smtp_tools.history(t.pk)})


class AdminSmtpTestView(AdminView):
    """GET : historique des tests SMTP ; POST {to?} : test de connexion (et envoi si adresse) avec l'erreur renvoyée."""

    def get(self, request):
        from . import smtp_tools
        smtp_tools.apply_defaults(self.tenant)
        return Response({"history": smtp_tools.history(self.tenant.pk)})

    def post(self, request):
        from . import smtp_tools
        to = str((request.data or {}).get("to") or "").strip()
        if to and "@" not in to:
            raise ApiError("VALIDATION_ERROR", "Adresse e-mail invalide.")
        smtp_tools.apply_defaults(self.tenant)
        res = smtp_tools.test(self.tenant.pk, to or None, request.user)
        audit.record(request.user, "Canal E-mail (SMTP)", "Test SMTP", "", f"{'OK' if res['ok'] else 'KO'} · {res['step']} {res['error']}")
        return Response({**res, "history": smtp_tools.history(self.tenant.pk)})


class PlatformConfigView(PlatformView):
    """GET/PUT /platform/config : URL publique de l'application (liens des e-mails) et état du SMTP plateforme."""

    def get(self, request):
        from django.conf import settings as dj
        from .mailer import APP_URL_KEY, LOCAL_URL, app_url, app_url_source
        from .models import PlatformSetting
        row = PlatformSetting.objects.filter(key=APP_URL_KEY).select_related("updated_by").first()
        return Response({"appUrl": (row.value or {}).get("url", "") if row else "", "effectiveUrl": app_url(), "source": app_url_source(),
                         "envUrl": getattr(dj, "APP_PUBLIC_URL", ""), "localUrl": LOCAL_URL,
                         "updatedBy": row.updated_by.display_name if row and row.updated_by else "", "updatedAt": row.updated_at if row else None,
                         "smtp": platform_smtp(), "smtpTests": __import__("configuration.smtp_tools", fromlist=["history"]).history(None)})

    def put(self, request):
        from .mailer import APP_URL_KEY, valid_url
        from .models import PlatformSetting
        raw = str((request.data or {}).get("appUrl") or "").strip()
        url = valid_url(raw)
        if raw and not url:
            raise ApiError("VALIDATION_ERROR", "URL invalide : elle doit commencer par http:// ou https:// (ex. https://app.mondomaine.fr).")
        row, _ = PlatformSetting.objects.get_or_create(key=APP_URL_KEY)
        old = (row.value or {}).get("url", "")
        row.value = {"url": url}
        row.updated_by = request.user
        row.save()
        audit.record(request.user, "Configuration de la plateforme", "URL publique de l'application", old, url or "(vide : localhost)", tenant=None)
        return self.get(request)


class AdminWhoAmIView(AdminView):
    """GET /admin/whoami : profil d'administration effectif (utilisé par le Pilote dans le menu Configuration)."""

    def get(self, request):
        from accounts.serializers import MeSerializer
        data = MeSerializer(request.user, context={"request": request}).data
        data["pilotMode"] = bool(getattr(request.user, "pilot_mode", False))
        return Response(data)


class PlatformSmtpView(PlatformView):
    """PUT /platform/config/smtp {host, port, security, username, from_address, password?} ; {reset: true} → retour au .env."""

    def put(self, request):
        from . import crypto
        from .mailer import PLATFORM_SMTP_KEY
        from .models import PlatformSetting
        d = request.data or {}
        row, _ = PlatformSetting.objects.get_or_create(key=PLATFORM_SMTP_KEY)
        if d.get("reset"):
            row.value = {}
            row.updated_by = request.user
            row.save()
            audit.record(request.user, "Configuration de la plateforme", "SMTP plateforme : retour au fichier .env", "", "", tenant=None)
            return PlatformConfigView().get(request)
        host = str(d.get("host") or "").strip()
        if not host:
            raise ApiError("VALIDATION_ERROR", "Serveur SMTP obligatoire.")
        try:
            port = int(d.get("port") or 587)
        except (TypeError, ValueError):
            raise ApiError("VALIDATION_ERROR", "Port invalide.")
        old = dict(row.value or {})
        v = {"host": host, "port": port, "security": d.get("security") if d.get("security") in ("starttls", "ssl", "none") else "starttls",
             "username": str(d.get("username") or "").strip(), "from_address": str(d.get("from_address") or "").strip(),
             "password": old.get("password", ""), "hint": old.get("hint", "")}
        if d.get("password"):
            v["password"] = crypto.encrypt(str(d["password"]))
            v["hint"] = str(d["password"])[-4:] if len(str(d["password"])) >= 8 else ""
        row.value = v
        row.updated_by = request.user
        row.save()
        audit.record(request.user, "Configuration de la plateforme", "SMTP plateforme modifié", "",
                     f"{host}:{port}" + (" · clé SMTP mise à jour" if d.get("password") else ""), tenant=None)
        return PlatformConfigView().get(request)
