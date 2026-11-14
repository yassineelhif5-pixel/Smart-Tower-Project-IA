import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("projects", "0012_project_status"),
        ("tenants", "0004_tenant_address_tenant_city_tenant_contact_email_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="AiCall",
            fields=[
                ("id", models.CharField(max_length=20, primary_key=True, serialize=False)),
                ("mode", models.CharField(default="audio", help_text="audio ou video", max_length=10)),
                ("objective", models.CharField(blank=True, max_length=300)),
                ("assistants", models.JSONField(default=list, help_text="Codes des assistants présents (Maestro toujours inclus)")),
                ("lead", models.CharField(help_text="Assistant qui rédige le document principal", max_length=20)),
                ("participants", models.JSONField(default=list, help_text="Humains présents : id, nom, rôle")),
                ("doc_type", models.CharField(blank=True, max_length=20)),
                ("doc_title", models.CharField(blank=True, max_length=200)),
                ("sections", models.JSONField(default=list)),
                ("turns", models.JSONField(default=list)),
                ("cards", models.JSONField(default=list)),
                ("files", models.JSONField(default=list)),
                ("state", models.JSONField(default=dict, help_text="Curseur d'entretien, version du prompt, compteurs")),
                ("status", models.CharField(choices=[("live", "En cours"), ("closed", "Clôturé")], default="live", max_length=10)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("document", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="projects.document")),
                ("organizer", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ai_calls", to="projects.project")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="tenants.tenant")),
            ],
            options={"ordering": ["-started_at"]},
        ),
    ]
