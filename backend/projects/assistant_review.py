"""Revue de projet du Chef de projet IA : il travaille comme un chef de projet humain, en binôme avec lui.

Il passe en revue les actions, la charge, le planning macro, le budget, les documents et les alertes ouvertes, puis
formule des propositions concrètes et motivées (relancer, replanifier, affecter, rééquilibrer, alerter l'équipe,
créer une action, demander un document…).

- Mode semi-automatique : les propositions sont conservées « en attente » ; le chef de projet humain les ajuste
  (responsable, échéance), les valide ou les écarte. Chaque décision est tracée.
- Mode automatique : l'assistant exécute lui-même les propositions et en rend compte au chef de projet humain.
- Revue quotidienne : au passage d'un membre dans l'application, au plus une fois par jour et par projet.
"""
import re
import secrets
from datetime import date, timedelta

from django.utils import timezone

from configuration import audit
from configuration.models import AppSetting, Notification

from .models import Action, Document, ProjectAccess

KEY = "assistant_review"
LEVEL_RANK = {"crit": 0, "warn": 1, "info": 2}
KINDS = {
    "late": ("⏰", "Retard"), "blocked": ("⛔", "Blocage"), "assign": ("👤", "Affectation"),
    "nudge": ("📌", "Échéance proche"), "rebalance": ("⚖️", "Charge"), "phase": ("🗓️", "Planning"),
    "budget": ("💶", "Budget"), "doc_missing": ("📂", "Documents"), "doc_date": ("📄", "Documents"),
    "alert_open": ("🚨", "Alertes"), "ask": ("❓", "Question à l'équipe"),
    "req_ambiguity": ("📐", "Besoin (AMOA)"), "req_missing": ("📐", "Besoin (AMOA)"), "req_story": ("📐", "Exigences (AMOA)"),
    "test_missing": ("🧪", "Qualité / recette"), "minutes": ("📝", "Compte rendu de réunion"),
}
# Mode automatique : actions courantes exécutées par l'IA ; les décisions restent soumises au chef de projet humain.
ROUTINE = {"ask", "nudge", "notify_pm", "alert"}


def _today():
    return timezone.localdate()


def _workday(d, n):
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def _pid(*parts):
    """Identifiant stable d'une proposition : la même situation donne la même proposition d'une revue à l'autre."""
    return "P-" + re.sub(r"[^A-Za-z0-9]+", "-", "-".join(str(p) for p in parts))[:60]


def _members(project):
    return {a.user_id: a.user for a in ProjectAccess.objects.filter(project=project, user__is_active=True).select_related("user", "user__role")}


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


def state_of(project):
    _, data = _store(project)
    st = data.get(project.id) or {}
    return {"at": st.get("at"), "pending": st.get("pending", []), "history": st.get("history", [])[:40],
            "dismissed": st.get("dismissed", {})}


# --------------------------------------------------------------------------- analyse « comme un chef de projet »
def build(project):
    """Analyse complète du projet → liste de propositions motivées, de la plus urgente à la moins urgente."""
    from .assistant_questions import open_question_for
    from .planning_view import workload
    from .workspace import DOC_TYPES, budget_of, live_phases

    today = _today()
    tasks = list(Action.objects.filter(project=project).select_related("owner"))
    open_ = [t for t in tasks if t.status != "done"]
    members = _members(project)
    load, _ = workload(project, tasks, today)
    by_load = sorted(load, key=lambda m: (m["remaining"], m["open"]))
    lightest = by_load[0] if by_load else None
    pm = project.pm
    props = []

    def add(kind, level, title, why, effect, do, payload=None, edit=None, key=None):
        props.append({"id": _pid(kind, key or title), "kind": kind, "icon": KINDS[kind][0], "category": KINDS[kind][1],
                      "level": level, "title": title, "why": why, "effect": effect, "do": do,
                      "payload": payload or {}, "edit": edit or {}})

    # 1. Actions en retard : relancer le responsable et proposer une nouvelle échéance réaliste.
    planned = {}
    for t in sorted([t for t in open_ if t.due and t.due < today], key=lambda t: t.due):
        days_late = (today - t.due).days
        need = max(1, round(float(t.raf or t.est or 4) / 7))
        start = planned.get(t.owner_id or 0, today)
        new_due = _workday(start, need)
        planned[t.owner_id or 0] = new_due
        who = t.owner.display_name if t.owner_id else "aucun responsable"
        add("late", "crit" if days_late > 5 else "warn",
            f"Relancer {who} et replanifier « {t.title} »",
            f"Échéance dépassée de {days_late} jour(s) (prévue le {t.due:%d/%m}). Statut : {t.status}. "
            f"Reste estimé : {float(t.raf or t.est or 0) or '—'} h.",
            f"Notification + e-mail à {who} ; nouvelle échéance proposée le {new_due:%d/%m/%Y}.",
            "late", {"task": t.id}, {"due": new_due.isoformat()}, key=t.id)
        if t.owner_id and not open_question_for(project, t.id):
            add("ask", "warn", f"Demander à {who} où en est « {t.title} »",
                f"Action en retard de {days_late} jour(s) : il faut connaître l'avancement réel, une date de fin réaliste et les éventuels blocages.",
                f"Question envoyée à {who} (notification + e-mail) ; sa réponse vous sera transmise et proposée en décision.",
                "ask", {"task": t.id, "kind": "late",
                        "question": f"L'action « {t.title} » devait être terminée le {t.due:%d/%m}. Où en êtes-vous (avancement en %) ? "
                                    "Quelle date de fin réaliste proposez-vous ? Y a-t-il un blocage ?"}, key=f"late-{t.id}")

    # 2. Actions bloquées : prévenir l'équipe et organiser un point de déblocage.
    for t in [t for t in open_ if t.status == "blocked"]:
        owner = (project.tl or pm)
        add("blocked", "crit", f"Débloquer « {t.title} »",
            f"L'action {t.id} est bloquée ({t.owner.display_name if t.owner_id else 'sans responsable'}). "
            "Un blocage non traité fait glisser la phase et les actions qui en dépendent.",
            f"Alerte « Action bloquée » à l'équipe + action « Point de déblocage » pour {owner.display_name if owner else '—'} sous 2 jours ouvrés.",
            "blocked", {"task": t.id}, {"owner": owner.id if owner else None, "due": _workday(today, 2).isoformat()}, key=t.id)
        if t.owner_id and not open_question_for(project, t.id):
            add("ask", "warn", f"Demander à {t.owner.display_name} la cause du blocage de « {t.title} »",
                "Pour débloquer, il faut connaître la cause exacte et l'aide attendue.",
                f"Question envoyée à {t.owner.display_name} (notification + e-mail).", "ask",
                {"task": t.id, "kind": "blocked",
                 "question": f"L'action « {t.title} » est bloquée. Quelle est la cause du blocage et de quoi avez-vous besoin "
                             "(personne, information, accès, décision) ? Quelle date pouvez-vous viser une fois débloqué ?"},
                key=f"blocked-{t.id}")

    # 3. Actions sans responsable : proposer le membre le moins chargé.
    for t in [t for t in open_ if not t.owner_id][:8]:
        if not lightest:
            break
        add("assign", "warn", f"Affecter « {t.title} » à {lightest['name']}",
            f"Action sans responsable. {lightest['name']} est le membre le moins chargé "
            f"({lightest['remaining']} h restantes, {lightest['open']} action(s) ouvertes).",
            f"{lightest['name']} devient responsable et reçoit une notification.",
            "assign", {"task": t.id}, {"owner": lightest["id"]}, key=t.id)

    # 4. Échéance dans les 3 jours et action pas démarrée : rappel au responsable.
    for t in [t for t in open_ if t.due and today <= t.due <= today + timedelta(days=3) and t.status in ("todo", "planned") and t.owner_id]:
        if open_question_for(project, t.id):
            continue
        add("ask", "info", f"Vérifier avec {t.owner.display_name} l'échéance du {t.due:%d/%m}",
            f"« {t.title} » est due dans {(t.due - today).days} jour(s) et n'est pas encore démarrée.",
            f"Question à {t.owner.display_name} : l'échéance sera-t-elle tenue ?", "ask",
            {"task": t.id, "kind": "due_soon",
             "question": f"L'action « {t.title} » est due le {t.due:%d/%m} et n'est pas encore démarrée. "
                         "Confirmez-vous que l'échéance sera tenue ? Sinon, quelle date proposez-vous ?"}, key=f"soon-{t.id}")
    # Actions en cours sans échéance : demander une date pour pouvoir planifier.
    for t in [t for t in open_ if not t.due and t.owner_id and t.status in ("doing", "review")][:5]:
        if open_question_for(project, t.id):
            continue
        add("ask", "info", f"Demander une échéance à {t.owner.display_name} pour « {t.title} »",
            "Action en cours sans échéance : impossible de la suivre dans le planning ni le plan de charge.",
            f"Question à {t.owner.display_name} : date de fin prévue.", "ask",
            {"task": t.id, "kind": "no_due",
             "question": f"L'action « {t.title} » est en cours mais n'a pas d'échéance. Quelle date de fin prévoyez-vous ?"},
            key=f"nodue-{t.id}")

    # 5. Surcharge : transférer une action du membre surchargé vers le moins chargé.
    for m in load:
        over = [w for w in m["weeks"][:2] if w["capacity"] and w["hours"] > w["capacity"] * 1.15]
        if not over or not lightest or lightest["id"] == m["id"]:
            continue
        cand = sorted([t for t in open_ if t.owner_id == m["id"] and t.status in ("todo", "planned")],
                      key=lambda t: (t.due or date.max))
        if not cand:
            continue
        t = cand[-1]
        add("rebalance", "warn", f"Transférer « {t.title} » de {m['name']} à {lightest['name']}",
            f"{m['name']} est chargé à {round(over[0]['hours'] / over[0]['capacity'] * 100)} % de sa capacité "
            f"(semaine du {over[0]['week']:%d/%m}). {lightest['name']} a le plus de disponibilité.",
            f"Changement de responsable de l'action {t.id} + notification aux deux personnes.",
            "assign", {"task": t.id}, {"owner": lightest["id"]}, key=f"{m['id']}-{t.id}")

    # 6. Planning macro : phase en retard ou fin proche avec avancement faible.
    from methodology.models import VPhase
    phases = list(VPhase.objects.filter(project=project).order_by("order", "id"))
    live = live_phases(project, phases, today)
    for ph in phases:
        st = live.get(ph.pk, {})
        end = ph.forecast_end or ph.end
        if st.get("status") == "late":
            add("phase", "crit", f"Phase « {ph.name} » en retard : prévenir l'équipe",
                f"Fin prévue le {end:%d/%m}, avancement réel {st.get('progress', 0)} %.",
                "Alerte « Critique » à tous les membres du projet (notification + e-mail) pour remobiliser l'équipe sur la phase.",
                "alert", {"title": f"Phase « {ph.name} » en retard", "level": "critical",
                          "message": f"La phase devait se terminer le {end:%d/%m} et n'est qu'à {st.get('progress', 0)} %. "
                                     "Merci de mettre à jour vos actions et de signaler tout blocage."}, key=ph.pk)
        elif end and today <= end <= today + timedelta(days=10) and st.get("live") and st.get("progress", 0) < 60:
            add("phase", "warn", f"Phase « {ph.name} » : fin le {end:%d/%m}, avancement {st.get('progress', 0)} %",
                "Risque de glissement : moins de 60 % réalisé à moins de 10 jours de la fin.",
                "Alerte « Attention » à tous les membres du projet (notification + e-mail).", "alert",
                {"title": f"Risque de glissement : {ph.name}", "level": "warning",
                 "message": f"Fin prévue le {end:%d/%m}, avancement {st.get('progress', 0)} %. Priorisez les actions de cette phase."},
                key=ph.pk)

    # 7. Budget : consommation proche ou au-delà du budget.
    try:
        b = budget_of(project)
        if b.get("rate") is not None and b["rate"] >= 85:
            add("budget", "crit" if b["rate"] >= 100 else "warn", f"Budget consommé à {b['rate']} %",
                f"Consommé + engagé = {b['rate']} % du budget ({b['budget']} €). Reste : {b['remaining']} €.",
                "Alerte interne (non visible du client) pour arbitrer le reste à faire.",
                "alert", {"title": f"Budget à {b['rate']} %", "level": "critical" if b["rate"] >= 100 else "warning",
                          "message": "Le budget est presque consommé : point d'arbitrage à prévoir (périmètre, avenant, priorisation).",
                          "clientVisible": False}, key="rate")
    except Exception:  # noqa: BLE001 — le budget est facultatif
        pass

    # 8. Documents : pièces clés manquantes selon l'avancement, dates repérées dans les documents.
    docs = list(Document.objects.filter(project=project).defer("content", "extracted_text"))
    types = {d.type for d in docs}
    labels = dict(DOC_TYPES)
    done_ratio = (sum(1 for t in tasks if t.status == "done") / len(tasks)) if tasks else 0
    expected = [("specs", "le cadrage")]
    if done_ratio >= 0.3:
        expected.append(("sfd", "la réalisation"))
    if done_ratio >= 0.7:
        expected.append(("test", "la recette"))
    from .team_docs import check_required, required_of
    required = required_of(project)[2]
    if required:  # documents obligatoires paramétrés pour ce projet : ils remplacent la liste par défaut
        expected = []
        for it in check_required(project, required, docs):
            if it["ok"] or not pm:
                continue
            add("doc_missing", "warn" if it["late"] else "info", f"Obtenir le document obligatoire « {it['label']} »",
                f"Document obligatoire pour ce projet, non encore déposé" + (f" (attendu pour le {it['due']})" if it.get("due") else "")
                + (f" — phase {it['phase']}" if it.get("phase") else "") + ".",
                f"Action « Déposer : {it['label']} » pour {pm.display_name}.",
                "create_task", {"title": f"Déposer : {it['label']}"[:300]},
                {"owner": pm.id, "due": it.get("due") or _workday(today, 5).isoformat()}, key=f"req-{it['id']}")
    for code, stage in expected:
        if code not in types and pm:
            add("doc_missing", "info", f"Demander le document « {labels[code]} »",
                f"Aucun document de ce type dans le projet alors qu'il est attendu pour {stage} "
                f"({round(done_ratio * 100)} % des actions terminées).",
                f"Action « Déposer : {labels[code]} » pour {pm.display_name} sous 5 jours ouvrés.",
                "create_task", {"title": f"Déposer : {labels[code]}"}, {"owner": pm.id, "due": _workday(today, 5).isoformat()},
                key=code)
    for d in docs:
        for raw in (d.extraction or {}).get("dates", [])[:10]:
            m = re.match(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", str(raw))
            if not m:
                continue
            try:
                dt = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                continue
            if today <= dt <= today + timedelta(days=14):
                add("doc_date", "info", f"Échéance du {dt:%d/%m} repérée dans « {d.name} »",
                    f"Le document ({labels.get(d.type, d.type)}) mentionne la date du {dt:%d/%m/%Y}. "
                    "Vérifiez qu'une action couvre cette échéance.",
                    f"Action « Préparer l'échéance du {dt:%d/%m} ({d.name}) » pour le chef de projet.",
                    "create_task", {"title": f"Préparer l'échéance du {dt:%d/%m} ({d.name})"[:300]},
                    {"owner": pm.id if pm else None, "due": dt.isoformat()}, key=f"{d.id}-{dt}")
                break

    # 9. Alertes lancées par les membres et toujours ouvertes depuis plus de 3 jours.
    from .project_alerts import alert_details
    for a in alert_details(project.tenant).values():
        if a.get("project") != project.id or a.get("closed"):
            continue
        try:
            age = (timezone.now() - timezone.datetime.fromisoformat(a["at"])).days
        except (KeyError, ValueError):
            continue
        if age >= 3 and pm:
            add("alert_open", "warn", f"Traiter l'alerte « {a['title']} » (ouverte depuis {age} j)",
                f"Lancée par {a['by']} ({a['levelLabel']}). Une alerte sans réponse démobilise l'équipe.",
                f"Notification à {pm.display_name} pour la traiter ou la clôturer.", "notify_pm",
                {"note": f"Alerte « {a['title']} » ouverte depuis {age} jours : à traiter ou clôturer."}, key=a["id"])

    from .ai_orchestrator import KIND_OWNER, nova_build, team_conf, vega_build
    conf = team_conf(project)
    on = {c for c, a in conf["assistants"].items() if a["enabled"]}
    extra = []
    if "nova" in on:
        extra += nova_build(project, pm)
    if "vega" in on:
        extra += vega_build(project, tasks, types, pm, today)
    for e in extra:
        add(e["kind"], e["level"], e["title"], e["why"], e["effect"], e["do"], e.get("payload"), e.get("edit"), key=e.get("key"))
    for p in props:
        p["assistant"] = KIND_OWNER.get(p["kind"], "atlas")
    if conf["licensed"]:
        props = [p for p in props if p["assistant"] in on]
    props.sort(key=lambda p: LEVEL_RANK[p["level"]])
    return props


# --------------------------------------------------------------------------- exécution d'une proposition
def execute(project, by, p, edit=None, via="Chef de projet IA"):
    """Applique une proposition (éventuellement ajustée par le chef de projet humain). Renvoie un compte rendu."""
    from django.contrib.auth import get_user_model
    from django.utils.dateparse import parse_date

    from .assistant import send_reminders
    from .workspace import _next_action_id

    edit = {**(p.get("edit") or {}), **{k: v for k, v in (edit or {}).items() if v not in (None, "")}}
    pay = p.get("payload") or {}
    User = get_user_model()
    task = Action.objects.filter(project=project, pk=pay.get("task")).select_related("owner").first() if pay.get("task") else None
    actor = by.display_name if by else via

    def notify(user, title, body):
        if user:
            Notification.objects.create(user=user, event="project_alert", title=f"[{project.code}] {title}"[:200],
                                        body=f"{body} · {project.id}"[:2000])

    def new_task(title, owner_id, due):
        t = Action.objects.create(tenant=project.tenant, project=project, id=_next_action_id(project), title=title[:300],
                                  status="todo", owner_id=owner_id or project.pm_id, due=parse_date(str(due or "")) or None)
        if t.owner_id and t.owner_id != getattr(by, "pk", None):
            notify(t.owner, f"Nouvelle action : {t.title}", f"Créée par {actor} ({via}), échéance {t.due:%d/%m}" if t.due else f"Créée par {actor} ({via})")
        return t

    do = p["do"]
    if do == "late":
        if task is None or task.status == "done":
            return "Action déjà terminée ou supprimée : rien à faire."
        sent, mailed, _ = send_reminders(project, by, [task], f"Nouvelle échéance proposée : {edit.get('due')}", via=via)
        new_due = parse_date(str(edit.get("due") or ""))
        if new_due:
            task.due = new_due
            task.save(update_fields=["due"])
        return f"Relance envoyée ({mailed} e-mail) et échéance de « {task.title} » portée au {new_due:%d/%m/%Y}." if new_due else "Relance envoyée."
    if do == "blocked":
        if task is None:
            return "Action introuvable."
        from .project_alerts import launch_alert
        n = launch_alert(project, by, f"Action bloquée : {task.title}"[:150], "Point de déblocage organisé par le chef de projet.",
                         "critical", action=task, client_visible=False,
                         by_label=f"Chef de projet IA ({'validé par ' + by.display_name if by else 'automatique'})")["notified"]
        t = new_task(f"Point de déblocage : {task.title}", edit.get("owner"), edit.get("due"))
        return f"Équipe alertée ({n} membre(s)) et action « {t.title} » créée ({t.id})."
    if do == "assign":
        if task is None:
            return "Action introuvable."
        owner = User.objects.filter(pk=edit.get("owner")).first()
        if owner is None or not ProjectAccess.objects.filter(project=project, user=owner).exists():
            return "Le responsable choisi n'est pas membre du projet."
        old = task.owner
        task.owner = owner
        task.save(update_fields=["owner"])
        notify(owner, f"Action affectée : {task.title}", f"Vous êtes responsable de l'action {task.id} (affectée par {actor})")
        if old and old.pk != owner.pk:
            notify(old, f"Action transférée : {task.title}", f"L'action {task.id} est transférée à {owner.display_name} pour alléger votre charge")
        audit.record(by, f"Tâche {task.id}", f"Responsable changé ({via})", old.display_name if old else "", owner.display_name, tenant=project.tenant)
        return f"« {task.title} » affectée à {owner.display_name}."
    if do == "nudge":
        if task is None or task.status == "done":
            return "Action déjà terminée."
        notify(task.owner, f"Rappel : « {task.title} » due le {task.due:%d/%m}", f"Pensez à démarrer cette action (rappel de {actor})")
        return f"Rappel envoyé à {task.owner.display_name if task.owner_id else '—'}."
    if do == "alert":
        from .project_alerts import launch_alert
        a = launch_alert(project, by, str(pay.get("title", ""))[:150], str(pay.get("message", ""))[:1500], pay.get("level", "warning"),
                         client_visible=pay.get("clientVisible") is not False,
                         by_label=f"Chef de projet IA ({'validé par ' + by.display_name if by else 'automatique'})")
        return f"Alerte « {a['title']} » envoyée à {a['notified']} membre(s)" + (f" ({a['mailed']} e-mail(s))." if a["mailed"] else ".")
    if do == "create_task":
        t = new_task(pay["title"], edit.get("owner"), edit.get("due"))
        return f"Action « {t.title} » créée ({t.id}), affectée à {t.owner.display_name if t.owner_id else '—'}."
    if do == "ask":
        from .assistant_questions import ask
        if task is None or task.status == "done":
            return "Action terminée : question inutile."
        q = ask(project, actor if by else "Chef de projet IA", task, pay.get("kind", ""), pay.get("question", ""))
        return f"Question envoyée à {q['toName']} sur « {task.title} »." if q else "Aucun destinataire pour la question."
    if do == "set_due":
        if task is None:
            return "Action introuvable."
        new_due = parse_date(str(edit.get("due") or ""))
        if not new_due:
            return "Date invalide."
        old = task.due
        task.due = new_due
        task.save(update_fields=["due"])
        if task.owner_id and task.owner_id != getattr(by, "pk", None):
            notify(task.owner, f"Échéance mise à jour : {task.title}", f"Nouvelle échéance le {new_due:%d/%m/%Y} (validée par {actor})")
        audit.record(by, f"Tâche {task.id}", f"Échéance modifiée ({via})", old.isoformat() if old else "", new_due.isoformat(), tenant=project.tenant)
        return f"Échéance de « {task.title} » portée au {new_due:%d/%m/%Y}."
    if do == "mark_blocked":
        if task is None:
            return "Action introuvable."
        task.status = "blocked"
        task.block = str(pay.get("cause") or "")[:2000]
        task.save(update_fields=["status", "block"])
        audit.record(by, f"Tâche {task.id}", f"Action bloquée ({via})", "", task.block[:200], tenant=project.tenant)
        return f"« {task.title} » passée en « Bloquée »."
    if do == "req_ask":
        from .assistant_questions import ask
        target = next((a.user for a in ProjectAccess.objects.filter(project=project, user__is_active=True).select_related("user", "user__role")
                       if a.user.role and not a.user.role.internal), None) or project.pm
        q = ask(project, "Nova (assistante fonctionnelle IA)", None, pay.get("qkind", "req"), pay.get("question", ""), target=target)
        return f"Question de cadrage envoyée à {q['toName']}." if q else "Aucun destinataire pour la question."
    if do == "req_task":
        t = new_task(pay["title"], edit.get("owner"), edit.get("due") or _workday(_today(), 5).isoformat())
        reqs = pay.get("requirements") or []
        if reqs:
            from .models import ActionComment
            ActionComment.objects.create(tenant=project.tenant, action=t, author=by, at=timezone.localdate().isoformat(), internal=True,
                                         body="Exigences repérées par Nova (assistante fonctionnelle IA) :\n" + "\n".join(f"- {r}" for r in reqs))
        return f"Action « {t.title} » créée ({t.id})" + (f" avec {len(reqs)} exigence(s) en commentaire." if reqs else ".")
    if do == "notify_pm":
        notify(project.pm, "Point à traiter", f"{pay.get('note', '')} (signalé par {actor})")
        return f"{project.pm.display_name if project.pm_id else 'Le chef de projet'} a été notifié."
    return "Proposition inconnue."


# --------------------------------------------------------------------------- revue, validation, revue quotidienne
def review(project, keep_dismissed=True):
    """Lance une revue et met à jour la liste des propositions en attente (les propositions écartées ne reviennent pas)."""
    row, data = _store(project)
    st = data.get(project.id) or {}
    dismissed = st.get("dismissed", {}) if keep_dismissed else {}
    recent = st.get("done", {})
    props = [p for p in build(project) if p["id"] not in dismissed and p["id"] not in recent]
    ids = {p["id"] for p in props}
    sticky = [p for p in st.get("pending", []) if p.get("sticky") and p["id"] not in ids and p["id"] not in dismissed]
    props = sorted(sticky + props, key=lambda p: LEVEL_RANK[p["level"]])
    from .ai_orchestrator import route, team_conf
    conf = team_conf(project)
    for p in props:
        p["validator"], p["decision"] = route(project, p, conf)
    st.update({"at": timezone.now().isoformat(), "pending": props})
    st.setdefault("history", [])
    data[project.id] = st
    _save(project, row, data)
    return props


def decide(project, by, accept_ids, reject_ids, edits, via, check=False):
    """Validation (humaine ou IA selon le circuit) : exécute les propositions acceptées, écarte les autres, trace tout."""
    from .ai_orchestrator import ROSTER, VALIDATORS, can_validate, log
    row, data = _store(project)
    st = data.get(project.id) or {"pending": [], "history": [], "dismissed": {}}
    pending = {p["id"]: p for p in st.get("pending", [])}
    if check and by is not None:
        allowed = {pid for pid, p in pending.items() if can_validate(by, project, p.get("validator") or "pm")}
        accept_ids = [i for i in accept_ids if i in allowed]
        reject_ids = [i for i in reject_ids if i in allowed]
    actor = by.display_name if by else via
    done = []
    for pid in accept_ids:
        p = pending.pop(pid, None)
        if p is None:
            continue
        who = ROSTER.get(p.get("assistant") or "atlas", ROSTER["atlas"])["name"]
        e = (edits or {}).get(pid) or {}
        changed = {k: (p.get("edit", {}).get(k), v) for k, v in e.items() if v not in (None, "") and str(p.get("edit", {}).get(k)) != str(v)}
        if changed and by is not None:
            log(project, "correction", actor, f"Proposition de {who} corrigée avant validation : « {p['title']} » — "
                + ", ".join(f"{k} : {a or '—'} → {b}" for k, (a, b) in changed.items()), p.get("assistant"), {"proposal": pid})
        log(project, "validation", actor, f"« {p['title']} » validée ({VALIDATORS.get(p.get('validator'), 'validation')})",
            p.get("assistant"), {"proposal": pid})
        result = execute(project, by, p, e, via=via)
        log(project, "execution", who, result, p.get("assistant"), {"proposal": pid})
        done.append({"title": p["title"], "result": result})
        st.setdefault("done", {})[pid] = timezone.localdate().isoformat()
        st.setdefault("history", []).insert(0, {"id": pid, "title": p["title"], "decision": "validée", "by": by.display_name if by else via,
                                                "result": result, "at": timezone.now().isoformat()})
    for pid in reject_ids:
        p = pending.pop(pid, None)
        if p is None:
            continue
        log(project, "refus", actor, f"« {p['title']} » écartée", p.get("assistant"), {"proposal": pid})
        st.setdefault("dismissed", {})[pid] = timezone.localdate().isoformat()
        st.setdefault("history", []).insert(0, {"id": pid, "title": p["title"], "decision": "écartée", "by": by.display_name if by else via,
                                                "result": "", "at": timezone.now().isoformat()})
    st["pending"] = list(pending.values())
    st["history"] = st.get("history", [])[:60]
    # Les propositions écartées peuvent revenir après 7 jours si la situation persiste.
    limit = (timezone.localdate() - timedelta(days=7)).isoformat()
    st["dismissed"] = {k: v for k, v in st.get("dismissed", {}).items() if v >= limit}
    # Une action exécutée n'est pas reproposée avant 3 jours (le temps que la situation évolue).
    limit3 = (timezone.localdate() - timedelta(days=3)).isoformat()
    st["done"] = {k: v for k, v in st.get("done", {}).items() if v >= limit3}
    data[project.id] = st
    _save(project, row, data)
    if done:
        audit.record(by, f"Projet {project.code}", f"Propositions du Chef de projet IA appliquées ({via})", "",
                     f"{len(done)} proposition(s)", tenant=project.tenant)
    return done, st


def add_pending(project, prop):
    """Ajoute une proposition (ex. issue d'une réponse d'un membre) à valider par le chef de projet humain."""
    row, data = _store(project)
    st = data.get(project.id) or {"pending": [], "history": []}
    pid = _pid(prop["kind"], prop.get("key") or prop["title"])
    if any(p["id"] == pid for p in st.get("pending", [])):
        return
    from .ai_orchestrator import KIND_OWNER, ROSTER, VALIDATORS, log, notify_validators, route
    full = {"id": pid, "icon": KINDS[prop["kind"]][0], "category": KINDS[prop["kind"]][1], "sticky": True,
            "payload": {}, "edit": {}, **{k: v for k, v in prop.items() if k != "key"}}
    full["assistant"] = full.get("assistant") or KIND_OWNER.get(full["kind"], "atlas")
    v, cat = route(project, full)
    if v in ("auto", "ai"):
        v = "pm"  # une proposition issue d'une réponse humaine est toujours validée par un humain
    full["validator"], full["decision"] = v, cat
    st["pending"] = [full] + st.get("pending", [])
    data[project.id] = st
    _save(project, row, data)
    log(project, "proposition", ROSTER[full["assistant"]]["name"], f"{full['title']} → {VALIDATORS[v]}", full["assistant"], {"proposal": pid})
    notify_validators(project, [full])


def cycle(project, pm_mode=None, force=False, manual=False):
    """Passage des assistants IA du projet, coordonné par l'Orchestrateur.

    - Revue complète (Atlas, Nova, Orion, Vega, Mercure selon les assistants affectés au projet).
    - Chaque proposition suit son circuit de validation : exécution directe / validation par l'Orchestrateur
      (assistant en mode automatique uniquement) ou validation humaine (chef de projet, tech lead, client, admin).
    - Automatique : au plus toutes les 30 min (2 min si forcé) ; semi-automatique : une fois par jour.
    Renvoie (actions exécutées, propositions en attente).
    """
    from .ai_orchestrator import ROSTER, VALIDATORS, any_active, log, notify_validators
    mode = any_active(project)
    if mode == "off":
        return [], []
    row, data = _store(project)
    st = data.get(project.id) or {}
    now = timezone.now()
    last = st.get("cycleAt")
    if not manual:
        gap = timedelta(minutes=2 if force else 30) if mode == "auto" else timedelta(hours=20)
        try:
            if last and timezone.datetime.fromisoformat(last) > now - gap:
                return [], st.get("pending", [])
        except ValueError:
            pass
    st["cycleAt"] = now.isoformat()
    data[project.id] = st
    _save(project, row, data)
    before = set(st.get("notified", []))
    props = review(project)
    for p in props:
        if p["id"] not in before:
            log(project, "proposition", ROSTER[p.get("assistant") or "atlas"]["name"],
                f"{p['title']} → {VALIDATORS.get(p['validator'], p['validator'])}", p.get("assistant"), {"proposal": p["id"]})
    auto_ids = [p["id"] for p in props if p["validator"] == "auto"]
    ai_ids = [p["id"] for p in props if p["validator"] == "ai"]
    done = []
    if auto_ids:
        d, _ = decide(project, None, auto_ids, [], {}, via="exécution directe (assistant automatique)")
        done += d
    if ai_ids:
        d, _ = decide(project, None, ai_ids, [], {}, via="validé par Maestro (Orchestrateur IA)")
        done += d
    row, data = _store(project)
    st = data.get(project.id) or {}
    pending = st.get("pending", [])
    new = [p for p in pending if p["id"] not in before]
    st["notified"] = [p["id"] for p in pending]
    data[project.id] = st
    _save(project, row, data)
    log(project, "cycle", "Maestro", f"Passage des assistants : {len(props)} constat(s), {len(done)} action(s) menée(s), "
        f"{len(pending)} proposition(s) en attente de validation", "maestro")
    if new:
        notify_validators(project, new)
    if done and project.pm:
        Notification.objects.create(
            user=project.pm, event="project_alert",
            title=f"[{project.code}] 🎼 Assistants IA : {len(done)} action(s) menée(s)"[:200],
            body=(" ; ".join(d["result"] for d in done[:5]) + f" · Détail dans l'Orchestrateur IA · {project.id}")[:2000])
    return done, pending


def daily_review(project, pm_mode):
    cycle(project, pm_mode)


def new_id():
    return secrets.token_hex(3)
