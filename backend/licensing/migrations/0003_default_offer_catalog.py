from django.db import migrations


def update_catalog(apps, schema_editor):
    Offer = apps.get_model("licensing", "Offer")
    OfferVersion = apps.get_model("licensing", "OfferVersion")
    defaults = [
        ("starter", "Standard", "Pour les équipes qui démarrent avec Project Control Tower.", 0),
        ("pro", "Premium", "Pour les organisations avec des besoins avancés.", 1),
        ("enterprise", "Entreprise", "Offre personnalisable par le Pilote : tarifs, quotas et licences.", 2),
    ]
    for code, name, description, position in defaults:
        offer, _ = Offer.objects.get_or_create(code=code, defaults={"name": name})
        offer.name, offer.description, offer.position, offer.is_active = name, description, position, True
        offer.save(update_fields=["name", "description", "position", "is_active"])
        if not OfferVersion.objects.filter(offer=offer).exists():
            OfferVersion.objects.create(offer=offer, number=1, is_published=False)
    Offer.objects.filter(code="demo").update(is_active=False, position=99)


class Migration(migrations.Migration):
    dependencies = [("licensing", "0002_initial_offers")]
    operations = [migrations.RunPython(update_catalog, migrations.RunPython.noop)]
