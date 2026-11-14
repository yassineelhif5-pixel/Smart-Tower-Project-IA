# Comptes de recette (QA) - un par profil, rattaches aux donnees de demonstration. A desactiver apres les tests.
import secrets, traceback
from pathlib import Path
from django.core.management import call_command
from django.contrib.auth import get_user_model
from accounts.models import Role
from tenants.models import DEFAULT_TENANT_SLUG, Tenant
from projects.models import Client, Project, ProjectAccess


User = get_user_model()
tenant = Tenant.objects.get(slug=DEFAULT_TENANT_SLUG)
path = Path("qa_accounts.txt")
old = dict(l.split("=", 1) for l in path.read_text(encoding="utf-8").split() if "=" in l) if path.exists() else {}

print("Clients :", [(c.code, c.name) for c in Client.objects.filter(tenant=tenant)])
print("Projets :", [(p.code, p.name, p.client_id) for p in Project.objects.filter(tenant=tenant)])
projects = list(Project.objects.filter(tenant=tenant).select_related("client").order_by("code")[:3])
client = projects[0].client if projects else Client.objects.first()
print("Projets de test :", [p.code for p in projects], "| client de test :", getattr(client, "code", None))

wanted = [("qa_pilote", "superadmin", None)] + [(f"qa_{r}", r, tenant) for r in
          ("admin", "direction", "manager", "commercial", "cdp", "techlead", "consultant", "dev", "testeur", "client")]
lines = []
for username, role, ten in wanted:
    if not Role.objects.filter(pk=role).exists():
        print("Role absent, ignore :", role); continue
    pwd = old.get(username) or "Qa-" + secrets.token_urlsafe(12)
    u = User.objects.filter(username=username).first() or User(username=username)
    u.first_name, u.last_name = "Recette", username.split("_", 1)[1].capitalize()
    u.role_id, u.tenant, u.is_active, u.must_change_password = role, ten, True, False
    u.client = client if role == "client" else None
    u.set_password(pwd); u.save()
    if ten and role in ("cdp", "techlead", "consultant", "dev", "testeur", "manager", "direction", "commercial"):
        for p in projects:
            ProjectAccess.objects.get_or_create(user=u, project=p, defaults={"can_edit": role != "direction"})
            if role in ("techlead", "consultant", "dev", "testeur"):
                p.team.add(u)
    if role == "cdp" and projects:
        projects[0].pm = u; projects[0].save(update_fields=["pm"])
    if role == "techlead" and projects:
        projects[0].tl = u; projects[0].save(update_fields=["tl"])
    if role == "manager" and client: client.managers.add(u)
    if role == "commercial" and client: client.sales.add(u)
    lines.append(f"{username}={pwd}")
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("QA accounts ready:", ", ".join(l.split("=")[0] for l in lines))
