import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("licensing", "0008_offervoucher_request_alter_licenserequest_status"),
        ("tenants", "0006_tenant_join_code_demo"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Payment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("offer", "Offre"), ("licenses", "Licences")], max_length=10)),
                ("license_kind", models.CharField(blank=True, choices=[("named", "Nominative"), ("concurrent", "Concurrente")], max_length=10)),
                ("quantity", models.PositiveIntegerField(default=1)),
                ("unit_amount", models.PositiveIntegerField(help_text="Montant unitaire en centimes")),
                ("amount", models.PositiveIntegerField(help_text="Montant total en centimes")),
                ("currency", models.CharField(default="EUR", max_length=3)),
                ("interval", models.CharField(blank=True, help_text="month, year ou vide (paiement unique)", max_length=10)),
                ("status", models.CharField(choices=[("pending", "En attente"), ("paid", "Payé"), ("applied", "Payé et appliqué"), ("failed", "Échec"), ("expired", "Expiré"), ("cancelled", "Abonnement résilié")], default="pending", max_length=10)),
                ("stripe_session", models.CharField(blank=True, max_length=255, null=True, unique=True)),
                ("stripe_customer", models.CharField(blank=True, max_length=255)),
                ("stripe_subscription", models.CharField(blank=True, max_length=255)),
                ("checkout_url", models.URLField(blank=True, max_length=1000)),
                ("error", models.CharField(blank=True, max_length=300)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("applied_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("offer_version", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="payments", to="licensing.offerversion")),
                ("request", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="payments", to="licensing.licenserequest")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payments", to="tenants.tenant")),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
