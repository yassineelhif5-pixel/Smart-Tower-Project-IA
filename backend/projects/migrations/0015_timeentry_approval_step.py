from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("projects", "0014_timesheet_lines_absences_natures")]

    operations = [
        migrations.AddField(model_name="timeentry", name="approval_step", field=models.PositiveSmallIntegerField(default=0)),
    ]
