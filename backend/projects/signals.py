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


# --------------------------------------------------------------------------- notifications des actions (socle mailer)
from django.db.models.signals import pre_save  # noqa: E402

from .models import ACTION_STATUSES, Action  # noqa: E402

_TRACKED = ("owner_id", "status", "due", "start_date", "est", "title")
_ST = dict(ACTION_STATUSES)


@receiver(pre_save, sender=Action, dispatch_uid="projects.action_before")
def action_before(sender, instance, **kwargs):
    try:
        instance._before = Action.objects.filter(pk=instance.pk).values(*_TRACKED).first() if instance.pk else None
    except Exception:  # noqa: BLE001
        instance._before = None


def _fmt(field, v):
    if v in (None, ""):
        return "—"
    if field == "status":
        return _ST.get(v, v)
    if hasattr(v, "strftime"):
        return v.strftime("%d/%m/%Y")
    return str(v)


@receiver(post_save, sender=Action, dispatch_uid="projects.action_after")
def action_after(sender, instance, created, **kwargs):
    """Création, affectation et modification d'une action par un utilisateur : notification (cloche + e-mail).
    Les créations sans utilisateur (import Excel en arrière-plan, tâches planifiées) ne notifient pas."""
    if getattr(instance, "_no_notify", False):
        return
    try:
        from configuration.context import current_user
        from configuration.mailer import dispatch
        from django.conf import settings
        actor = current_user()
        if actor is None:
            return
        p = instance.project
        from configuration.mailer import app_url
        link = f"{app_url()}/#projets"
        base = {"Action": f"{instance.id} — {instance.title}", "Statut": _ST.get(instance.status, instance.status),
                "Échéance": _fmt("due", instance.due), "Responsable": instance.owner.display_name if instance.owner_id else "—"}
        pm = p.pm if p.pm_id else None
        before = getattr(instance, "_before", None)
        if created or before is None:
            if instance.owner_id:
                dispatch("action_assigned", [instance.owner], f"Nouvelle action assignée : {instance.title}",
                         "Une action vous est assignée.", project=p, details=base, link=link, actor=actor)
            if pm and pm.pk != instance.owner_id:
                dispatch("action_created", [pm], f"Action créée : {instance.title}", "Une nouvelle action a été créée sur votre projet.",
                         project=p, details=base, link=link, actor=actor)
            return
        changes = []
        labels = {"owner_id": "Responsable", "status": "Statut", "due": "Échéance", "start_date": "Début", "est": "Estimation (h)", "title": "Titre"}
        for f in _TRACKED:
            old, new = before.get(f), getattr(instance, f)
            if f in ("est",):
                old, new = (float(old) if old is not None else None), (float(new) if new is not None else None)
            if old != new and f != "owner_id":
                changes.append(f"{labels[f]} : {_fmt(f, old)} → {_fmt(f, new)}")
        if before.get("owner_id") != instance.owner_id:
            from django.contrib.auth import get_user_model
            old_owner = get_user_model().objects.filter(pk=before.get("owner_id")).first() if before.get("owner_id") else None
            if instance.owner_id:
                dispatch("action_assigned", [instance.owner], f"Action assignée : {instance.title}",
                         "Cette action vous est maintenant assignée" + (f" (auparavant : {old_owner.display_name})." if old_owner else "."),
                         project=p, details=base, link=link, actor=actor)
            if old_owner:
                dispatch("action_updated", [old_owner], f"Action réassignée : {instance.title}",
                         f"Cette action est désormais confiée à {instance.owner.display_name if instance.owner_id else 'personne'}.",
                         project=p, details=base, link=link, actor=actor)
        if changes:
            targets = [u for u in (instance.owner if instance.owner_id else None, pm) if u is not None]
            dispatch("action_updated", targets, f"Action modifiée : {instance.title}", "\n".join(changes),
                     project=p, details=base, link=link, actor=actor)
    except Exception:  # noqa: BLE001
        logger.warning("Notification d'action impossible", exc_info=True)
