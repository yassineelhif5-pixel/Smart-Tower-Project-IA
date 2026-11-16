"""Invitations : le Pilote ou un administrateur invite une ou plusieurs personnes à créer leur compte.

Le lien reçu par e-mail prouve la possession de l'adresse : le compte créé avec ce lien (mot de passe ou Google)
est confirmé d'office. Une invitation d'entreprise rattache directement le compte à cette entreprise avec le
profil choisi ; une invitation du Pilote sans entreprise mène au parcours d'accueil (démo ou code entreprise).
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from html import escape

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework import status

from config.errors import ApiError
from configuration import audit

from .models import ADMIN_ROLE, Invitation, SignupProfile, TenantMembership

User = get_user_model()
VALID_DAYS = 14
MAX_PER_BATCH = 50

MODULE_PITCH = [
    ("📁", "Projets & portefeuille", "Suivi complet des projets, jalons, risques, actions et décisions."),
    ("🗓️", "Planning & capacité", "Gantt, charge des équipes, disponibilité des ressources."),
    ("⏱️", "Saisie des temps & CRA", "Feuilles de temps, validation multi-niveaux, CRA et factures en PDF."),
    ("💶", "Budget & facturation", "Budget consommé, TJM, rapports mensuels de consommation."),
    ("🤝", "Espace client", "Portail client : validation, documents, reporting et licences."),
    ("📄", "Documents & méthodologie", "Bibliothèque documentaire, modèles et cadre méthodologique."),
    ("👥", "Collaboration", "Discussions, notifications et récapitulatifs hebdomadaires par e-mail."),
    ("📊", "Reporting", "Tableaux de bord et exports pour la direction et les clients."),
]


def _hash(token):
    return hashlib.sha256(str(token).encode()).hexdigest()


def status_of(inv):
    if inv.accepted_at:
        return "accepted"
    if inv.revoked_at:
        return "revoked"
    if inv.expires_at < timezone.now():
        return "expired"
    return "pending"


STATUS_LABEL = {"accepted": "Compte créé", "revoked": "Révoquée", "expired": "Expirée", "pending": "Envoyée"}


def row(inv):
    st = status_of(inv)
    return {"id": inv.pk, "email": inv.email, "tenant": inv.tenant.name if inv.tenant_id else None,
            "role": inv.role.label if inv.role_id else None, "status": st, "statusLabel": STATUS_LABEL[st],
            "invitedBy": inv.invited_by.display_name if inv.invited_by_id else "", "createdAt": inv.created_at,
            "sentAt": inv.sent_at, "expiresAt": inv.expires_at, "acceptedAt": inv.accepted_at,
            "acceptedUser": inv.accepted_user.display_name if inv.accepted_user_id else None}


# --------------------------------------------------------------------------- e-mail commercial
def _email(inv, link):
    inviter = inv.invited_by.display_name if inv.invited_by_id else "L'équipe ZirconAI"
    where = f"l'espace de <b>{escape(inv.tenant.name)}</b>" if inv.tenant_id else "<b>Project Control Tower</b>"
    where_txt = f"l'espace de {inv.tenant.name}" if inv.tenant_id else "Project Control Tower"
    subject = (f"{inviter} vous invite à rejoindre {inv.tenant.name} sur Control Tower" if inv.tenant_id
               else f"{inviter} vous invite à découvrir Project Control Tower")
    personal = (f"<blockquote style='margin:14px 0;padding:10px 14px;border-left:3px solid #6366f1;background:#f5f3ff;"
                f"color:#334155;font-style:italic'>{escape(inv.message)}</blockquote>") if inv.message else ""
    modules = "".join(
        f"<td style='width:50%;padding:8px;vertical-align:top'><div style='font-size:20px'>{icon}</div>"
        f"<div style='font-weight:700;color:#0f172a;font-size:14px'>{escape(t)}</div>"
        f"<div style='color:#64748b;font-size:12px'>{escape(d)}</div></td>"
        + ("</tr><tr>" if i % 2 == 1 and i < len(MODULE_PITCH) - 1 else "")
        for i, (icon, t, d) in enumerate(MODULE_PITCH))
    pillars = [
        ("🇪🇺", "Vos données restent en Europe",
         "Hébergement et base de données dans l'Union européenne (Irlande), chiffrement des échanges, "
         "cloisonnement strict entre entreprises et conformité RGPD."),
        ("🤖", "Une IA au service de vos projets",
         "Assistants intelligents intégrés pour analyser, résumer et préparer vos reportings ; "
         "vous gardez la main sur leur utilisation et sur vos données."),
        ("🎁", "Un accompagnement offert",
         "Nos experts vous accompagnent gratuitement dans la prise en main : paramétrage, import de vos projets "
         "et bonnes pratiques de pilotage."),
    ]
    pill_html = "".join(
        f"<tr><td style='padding:8px 12px 8px 0;font-size:22px;vertical-align:top'>{i}</td>"
        f"<td style='padding:8px 0'><div style='font-weight:700;color:#0f172a'>{escape(t)}</div>"
        f"<div style='color:#475569;font-size:13px'>{escape(d)}</div></td></tr>" for i, t, d in pillars)
    trial = ("" if inv.tenant_id else
             "<p style='margin:14px 0 0;color:#334155'>Dès votre inscription, profitez d'une <b>démo complète de 3 jours</b> "
             "(tous les modules), ou rejoignez l'espace de votre entreprise avec son code.</p>")
    html = f"""<div style="font-family:Segoe UI,Arial,sans-serif;background:#eef2ff;padding:24px">
<div style="max-width:640px;margin:auto;background:#fff;border-radius:16px;overflow:hidden;border:1px solid #e0e7ff">
 <div style="background:linear-gradient(120deg,#312e81,#6d28d9);color:#fff;padding:28px 28px 24px">
  <div style="font-size:12px;letter-spacing:2px;text-transform:uppercase;opacity:.8">Project Control Tower · by ZirconAI</div>
  <h1 style="margin:10px 0 6px;font-size:24px;line-height:1.25">Pilotez vos projets, vos équipes et vos clients depuis une seule tour de contrôle.</h1>
  <p style="margin:0;opacity:.9;font-size:14px">{escape(inviter)} vous invite à rejoindre {where}.</p>
 </div>
 <div style="padding:24px 28px">
  {personal}
  <p style="margin:0 0 10px;color:#334155">Control Tower est la plateforme SaaS de pilotage de projets conçue par ZirconAI pour les ESN, cabinets
  de conseil et directions de projets : une vision claire de l'avancement, des temps, des budgets et de la relation client.</p>
  <p style="text-align:center;margin:22px 0">
   <a href="{escape(link)}" style="background:#4f46e5;color:#fff;padding:13px 26px;border-radius:10px;text-decoration:none;font-weight:700;font-size:15px;display:inline-block">Créer mon compte</a>
  </p>
  {trial}
  <h3 style="margin:26px 0 6px;color:#0f172a;font-size:16px">Tout ce dont vos projets ont besoin</h3>
  <table style="width:100%;border-collapse:collapse"><tr>{modules}</tr></table>
  <h3 style="margin:22px 0 6px;color:#0f172a;font-size:16px">Pourquoi Control Tower ?</h3>
  <table style="border-collapse:collapse">{pill_html}</table>
  <p style="text-align:center;margin:24px 0 6px">
   <a href="{escape(link)}" style="color:#4f46e5;font-weight:700;text-decoration:none">Accepter l'invitation →</a>
  </p>
  <p style="margin:0;color:#94a3b8;font-size:12px;text-align:center">Lien personnel valable {VALID_DAYS} jours, réservé à {escape(inv.email)}.</p>
 </div>
 <div style="padding:14px 28px;font-size:11px;color:#94a3b8;border-top:1px solid #eef2ff">
  Vous recevez cet e-mail car {escape(inviter)} vous a invité sur Project Control Tower. Si vous ne souhaitez pas créer de compte, ignorez simplement ce message.<br>
  Project Control Tower — © <a href="https://zirconai.fr/" style="color:#94a3b8">ZirconAI</a>
 </div>
</div></div>"""
    text = "\n".join([
        subject, "",
        f"{inviter} vous invite à rejoindre {where_txt}.",
        *([f"Message : {inv.message}"] if inv.message else []), "",
        "Control Tower est la plateforme SaaS de pilotage de projets conçue par ZirconAI.", "",
        "Modules : " + ", ".join(t for _, t, _ in MODULE_PITCH) + ".", "",
        "- Vos données restent en Europe (hébergement UE, RGPD).",
        "- Une IA au service de vos projets.",
        "- Un accompagnement offert à la prise en main.", "",
        f"Créer mon compte : {link}",
        f"(lien personnel valable {VALID_DAYS} jours)", "",
        "Project Control Tower — © ZirconAI (https://zirconai.fr/)",
    ])
    return subject, text, html


def _send(inv, token, base_url):
    from configuration.mailer import send_mail
    link = f"{base_url.rstrip('/')}/?invite={token}"
    subject, text, html = _email(inv, link)
    res = send_mail(None, [inv.email], subject, text, html, event="invitation", wait=True)
    inv.sent_at = timezone.now()
    inv.save(update_fields=["sent_at"])
    return res


# --------------------------------------------------------------------------- création
def parse_emails(raw):
    from .signup import normalize_email
    if isinstance(raw, str):
        raw = raw.replace(";", ",").replace("\n", ",").split(",")
    emails, invalid = [], []
    for item in raw or []:
        item = str(item).strip()
        if not item:
            continue
        try:
            e = normalize_email(item)
        except ApiError:
            invalid.append(item)
            continue
        if e not in emails:
            emails.append(e)
    return emails, invalid


def invite(*, by, emails_raw, base_url, tenant=None, role_code="", message=""):
    from .signup import assignable_roles
    emails, invalid = parse_emails(emails_raw)
    if invalid:
        raise ApiError("VALIDATION_ERROR", "Adresse(s) invalide(s) : " + ", ".join(invalid[:5]))
    if not emails:
        raise ApiError("VALIDATION_ERROR", "Indiquez au moins une adresse e-mail.")
    if len(emails) > MAX_PER_BATCH:
        raise ApiError("VALIDATION_ERROR", f"{MAX_PER_BATCH} invitations maximum par envoi.")
    role = None
    if tenant is not None:
        role = assignable_roles(tenant).filter(code=role_code or "").first()
        if role is None:
            raise ApiError("VALIDATION_ERROR", "Choisissez le profil des personnes invitées.")
        if role.code == ADMIN_ROLE and not (by.is_platform_admin or by.is_app_admin):
            raise ApiError("FORBIDDEN_PERMISSION", "Seul un administrateur peut inviter un administrateur.", status.HTTP_403_FORBIDDEN)
    sent, skipped = [], []
    for email in emails:
        existing = User.objects.filter(email__iexact=email).first()
        if existing is not None and (tenant is None or existing.tenant_id == tenant.pk
                                     or TenantMembership.objects.filter(user=existing, tenant=tenant).exists()):
            skipped.append({"email": email, "reason": "a déjà un compte" if tenant is None else "a déjà accès à l'entreprise"})
            continue
        # Une invitation encore valide pour la même adresse et la même entreprise est remplacée.
        Invitation.objects.filter(email__iexact=email, tenant=tenant, accepted_at__isnull=True, revoked_at__isnull=True).update(revoked_at=timezone.now())
        token = secrets.token_urlsafe(32)
        inv = Invitation.objects.create(email=email, tenant=tenant, role=role, message=str(message or "").strip()[:1000],
                                        token_hash=_hash(token), invited_by=by, expires_at=timezone.now() + timedelta(days=VALID_DAYS))
        try:
            _send(inv, token, base_url)
        except Exception:  # noqa: BLE001 — l'invitation reste visible et peut être renvoyée
            pass
        sent.append(row(inv))
    audit.record(by, "Invitations", "Personnes invitées", "", f"{len(sent)} envoyée(s) · {tenant.name if tenant else 'plateforme'}",
                 tenant=tenant)
    return {"sent": sent, "skipped": skipped}


def resend(by, inv, base_url):
    if status_of(inv) in ("accepted", "revoked"):
        raise ApiError("VALIDATION_ERROR", "Cette invitation ne peut plus être renvoyée.")
    token = secrets.token_urlsafe(32)
    inv.token_hash, inv.expires_at = _hash(token), timezone.now() + timedelta(days=VALID_DAYS)
    inv.save(update_fields=["token_hash", "expires_at"])
    _send(inv, token, base_url)
    return inv


def revoke(inv):
    if inv.accepted_at:
        raise ApiError("VALIDATION_ERROR", "Le compte a déjà été créé.")
    inv.revoked_at = timezone.now()
    inv.save(update_fields=["revoked_at"])
    return inv


# --------------------------------------------------------------------------- acceptation
def find(token):
    if not token:
        return None
    inv = Invitation.objects.select_related("tenant", "role", "invited_by").filter(token_hash=_hash(token)).first()
    if inv is None or status_of(inv) != "pending":
        return None
    return inv


def public_info(token):
    inv = find(token)
    if inv is None:
        return {"valid": False}
    return {"valid": True, "email": inv.email, "tenant": inv.tenant.name if inv.tenant_id else None,
            "invitedBy": inv.invited_by.display_name if inv.invited_by_id else "ZirconAI", "message": inv.message}


@transaction.atomic
def accept(inv, user):
    """Le compte (nouveau ou existant) de la personne invitée : adresse confirmée et rattachement éventuel."""
    inv = Invitation.objects.select_for_update().select_related("tenant", "role").get(pk=inv.pk)
    if status_of(inv) != "pending" or inv.email.lower() != (user.email or "").lower():
        return False
    profile, _ = SignupProfile.objects.get_or_create(user=user, defaults={"source": "password"})
    profile.email_verified = True
    if inv.tenant_id:
        profile.profile_done = True
    profile.save()
    if inv.tenant_id and user.tenant_id != inv.tenant_id:
        from licensing import services as lic
        try:
            lic.check_user_quota(inv.tenant)
        except lic.LicenseError:
            # Plus de place dans l'entreprise : on passe par une demande d'adhésion que l'admin traitera.
            from .models import TenantJoinRequest
            TenantJoinRequest.objects.get_or_create(user=user, tenant=inv.tenant, status=TenantJoinRequest.PENDING,
                                                    defaults={"message": "Invitation acceptée (quota d'utilisateurs atteint)."})
        else:
            if user.tenant_id:
                from .tenant_switch import ensure_home_membership
                ensure_home_membership(user)
            TenantMembership.objects.update_or_create(user=user, tenant=inv.tenant, defaults={"role": inv.role, "granted_by": inv.invited_by})
            user.tenant, user.role, user.client = inv.tenant, inv.role, None
            user.save(update_fields=["tenant", "role", "client"])
    inv.accepted_at, inv.accepted_user = timezone.now(), user
    inv.save(update_fields=["accepted_at", "accepted_user"])
    audit.record(user, f"Invitation {inv.email}", "Invitation acceptée", "", inv.tenant.name if inv.tenant_id else "plateforme",
                 tenant=inv.tenant)
    return True
