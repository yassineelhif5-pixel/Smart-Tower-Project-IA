from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("tenants", "0004_tenant_address_tenant_city_tenant_contact_email_and_more"),
                    ("projects", "0014_timesheet_lines_absences_natures")]

    operations = [
        migrations.AddField(
            model_name="tenantdomain", name="client",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="domains", to="projects.client")),
    ]
