"""Règles des licences, toutes appliquées côté serveur.

Concurrence : chaque opération qui consomme ou rend une licence s'exécute dans une transaction et verrouille
les lignes concernées (SELECT … FOR UPDATE). La réservation d'une licence concurrente prend une licence
libre avec SKIP LOCKED : deux connexions simultanées ne peuvent jamais obtenir la même. Des contraintes
d'unicité en base (une session ouverte par licence, un titulaire par licence) servent de dernier rempart.
"""
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from accounts.capabilities import has_capability
from accounts.models import PLATFORM_ROLE
from configuration import audit
from configuration.models import Notification
from tenants.models import Tenant

from . import models as L

User = get_user_model()


class LicenseError(Exception):
    """Refus d'une règle de licence. `code` est renvoyé tel quel par l'API."""

    def __init__(self, code, message, http_status=400):
        super().__init__(message)
        self.code, self.message, self.http_status = code, message, http_status


def today():
    return timezone.localdate()


# --------------------------------------------------------------------------- abonnement
def _expire_if_due(sub):
    due = sub.status in (L.TRIAL, L.ACTIVE) and (
        (sub.status == L.TRIAL and sub.trial_end and sub.trial_end < today())
        or (sub.end_date and sub.end_date < today()))
    if due:
        before = sub.get_status_display()
        sub.status, sub.ended_at = L.EXPIRED, timezone.now()
        sub.save(update_fields=["status", "ended_at"])
        audit.record(None, f"Abonnement {sub.offer_version}", "Abonnement expiré", before, "Expiré", tenant=sub.tenant)
    return sub


def current_subscription(tenant):
    """Abonnement en cours (essai, actif ou suspendu), après mise à jour de son échéance ; None sinon."""
    sub = L.Subscription.objects.filter(tenant=tenant, status__in=L.CURRENT).select_related("offer_version__offer").first()
    if sub is None:
        return None
    _expire_if_due(sub)
    return sub if sub.status in L.CURRENT else None


def is_enforced(tenant):
    """Les licences s'appliquent dès qu'un tenant a eu au moins un abonnement.

    Un tenant qui n'en a jamais eu (données antérieures au module, ex. Demo ESN) n'est pas soumis aux
    licences : il apparaît comme « sans abonnement » dans le tableau de bord du Pilote.
    """
    return tenant is not None and L.Subscription.objects.filter(tenant=tenant).exists()


def subscription_problem(tenant):
    """Raison pour laquelle l'accès est bloqué par l'abonnement, ou None."""
    if not is_enforced(tenant):
        return None
    sub = current_subscription(tenant)
    if sub is None:
        return LicenseError("SUBSCRIPTION_EXPIRED", "L'abonnement de votre entreprise a expiré. Contactez votre administrateur.", 403)
    if sub.status == L.SUSPENDED:
        return LicenseError("SUBSCRIPTION_SUSPENDED", "L'abonnement de votre entreprise est suspendu.", 403)
    return None


def module_enabled(tenant, module):
    """Les fonctionnalités de l'offre limitent les modules accessibles (liste vide = tous)."""
    sub = current_subscription(tenant) if is_enforced(tenant) else None
    if sub is None:
        return True
    features = sub.offer_version.features or []
    return not features or module in features


def user_quota(tenant):
    sub = current_subscription(tenant) if is_enforced(tenant) else None
    return sub.offer_version.max_users if sub else None


def check_user_quota(tenant, adding=1):
    """Refuse la création ou la réactivation d'un compte au-delà du maximum de l'offre."""
    quota = user_quota(tenant)
    if quota is None:
        return
    active = User.objects.filter(tenant=tenant, is_active=True).count()
    if active + adding > quota:
        raise LicenseError("USER_QUOTA_REACHED", f"Votre offre autorise {quota} utilisateurs actifs ; la limite est atteinte.")


@transaction.atomic
def create_subscription(*, by, tenant, version, start_date=None, end_date=None, contract_reference="", terms=""):
    if not version.is_published or not version.offer.is_active:
        raise LicenseError("VALIDATION_ERROR", "Cette version d'offre n'est pas publiée ou l'offre est désactivée.")
    Tenant.objects.select_for_update().get(pk=tenant.pk)
    if current_subscription(tenant) is not None:
        raise LicenseError("VALIDATION_ERROR", "Ce tenant a déjà un abonnement en cours : modifiez-le ou résiliez-le d'abord.")
    start = start_date or today()
    if end_date is None and version.duration_days:
        end_date = start + timedelta(days=version.duration_days)
    contract = None
    if contract_reference:
        if L.Contract.objects.filter(reference=contract_reference).exists():
            raise LicenseError("VALIDATION_ERROR", f"La référence de contrat {contract_reference} existe déjà.")
        contract = L.Contract.objects.create(tenant=tenant, reference=contract_reference, start_date=start,
                                             end_date=end_date, terms=terms, created_by=by)
    trial_end = start + timedelta(days=version.trial_days) if version.trial_days else None
    sub = L.Subscription.objects.create(tenant=tenant, contract=contract, offer_version=version, start_date=start,
                                        end_date=end_date, trial_end=trial_end, status=L.TRIAL if trial_end else L.ACTIVE,
                                        created_by=by)
    audit.record(by, f"Abonnement {version}", "Abonnement créé", "",
                 f"du {start} au {end_date or 'sans terme'}{' · essai ' + str(trial_end) if trial_end else ''}", tenant=tenant)
    for kind, qty in ((L.NAMED, version.named_licenses), (L.CONCURRENT, version.concurrent_licenses)):
        if qty:
            allocate(by=by, tenant=tenant, kind=kind, delta=qty, reason=f"Stock initial de l'offre {version}", subscription=sub)
    return sub


@transaction.atomic
def change_subscription(*, by, sub, status=None, end_date=None, reason=""):
    _expire_if_due(sub)
    sub = L.Subscription.objects.select_for_update().get(pk=sub.pk)
    allowed = {L.TRIAL: {L.ACTIVE, L.SUSPENDED, L.CANCELLED}, L.ACTIVE: {L.SUSPENDED, L.CANCELLED},
               L.SUSPENDED: {L.ACTIVE, L.CANCELLED}, L.EXPIRED: {L.ACTIVE}, L.CANCELLED: set()}
    changes = []
    if end_date is not None and end_date != sub.end_date:
        changes.append(("Échéance modifiée", str(sub.end_date or "sans terme"), str(end_date)))
        sub.end_date = end_date
    if status and status != sub.status:
        if status not in allowed[sub.status]:
            raise LicenseError("VALIDATION_ERROR", f"Passage de « {sub.get_status_display()} » à « {dict(L.SUB_STATUSES)[status]} » non autorisé.")
        if sub.status == L.EXPIRED and (sub.end_date is None or sub.end_date < today()):
            raise LicenseError("VALIDATION_ERROR", "Pour réactiver un abonnement expiré, reportez d'abord son échéance.")
        if status != L.ACTIVE and not reason.strip():
            raise LicenseError("VALIDATION_ERROR", "Indiquez le motif de ce changement.")
        if sub.status == L.EXPIRED and current_subscription(sub.tenant) is not None:
            raise LicenseError("VALIDATION_ERROR", "Ce tenant a déjà un autre abonnement en cours.")
        changes.append(("Statut modifié", sub.get_status_display(), dict(L.SUB_STATUSES)[status] + (f" · {reason}" if reason else "")))
        sub.status = status
        sub.ended_at = timezone.now() if status in (L.CANCELLED, L.EXPIRED) else None
        if status == L.ACTIVE:
            sub.trial_end = None
    sub.save()
    for event, old, new in changes:
        audit.record(by, f"Abonnement {sub.offer_version}", event, old, new, tenant=sub.tenant)
    if sub.status in (L.SUSPENDED, L.CANCELLED):
        end_tenant_sessions(sub.tenant, "revoked")
    return sub


# --------------------------------------------------------------------------- stock
def stock(tenant):
    rows = L.License.objects.filter(tenant=tenant).exclude(status=L.REVOKED).values("kind").annotate(
        total=Count("id"), used=Count("id", filter=Q(status__in=[L.ASSIGNED, L.IN_USE])))
    out = {L.NAMED: {"total": 0, "used": 0}, L.CONCURRENT: {"total": 0, "used": 0}}
    for r in rows:
        out[r["kind"]] = {"total": r["total"], "used": r["used"]}
    for v in out.values():
        v["available"] = v["total"] - v["used"]
    return out


@transaction.atomic
def allocate(*, by, tenant, kind, delta, reason, subscription=None, request=None):
    """Le Pilote ajoute (+) ou retire (−) des licences au stock d'un tenant. Seules des licences libres sont retirées."""
    if kind not in dict(L.LICENSE_KINDS) or not delta:
        raise LicenseError("VALIDATION_ERROR", "Type de licence ou quantité invalide.")
    if not reason.strip():
        raise LicenseError("VALIDATION_ERROR", "Indiquez le motif de ce mouvement de stock.")
    Tenant.objects.select_for_update().get(pk=tenant.pk)
    subscription = subscription or current_subscription(tenant)
    free = list(L.License.objects.select_for_update().filter(tenant=tenant, kind=kind, status=L.AVAILABLE).order_by("-number"))
    if delta < 0 and len(free) < -delta:
        raise LicenseError("STOCK_IN_USE", f"Impossible de retirer {-delta} licence(s) : seules {len(free)} sont libres. "
                                           "Libérez d'abord des licences affectées.")
    movement = L.LicenseAllocation.objects.create(tenant=tenant, subscription=subscription, kind=kind, delta=delta,
                                                  reason=reason.strip()[:300], request=request, by=by)
    if delta > 0:
        start = L.License.objects.filter(tenant=tenant).count()
        prefix = "N" if kind == L.NAMED else "C"
        L.License.objects.bulk_create(L.License(tenant=tenant, kind=kind, allocation=movement,
                                                number=f"{tenant.slug.upper()}-{prefix}-{start + i + 1:05d}")
                                      for i in range(delta))
    else:
        ids = [lic.pk for lic in free[:-delta]]
        L.License.objects.filter(pk__in=ids).update(status=L.REVOKED, revoked_by_allocation=movement)
    audit.record(by, f"Stock de licences {dict(L.LICENSE_KINDS)[kind].lower()}s", "Stock ajusté",
                 "", f"{'+' if delta > 0 else ''}{delta} · {reason.strip()}", tenant=tenant)
    return movement


# --------------------------------------------------------------------------- licences nominatives
def _same_tenant(actor, *objects):
    if actor.role_id != PLATFORM_ROLE and any(o.tenant_id != actor.tenant_id for o in objects):
        raise LicenseError("NOT_FOUND", "Élément introuvable.", 404)


@transaction.atomic
def assign(*, by, license, user):
    lic = L.License.objects.select_for_update().get(pk=license.pk)
    _same_tenant(by, lic, user)
    if lic.kind != L.NAMED:
        raise LicenseError("VALIDATION_ERROR", "Seule une licence nominative s'affecte à un utilisateur.")
    if lic.status != L.AVAILABLE:
        raise LicenseError("LICENSE_UNAVAILABLE", "Cette licence n'est pas disponible.")
    if not user.is_active:
        raise LicenseError("VALIDATION_ERROR", "Le compte est désactivé : réactivez-le avant de lui affecter une licence.")
    problem = subscription_problem(lic.tenant)
    if problem:
        raise problem
    if L.LicenseAssignment.objects.filter(user=user, released_at__isnull=True).exists():
        raise LicenseError("ALREADY_LICENSED", f"{user.username} a déjà une licence nominative.")
    try:
        with transaction.atomic():
            L.LicenseAssignment.objects.create(tenant=lic.tenant, license=lic, user=user, assigned_by=by)
    except IntegrityError as exc:  # course perdue contre une autre affectation simultanée
        raise LicenseError("LICENSE_UNAVAILABLE", "Cette licence vient d'être affectée par ailleurs.") from exc
    lic.status = L.ASSIGNED
    lic.save(update_fields=["status"])
    audit.record(by, f"Licence {lic.number}", "Licence affectée", "", user.username, tenant=lic.tenant)
    return lic


@transaction.atomic
def release(*, by, license, reason=""):
    lic = L.License.objects.select_for_update().get(pk=license.pk)
    _same_tenant(by, lic)
    current = L.LicenseAssignment.objects.select_for_update().filter(license=lic, released_at__isnull=True).first()
    if current is None:
        raise LicenseError("VALIDATION_ERROR", "Cette licence n'est affectée à personne.")
    current.released_at, current.released_by, current.release_reason = timezone.now(), by, reason.strip()[:200]
    current.save(update_fields=["released_at", "released_by", "release_reason"])
    lic.status = L.AVAILABLE
    lic.save(update_fields=["status"])
    # Le titulaire perd ses sessions : il devra se reconnecter (et prendre une licence concurrente s'il en reste).
    for s in L.ConcurrentSession.objects.filter(user=current.user, ended_at__isnull=True, license__isnull=True):
        close_session(s, "revoked")
    audit.record(by, f"Licence {lic.number}", "Licence libérée", current.user.username, reason.strip(), tenant=lic.tenant)
    return lic


@transaction.atomic
def reassign(*, by, license, user, reason=""):
    release(by=by, license=license, reason=reason or f"Réaffectée à {user.username}")
    return assign(by=by, license=license, user=user)


def named_license_of(user):
    a = L.LicenseAssignment.objects.filter(user=user, released_at__isnull=True).select_related("license").first()
    return a.license if a else None


# --------------------------------------------------------------------------- sessions et licences concurrentes
def idle_timeout():
    return timedelta(minutes=getattr(settings, "LICENSE_SESSION_IDLE_MINUTES", 30))


def close_session(session, reason):
    with transaction.atomic():
        s = L.ConcurrentSession.objects.select_for_update().get(pk=session.pk)
        if s.ended_at:
            return s
        s.ended_at, s.end_reason = timezone.now(), reason
        s.save(update_fields=["ended_at", "end_reason"])
        if s.license_id:
            L.License.objects.filter(pk=s.license_id, status=L.IN_USE).update(status=L.AVAILABLE)
        return s


def expire_sessions(tenant=None):
    """Ferme les sessions inactives au-delà du délai et rend leurs licences concurrentes."""
    qs = L.ConcurrentSession.objects.filter(ended_at__isnull=True, expires_at__lt=timezone.now())
    if tenant is not None:
        qs = qs.filter(tenant=tenant)
    count = 0
    for s in qs:
        close_session(s, "expired")
        count += 1
    return count


def end_tenant_sessions(tenant, reason):
    for s in L.ConcurrentSession.objects.filter(tenant=tenant, ended_at__isnull=True):
        close_session(s, reason)


def open_session(user, session_key):
    """À la connexion : vérifie l'accès et réserve une licence. Lève LicenseError si l'accès est refusé."""
    tenant = user.tenant
    if user.is_platform_admin or tenant is None or not is_enforced(tenant):
        return None
    # Hors transaction : le passage d'un abonnement échu à « Expiré » doit rester enregistré même si l'accès est refusé.
    problem = subscription_problem(tenant)
    if problem:
        raise problem
    return _reserve(user, tenant, session_key)


@transaction.atomic
def _reserve(user, tenant, session_key):
    now = timezone.now()
    expire_sessions(tenant)
    version = current_subscription(tenant).offer_version
    mine = L.ConcurrentSession.objects.filter(user=user, ended_at__isnull=True)
    if version.max_sessions_per_user and mine.count() >= version.max_sessions_per_user:
        raise LicenseError("SESSION_LIMIT", "Nombre maximal de connexions simultanées atteint pour votre compte. "
                                            "Déconnectez-vous d'un autre appareil.", 403)
    seat = None
    if named_license_of(user) is None:
        # SKIP LOCKED : chaque connexion simultanée verrouille une licence différente, jamais la même.
        seat = L.License.objects.select_for_update(skip_locked=True).filter(
            tenant=tenant, kind=L.CONCURRENT, status=L.AVAILABLE).order_by("number").first()
        if seat is None:
            has_concurrent = L.License.objects.filter(tenant=tenant, kind=L.CONCURRENT).exclude(status=L.REVOKED).exists()
            if has_concurrent:
                raise LicenseError("LICENSE_CAPACITY_REACHED", "Toutes les licences concurrentes de votre entreprise sont "
                                                               "occupées. Réessayez plus tard.", 403)
            raise LicenseError("NO_LICENSE", "Aucune licence ne vous est affectée. Contactez votre administrateur.", 403)
        seat.status = L.IN_USE
        seat.save(update_fields=["status"])
    return L.ConcurrentSession.objects.create(tenant=tenant, user=user, license=seat, session_key=session_key or "",
                                              last_seen_at=now, expires_at=now + idle_timeout())


def active_session(user, session_key):
    return L.ConcurrentSession.objects.filter(user=user, session_key=session_key, ended_at__isnull=True).first()


def touch(session):
    """Prolonge une session active (au plus une écriture par minute)."""
    now = timezone.now()
    if session.expires_at < now:
        close_session(session, "expired")
        return False
    if (now - session.last_seen_at).total_seconds() >= 60:
        L.ConcurrentSession.objects.filter(pk=session.pk).update(last_seen_at=now, expires_at=now + idle_timeout())
    return True


def rekey_session(user, old_key, new_key):
    """La session Django change d'identifiant (changement de mot de passe) : la licence occupée la suit."""
    if old_key and new_key and old_key != new_key:
        L.ConcurrentSession.objects.filter(user=user, session_key=old_key, ended_at__isnull=True).update(session_key=new_key)


def close_user_session(user, session_key, reason="logout"):
    s = active_session(user, session_key)
    if s:
        close_session(s, reason)


# --------------------------------------------------------------------------- demandes et approbations
TENANT_MOVES = {
    L.DRAFT: {L.SUBMITTED, L.CANCELLED_R},
    L.SUBMITTED: {L.CANCELLED_R},
    L.UNDER_REVIEW: {L.CANCELLED_R},
    L.INFO_REQUIRED: {L.SUBMITTED, L.CANCELLED_R},
}
PILOT_MOVES = {
    L.SUBMITTED: {L.UNDER_REVIEW, L.INFO_REQUIRED, L.APPROVED, L.PARTIALLY_APPROVED, L.REJECTED},
    L.UNDER_REVIEW: {L.INFO_REQUIRED, L.APPROVED, L.PARTIALLY_APPROVED, L.REJECTED},
}
QUANTITY_KINDS = {"named", "concurrent", "quota"}


def _event(req, actor, old, new, comment=""):
    L.LicenseRequestEvent.objects.create(request=req, actor=actor, from_status=old, to_status=new, comment=comment)


def _notify_pilots(title, body):
    pilots = User.objects.filter(role_id=PLATFORM_ROLE, tenant__isnull=True, is_active=True)
    Notification.objects.bulk_create(Notification(user=p, event="validation_requested", title=title, body=body) for p in pilots)


def _notify_tenant(tenant, title, body):
    admins = [u for u in User.objects.filter(tenant=tenant, is_active=True) if has_capability(u, "requests.view")]
    Notification.objects.bulk_create(Notification(user=u, event="validation_requested", title=title, body=body) for u in admins)


@transaction.atomic
def create_request(*, by, kind, quantity=None, target_offer=None, justification="", submit=True):
    if kind not in dict(L.REQUEST_KINDS):
        raise LicenseError("VALIDATION_ERROR", "Type de demande inconnu.")
    if kind in QUANTITY_KINDS and not quantity:
        raise LicenseError("VALIDATION_ERROR", "Indiquez la quantité demandée.")
    if kind == "offer" and target_offer is None:
        raise LicenseError("VALIDATION_ERROR", "Indiquez l'offre souhaitée.")
    if not justification.strip():
        raise LicenseError("VALIDATION_ERROR", "Expliquez le besoin : la demande sera étudiée par le Pilote.")
    req = L.LicenseRequest.objects.create(tenant=by.tenant, kind=kind, quantity=quantity if kind in QUANTITY_KINDS else None,
                                          target_offer=target_offer, justification=justification.strip(), created_by=by)
    _event(req, by, "", L.DRAFT, "Demande créée")
    audit.record(by, f"Demande n° {req.id}", "Demande créée", "", req.get_kind_display(), tenant=by.tenant)
    if submit:
        req = tenant_move(by=by, req=req, status=L.SUBMITTED)
    return req


@transaction.atomic
def tenant_move(*, by, req, status, comment=""):
    req = L.LicenseRequest.objects.select_for_update().get(pk=req.pk)
    _same_tenant(by, req)
    if status not in TENANT_MOVES.get(req.status, set()):
        raise LicenseError("VALIDATION_ERROR", f"Action impossible sur une demande au statut {req.status}.")
    old = req.status
    req.status = status
    if status == L.SUBMITTED:
        req.submitted_at = timezone.now()
    req.save()
    _event(req, by, old, status, comment)
    audit.record(by, f"Demande n° {req.id}", "Demande soumise" if status == L.SUBMITTED else "Demande annulée", old, status, tenant=req.tenant)
    if status == L.SUBMITTED:
        _notify_pilots(f"Nouvelle demande de {req.tenant.name}", f"{req.get_kind_display()} · n° {req.id}")
    return req


@transaction.atomic
def pilot_decide(*, by, req, status, quantity_granted=None, comment=""):
    req = L.LicenseRequest.objects.select_for_update().get(pk=req.pk)
    if status not in PILOT_MOVES.get(req.status, set()):
        raise LicenseError("VALIDATION_ERROR", f"Action impossible sur une demande au statut {req.status}.")
    if status in (L.INFO_REQUIRED, L.REJECTED) and not comment.strip():
        raise LicenseError("VALIDATION_ERROR", "Un commentaire est obligatoire pour cette décision.")
    if status in (L.APPROVED, L.PARTIALLY_APPROVED) and req.kind in QUANTITY_KINDS:
        if status == L.APPROVED:
            quantity_granted = req.quantity
        elif not quantity_granted or not 0 < quantity_granted < req.quantity:
            raise LicenseError("VALIDATION_ERROR", f"Une approbation partielle accorde entre 1 et {req.quantity - 1} unité(s).")
        req.quantity_granted = quantity_granted
    old = req.status
    req.status = status
    if status in (L.APPROVED, L.PARTIALLY_APPROVED, L.REJECTED):
        req.decided_by, req.decided_at = by, timezone.now()
    req.save()
    _event(req, by, old, status, comment)
    audit.record(by, f"Demande n° {req.id}", "Décision du Pilote", old,
                 f"{status}{f' · {req.quantity_granted} accordée(s)' if req.quantity_granted else ''}", tenant=req.tenant)
    _notify_tenant(req.tenant, f"Demande n° {req.id} : {status}", comment)
    return req


@transaction.atomic
def fulfil(*, by, req, comment=""):
    """Exécution effective d'une demande approuvée : sans elle, la demande n'est pas considérée comme réalisée."""
    req = L.LicenseRequest.objects.select_for_update().get(pk=req.pk)
    if req.status not in (L.APPROVED, L.PARTIALLY_APPROVED):
        raise LicenseError("VALIDATION_ERROR", "Seule une demande approuvée peut être exécutée.")
    if req.kind in ("named", "concurrent"):
        allocate(by=by, tenant=req.tenant, kind=req.kind, delta=req.quantity_granted,
                 reason=f"Demande n° {req.id} approuvée", request=req)
    elif not comment.strip():
        # Quota, offre ou option : l'opération se fait sur l'offre ou l'abonnement ; le Pilote décrit ce qui a été fait.
        raise LicenseError("VALIDATION_ERROR", "Décrivez l'opération réalisée (nouvel abonnement, nouvelle version d'offre…).")
    old = req.status
    req.status, req.fulfilled_at = L.FULFILLED, timezone.now()
    req.save()
    _event(req, by, old, L.FULFILLED, comment or "Licences ajoutées au stock")
    audit.record(by, f"Demande n° {req.id}", "Demande exécutée", old, L.FULFILLED, tenant=req.tenant)
    _notify_tenant(req.tenant, f"Demande n° {req.id} réalisée", comment or "Les licences sont disponibles dans votre stock.")
    return req


def comment(*, by, req, text):
    if not text.strip():
        raise LicenseError("VALIDATION_ERROR", "Le commentaire est vide.")
    if by.role_id != PLATFORM_ROLE:
        _same_tenant(by, req)
    _event(req, by, req.status, req.status, text.strip())
    return req
