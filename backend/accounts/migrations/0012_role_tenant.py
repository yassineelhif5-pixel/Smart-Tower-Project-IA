from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0011_methodology_permissions"),
        ("tenants", "0002_default_tenant"),
    ]

    operations = [
        migrations.AddField(
            model_name="role",
            name="tenant",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="roles", to="tenants.tenant"),
        ),
    ]
