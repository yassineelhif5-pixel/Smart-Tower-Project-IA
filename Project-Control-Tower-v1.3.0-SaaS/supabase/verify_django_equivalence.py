"""Vérifie que les règles de lecture Django (projects.access.visible) donnent les mêmes lignes que les RLS Supabase.

Outil de contrôle ponctuel (lot 2b), pas un test automatique : il faut une copie locale du schéma Supabase.
1. Base « sb » sur un PostgreSQL local : rôles authenticated/anon, schéma auth avec auth.users et auth.uid()
   (lecture de request.jwt.claim.sub), puis migrations/20261030220000_schema.sql et seed.sql.
2. Comptes : insert into auth.users(id, email) select md5(id)::uuid, email from public.people where email is not null;
3. Base Django avec python manage.py migrate et load_demo, puis :
   SB_PSQL="psql -h localhost -p 5432 -U postgres -d sb" python manage.py shell < ../supabase/verify_django_equivalence.py
Résultat du 2026-11-01 : 280 contrôles (20 tables × 14 personnes actives), 0 écart.
"""
import os
import shlex
import hashlib
import subprocess
import uuid

from accounts.models import User
from projects import models as m
from projects.access import visible

PSQL = shlex.split(os.environ.get("SB_PSQL", "psql -h localhost -p 5432 -U postgres -d sb"))


def sb(sub, sql):
    q = f"begin; set local role authenticated; set local request.jwt.claim.sub = '{sub}'; {sql}; commit;"
    out = subprocess.run(PSQL + ["-At", "-c", q],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return {line for line in out.stdout.splitlines() if line not in ("BEGIN", "SET", "COMMIT")}


T = {
    "clients": (m.Client, "select id from public.clients", lambda o: o.code),
    "client_contracts": (m.ClientContract, "select ref from public.client_contracts", lambda o: o.ref),
    "people_internal": (m.PersonCapacity, "select person_id from public.people_internal", lambda o: o.user.person_code),
    "projects": (m.Project, "select id from public.projects", lambda o: o.id),
    "project_internal": (m.ProjectInternal, "select project_id from public.project_internal", lambda o: o.project_id),
    "project_finance": (m.ProjectFinance, "select project_id from public.project_finance", lambda o: o.project_id),
    "actions": (m.Action, "select id from public.actions", lambda o: o.id),
    "action_comments": (m.ActionComment, "select action_id||'|'||body from public.action_comments", lambda o: o.action_id + "|" + o.body),
    "user_stories": (m.UserStory, "select id from public.user_stories", lambda o: o.id),
    "objectives": (m.Objective, "select id from public.objectives", lambda o: o.id),
    "todos": (m.Todo, "select owner||'|'||label from public.todos", lambda o: o.owner.person_code + "|" + o.label),
    "time_entries": (m.TimeEntry, "select person_id||'|'||project_id||'|'||work_date||'|'||hours::numeric(6,2)||'|'||coalesce(action_id,'') from public.time_entries",
                     lambda o: f"{o.person.person_code}|{o.project_id}|{o.work_date}|{o.hours}|{o.action_id or ''}"),
    "risks": (m.Risk, "select id from public.risks", lambda o: o.id),
    "issues": (m.Issue, "select id from public.issues", lambda o: o.id),
    "change_requests": (m.ChangeRequest, "select id from public.change_requests", lambda o: o.id),
    "change_request_amounts": (m.ChangeRequestAmount, "select cr_id from public.change_request_amounts", lambda o: o.change_request_id),
    "test_campaigns": (m.TestCampaign, "select id from public.test_campaigns", lambda o: o.id),
    "defects": (m.Defect, "select id from public.defects", lambda o: o.id),
    "documents": (m.Document, "select id from public.documents", lambda o: o.id),
    "meetings": (m.Meeting, "select id from public.meetings", lambda o: o.id),
}

checks = diffs = 0
for u in User.objects.exclude(person_code=None).filter(is_active=True).order_by("person_code"):
    sub = str(uuid.UUID(hashlib.md5(u.person_code.encode()).hexdigest()))
    for table, (model, sql, key) in T.items():
        a = sb(sub, sql)
        b = {key(o) for o in visible(u, model).select_related()}
        checks += 1
        if a != b:
            diffs += 1
            print("ÉCART", u.person_code, u.role_id, table, "supabase seul:", sorted(a - b)[:3], "django seul:", sorted(b - a)[:3])
print(f"{checks} contrôles ({len(T)} tables × personnes actives), {diffs} écarts")
