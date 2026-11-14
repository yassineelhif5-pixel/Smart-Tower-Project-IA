from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("projects", "0013_timeentry_client_status"), ("tenants", "0004_tenant_address_tenant_city_tenant_contact_email_and_more"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.AlterField(
            model_name="timeentry", name="approval_status",
            field=models.CharField(choices=[("draft", "Brouillon"), ("pending", "À valider"), ("client", "Chez le client"), ("approved", "Validé"), ("rejected", "Refusé")],
                                   default="pending", max_length=10)),
        migrations.AddField(model_name="timeentry", name="line", field=models.CharField(blank=True, default="", max_length=40)),
        migrations.AddField(model_name="project", name="natures", field=models.JSONField(blank=True, default=list)),
        migrations.CreateModel(
            name="TimeAbsence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("work_date", models.DateField()),
                ("kind", models.CharField(choices=[("cp", "Congés payés"), ("rtt", "RTT"), ("sick", "Maladie"), ("training", "Formation"), ("holiday", "Jour férié"), ("unpaid", "Congé sans solde"), ("other", "Autre absence")], max_length=10)),
                ("hours", models.DecimalField(decimal_places=2, max_digits=5)),
                ("status", models.CharField(choices=[("draft", "Brouillon"), ("submitted", "Envoyée")], default="draft", max_length=10)),
                ("person", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="time_absences", to=settings.AUTH_USER_MODEL)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="tenants.tenant")),
            ],
            options={"ordering": ["work_date", "id"]},
        ),
        migrations.AddConstraint(model_name="timeabsence", constraint=models.UniqueConstraint(fields=("person", "work_date", "kind"), name="absence_unique_day_kind")),
    ]
