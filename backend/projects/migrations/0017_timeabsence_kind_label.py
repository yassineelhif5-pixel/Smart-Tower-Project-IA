from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("projects", "0016_timeentry_reject_reason")]

    operations = [
        migrations.AlterField("timeabsence", "kind", models.CharField(choices=[("cp", "Congés payés"), ("rtt", "RTT"), ("sick", "Maladie"), ("training", "Formation"), ("holiday", "Jour férié"), ("unpaid", "Congé sans solde"), ("other", "Absence / temps non saisi")], max_length=10)),
    ]
