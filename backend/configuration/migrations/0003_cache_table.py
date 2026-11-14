"""Table du cache partagé (DatabaseCache).

Le compteur de tentatives de connexion (10 par minute) vivait en mémoire locale :
remis à zéro à chaque redémarrage et non partagé entre plusieurs processus serveur.
Il est désormais stocké dans PostgreSQL, partagé par tous les processus.
"""
from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    call_command("createcachetable", database=schema_editor.connection.alias, verbosity=0)


class Migration(migrations.Migration):
    dependencies = [("configuration", "0002_seed_notifications")]
    operations = [migrations.RunPython(create_cache_table, migrations.RunPython.noop)]
