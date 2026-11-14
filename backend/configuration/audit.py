import uuid

from . import context
from .models import AuditEvent


_ACTOR_TENANT = object()


def record(actor, entity, event, old="", new="", tenant=_ACTOR_TENANT, result="success"):
    """Ajoute une ligne au journal d'audit. Ne jamais y passer de secret ni de mot de passe.

    Le tenant est par défaut celui de l'auteur ; `tenant=None` marque un événement de la plateforme.
    """
    actor = actor if (actor and actor.is_authenticated) else None
    if tenant is _ACTOR_TENANT:
        tenant = actor.tenant if actor else None
    return AuditEvent.objects.create(
        tenant=tenant,
        ip=context.current_ip(),
        result=result,
        actor=actor,
        entity=entity[:200],
        event=event[:120],
        old_value=str(old if old is not None else "")[:2000],
        new_value=str(new if new is not None else "")[:2000],
        trace=uuid.uuid4().hex[:8],
    )
