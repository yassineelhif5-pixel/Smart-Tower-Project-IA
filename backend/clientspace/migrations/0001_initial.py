import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("projects", "0013_timeentry_client_status"),
        ("tenants", "0004_tenant_address_tenant_city_tenant_contact_email_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="SupportContract",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("enabled", models.BooleanField(default=False)),
                ("levels", models.JSONField(default=list, help_text="Niveaux couverts : N1, N2, N3")),
                ("rates", models.JSONField(blank=True, default=dict, help_text='TJM par niveau, ex. {"N1": 450}')),
                ("starts_on", models.DateField(blank=True, null=True)),
                ("ends_on", models.DateField(blank=True, null=True)),
                ("granted", models.JSONField(blank=True, default=list, help_text="Accès projet ouverts par le contrat : [[user, projet]]")),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("client", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="support_contract", to="projects.client")),
                ("members", models.ManyToManyField(blank=True, related_name="support_contracts", to=settings.AUTH_USER_MODEL)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="tenants.tenant")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="ClientDocument",
            fields=[
                ("id", models.CharField(max_length=20, primary_key=True, serialize=False)),
                ("kind", models.CharField(choices=[("cra", "Compte rendu d'activité"), ("invoice", "Facture"), ("other", "Autre")], max_length=10)),
                ("period", models.CharField(blank=True, help_text="AAAA-MM", max_length=7)),
                ("name", models.CharField(max_length=255)),
                ("number", models.CharField(blank=True, help_text="Numéro de facture", max_length=30)),
                ("content", models.BinaryField()),
                ("mime", models.CharField(default="application/vnd.openxmlformats-officedocument.wordprocessingml.document", max_length=100)),
                ("size_bytes", models.PositiveIntegerField(default=0)),
                ("amount_ht", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ("vat_rate", models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ("amount_ttc", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ("days", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("version", models.PositiveIntegerField(default=1)),
                ("meta", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("client", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="space_documents", to="projects.client")),
                ("person", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="client_documents", to=settings.AUTH_USER_MODEL)),
                ("readers", models.ManyToManyField(blank=True, related_name="readable_client_documents", to=settings.AUTH_USER_MODEL)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="tenants.tenant")),
            ],
            options={"ordering": ["-period", "person_id", "kind"],
                     "indexes": [models.Index(fields=["client", "period"], name="clientdoc_client_period")]},
        ),
    ]
