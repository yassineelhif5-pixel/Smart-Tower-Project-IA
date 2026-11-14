# Types de projet étendus et version cible.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0008_project_type_rates_documents'),
    ]

    operations = [
        migrations.AlterField(
            model_name='project',
            name='project_type',
            field=models.CharField(choices=[('new', 'Nouveau projet (from scratch)'), ('evolution', 'Évolution (nouvelle version)'), ('improvement', "Amélioration d'une version existante"), ('bugfix', "Correction d'incidents"), ('restoration', 'Restauration / reprise'), ('migration', 'Migration (technique ou de données)'), ('maintenance', 'Maintenance / TMA'), ('integration', 'Intégration / déploiement'), ('audit', 'Audit / conseil'), ('other', 'Autre')], default='new', max_length=12),
        ),
        migrations.AlterField(
            model_name='project',
            name='base_version',
            field=models.CharField(blank=True, help_text='Version source (existante)', max_length=40),
        ),
        migrations.AddField(
            model_name='project',
            name='target_version',
            field=models.CharField(blank=True, help_text='Version cible (à livrer)', max_length=40),
        ),
    ]
