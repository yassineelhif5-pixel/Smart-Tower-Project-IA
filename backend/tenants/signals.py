"""Refuse toute relation plusieurs-à-plusieurs entre deux tenants (équipe d'un projet, participants d'une réunion…).

Les relations simples (ForeignKey) sont contrôlées par TenantOwned.save() ; les relations multiples
passent par ce signal, déclenché à chaque add() ou set().
"""
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from .models import CrossTenantError


@receiver(m2m_changed)
def same_tenant_only(sender, instance, action, reverse, model, pk_set, **kwargs):
    if action != "pre_add" or not pk_set:
        return
    own = getattr(instance, "tenant_id", None)
    if own is None or not any(f.name == "tenant" for f in model._meta.fields):
        return
    others = set(model._default_manager.filter(pk__in=pk_set).values_list("tenant_id", flat=True))
    if others - {own}:
        raise CrossTenantError(f"{type(instance).__name__} : impossible de lier des éléments d'un autre tenant.")
