from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("collaboration", "0003_projectconnectorgrant")]

    operations = [
        migrations.AddField(model_name="projectdiscussion", name="ai_members",
                            field=models.JSONField(blank=True, default=list, help_text="Assistants IA ajoutés à la discussion (codes)")),
        migrations.AddField(model_name="discussionmessage", name="ai_author",
                            field=models.CharField(blank=True, help_text="Code de l'assistant IA auteur du message", max_length=20)),
    ]
