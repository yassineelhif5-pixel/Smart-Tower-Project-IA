import uuid

from .models import AuditEvent


def record(actor, entity, event, old="", new=""):
    """Ajoute une ligne au journal d'audit. Ne jamais y passer de secret ni de mot de passe."""
    return AuditEvent.objects.create(
        actor=actor if (actor and actor.is_authenticated) else None,
        entity=entity[:200],
        event=event[:120],
        old_value=str(old if old is not None else "")[:2000],
        new_value=str(new if new is not None else "")[:2000],
        trace=uuid.uuid4().hex[:8],
    )
