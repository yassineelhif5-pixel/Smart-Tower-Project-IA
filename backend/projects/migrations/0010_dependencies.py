from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0009_project_target_version_types"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="parent",
            field=models.ForeignKey(blank=True, help_text="Projet parent (programme) dont ce projet est un sous-projet", null=True,
                                    on_delete=django.db.models.deletion.SET_NULL, related_name="children", to="projects.project"),
        ),
        migrations.AddField(
            model_name="project",
            name="depends_on",
            field=models.ManyToManyField(blank=True, help_text="Projets dont celui-ci dépend (prérequis)", related_name="dependents", to="projects.project"),
        ),
        migrations.AddField(
            model_name="action",
            name="depends_on",
            field=models.ManyToManyField(blank=True, related_name="successors", to="projects.action"),
        ),
    ]
