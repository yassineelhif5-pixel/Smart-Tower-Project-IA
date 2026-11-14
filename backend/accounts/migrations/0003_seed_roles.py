"""Rôles et matrice des droits par défaut, repris tels quels de ROLES et MATRIX_SRC dans index.html."""
from django.db import migrations

ROLES = [
    ("admin", "Administrateur", "La plateforme et les accès sont-ils maîtrisés ?", True, False, True),
    ("direction", "Direction", "Quel est l'état global du portefeuille ?", True, True, True),
    ("manager", "Manager", "Quels projets nécessitent mon attention ?", True, False, True),
    ("commercial", "Commercial", "Le projet respecte-t-il le contrat et le budget ?", True, True, True),
    ("cdp", "Chef de projet", "Mon projet est-il maîtrisé ?", True, False, True),
    ("techlead", "Tech Lead", "Mon équipe avance-t-elle ?", False, False, True),
    ("consultant", "Consultant", "Qu'est-ce que je dois faire ?", False, False, True),
    ("dev", "Développeur", "Qu'est-ce que je dois faire ?", False, False, True),
    ("testeur", "Testeur", "La qualité est-elle au rendez-vous ?", False, False, True),
    ("client", "Client", "Mon projet avance-t-il comme prévu ?", False, False, False),
]
MODULES = ["project", "client", "planning", "action", "budget", "resource", "document", "test", "risk", "report", "user", "settings"]
MATRIX_SRC = {
    "admin":      "11111 11111 11111 11111 11111 11111 11111 11111 11111 11111 11111 11111",
    "direction":  "11001 11101 10000 10000 10001 10000 10000 10000 10000 10000 10000 10000",
    "manager":    "11101 11100 10000 11101 10100 11101 11100 10000 11101 10000 10000 10000",
    "commercial": "11000 11100 10000 00000 11101 00000 11000 00000 10000 10000 00000 00000",
    "cdp":        "10100 10000 11111 11111 10100 10100 11110 10000 11101 10000 00000 10000",
    "techlead":   "10000 00000 10000 11101 00000 10000 11000 10000 11000 00000 00000 00000",
    "consultant": "10000 00000 10000 11100 00000 00000 11000 00000 10000 00000 00000 00000",
    "dev":        "10000 00000 10000 11100 00000 00000 11000 00000 10000 00000 00000 00000",
    "testeur":    "10000 00000 10000 11100 00000 00000 11000 11101 10000 00000 00000 00000",
    "client":     "11000 10000 10000 10100 00000 00000 10000 00000 10000 00000 00000 00000",
}
VERBS = ["read", "create", "update", "delete", "approve"]


def seed(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    RolePermission = apps.get_model("accounts", "RolePermission")
    for position, (code, label, question, money, margin, internal) in enumerate(ROLES):
        Role.objects.update_or_create(code=code, defaults=dict(
            label=label, question=question, money=money, margin=margin, internal=internal, position=position))
        for module, flags in zip(MODULES, MATRIX_SRC[code].split()):
            RolePermission.objects.update_or_create(role_id=code, module=module, defaults={
                f"can_{verb}": flag == "1" for verb, flag in zip(VERBS, flags)})


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
