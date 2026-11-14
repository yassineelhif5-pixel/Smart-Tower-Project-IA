# Délégation de validation des temps pendant une absence (circuit de validation configurable).

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0006_timeentry_approval_status_timeentry_approved_at_and_more'),
        ('tenants', '0004_tenant_address_tenant_city_tenant_contact_email_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TimeApprovalDelegation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('start_date', models.DateField()),
                ('end_date', models.DateField()),
                ('reason', models.CharField(blank=True, max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('delegate', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='time_delegations_received', to=settings.AUTH_USER_MODEL)),
                ('delegator', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='time_delegations_given', to=settings.AUTH_USER_MODEL)),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='tenants.tenant')),
            ],
            options={
                'ordering': ['-start_date', '-id'],
                'abstract': False,
                'indexes': [models.Index(fields=['delegator', 'start_date', 'end_date'], name='time_deleg_period_idx')],
                'constraints': [
                    models.CheckConstraint(condition=models.Q(('end_date__gte', models.F('start_date'))), name='time_delegation_dates'),
                    models.CheckConstraint(condition=models.Q(('delegator', models.F('delegate')), _negated=True), name='time_delegation_not_self'),
                ],
            },
        ),
    ]
