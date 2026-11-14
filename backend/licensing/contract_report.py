"""Pilote : reporting des contrats des entreprises clientes (dates de fin, jours restants, état) et relance
par e-mail du contact de l'entreprise et de ses administrateurs.

Échéance retenue : fin de l'abonnement en cours, sinon fin du contrat actif, sinon fin d'essai.
Envoi : serveur SMTP de la plateforme (PLATFORM_EMAIL_*). Sans serveur configuré, la relance est notifiée dans
l'application aux administrateurs de l'entreprise et le Pilote peut l'ouvrir dans sa propre messagerie.
"""
from datetime import date

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage, get_connection
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsPlatformAdmin, PasswordChangeNotRequired
from config.errors import ApiError
from configuration import audit
from configuration.models import AuditEvent
from tenants.models import Tenant

from .models import CURRENT, Contract, Subscription

User = get_user_model()
PILOT = [permissions.IsAuthenticated, PasswordChangeNotRequired, IsPlatformAdmin]
REMIND_EVENT = "Relance de contrat envoyée"


def _state(days):
    if days is None:
        return "open", "Sans échéance"
    if days < 0:
        return "expired", "Expiré"
    if days <= 30:
        return "soon", "Expire sous 30 jours"
    if days <= 90:
        return "watch", "Expire sous 90 jours"
    return "ok", "En cours"


def _recipients(tenant):
    emails = []
    if tenant.contact_email:
        emails.append(tenant.contact_email)
    for u in User.objects.filter(tenant=tenant, role_id="admin", is_active=True).exclude(email=""):
        if u.email.lower() not in {e.lower() for e in emails}:
            emails.append(u.email)
    return emails


def contract_rows():
    today = timezone.localdate()
    last = {}
    for ev in AuditEvent.objects.filter(event=REMIND_EVENT).order_by("-id")[:500]:
        key = getattr(ev, "tenant_id", None)
        if key and key not in last:
            last[key] = ev
    rows = []
    for t in Tenant.objects.all().order_by("name"):
        sub = Subscription.objects.filter(tenant=t, status__in=CURRENT).select_related("offer_version__offer", "contract").first()
        sub = sub or Subscription.objects.filter(tenant=t).select_related("offer_version__offer", "contract").order_by("-start_date").first()
        contract = (sub.contract if sub and sub.contract_id else None) or Contract.objects.filter(tenant=t).order_by("-start_date").first()
        end = (sub.end_date if sub else None) or (contract.end_date if contract else None) or (sub.trial_end if sub else None)
        days = (end - today).days if end else None
        st, label = _state(days)
        ev = last.get(t.id)
        offer = sub.offer_version.offer if sub else None
        rows.append({
            "tenant": t.id, "name": t.name, "slug": t.slug, "tenantStatus": t.status,
            "contact": t.contact_name, "contactEmail": t.contact_email, "recipients": _recipients(t),
            "contract": contract.reference if contract else None, "contractStatus": contract.get_status_display() if contract else None,
            "offer": f"{offer.name} v{sub.offer_version.number}" if offer else None,
            "subscriptionStatus": sub.get_status_display() if sub else "Aucun abonnement",
            "start": (sub.start_date if sub else (contract.start_date if contract else None)),
            "end": end, "trialEnd": sub.trial_end if sub else None, "daysLeft": days, "state": st, "stateLabel": label,
            "lastReminder": {"at": ev.at, "detail": ev.new_value} if ev else None,
        })
    order = {"expired": 0, "soon": 1, "watch": 2, "ok": 3, "open": 4}
    rows.sort(key=lambda r: (order[r["state"]], r["daysLeft"] if r["daysLeft"] is not None else 10 ** 6))
    return rows


def default_message(row):
    end = row["end"].strftime("%d/%m/%Y") if isinstance(row["end"], date) else "—"
    when = ("est arrivé à échéance le " + end) if (row["daysLeft"] is not None and row["daysLeft"] < 0) else \
        (f"arrive à échéance le {end} (dans {row['daysLeft']} jour(s))" if row["daysLeft"] is not None else "n'a pas de date de fin")
    subject = f"[Control Tower] Échéance de votre contrat — {row['name']}"
    body = (f"Bonjour{(' ' + row['contact']) if row['contact'] else ''},\n\n"
            f"Votre abonnement Control Tower ({row['offer'] or 'offre en cours'}"
            f"{', contrat ' + row['contract'] if row['contract'] else ''}) {when}.\n\n"
            "Pour assurer la continuité du service pour vos équipes, merci de nous indiquer si vous souhaitez le renouveler "
            "ou de nous contacter pour en discuter.\n\nBien cordialement,\nL'équipe Control Tower")
    return subject, body


def platform_smtp():
    if not getattr(settings, "PLATFORM_EMAIL_HOST", ""):
        return None
    sec = settings.PLATFORM_EMAIL_SECURITY
    return get_connection("django.core.mail.backends.smtp.EmailBackend", host=settings.PLATFORM_EMAIL_HOST,
                          port=settings.PLATFORM_EMAIL_PORT, username=settings.PLATFORM_EMAIL_USER or None,
                          password=settings.PLATFORM_EMAIL_PASSWORD or None, use_tls=sec == "starttls", use_ssl=sec == "ssl", timeout=10)


class ContractReportView(APIView):
    permission_classes = PILOT

    def get(self, request):
        rows = contract_rows()
        for r in rows:
            r["subject"], r["message"] = default_message(r)
        counts = {k: sum(1 for r in rows if r["state"] == k) for k in ("expired", "soon", "watch", "ok", "open")}
        return Response({"rows": rows, "counts": counts, "smtp": bool(getattr(settings, "PLATFORM_EMAIL_HOST", ""))})


class ContractRemindView(APIView):
    """POST {subject?, message?, to?: [emails]} : relance l'entreprise par e-mail (+ notification aux administrateurs)."""
    permission_classes = PILOT

    def post(self, request, tenant_id):
        from configuration.models import Notification
        tenant = get_object_or_404(Tenant, pk=tenant_id)
        row = next((r for r in contract_rows() if r["tenant"] == tenant.id), None)
        subject, body = default_message(row)
        subject = str(request.data.get("subject") or subject)[:200]
        body = str(request.data.get("message") or body)[:5000]
        to = [e for e in (request.data.get("to") or row["recipients"]) if isinstance(e, str) and "@" in e][:20]
        if not to:
            raise ApiError("VALIDATION_ERROR", "Aucune adresse : renseignez l'e-mail du contact de l'entreprise ou d'un administrateur.")
        sent, via = False, "inapp"
        conn = platform_smtp()
        if conn is not None:
            try:
                EmailMessage(subject, body, settings.PLATFORM_EMAIL_FROM or settings.PLATFORM_EMAIL_USER, to, connection=conn).send()
                sent, via = True, "email"
            except Exception as exc:  # pragma: no cover - dépend du serveur SMTP
                via = f"échec e-mail ({type(exc).__name__})"
        for u in User.objects.filter(tenant=tenant, role_id="admin", is_active=True):
            Notification.objects.create(user=u, event="key_date_reminder", title=subject[:200], body=body[:2000])
        audit.record(request.user, f"Entreprise {tenant.name}", REMIND_EVENT, "", f"{', '.join(to)} · {via}", tenant=tenant)
        return Response({"sent": sent, "via": via, "to": to, "subject": subject, "message": body})
