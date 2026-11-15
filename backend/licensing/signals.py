"""Notifications des demandes de licence (socle configuration.mailer).

- Envoi ou commentaire côté entreprise → le Pilote (administrateurs de la plateforme) est notifié (cloche + e-mail plateforme).
- Décision ou commentaire du Pilote → le demandeur et les administrateurs de l'entreprise sont notifiés.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import DRAFT, REQUEST_KINDS, LicenseRequestEvent

STATUS_FR = {"SUBMITTED": "envoyée", "UNDER_REVIEW": "en cours d'étude", "ADDITIONAL_INFORMATION_REQUIRED": "informations complémentaires demandées",
             "APPROVED": "approuvée", "PARTIALLY_APPROVED": "partiellement approuvée", "REJECTED": "refusée", "CANCELLED": "annulée",
             "FULFILLED": "honorée", "INSTALLED": "installée"}


@receiver(post_save, sender=LicenseRequestEvent, dispatch_uid="licensing.notify_request_event")
def on_request_event(sender, instance, created, **kwargs):
    if not created or instance.to_status == DRAFT:
        return
    try:
        from accounts.models import ADMIN_ROLE, PLATFORM_ROLE
        from configuration.mailer import dispatch
        User = get_user_model()
        req = instance.request
        actor = instance.actor
        kind = dict(REQUEST_KINDS).get(req.kind, req.kind)
        is_comment = not instance.to_status or instance.to_status == instance.from_status
        status = STATUS_FR.get(instance.to_status, instance.to_status or "commentaire")
        details = {"Entreprise": req.tenant.name, "Type": kind, "Quantité": req.quantity or "", "Statut": status,
                   "Justification": (req.justification or "")[:300], "Commentaire": (instance.comment or "")[:500],
                   "Demande n°": req.pk}
        from configuration.mailer import app_url
        base = app_url()
        if actor is None or actor.tenant_id:  # côté entreprise → Pilote
            pilots = list(User.objects.filter(tenant__isnull=True, role_id=PLATFORM_ROLE, is_active=True))
            title = (f"Commentaire de {req.tenant.name} sur sa demande de licence" if is_comment
                     else f"Nouvelle demande de licence — {req.tenant.name}" if instance.to_status == "SUBMITTED"
                     else f"Demande de licence {req.tenant.name} : {status}")
            dispatch("licence_request", pilots, title, f"{kind} demandée par {actor.display_name if actor else 'l’entreprise'}.",
                     details=details, link=f"{base}/#licences" if base else None, actor=actor)
        else:  # décision du Pilote → demandeur + administrateurs de l'entreprise
            targets = list(User.objects.filter(tenant=req.tenant, role_id=ADMIN_ROLE, is_active=True))
            if req.created_by_id:
                targets.append(req.created_by)
            dispatch("licence_request", targets,
                     "Nouveau commentaire du Pilote sur votre demande de licence" if is_comment else f"Votre demande de licence : {status}",
                     f"Le Pilote a {'commenté' if is_comment else 'mis à jour'} votre demande ({kind}).", details=details,
                     link=f"{base}/#licences" if base else None, actor=actor)
    except Exception:  # noqa: BLE001 — une notification ne doit jamais bloquer la demande
        import logging
        logging.getLogger("notifications").warning("Notification de demande de licence impossible", exc_info=True)
