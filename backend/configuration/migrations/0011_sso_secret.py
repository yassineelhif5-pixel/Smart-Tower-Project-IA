from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("configuration", "0010_methodology_notification_rules")]
    operations = [
        migrations.AlterField(
            model_name="servicesecret",
            name="key",
            field=models.CharField(choices=[
                ("smtp_password", "Mot de passe SMTP"),
                ("teams_webhook_url", "URL du webhook Teams"),
                ("slack_webhook_url", "URL du webhook Slack"),
                ("teams_client_secret", "Secret client de l'application Microsoft"),
                ("sso_client_secret", "Secret du connecteur SSO"),
            ], max_length=40),
        ),
    ]
