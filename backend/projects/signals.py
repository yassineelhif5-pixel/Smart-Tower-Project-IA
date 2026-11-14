"""Consommation budgétaire automatique : chaque saisie, validation ou suppression de temps met à jour le projet."""
import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import TimeEntry

logger = logging.getLogger(__name__)


@receiver([post_save, post_delete], sender=TimeEntry)
def time_changed(sender, instance, **kwargs):
    try:
        from .budget_report import sync_finance
        sync_finance(instance.project)
    except Exception:  # le calcul ne doit jamais bloquer la saisie
        logger.warning("Mise à jour du budget consommé impossible", exc_info=True)


@receiver(post_save, sender="projects.ProjectFinance")
def finance_changed(sender, instance, **kwargs):
    """Budget modifié (saisie du CP, budget supplémentaire) : les seuils de 80 % / 100 % sont revérifiés."""
    try:
        from .budget_report import check_thresholds
        check_thresholds(instance.project)
    except Exception:
        logger.warning("Contrôle des seuils budgétaires impossible", exc_info=True)


@receiver(post_save, sender="projects.Project")
def project_created_connectors(sender, instance, created, **kwargs):
    """Nouveau projet : il reçoit les connecteurs accordés par le Pilote à son client."""
    if not created:
        return
    try:
        from collaboration.client_connectors import apply_to_new_project
        apply_to_new_project(instance)
    except Exception:
        logger.warning("Connecteurs du client non appliqués au nouveau projet", exc_info=True)
