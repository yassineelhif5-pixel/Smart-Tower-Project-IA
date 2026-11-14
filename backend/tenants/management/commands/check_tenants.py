"""Contrôle de cohérence : aucune ligne ne doit être reliée à un objet d'un autre tenant.

Utile après un import, une restauration ou une intervention manuelle en base. Code de sortie 1 en cas d'écart.
"""
from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import models
from django.db.models import F

from tenants.models import TenantOwned


class Command(BaseCommand):
    help = "Vérifie que chaque relation (clé étrangère et plusieurs-à-plusieurs) reste à l'intérieur d'un même tenant."

    def handle(self, *args, **options):
        problems = []
        for model in apps.get_models():
            # Tout modèle portant une colonne tenant : métier (TenantOwned), configuration, licences…
            if not issubclass(model, TenantOwned) and not any(f.name == "tenant" for f in model._meta.concrete_fields):
                continue
            for field in model._meta.get_fields():
                target = getattr(field, "related_model", None)
                if target is None or not any(f.name == "tenant" for f in target._meta.fields if hasattr(f, "name")):
                    continue
                if field.name == "tenant" or field.auto_created and not field.concrete:
                    continue
                if isinstance(field, models.ForeignKey):
                    if field.related_model._meta.label == "tenants.Tenant":
                        continue
                    # Un lien vers un compte sans tenant (le Pilote, acteur de la plateforme) n'est pas une fuite.
                    bad = model.objects.filter(**{f"{field.name}__isnull": False, f"{field.name}__tenant__isnull": False,
                                                  "tenant__isnull": False}).exclude(
                        **{f"{field.name}__tenant_id": F("tenant_id")}).count()
                elif isinstance(field, models.ManyToManyField):
                    bad = model.objects.exclude(**{f"{field.name}__isnull": True}).exclude(
                        **{f"{field.name}__tenant_id": F("tenant_id")}).values("pk").distinct().count()
                else:
                    continue
                if bad:
                    problems.append(f"{model.__name__}.{field.name} : {bad} ligne(s) reliée(s) à un autre tenant")
        if problems:
            raise CommandError("Incohérences entre tenants :\n- " + "\n- ".join(problems))
        self.stdout.write(self.style.SUCCESS("Aucune relation entre tenants : cohérence vérifiée."))
