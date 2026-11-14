"""Automatismes : nouveau projet d'un client sous contrat de support, CRA à la validation complète d'un mois passé."""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender="projects.Project")
def project_saved(sender, instance, created, **kwargs):
    try:
        from .models import SupportContract
        from .support import sync_access
        contract = SupportContract.objects.filter(client_id=instance.client_id).first()
        if contract:
            sync_access(contract)
    except Exception:
        logger.warning("Synchronisation du support impossible", exc_info=True)


@receiver(post_save, sender="projects.TimeEntry")
def time_saved(sender, instance, **kwargs):
    """Dernière validation d'un mois terminé : le CRA et la facture partent sans attendre le passage quotidien."""
    if instance.approval_status != "approved":
        return
    try:
        from django.utils import timezone
        from .billing import bounds, try_generate
        period = f"{instance.work_date:%Y-%m}"
        if timezone.localdate() > bounds(period)[1]:
            try_generate(instance.tenant, instance.person_id, instance.project.client_id, period, instance.approved_by)
    except Exception:
        logger.warning("Génération du CRA impossible", exc_info=True)
