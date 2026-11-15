import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

EVENTS = [("action_assigned", "Action assignée"), ("action_late", "Action en retard"), ("validation_requested", "Validation demandée"), ("budget_risk", "Budget en risque"), ("risk_critical", "Risque critique"), ("comment_mention", "Commentaire et mention"), ("document_new", "Nouveau document"), ("scope_changed", "Changement de périmètre"), ("key_date_reminder", "Rappel des dates clés"), ("date_changed", "Modification de date"), ("owner_changed", "Changement de responsable"), ("action_blocked", "Action bloquée"), ("deadline_reminder", "Rappel avant échéance"), ("milestone_reminder", "Rappel de jalon"), ("discussion_message", "Nouveau message de discussion"), ("week_start", "Début de semaine"), ("weekly_planning", "Rappel de préparation de la semaine"), ("sprint_planning", "Rappel de Sprint Planning"), ("daily_scrum", "Rappel de Daily Scrum"), ("sprint_review", "Rappel de Sprint Review"), ("retro_reminder", "Rappel de rétrospective"), ("sprint_close", "Rappel de clôture du sprint"), ("improvement_overdue", "Action d'amélioration non réalisée"), ("licence_request", "Demande de licence"), ("action_created", "Action créée"), ("action_updated", "Action modifiée"), ("action_due", "Échéance d'action atteinte"), ("weekly_recap", "Récapitulatif hebdomadaire"), ("project_alert", "Alerte projet")]


class Migration(migrations.Migration):
    dependencies = [("configuration", "0012_default_smtp"), ("tenants", "0005_tenantdomain_client")]

    operations = [
        migrations.AlterField("notification", "event", models.CharField(choices=EVENTS, max_length=30)),
        migrations.AlterField("notificationrule", "event", models.CharField(choices=EVENTS, max_length=30)),
        migrations.AlterField("usernotificationpreference", "event", models.CharField(choices=EVENTS, max_length=30)),
        migrations.CreateModel(
            name="NotificationDelivery",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("event", models.CharField(blank=True, max_length=30)),
                ("channel", models.CharField(default="email", max_length=10)),
                ("recipient", models.CharField(max_length=254)),
                ("subject", models.CharField(max_length=200)),
                ("status", models.CharField(choices=[("sent", "Envoyé"), ("failed", "Échec"), ("skipped", "Non envoyé")], default="sent", max_length=10)),
                ("error", models.CharField(blank=True, max_length=300)),
                ("source", models.CharField(blank=True, help_text="tenant | platform", max_length=40)),
                ("tenant", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="tenants.tenant")),
            ],
            options={"ordering": ["-at"]},
        ),
    ]
