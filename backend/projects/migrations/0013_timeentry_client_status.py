from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("projects", "0012_project_status")]

    operations = [
        migrations.AlterField(
            model_name="timeentry", name="approval_status",
            field=models.CharField(choices=[("pending", "À valider"), ("client", "Chez le client"), ("approved", "Validé"), ("rejected", "Refusé")],
                                   default="pending", max_length=10)),
    ]
