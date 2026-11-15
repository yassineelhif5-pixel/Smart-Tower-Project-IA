from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tenants", "0005_tenantdomain_client")]

    operations = [
        migrations.AddField("tenant", "join_code", models.CharField(blank=True, help_text="Code secret pour demander à rejoindre l'entreprise", max_length=20, null=True, unique=True)),
        migrations.AddField("tenant", "demo_until", models.DateField(blank=True, help_text="Tenant de démonstration : dernier jour d'accès", null=True)),
    ]
