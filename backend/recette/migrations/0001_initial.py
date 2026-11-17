import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

PRIO = [("bloquante", "Bloquante"), ("critique", "Critique"), ("majeure", "Majeure"), ("mineure", "Mineure"), ("autre", "Autre")]


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("projects", "0017_timeabsence_kind_label"),
        ("tenants", "0006_tenant_join_code_demo"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TestStory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=20)),
                ("title", models.CharField(max_length=300)),
                ("description", models.TextField(blank=True, help_text="En tant que… je veux… afin de…")),
                ("acceptance", models.TextField(blank=True, help_text="Critères d'acceptation")),
                ("scenario", models.TextField(blank=True, help_text="Étapes de test")),
                ("expected", models.TextField(blank=True, help_text="Résultat attendu")),
                ("feature", models.CharField(blank=True, help_text="Lot / fonctionnalité", max_length=120)),
                ("priority", models.CharField(choices=PRIO, default="majeure", max_length=10)),
                ("status", models.CharField(choices=[("a_tester", "À tester"), ("en_test", "En test"), ("validee", "Validée"), ("echec", "En échec"), ("a_retester", "Prête à retester"), ("bloquee", "Bloquée")], default="a_tester", max_length=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("tested_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="test_stories", to="projects.project")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="tenants.tenant")),
                ("tested_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("tester", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["project_id", "id"]},
        ),
        migrations.CreateModel(
            name="Bug",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=20)),
                ("title", models.CharField(max_length=300)),
                ("description", models.TextField(blank=True)),
                ("steps", models.TextField(blank=True, help_text="Étapes pour reproduire")),
                ("severity", models.CharField(choices=PRIO, default="majeure", max_length=10)),
                ("status", models.CharField(choices=[("nouveau", "Nouveau"), ("assigne", "Assigné"), ("en_cours", "En cours"), ("cloture", "Clôturé"), ("rejete", "Rejeté"), ("rouvert", "Rouvert")], default="nouveau", max_length=10)),
                ("resolution", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("assignee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="bugs", to="projects.project")),
                ("reported_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("story", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="bugs", to="recette.teststory")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="tenants.tenant")),
            ],
            options={"ordering": ["project_id", "id"]},
        ),
        migrations.CreateModel(
            name="TestComment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("body", models.TextField()),
                ("kind", models.CharField(default="comment", help_text="comment ou event", max_length=8)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("author", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("bug", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="comments", to="recette.bug")),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="projects.project")),
                ("story", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="comments", to="recette.teststory")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="tenants.tenant")),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
        migrations.AddConstraint(model_name="teststory", constraint=models.UniqueConstraint(fields=("project", "code"), name="uniq_test_story_code")),
        migrations.AddConstraint(model_name="bug", constraint=models.UniqueConstraint(fields=("project", "code"), name="uniq_bug_code")),
    ]
