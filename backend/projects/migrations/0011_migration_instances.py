import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0010_dependencies"),
        ("tenants", "0004_tenant_address_tenant_city_tenant_contact_email_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(model_name="project", name="mig_source",
                            field=models.CharField(blank=True, help_text="Outil / système source (migration)", max_length=120)),
        migrations.AddField(model_name="project", name="mig_target",
                            field=models.CharField(blank=True, help_text="Outil / système cible (migration)", max_length=120)),
        migrations.AddField(model_name="project", name="mig_status",
                            field=models.CharField(blank=True, help_text="Statut global de la migration", max_length=20)),
        migrations.CreateModel(
            name="MigrationInstance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("code", models.CharField(blank=True, max_length=40)),
                ("description", models.TextField(blank=True)),
                ("is_pilot", models.BooleanField(default=False)),
                ("source_tool", models.CharField(blank=True, max_length=120)),
                ("target_tool", models.CharField(blank=True, max_length=120)),
                ("status", models.CharField(choices=[("not_started", "Non démarrée"), ("preparing", "Préparation"), ("extracting", "Extraction"),
                                                     ("migrating", "Migration en cours"), ("testing", "Recette"), ("cutover", "Bascule"),
                                                     ("done", "Terminée"), ("blocked", "Bloquée"), ("cancelled", "Annulée")],
                                            default="not_started", max_length=20)),
                ("start_date", models.DateField(blank=True, null=True)),
                ("end_date", models.DateField(blank=True, null=True)),
                ("cutover_date", models.DateField(blank=True, null=True)),
                ("objects_total", models.IntegerField(default=0)),
                ("objects_migrated", models.IntegerField(default=0)),
                ("objects_failed", models.IntegerField(default=0)),
                ("order", models.IntegerField(default=0)),
                ("notes", models.TextField(blank=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="instances", to="projects.project")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="tenants.tenant")),
            ],
            options={"ordering": ["order", "id"], "abstract": False},
        ),
        migrations.AddField(model_name="action", name="instance",
                            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="actions", to="projects.migrationinstance")),
    ]
