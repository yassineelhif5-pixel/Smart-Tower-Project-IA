"""1.5.0 : reprise des données méthodologiques existantes (méthode, phases, équipe, sprints, user stories).
Aucune donnée d'origine n'est modifiée ; le retour arrière supprime seulement ce qui a été créé ici."""
from django.db import migrations

from methodology.bootstrap import bootstrap_all


def forward(apps, schema_editor):
    def M(name):
        for app in ("methodology", "projects", "accounts"):
            try:
                return apps.get_model(app, name)
            except LookupError:
                continue
        raise LookupError(name)
    bootstrap_all(M)


def backward(apps, schema_editor):
    for name in ("Retrospective", "SprintBacklogItem", "SprintGoal", "Sprint", "ProductBacklogItem", "TeamMemberAllocation",
                 "VPhase", "ProjectMethodology"):
        apps.get_model("methodology", name).objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("methodology", "0001_initial"), ("projects", "0005_tenant_required"), ("accounts", "0011_methodology_permissions")]
    operations = [migrations.RunPython(forward, backward)]
