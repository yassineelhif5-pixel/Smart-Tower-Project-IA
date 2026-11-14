"""Questions du Chef de projet IA aux membres du projet (et à leurs assistants IA).

Comme un chef de projet humain, l'assistant demande où en sont les actions, les dates réalistes et les blocages.
Le membre répond depuis la cloche ou depuis son propre assistant ; la réponse est transmise au chef de projet et
transformée en proposition (nouvelle échéance, action bloquée…) à valider.
"""
import secrets
import threading

from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.errors import ApiError
from configuration import audit
from configuration.models import AppSetting, Notification, NotificationChannel

from .models import Action

KEY = "assistant_questions"
KEEP = 80


def _store(project):
    row = AppSetting.objects.filter(tenant=project.tenant, key=KEY).first()
    data = row.value if row and isinstance(row.value, dict) else {}
    return row, data


def _save(project, row, data):
    if row:
        row.value = data
        row.save(update_fields=["value", "updated_at"])
    else:
        AppSetting.objects.create(tenant=project.tenant, key=KEY, value=data)


def questions_of(project):
    _, data = _store(project)
    return data.get(project.id, [])


def open_question_for(project, task_id):
    """Question en cours (ou répondue il y a moins de 3 jours) sur cette action : on ne redemande pas."""
    now = timezone.now()
    for q in questions_of(project):
        if q.get("task") != task_id:
            continue
        if q["status"] == "open":
            return q
        try:
            if (now - timezone.datetime.fromisoformat(q.get("answeredAt") or q["at"])).days < 3:
                return q
        except ValueError:
            continue
    return None


def _mail(project, user, subject, text):
    channel = NotificationChannel.objects.filter(tenant=project.tenant, kind="email", enabled=True).first()
    if not (channel and user and user.email):
        return
    from .project_alerts import _send_mails
    threading.Thread(target=_send_mails, args=(channel.pk, [user.email], subject, text), daemon=True).start()


def ask(project, by_label, task, kind, question, target=None):
    """Pose une question (au responsable de l'action, ou à `target`) : notification + e-mail. Renvoie la question."""
    target = target or (task.owner if task else None) or project.pm
    if target is None:
        return None
    subject = task.title if task else "Expression de besoin"
    q = {"id": f"Q{secrets.token_hex(4).upper()}", "task": task.id if task else None, "taskTitle": subject, "kind": kind,
         "to": target.pk, "toName": target.display_name, "question": question, "by": by_label,
         "at": timezone.now().isoformat(), "status": "open", "answer": "", "answeredAt": None,
         "newDue": None, "progress": None, "blocked": False}
    row, data = _store(project)
    data[project.id] = ([q] + data.get(project.id, []))[:KEEP]
    _save(project, row, data)
    who = by_label.split(" (")[0] if by_label and "Nova" in by_label else "Chef de projet IA"
    title = f"[{project.code}] ❓ Question de {who} : {subject}"[:200]
    Notification.objects.create(user=target, event="project_alert", title=title,
                                body=f"{question} · #Q:{q['id']} · {project.id}"[:2000])
    from .ai_orchestrator import log
    log(project, "question", who, f"Question à {target.display_name} : {question[:300]}", "nova" if who != "Chef de projet IA" else "atlas",
        {"question": q["id"]})
    _mail(project, target, title, f"{question}\n\nSujet : {subject}\nProjet : {project.name}\n\n"
                                  "Répondez depuis Smart Tower : cloche des notifications → cette question → « Répondre ».")
    return q


def answer(project, user, qid, text, new_due=None, progress=None, blocked=False):
    row, data = _store(project)
    items = data.get(project.id, [])
    q = next((x for x in items if x["id"] == qid), None)
    if q is None:
        raise ApiError("NOT_FOUND", "Question introuvable.", status.HTTP_404_NOT_FOUND)
    if q["to"] != user.pk and project.pm_id != user.pk and not user.is_app_admin:
        raise ApiError("FORBIDDEN_PERMISSION", "Cette question ne vous est pas adressée.", status.HTTP_403_FORBIDDEN)
    due = parse_date(str(new_due or "")) if new_due else None
    q.update({"status": "answered", "answer": str(text or "").strip()[:2000], "answeredAt": timezone.now().isoformat(),
              "answeredBy": user.display_name, "newDue": due.isoformat() if due else None,
              "progress": int(progress) if str(progress or "").isdigit() else None, "blocked": bool(blocked)})
    _save(project, row, data)
    from .ai_orchestrator import log
    log(project, "reponse", user.display_name, f"Réponse sur « {q['taskTitle']} » : {q['answer'][:300] or '—'}"
        + (f" (nouvelle date {due:%d/%m/%Y})" if due else "") + (" — bloqué" if blocked else ""), None, {"question": q["id"]})
    task = Action.objects.filter(project=project, pk=q["task"]).first() if q.get("task") else None
    # Le chef de projet humain est informé ; la réponse devient une proposition à valider.
    if project.pm and project.pm_id != user.pk:
        Notification.objects.create(
            user=project.pm, event="project_alert",
            title=f"[{project.code}] 💬 Réponse de {user.display_name} : {q['taskTitle']}"[:200],
            body=(f"{q['answer'] or '—'}" + (f" · nouvelle date proposée : {due:%d/%m/%Y}" if due else "")
                  + (" · action bloquée" if blocked else "") + f" · {project.id}")[:2000])
    from .assistant_review import add_pending
    if task and due and due != task.due:
        add_pending(project, {
            "kind": "late", "level": "warn", "do": "set_due", "key": f"ans-due-{q['id']}",
            "title": f"Porter l'échéance de « {task.title} » au {due:%d/%m}",
            "why": f"Réponse de {user.display_name} : « {q['answer'][:200]} ». Échéance actuelle : "
                   f"{task.due.strftime('%d/%m') if task.due else 'aucune'}.",
            "effect": f"Nouvelle échéance le {due:%d/%m/%Y} pour l'action {task.id}.",
            "payload": {"task": task.id}, "edit": {"due": due.isoformat()}})
    if task and blocked and task.status != "blocked":
        add_pending(project, {
            "kind": "blocked", "level": "crit", "do": "mark_blocked", "key": f"ans-block-{q['id']}",
            "title": f"Passer « {task.title} » en « Bloquée »",
            "why": f"{user.display_name} signale un blocage : « {q['answer'][:200]} ».",
            "effect": "Statut « Bloquée » et cause enregistrée ; la prochaine revue proposera un point de déblocage.",
            "payload": {"task": task.id, "cause": q["answer"][:500]}, "edit": {}})
    audit.record(user, f"Tâche {q['task']}", "Réponse au Chef de projet IA", "", q["answer"][:200], tenant=project.tenant)
    return q


class ProjectQuestionsView(APIView):
    """GET : questions du Chef de projet IA (les miennes ; toutes pour le chef de projet). POST : répondre."""

    def get(self, request, pk):
        from .workspace import _project, _rights
        project = _project(request.user, pk)
        r = _rights(request.user, project)
        items = questions_of(project)
        boss = r["isPm"] or r["isTl"] or request.user.is_app_admin
        mine = [q for q in items if q["to"] == request.user.pk]
        return Response({"mine": mine, "all": items[:40] if boss else [], "isPm": boss})

    def post(self, request, pk):
        from .workspace import _project
        project = _project(request.user, pk)
        if not str(request.data.get("answer") or "").strip() and not request.data.get("newDue"):
            raise ApiError("VALIDATION_ERROR", "Écrivez une réponse (ou indiquez une nouvelle date).")
        q = answer(project, request.user, str(request.data.get("id") or ""), request.data.get("answer"),
                   request.data.get("newDue"), request.data.get("progress"), bool(request.data.get("blocked")))
        return Response(q)
