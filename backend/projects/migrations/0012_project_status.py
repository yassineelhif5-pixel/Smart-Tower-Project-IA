from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("projects", "0011_migration_instances")]

    operations = [
        migrations.AddField(model_name="project", name="status",
                            field=models.CharField(choices=[("active", "En cours"), ("paused", "En pause"), ("closed", "Clôturé")], default="active", max_length=10)),
        migrations.AddField(model_name="project", name="closed_at", field=models.DateField(blank=True, null=True)),
    ]
