"""Inscription libre, vérification de l'e-mail et parcours d'accueil.

Un compte créé librement (mot de passe ou Google) n'appartient d'abord à aucune entreprise. À la première
connexion, l'utilisateur renseigne son profil puis choisit :
- une démo : un tenant « demo-<identifiant> » dont il est administrateur, tous modules, 2 projets, 3 jours ;
- rejoindre une entreprise existante avec son code secret : l'admin de l'entreprise ou le Pilote valide.
À la fin de la démo, il active une licence (voucher ou demande au Pilote) ou rejoint une autre entreprise.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status

from config.errors import ApiError
from configuration import audit

from .models import ADMIN_ROLE, PLATFORM_ROLE, Role, SignupProfile, TenantJoinRequest, TenantMembership

User = get_user_model()

DEMO_OFFER = "demo-inscription"  # offre dédiée aux démos des comptes inscrits
DEMO_DAYS = 3
DEMO_MAX_PROJECTS = 2
DEMO_SEATS = 5
VERIFY_HOURS = 48
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _hash(token):
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def today():
    return timezone.localdate()


# --------------------------------------------------------------------------- e-mails
def _send(email, subject, title, body, link=None, details=None):
    from configuration.mailer import render, send_mail
    text, html = render(title, body, details=details, link=link)
    # Envoi synchrone : sur un hébergement serverless, un fil d'exécution en arrière-plan peut être interrompu.
    return send_mail(None, [email], subject, text, html, event="signup", wait=True)


def _verify_link(token):
    from configuration.mailer import app_url
    return f"{app_url().rstrip('/')}/api/v1/auth/signup/verify?token={token}"


def send_verification(profile):
    token = secrets.token_urlsafe(32)
    profile.verify_hash = _hash(token)
    profile.verify_sent_at = timezone.now()
    profile.save(update_fields=["verify_hash", "verify_sent_at"])
    user = profile.user
    from django.conf import settings
    if settings.DEBUG:  # développement : lien lisible dans le journal pour tester sans boîte mail
        import logging
        logging.getLogger("accounts.signup").info("Lien de confirmation (DEBUG) pour %s : %s", user.email, _verify_link(token))
    return _send(user.email, "Confirmez votre adresse e-mail · Control Tower",
                 f"Bienvenue {user.first_name or ''}".strip(),
                 "Confirmez votre adresse e-mail pour activer votre compte Control Tower. "
                 f"Le lien est valable {VERIFY_HOURS} heures.",
                 link=_verify_link(token))


# --------------------------------------------------------------------------- inscription
def normalize_email(value):
    email = str(value or "").strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 150:
        raise ApiError("VALIDATION_ERROR", "Adresse e-mail invalide.", details=[{"field": "email", "message": "Adresse e-mail invalide."}])
    return email


def unique_username(email):
    base = email[:150]
    candidate, n = base, 1
    while User.objects.filter(username__iexact=candidate).exists():
        n += 1
        tail = f"-{n}"
        candidate = base[:150 - len(tail)] + tail
    return candidate


def register(*, email, password, first_name, last_name):
    """Crée un compte (sans entreprise) et envoie le lien de confirmation. Ne révèle pas si l'adresse existe déjà."""
    from .serializers import validate_new_password
    email = normalize_email(email)
    first_name, last_name = str(first_name or "").strip()[:150], str(last_name or "").strip()[:150]
    if not first_name or not last_name:
        raise ApiError("VALIDATION_ERROR", "Indiquez votre prénom et votre nom.")
    existing = User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).first()
    if existing is not None:
        profile = SignupProfile.objects.filter(user=existing).first()
        if profile and not profile.email_verified:
            send_verification(profile)
        else:
            _send(email, "Vous avez déjà un compte · Control Tower", "Vous avez déjà un compte",
                  "Une inscription a été demandée avec cette adresse, mais un compte existe déjà. "
                  "Connectez-vous, ou utilisez « Mot de passe oublié ? » sur la page de connexion.")
        return
    user = User(username=unique_username(email), email=email, first_name=first_name, last_name=last_name,
                is_active=True, auth_mode="standard")
    validate_new_password(password, user, field="password")
    user.set_password(password)
    try:
        with transaction.atomic():
            user.save()
            profile = SignupProfile.objects.create(user=user, source="password")
    except IntegrityError:
        return
    audit.record(None, f"Utilisateur {user.username}", "Inscription", "", "en attente de confirmation de l'e-mail", tenant=None)
    send_verification(profile)


def verify(token):
    """Valide le lien reçu par e-mail. Renvoie l'utilisateur, ou None si le lien est invalide ou expiré."""
    if not token:
        return None
    profile = SignupProfile.objects.select_related("user").filter(verify_hash=_hash(token)).first()
    if profile is None:
        return None
    if profile.verify_sent_at and timezone.now() - profile.verify_sent_at > timedelta(hours=VERIFY_HOURS):
        return None
    profile.email_verified, profile.verify_hash = True, ""
    profile.save(update_fields=["email_verified", "verify_hash"])
    audit.record(profile.user, f"Utilisateur {profile.user.username}", "Adresse e-mail confirmée", tenant=None)
    return profile.user


def resend(email):
    try:
        email = normalize_email(email)
    except ApiError:
        return
    profile = SignupProfile.objects.select_related("user").filter(user__email__iexact=email, email_verified=False).first()
    if profile and (not profile.verify_sent_at or timezone.now() - profile.verify_sent_at > timedelta(seconds=60)):
        send_verification(profile)


def profile_of(user):
    try:
        return user.signup
    except SignupProfile.DoesNotExist:
        return None


def email_blocked(user):
    """Compte inscrit dont l'adresse n'est pas encore confirmée."""
    p = profile_of(user)
    return bool(p and not p.email_verified)


# --------------------------------------------------------------------------- démo
def demo_state(tenant):
    if tenant is None or not tenant.demo_until:
        return None
    from licensing import services as lic
    expired = today() > tenant.demo_until or lic.subscription_problem(tenant) is not None
    from projects.models import Project
    return {"tenant": tenant.name, "until": tenant.demo_until.isoformat(), "expired": expired,
            "daysLeft": max(0, (tenant.demo_until - today()).days + 1) if not expired else 0,
            "maxProjects": demo_max_projects(tenant), "projects": Project.objects.filter(tenant=tenant).count()}


def demo_expired(user):
    """Appelé à chaque requête : ne coûte rien hors tenant de démo."""
    if not user.tenant_id:
        return False
    t = user.tenant
    if not t.demo_until:
        return False
    if today() > t.demo_until:
        return True
    from licensing import services as lic
    return lic.subscription_problem(t) is not None


def demo_max_projects(tenant):
    from licensing.models import Subscription
    sub = Subscription.objects.filter(tenant=tenant).select_related("offer_version").order_by("-id").first()
    limits = (sub.offer_version.limits or {}) if sub else {}
    try:
        return int(limits.get("max_projects", DEMO_MAX_PROJECTS))
    except (TypeError, ValueError):
        return DEMO_MAX_PROJECTS


def demo_version():
    """Offre « Démo » (créée au premier usage, modifiable ensuite par le Pilote)."""
    from licensing.models import Offer, OfferVersion
    offer, _ = Offer.objects.get_or_create(code=DEMO_OFFER, defaults={
        "name": "Démo 3 jours (inscription)", "position": 0,
        "description": "Essai gratuit des comptes inscrits : tous les modules, 2 projets, 3 jours."})
    if not offer.is_active:
        raise ApiError("DEMO_UNAVAILABLE", "Les démos sont momentanément indisponibles. Rejoignez une entreprise avec son code "
                                           "ou réessayez plus tard.", status.HTTP_409_CONFLICT)
    version = OfferVersion.objects.filter(offer=offer, is_published=True).order_by("-number").first()
    if version is None:
        number = (OfferVersion.objects.filter(offer=offer).order_by("-number").values_list("number", flat=True).first() or 0) + 1
        version = OfferVersion.objects.create(
            offer=offer, number=number, is_published=True, price=0, billing_period="once", duration_days=DEMO_DAYS,
            trial_days=DEMO_DAYS, license_model="named", max_users=DEMO_SEATS, named_licenses=DEMO_SEATS,
            concurrent_licenses=0, features=[], limits={"max_projects": DEMO_MAX_PROJECTS},
            conditions="Démo gratuite, sans engagement.")
    return version


@transaction.atomic
def start_demo(user):
    from licensing import models as L
    from licensing import services as lic
    from tenants.services import provision
    from tenants.models import Tenant

    profile = profile_of(user)
    if profile is None:
        raise ApiError("FORBIDDEN_PERMISSION", "La démo est réservée aux comptes créés par inscription.", status.HTTP_403_FORBIDDEN)
    if profile.demo_tenant_id:
        raise ApiError("DEMO_ALREADY_USED", "Vous avez déjà utilisé votre démo. Activez une licence ou rejoignez une entreprise.",
                       status.HTTP_409_CONFLICT)
    if user.tenant_id:
        raise ApiError("VALIDATION_ERROR", "Votre compte est déjà rattaché à une entreprise.", status.HTTP_409_CONFLICT)
    # Le slug sert aussi de préfixe aux numéros de licence (40 caractères max.) : on le garde court.
    login_id = slugify(user.username.split("@", 1)[0]) or str(user.pk)
    base = f"demo-{login_id}"[:28].rstrip("-") or "demo"
    slug, n = base, 1
    while Tenant.objects.filter(slug=slug).exists():
        n += 1
        tail = f"-{n}"
        slug = base[:28 - len(tail)] + tail
    version = demo_version()
    label = profile.company_name if profile.kind == SignupProfile.COMPANY and profile.company_name else user.display_name
    tenant = Tenant.objects.create(slug=slug, name=f"Démo · {label}"[:120], created_by=user,
                                   contact_name=user.display_name[:150], contact_email=user.email,
                                   contact_phone=profile.phone, country=profile.country,
                                   demo_until=today() + timedelta(days=DEMO_DAYS - 1))
    provision(tenant)
    user.tenant, user.role_id = tenant, ADMIN_ROLE
    user.save(update_fields=["tenant", "role"])
    TenantMembership.objects.get_or_create(user=user, tenant=tenant, defaults={"role_id": ADMIN_ROLE})
    try:
        lic.create_subscription(by=user, tenant=tenant, version=version, end_date=today() + timedelta(days=DEMO_DAYS))
        seat = L.License.objects.filter(tenant=tenant, kind=L.NAMED, status=L.AVAILABLE).order_by("number").first()
        if seat is not None:
            lic.assign(by=user, license=seat, user=user)
    except lic.LicenseError as exc:
        raise ApiError(exc.code, exc.message, exc.http_status) from exc
    profile.demo_tenant = tenant
    profile.save(update_fields=["demo_tenant"])
    audit.record(user, f"Entreprise {tenant.name}", "Démo créée", "", f"jusqu'au {tenant.demo_until}", tenant=None)
    return tenant


def end_demo_if_needed(tenant, version):
    """Une offre réelle activée sur un tenant de démo le transforme en tenant normal."""
    if tenant.demo_until and version.offer.code != DEMO_OFFER:
        tenant.demo_until = None
        tenant.save(update_fields=["demo_until"])


def check_project_limit(project):
    """Appelé avant la création d'un projet : une démo est limitée en nombre de projets."""
    from projects.models import Project
    tenant = project.tenant
    if tenant is None or not tenant.demo_until:
        return
    limit = demo_max_projects(tenant)
    if Project.objects.filter(tenant=tenant).count() >= limit:
        raise ApiError("DEMO_LIMIT", f"La démo est limitée à {limit} projets. Activez une licence pour en créer davantage.",
                       status.HTTP_403_FORBIDDEN)


# --------------------------------------------------------------------------- code entreprise et adhésion
def new_join_code():
    from tenants.models import Tenant
    while True:
        raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        code = f"{raw[:4]}-{raw[4:]}"
        if not Tenant.objects.filter(join_code=code).exists():
            return code


def join_code_of(tenant, regenerate=False):
    if regenerate or not tenant.join_code:
        tenant.join_code = new_join_code()
        tenant.save(update_fields=["join_code"])
    return tenant.join_code


def _normalize_code(code):
    raw = re.sub(r"[^A-Z0-9]", "", str(code or "").upper())
    return f"{raw[:4]}-{raw[4:]}" if len(raw) == 8 else ""


def _approvers(tenant):
    from accounts.capabilities import has_capability
    admins = [u for u in User.objects.filter(tenant=tenant, is_active=True) if has_capability(u, "users.approve_sso")]
    pilots = list(User.objects.filter(role_id=PLATFORM_ROLE, tenant__isnull=True, is_active=True))
    return admins, pilots


def request_join(user, code, message=""):
    from tenants.models import Tenant
    normalized = _normalize_code(code)
    tenant = Tenant.objects.filter(join_code=normalized, status="active").first() if normalized else None
    if tenant is None or tenant.demo_until:
        raise ApiError("JOIN_CODE_INVALID", "Code entreprise inconnu. Vérifiez-le auprès de l'administrateur de l'entreprise.",
                       status.HTTP_400_BAD_REQUEST)
    if user.tenant_id == tenant.pk or TenantMembership.objects.filter(user=user, tenant=tenant).exists():
        raise ApiError("VALIDATION_ERROR", "Vous avez déjà accès à cette entreprise.", status.HTTP_409_CONFLICT)
    try:
        with transaction.atomic():
            req = TenantJoinRequest.objects.create(user=user, tenant=tenant, message=str(message or "").strip()[:500])
    except IntegrityError as exc:
        raise ApiError("VALIDATION_ERROR", "Une demande est déjà en attente pour cette entreprise.", status.HTTP_409_CONFLICT) from exc
    audit.record(user, f"Demande d'adhésion {user.email}", "Demande pour rejoindre l'entreprise", "", req.message[:120], tenant=tenant)
    from configuration.models import Notification
    admins, pilots = _approvers(tenant)
    title = f"Demande d'accès : {user.display_name}"
    body = f"{user.display_name} ({user.email}) demande à rejoindre {tenant.name}." + (f" Message : {req.message}" if req.message else "")
    Notification.objects.bulk_create(Notification(user=u, event="validation_requested", title=title, body=body) for u in admins + pilots)
    from configuration.mailer import app_url
    for u in admins + pilots:
        if u.email:
            try:
                _send(u.email, f"{title} · Control Tower", title, body + " Validez ou refusez la demande dans Control Tower.",
                      link=app_url())
            except Exception:  # noqa: BLE001 — l'envoi ne doit pas bloquer la demande
                pass
    return req


def cancel_join(user, pk):
    req = TenantJoinRequest.objects.filter(pk=pk, user=user, status=TenantJoinRequest.PENDING).first()
    if req is None:
        raise ApiError("NOT_FOUND", "Demande introuvable.", status.HTTP_404_NOT_FOUND)
    req.status, req.decided_at = TenantJoinRequest.CANCELLED, timezone.now()
    req.save(update_fields=["status", "decided_at"])
    return req


def assignable_roles(tenant):
    return (Role.objects.filter(internal=True).filter(Q(tenant__isnull=True) | Q(tenant=tenant))
            .exclude(code=PLATFORM_ROLE).order_by("position", "label"))


@transaction.atomic
def decide_join(*, by, req, approve, role_code="", comment=""):
    from licensing import models as L
    from licensing import services as lic
    req = TenantJoinRequest.objects.select_for_update().select_related("user", "tenant").get(pk=req.pk)
    if req.status != TenantJoinRequest.PENDING:
        raise ApiError("VALIDATION_ERROR", "Cette demande a déjà été traitée.", status.HTTP_409_CONFLICT)
    user, tenant = req.user, req.tenant
    if approve:
        role = assignable_roles(tenant).filter(code=role_code).first()
        if role is None:
            raise ApiError("VALIDATION_ERROR", "Choisissez le profil à attribuer.")
        if role.code == ADMIN_ROLE and not (by.is_platform_admin or by.is_app_admin):
            raise ApiError("FORBIDDEN_PERMISSION", "Seul un administrateur peut attribuer le profil administrateur.", status.HTTP_403_FORBIDDEN)
        try:
            lic.check_user_quota(tenant)
        except lic.LicenseError as exc:
            raise ApiError(exc.code, exc.message, exc.http_status) from exc
        if user.tenant_id:
            from .tenant_switch import ensure_home_membership
            ensure_home_membership(user)
            TenantMembership.objects.filter(user=user, tenant_id=user.tenant_id).update(role_id=user.role_id, client_id=user.client_id)
        TenantMembership.objects.update_or_create(user=user, tenant=tenant, defaults={"role": role, "granted_by": by})
        for s in L.ConcurrentSession.objects.filter(user=user, ended_at__isnull=True):
            lic.close_session(s, "replaced")
        user.tenant, user.role, user.client = tenant, role, None
        user.save(update_fields=["tenant", "role", "client"])
        req.role = role
    req.status = TenantJoinRequest.APPROVED if approve else TenantJoinRequest.REJECTED
    req.comment, req.decided_at, req.decided_by = str(comment or "").strip()[:300], timezone.now(), by
    req.save(update_fields=["status", "role", "comment", "decided_at", "decided_by"])
    audit.record(by, f"Demande d'adhésion {user.email}", "Adhésion acceptée" if approve else "Adhésion refusée",
                 "En attente", f"{req.role.label if req.role else ''} {req.comment}".strip(), tenant=tenant)
    from configuration.mailer import app_url
    if approve:
        _send(user.email, f"Accès accordé à {tenant.name} · Control Tower", f"Bienvenue chez {tenant.name}",
              f"Votre demande a été acceptée avec le profil « {req.role.label} ». Reconnectez-vous pour y accéder.",
              link=app_url())
    else:
        _send(user.email, f"Demande refusée · {tenant.name}", "Demande d'accès refusée",
              f"Votre demande pour rejoindre {tenant.name} a été refusée." + (f" Motif : {req.comment}" if req.comment else ""))
    return req


def join_row(req, with_user=True):
    row = {"id": req.pk, "tenant": req.tenant.name, "tenantId": req.tenant_id, "status": req.status,
           "message": req.message, "comment": req.comment, "createdAt": req.created_at, "decidedAt": req.decided_at,
           "role": req.role.label if req.role_id else None}
    if with_user:
        p = profile_of(req.user)
        row.update({"user": req.user.display_name, "email": req.user.email,
                    "kind": p.kind if p else "", "company": p.company_name if p else "", "phone": p.phone if p else "",
                    "jobTitle": p.job_title if p else "", "decidedBy": req.decided_by.display_name if req.decided_by_id else None})
    return row


# --------------------------------------------------------------------------- état d'accueil
def onboarding_state(user):
    """Ce que l'interface doit afficher avant l'application (ou None pour un compte classique sans parcours)."""
    if user.is_platform_admin or user.is_platform_support:
        return None
    profile = profile_of(user)
    demo = demo_state(user.tenant if user.tenant_id else None)
    if profile is None and not demo:
        return None
    joins = [join_row(r, with_user=False) for r in TenantJoinRequest.objects.filter(user=user).select_related("tenant", "role")[:10]]
    pending = any(r["status"] == "pending" for r in joins)
    reason = None
    if not user.tenant_id:
        reason = "no_tenant"
    elif demo and demo["expired"]:
        reason = "demo_expired"
    if reason == "no_tenant":
        step = "profile" if profile and not profile.profile_done else ("pending" if pending else "choice")
    elif reason == "demo_expired":
        step = "demo_expired"
    else:
        step = None
    return {
        "required": reason is not None,
        "reason": reason,
        "step": step,
        "source": profile.source if profile else None,
        "hasHadDemo": bool(profile and profile.demo_tenant_id),
        "isDemoAdmin": bool(demo and user.role_id == ADMIN_ROLE),
        "profile": {"kind": profile.kind, "phone": profile.phone, "jobTitle": profile.job_title,
                    "companyName": profile.company_name, "companySize": profile.company_size,
                    "country": profile.country, "done": profile.profile_done,
                    "firstName": user.first_name, "lastName": user.last_name} if profile else None,
        "demo": demo,
        "joinRequests": joins,
    }


def save_profile(user, data):
    profile = profile_of(user)
    if profile is None:
        raise ApiError("FORBIDDEN_PERMISSION", "Profil indisponible pour ce compte.", status.HTTP_403_FORBIDDEN)
    kind = data.get("kind")
    if kind not in (SignupProfile.COMPANY, SignupProfile.INDIVIDUAL):
        raise ApiError("VALIDATION_ERROR", "Indiquez si vous représentez une entreprise ou si vous êtes indépendant.")
    first, last = str(data.get("firstName") or user.first_name).strip()[:150], str(data.get("lastName") or user.last_name).strip()[:150]
    if not first or not last:
        raise ApiError("VALIDATION_ERROR", "Indiquez votre prénom et votre nom.")
    company = str(data.get("companyName") or "").strip()[:120]
    if kind == SignupProfile.COMPANY and not company:
        raise ApiError("VALIDATION_ERROR", "Indiquez le nom de votre entreprise.",
                       details=[{"field": "companyName", "message": "Nom de l'entreprise obligatoire."}])
    profile.kind = kind
    profile.company_name = company if kind == SignupProfile.COMPANY else ""
    profile.company_size = str(data.get("companySize") or "").strip()[:20] if kind == SignupProfile.COMPANY else ""
    profile.phone = str(data.get("phone") or "").strip()[:40]
    profile.job_title = str(data.get("jobTitle") or "").strip()[:120]
    profile.country = str(data.get("country") or "").strip()[:80]
    profile.profile_done = True
    profile.save()
    user.first_name, user.last_name = first, last
    user.title = profile.job_title or user.title
    user.company = profile.company_name or user.company
    user.save(update_fields=["first_name", "last_name", "title", "company"])
    return profile


# --------------------------------------------------------------------------- fin de démo : activation
def activation_offers():
    from licensing.models import OfferVersion
    rows = (OfferVersion.objects.filter(is_published=True, offer__is_active=True).exclude(offer__code=DEMO_OFFER)
            .select_related("offer").order_by("offer__position", "offer__name", "-number"))
    seen, out = set(), []
    for v in rows:
        if v.offer_id in seen:
            continue
        seen.add(v.offer_id)
        out.append({"id": v.pk, "offer": v.offer.name, "description": v.offer.description, "version": v.number,
                    "price": str(v.price) if v.price is not None else None, "currency": v.currency,
                    "period": v.get_billing_period_display(), "maxUsers": v.max_users})
    return out


def activate(user, data):
    from licensing import models as L
    from licensing import services as lic
    tenant = user.tenant if user.tenant_id else None
    if tenant is None or not tenant.demo_until:
        raise ApiError("VALIDATION_ERROR", "Aucune démo à activer.")
    if user.role_id != ADMIN_ROLE:
        raise ApiError("FORBIDDEN_PERMISSION", "Seul l'administrateur de la démo peut activer une licence.", status.HTTP_403_FORBIDDEN)
    mode = data.get("mode")
    try:
        if mode == "voucher":
            sub = lic.redeem_voucher(code=data.get("code", ""), by=user)
            end_demo_if_needed(tenant, sub.offer_version)
            return {"activated": True}
        if mode == "request":
            version = L.OfferVersion.objects.filter(pk=data.get("versionId"), is_published=True).exclude(offer__code=DEMO_OFFER).first()
            if version is None:
                raise ApiError("VALIDATION_ERROR", "Choisissez l'offre souhaitée.")
            if L.LicenseRequest.objects.filter(tenant=tenant, status__in=[L.SUBMITTED, L.UNDER_REVIEW, L.INFO_REQUIRED]).exists():
                raise ApiError("VALIDATION_ERROR", "Une demande de licence est déjà en cours d'étude par le Pilote.", status.HTTP_409_CONFLICT)
            justification = str(data.get("justification") or "").strip() or f"Fin de démo : activation de l'offre {version.offer.name}."
            req = lic.create_request(by=user, kind="offer", target_version=version, justification=justification)
            return {"requested": True, "requestId": req.pk}
    except lic.LicenseError as exc:
        raise ApiError(exc.code, exc.message, exc.http_status) from exc
    raise ApiError("VALIDATION_ERROR", "Choisissez un voucher ou une demande de licence.")


def pending_license_request(tenant):
    from licensing import models as L
    if tenant is None:
        return None
    r = L.LicenseRequest.objects.filter(tenant=tenant).select_related("target_offer").order_by("-created_at").first()
    if r is None:
        return None
    return {"id": r.pk, "status": r.status, "statusLabel": r.get_status_display(), "offer": r.target_offer.name if r.target_offer_id else "",
            "createdAt": r.created_at}
