# Comptes de recette (QA) créés par Claude pour parcourir le Paramétrage. À désactiver après les tests.
import secrets
from django.contrib.auth import get_user_model
from accounts.models import ADMIN_ROLE, PLATFORM_ROLE
from tenants.models import DEFAULT_TENANT_SLUG, Tenant

User = get_user_model()
lines = []
for username, role, tenant in (("qa_pilote", PLATFORM_ROLE, None),
                               ("qa_admin", ADMIN_ROLE, Tenant.objects.get(slug=DEFAULT_TENANT_SLUG))):
    pwd = "Qa-" + secrets.token_urlsafe(12)
    user = User.objects.filter(username=username).first() or User(username=username)
    user.first_name, user.last_name = "Recette", username.split("_")[1].capitalize()
    user.role_id, user.tenant, user.is_active, user.must_change_password = role, tenant, True, False
    user.set_password(pwd)
    user.save()
    lines.append(f"{username}={pwd}")
open("qa_accounts.txt", "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("QA accounts ready:", ", ".join(l.split("=")[0] for l in lines))
