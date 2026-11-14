import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0018_tenantmembership"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserPhoto",
            fields=[
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, related_name="photo",
                                              serialize=False, to=settings.AUTH_USER_MODEL)),
                ("content", models.BinaryField()),
                ("mime", models.CharField(default="image/jpeg", max_length=40)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
