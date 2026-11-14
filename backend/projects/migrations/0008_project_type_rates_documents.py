# Type de projet (nouveau / évolution / amélioration), TJM par membre, fichiers des documents.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0007_timeapprovaldelegation'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='project_type',
            field=models.CharField(choices=[('new', 'Nouveau projet (from scratch)'), ('evolution', "Évolution d'un projet existant"), ('improvement', "Amélioration d'un projet existant")], default='new', max_length=12),
        ),
        migrations.AddField(
            model_name='project',
            name='base_project',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='projects.project'),
        ),
        migrations.AddField(
            model_name='project',
            name='base_version',
            field=models.CharField(blank=True, help_text='Version du produit existant concernée', max_length=40),
        ),
        migrations.AddField(
            model_name='projectaccess',
            name='daily_rate',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='TJM du membre sur ce projet (calcul de la consommation du budget)', max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='document',
            name='content',
            field=models.BinaryField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name='document',
            name='mime',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='document',
            name='size_bytes',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='document',
            name='description',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='document',
            name='extracted_text',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='document',
            name='extraction',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
