from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("projects", "0015_timeentry_approval_step")]

    operations = [
        migrations.AddField(model_name="timeentry", name="reject_reason", field=models.CharField(blank=True, default="", max_length=500)),
        migrations.AddField(model_name="timeentry", name="approvals", field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name="action", name="ticket", field=models.CharField(blank=True, default="", max_length=60)),
        migrations.AddField(model_name="action", name="ext_owner", field=models.CharField(blank=True, default="", max_length=120)),
        migrations.AddField(model_name="action", name="incident_date", field=models.DateField(blank=True, null=True)),
    ]
