import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0021_user_billing_profile"), ("tenants", "0006_tenant_join_code_demo")]

    operations = [
        migrations.CreateModel(
            name="SignupProfile",
            fields=[
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, related_name="signup",
                                              serialize=False, to=settings.AUTH_USER_MODEL)),
                ("source", models.CharField(default="password", help_text="password ou google", max_length=10)),
                ("email_verified", models.BooleanField(default=False)),
                ("verify_hash", models.CharField(blank=True, db_index=True, max_length=64)),
                ("verify_sent_at", models.DateTimeField(blank=True, null=True)),
                ("google_sub", models.CharField(blank=True, max_length=255, null=True, unique=True)),
                ("profile_done", models.BooleanField(default=False)),
                ("kind", models.CharField(blank=True, choices=[("company", "Entreprise"), ("individual", "Particulier / indépendant")], max_length=12)),
                ("phone", models.CharField(blank=True, max_length=40)),
                ("job_title", models.CharField(blank=True, max_length=120)),
                ("company_name", models.CharField(blank=True, max_length=120)),
                ("company_size", models.CharField(blank=True, max_length=20)),
                ("country", models.CharField(blank=True, max_length=80)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("demo_tenant", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="tenants.tenant")),
            ],
        ),
        migrations.CreateModel(
            name="TenantJoinRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("message", models.CharField(blank=True, max_length=500)),
                ("status", models.CharField(choices=[("pending", "En attente"), ("approved", "Acceptée"), ("rejected", "Refusée"), ("cancelled", "Annulée")], default="pending", max_length=10)),
                ("comment", models.CharField(blank=True, max_length=300)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decided_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("role", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="accounts.role")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="join_requests", to="tenants.tenant")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="join_requests", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="tenantjoinrequest",
            constraint=models.UniqueConstraint(condition=models.Q(("status", "pending")), fields=("user", "tenant"), name="uniq_pending_join_request"),
        ),
    ]
