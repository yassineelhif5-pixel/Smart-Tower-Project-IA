import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("clientspace", "0001_initial"),
        ("tenants", "0005_tenantdomain_client"),
    ]

    operations = [
        migrations.CreateModel(
            name="InvoiceTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("scope", models.CharField(choices=[("person", "Personne"), ("group", "Groupe de personnes"), ("company", "Société"), ("default", "Par défaut")], max_length=10)),
                ("company", models.CharField(blank=True, max_length=120)),
                ("filename", models.CharField(max_length=255)),
                ("content", models.BinaryField()),
                ("size_bytes", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("persons", models.ManyToManyField(blank=True, related_name="invoice_templates", to=settings.AUTH_USER_MODEL)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="tenants.tenant")),
                ("uploaded_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["scope", "name"]},
        ),
    ]
