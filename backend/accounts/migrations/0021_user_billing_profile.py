from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0020_client_support_roles")]

    operations = [
        migrations.AddField("user", "company", models.CharField(blank=True, help_text="Société de rattachement (ex. société du consultant externe)", max_length=120)),
        migrations.AddField("user", "external", models.BooleanField(default=False, help_text="Intervenant externe rattaché à une société")),
        migrations.AddField("user", "daily_rate", models.DecimalField(blank=True, decimal_places=2, help_text="TJM HT par défaut de la personne", max_digits=10, null=True)),
    ]
