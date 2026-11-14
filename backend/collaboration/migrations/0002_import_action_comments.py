"""1.4.0 : les commentaires d'actions existants sont repris dans une discussion interne par action.
Les commentaires d'origine sont conservés tels quels (aucune suppression)."""
import hashlib

from django.db import migrations
from django.utils import timezone


def forward(apps, schema_editor):
    Comment = apps.get_model("projects", "ActionComment")
    Discussion = apps.get_model("collaboration", "ProjectDiscussion")
    Message = apps.get_model("collaboration", "DiscussionMessage")
    groups = {}
    for c in Comment.objects.select_related("action").order_by("id"):
        groups.setdefault(c.action_id, []).append(c)
    for action_id, comments in groups.items():
        action = comments[0].action
        if Discussion.objects.filter(action_id=action_id, title__startswith="Commentaires · ").exists():
            continue
        d = Discussion.objects.create(tenant_id=action.tenant_id, project_id=action.project_id, action_id=action_id,
                                      title=f"Commentaires · {action.title}"[:200], destination="internal",
                                      created_by_id=comments[0].author_id, last_message_at=timezone.now())
        for c in comments:
            Message.objects.create(tenant_id=action.tenant_id, discussion=d, author_id=c.author_id, body=c.body,
                                   body_hash=hashlib.sha256(" ".join(c.body.split()).encode()).hexdigest())


def backward(apps, schema_editor):
    apps.get_model("collaboration", "ProjectDiscussion").objects.filter(title__startswith="Commentaires · ",
                                                                         destination="internal").delete()


class Migration(migrations.Migration):
    dependencies = [("collaboration", "0001_initial"), ("projects", "0005_tenant_required")]
    operations = [migrations.RunPython(forward, backward)]
