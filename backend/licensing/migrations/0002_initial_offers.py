"""Offres de départ du cahier des charges : Demo, Starter, Pro, Enterprise.

Ce sont des données modifiables par le Pilote, pas des règles du code. Seule l'offre Demo est publiée,
avec la durée de 7 jours prévue au cahier des charges et des limites de départ réduites. Starter, Pro et
Enterprise sont créées en brouillon, sans prix ni quotas : le Pilote les complète puis les publie.
"""
from django.db import migrations

OFFERS = [
    ("demo", "Demo", "Découverte de la plateforme pendant 7 jours.", 0,
     dict(is_published=True, duration_days=7, max_users=5, named_licenses=3, concurrent_licenses=2, license_model="mixed")),
    ("starter", "Starter", "Pour les petites entreprises.", 1, dict(is_published=False)),
    ("pro", "Pro", "Pour les entreprises aux besoins plus importants.", 2, dict(is_published=False)),
    ("enterprise", "Enterprise", "Offre personnalisable : licences nominatives ou concurrentes, quotas et conditions spécifiques.", 3,
     dict(is_published=False, license_model="mixed")),
]


def seed(apps, schema_editor):
    Offer = apps.get_model("licensing", "Offer")
    OfferVersion = apps.get_model("licensing", "OfferVersion")
    for code, name, description, position, version in OFFERS:
        offer, created = Offer.objects.get_or_create(code=code, defaults={"name": name, "description": description, "position": position})
        if created:
            OfferVersion.objects.create(offer=offer, number=1, **version)


class Migration(migrations.Migration):
    dependencies = [("licensing", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
