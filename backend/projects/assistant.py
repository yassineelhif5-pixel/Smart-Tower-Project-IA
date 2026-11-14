"""Assistant projet : vérifie les actions, rédige un rapport, analyse le projet et agit comme un chef de projet
(relances, création de tâches, relances automatiques), dans la limite des droits configurés par l'administrateur.

- Accès : réglage AppSetting « assistant » (profils autorisés à utiliser l'assistant, profils autorisés à agir).
  Le client n'y a accès que si l'administrateur l'autorise explicitement.
- Données : uniquement celles des projets visibles par l'utilisateur ; le budget seulement pour les profils financiers.
- IA : l'analyse repose sur les données du projet (règles). Si la variable d'environnement ANTHROPIC_API_KEY est
  définie côté serveur, les questions libres et la rédaction du rapport sont confiées à Claude (données du projet
  envoyées dans la requête) ; sinon l'assistant répond avec son moteur local.
- Toute action (relance, tâche créée, automatisation) est tracée dans le journal d'audit « via l'assistant ».
"""
import json
import logging
import os
from datetime import timedelta

import requests
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.errors import ApiError
from configuration import audit, notify
from configuration.models import AppSetting, NotificationChannel, Notification

from .access import in_active_tenant, visible_projects
from .models import Action, ProjectAccess
from .planning_view import project_alerts, workload
from .workspace import _next_action_id, _project, _rights, budget_of, live_phases

logger = logging.getLogger("assistant")

MODES = {"auto": "Automatique (agit seul, remplace le chef de projet humain)",
         "semi": "Semi-automatique (propose, un humain valide)", "off": "Désactivé"}
RANK = {"off": 0, "semi": 1, "auto": 2}

# Assistants par profil : nom, rôle joué et missions proposées.
PERSONAS = {
    "pm": {"name": "Atlas · Chef de projet IA", "pitch": "Je suis votre binôme de pilotage : je passe le projet en revue comme un chef de projet (actions, charge, planning, budget, documents, alertes), je vous recommande et je propose des actions concrètes.",
           "missions": ["review", "check", "docs", "analyze", "report", "alert", "remind", "create_task", "replan", "automate"]},
    "tl": {"name": "Orion · Tech Lead IA", "pitch": "Je surveille les blocages techniques, la charge de l'équipe et les actions à relancer.",
           "missions": ["review", "check", "workload", "docs", "analyze", "alert", "remind", "create_task"]},
    "team": {"name": "Echo · Assistant d'équipe IA", "pitch": "Je vous dis quoi faire en priorité et je prépare votre point d'avancement.",
             "missions": ["my_tasks", "today", "my_report", "check"]},
    "client": {"name": "Lyra · Relation client IA", "pitch": "Je vous résume l'état du projet et je transmets vos demandes au chef de projet.",
               "missions": ["report", "check", "request", "remind_pm"]},
    "sales": {"name": "Mercure · Assistant commercial & budget IA", "pitch": "Je suis l'avancement, le budget et les risques pour la relation client.",
              "missions": ["report", "analyze", "budget"]},
    "exec": {"name": "Sirius · Assistant direction IA", "pitch": "Je synthétise la santé du projet, les risques et les décisions à prendre.",
             "missions": ["analyze", "report", "budget", "check"]},
}
ROLE_PERSONA = {"admin": "pm", "cdp": "pm", "manager": "pm", "techlead": "tl", "dev": "team", "consultant": "team",
                "testeur": "team", "client": "client", "commercial": "sales", "direction": "exec", "readonly": "team"}
MISSIONS = {
    "review": ("🧭", "Revue de projet (binôme)", "Je passe tout le projet en revue et je vous propose des actions concrètes et motivées."),
    "docs": ("📂", "Vérifier les documents", "Documents déposés, pièces clés manquantes, échéances repérées dans les documents."),
    "alert": ("🚨", "Lancer une alerte", "Alerte à tous les membres du projet (notification + e-mail)."),
    "check": ("🔎", "Vérifier les actions", "Retards, blocages, échéances proches, actions sans responsable."),
    "analyze": ("📊", "Analyser et recommander", "Indice de santé, risques et recommandations."),
    "report": ("📝", "Rapport d'avancement", "Météo, avancement prévu / réel, phases, échéances, points d'attention."),
    "remind": ("📨", "Relancer les retards", "Notification (et e-mail) aux responsables des actions en retard."),
    "create_task": ("➕", "Créer une action", "Nouvelle tâche affectée à un membre de l'équipe."),
    "replan": ("🗓️", "Replanifier les retards", "Proposer de nouvelles échéances réalistes pour les actions en retard."),
    "automate": ("🤖", "Relances automatiques", "Relancer automatiquement les retards à une fréquence choisie."),
    "workload": ("⚖️", "Plan de charge", "Surcharges et sous-charges de l'équipe sur 8 semaines."),
    "my_tasks": ("✅", "Mes actions", "Vos actions ouvertes triées par priorité et échéance."),
    "today": ("☀️", "Ma journée", "Ce que vous devez faire aujourd'hui en priorité."),
    "my_report": ("🗒️", "Mon point d'avancement", "Ce que vous avez fait et ce qu'il reste, prêt à partager."),
    "request": ("📩", "Faire une demande", "Transmettre une demande au chef de projet (crée une action)."),
    "remind_pm": ("🔔", "Relancer le chef de projet", "Notifier le chef de projet sur un point en attente."),
    "budget": ("💶", "Budget", "Consommé, engagé et reste à faire (profils autorisés)."),
}
ACTING = {"review", "alert", "remind", "create_task", "replan", "automate", "request", "remind_pm"}


def license_of(tenant):
    """Licence accordée par le Pilote à l'entreprise : activée et mode maximal autorisé."""
    row = AppSetting.objects.filter(tenant=tenant, key="assistant_license").first()
    v = row.value if row and isinstance(row.value, dict) else {}
    return {"enabled": bool(v.get("enabled", False)), "maxMode": v.get("maxMode", "semi") if v.get("maxMode") in MODES else "semi"}


def conf_of(tenant):
    row = AppSetting.objects.filter(tenant=tenant, key="assistant").first()
    v = row.value if row and isinstance(row.value, dict) else {}
    return {"profiles": v.get("profiles") or {}, "llm": v.get("llm", True)}


def mode_of(user):
    """Mode effectif de l'assistant pour l'utilisateur (licence Pilote ∩ réglage admin du profil)."""
    if not in_active_tenant(user):
        return "off"
    lic = license_of(user.tenant)
    if not lic["enabled"]:
        return "off"
    mode = conf_of(user.tenant)["profiles"].get(user.role_id, "off")
    mode = mode if mode in MODES else "off"
    return mode if RANK[mode] <= RANK[lic["maxMode"]] else lic["maxMode"]


def pm_mode_of(tenant):
    """Mode du Chef de projet IA pour l'entreprise (profil chef de projet, plafonné par la licence)."""
    lic = license_of(tenant)
    if not lic["enabled"]:
        return "off"
    mode = conf_of(tenant)["profiles"].get("cdp", "off")
    mode = mode if mode in MODES else "off"
    return mode if RANK[mode] <= RANK[lic["maxMode"]] else lic["maxMode"]


def persona_of(user):
    return ROLE_PERSONA.get(user.role_id, "team" if (user.role and user.role.internal) else "client")


def access_of(user, project=None):
    mode = mode_of(user)
    use = mode != "off"
    return use, use


# --------------------------------------------------------------------------- moteur local
def _today():
    return timezone.localdate()


def check(project, user):
    today = _today()
    tasks = list(Action.objects.filter(project=project).select_related("owner"))
    late = sorted([t for t in tasks if t.due and t.due < today and t.status != "done"], key=lambda t: t.due)
    blocked = [t for t in tasks if t.status == "blocked"]
    soon = [t for t in tasks if t.due and today <= t.due <= today + timedelta(days=3) and t.status != "done"]
    unassigned = [t for t in tasks if not t.owner_id and t.status != "done"]
    who = lambda t: t.owner.display_name if t.owner_id else "non affectée"  # noqa: E731
    lines = [f"**Vérification des actions — {project.name}** ({len(tasks)} actions)"]
    if not (late or blocked or soon or unassigned):
        lines.append("✅ Rien à signaler : aucune action en retard, bloquée ou à échéance imminente.")
    if late:
        lines.append(f"⛔ **{len(late)} en retard** :")
        lines += [f"- {t.title} — {who(t)}, échéance {t.due:%d/%m} ({(today - t.due).days} j)" for t in late[:10]]
    if blocked:
        lines.append(f"🧱 **{len(blocked)} bloquée(s)** :")
        lines += [f"- {t.title} — {who(t)}" for t in blocked[:10]]
    if soon:
        lines.append(f"⏰ **{len(soon)} à échéance sous 3 jours** :")
        lines += [f"- {t.title} — {who(t)}, le {t.due:%d/%m}" for t in soon[:10]]
    if unassigned:
        lines.append(f"👤 **{len(unassigned)} sans responsable** : " + ", ".join(t.title for t in unassigned[:8]))
    suggestions = []
    if late:
        suggestions.append({"intent": "remind", "label": f"Relancer les {len(late)} retard(s)"})
    if unassigned:
        suggestions.append({"intent": "report", "label": "Rapport d'avancement"})
    return "\n".join(lines), suggestions


def _facts(project, user):
    today = _today()
    from methodology.models import VPhase
    phases = list(VPhase.objects.filter(project=project).order_by("order", "id"))
    live = live_phases(project, phases, today)
    tasks = list(Action.objects.filter(project=project).select_related("owner"))
    load, _ = workload(project, tasks, today)
    rights = _rights(user, project)
    alerts = project_alerts(project, today, live, tasks, load, with_budget=rights["canSeeMoney"])
    weight = lambda t: float(t.est or 0) or 1.0  # noqa: E731
    total = sum(weight(t) for t in tasks)
    real = round(sum(weight(t) for t in tasks if t.status == "done") / total * 100) if total else 0
    from .workspace import _planned_pct
    pw = [(p, max(1, (p.end - p.start).days)) for p in phases if p.start and p.end]
    planned = (round(sum(w * (_planned_pct(p.start, p.end, today) or 0) for p, w in pw) / sum(w for _, w in pw)) if pw
               else (_planned_pct(project.start_date, project.end_date, today) or 0))
    return {
        "today": today, "phases": phases, "live": live, "tasks": tasks, "load": load, "alerts": alerts,
        "real": real, "planned": planned, "budget": budget_of(project) if rights["canSeeMoney"] else None,
        "done_week": [t for t in tasks if t.status == "done" and t.done_at and t.done_at >= today - timedelta(days=7)],
    }


def report(project, user):
    f = _facts(project, user)
    t = f["tasks"]
    gap = f["real"] - f["planned"]
    weather = "☀️ Au vert" if gap >= -5 and not any(a["level"] == "crit" for a in f["alerts"]) else (
        "⛅ Sous surveillance" if gap >= -15 else "⛈️ En difficulté")
    lines = [
        f"**Rapport d'avancement — {project.name}** · {f['today']:%d/%m/%Y}",
        f"Météo du projet : **{weather}**",
        f"- Type : {project.get_project_type_display()}" + (f" ({project.base_version or '—'} → {project.target_version or '—'})" if project.project_type != "new" else ""),
        f"- Avancement : **{f['real']} %** réalisé pour {f['planned']} % prévu ({'+' if gap >= 0 else ''}{gap} pts)",
        f"- Actions : {sum(1 for x in t if x.status == 'done')}/{len(t)} terminées · "
        f"{sum(1 for x in t if x.status in ('doing', 'review'))} en cours · "
        f"{sum(1 for x in t if x.due and x.due < f['today'] and x.status != 'done')} en retard",
    ]
    if f["phases"]:
        lines.append("**Phases** :")
        for p in f["phases"]:
            lv = f["live"][p.pk]
            lines.append(f"- {p.name} : {lv['progress']} % · {dict(type(p)._meta.get_field('status').choices).get(lv['status'])}"
                         + (f" · fin {p.end:%d/%m}" if p.end else ""))
    if f["done_week"]:
        lines.append("**Réalisé ces 7 derniers jours** : " + ", ".join(x.title for x in f["done_week"][:8]))
    nxt = sorted([x for x in t if x.status != "done" and x.due and x.due >= f["today"]], key=lambda x: x.due)[:5]
    if nxt:
        lines.append("**Prochaines échéances** :")
        lines += [f"- {x.title} — {x.owner.display_name if x.owner_id else 'non affectée'}, {x.due:%d/%m}" for x in nxt]
    if f["budget"] and f["budget"]["budget"]:
        b = f["budget"]
        lines.append(f"**Budget** : {float(b['consumed']):,.0f} € consommés + {float(b['pending']):,.0f} € engagés sur {float(b['budget']):,.0f} € ({b['rate']} %)".replace(",", " "))
    if f["alerts"]:
        lines.append("**Points d'attention** :")
        lines += [f"- {a['message']}" for a in f["alerts"][:6]]
    lines.append("_Export complet (PDF, image, Excel) : module Reporting._")
    return "\n".join(lines), [{"intent": "analyze", "label": "Analyser et recommander"}]


def analyze(project, user):
    f = _facts(project, user)
    recos, risks = [], []
    gap = f["real"] - f["planned"]
    if gap < -10:
        risks.append(f"Retard global de {abs(gap)} points sur l'avancement prévu.")
        recos.append("Re-prioriser le reste à faire et confirmer les dates des phases en cours (fin réestimée).")
    late = [t for t in f["tasks"] if t.due and t.due < f["today"] and t.status != "done"]
    if late:
        owners = {}
        for t in late:
            owners[t.owner.display_name if t.owner_id else "non affectées"] = owners.get(t.owner.display_name if t.owner_id else "non affectées", 0) + 1
        risks.append(f"{len(late)} action(s) en retard (" + ", ".join(f"{k} : {v}" for k, v in owners.items()) + ").")
        recos.append("Relancer les responsables et organiser un point de déblocage cette semaine.")
    over = [m for m in f["load"] if any(w["capacity"] and w["hours"] > w["capacity"] * 1.1 for w in m["weeks"])]
    idle = [m for m in f["load"] if m["open"] == 0]
    if over:
        risks.append("Surcharge : " + ", ".join(m["name"] for m in over) + ".")
        recos.append("Rééquilibrer la charge" + (f" vers {', '.join(m['name'] for m in idle[:3])}" if idle else "") + ".")
    unassigned = [t for t in f["tasks"] if not t.owner_id and t.status != "done"]
    if unassigned:
        risks.append(f"{len(unassigned)} action(s) sans responsable.")
        recos.append("Affecter un responsable à chaque action ouverte (Mes projets › Tâches).")
    blocked = [t for t in f["tasks"] if t.status == "blocked"]
    if blocked:
        risks.append(f"{len(blocked)} action(s) bloquée(s).")
        recos.append("Identifier la cause de blocage et l'escalader au comité de pilotage si besoin.")
    if f["budget"] and f["budget"]["rate"] and f["budget"]["rate"] > 85:
        risks.append(f"Budget consommé ou engagé à {f['budget']['rate']} %.")
        recos.append("Réestimer le reste à faire et préparer un avenant ou un arbitrage de périmètre.")
    no_dates = [p.name for p in f["phases"] if not (p.start and p.end)]
    if no_dates:
        recos.append("Compléter les dates des phases : " + ", ".join(no_dates) + ".")
    if not f["phases"] and project.project_type != "maintenance":
        recos.append("Saisir le planning macro (phases clés) pour suivre le prévu / réel.")
    score = max(0, 100 - 8 * len(late) - 10 * len(blocked) - 6 * len(over) - max(0, -gap))
    lines = [f"**Analyse — {project.name}** · indice de santé **{score}/100**"]
    lines.append("**Risques identifiés** :" if risks else "✅ Aucun risque majeur détecté.")
    lines += [f"- {r}" for r in risks]
    if recos:
        lines.append("**Recommandations** :")
        lines += [f"{i}. {r}" for i, r in enumerate(recos, 1)]
    sugg = []
    if late:
        sugg.append({"intent": "remind", "label": "Relancer les retards"})
        sugg.append({"intent": "automate", "label": "Programmer des relances automatiques"})
    return "\n".join(lines), sugg


# --------------------------------------------------------------------------- actions (rôle de chef de projet)
def send_reminders(project, by, tasks=None, note="", via="l'assistant"):
    today = _today()
    tasks = tasks if tasks is not None else [t for t in Action.objects.filter(project=project).select_related("owner")
                                             if t.due and t.due < today and t.status != "done"]
    channel = NotificationChannel.objects.filter(tenant=project.tenant, kind="email", enabled=True).first()
    sent, mailed, skipped = [], 0, []
    for t in tasks:
        target = t.owner or project.pm
        if target is None:
            skipped.append(t.title)
            continue
        days = (today - t.due).days if t.due and t.due < today else 0
        title = f"[{project.code}] Relance : {t.title}"[:200]
        body = (f"{project.name} · {'en retard de ' + str(days) + ' j' if days else 'échéance le ' + t.due.strftime('%d/%m') if t.due else 'à traiter'}"
                f" · relance envoyée par {by.display_name if by else 'automatisation'} via {via}" + (f" · {note}" if note else "") + f" · {project.id}")
        Notification.objects.create(user=target, event="project_alert", title=title, body=body[:2000])
        if channel and target.email:
            try:
                notify.send_email(channel, [target.email], title, body.rsplit(" · ", 1)[0])
                mailed += 1
            except notify.ChannelError:
                pass
        sent.append(f"{t.title} → {target.display_name}")
    audit.record(by, f"Projet {project.code}", f"Relances envoyées (via {via})", "", f"{len(sent)} relance(s)", tenant=project.tenant)
    return sent, mailed, skipped


def run_automations(project):
    """Relances automatiques : exécutées au plus une fois par période, au passage d'un membre dans l'application."""
    try:  # revue quotidienne du Chef de projet IA (auto : il agit ; semi : il prépare les propositions)
        from .assistant_review import daily_review
        daily_review(project, pm_mode_of(project.tenant))
    except Exception:  # noqa: BLE001
        logger.exception("Revue quotidienne du Chef de projet IA impossible")
    row = AppSetting.objects.filter(tenant=project.tenant, key="assistant_auto").first()
    rules = row.value if row and isinstance(row.value, dict) else {}
    rule = rules.get(project.id)
    if not rule:
        # Chef de projet IA en mode automatique : relances des retards tous les 2 jours, sans réglage préalable.
        pm_auto = license_of(project.tenant)["enabled"] and license_of(project.tenant)["maxMode"] == "auto" and \
            conf_of(project.tenant)["profiles"].get("cdp") == "auto"
        rule = {"enabled": pm_auto, "everyDays": 2, "by": "Chef de projet IA (automatique)"} if pm_auto else None
    if not rule or not rule.get("enabled"):
        return 0
    last = rule.get("lastRun")
    every = int(rule.get("everyDays") or 2)
    now = timezone.now()
    if last and timezone.datetime.fromisoformat(last) > now - timedelta(days=every):
        return 0
    sent, _, _ = send_reminders(project, None, via="la relance automatique")
    rule["lastRun"] = now.isoformat()
    rules[project.id] = rule
    AppSetting.objects.update_or_create(tenant=project.tenant, key="assistant_auto", defaults={"value": rules})
    return len(sent)


def _automation(project):
    row = AppSetting.objects.filter(tenant=project.tenant, key="assistant_auto").first()
    rules = row.value if row and isinstance(row.value, dict) else {}
    return rules.get(project.id) or {"enabled": False, "everyDays": 2}


# --------------------------------------------------------------------------- IA (facultatif)
def _llm(question, context):
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return None
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": os.environ.get("ASSISTANT_MODEL", "claude-sonnet-4-5"), "max_tokens": 900,
                  "system": ("Tu es l'assistant de pilotage de projet de Project Control Tower. Réponds en français, de façon "
                             "concise et structurée (markdown simple), uniquement à partir des données fournies. "
                             "N'invente aucune donnée. Si une action est souhaitée (relance, création de tâche), propose-la "
                             "sans prétendre l'avoir faite."),
                  "messages": [{"role": "user", "content": f"Données du projet (JSON) :\n{context}\n\nDemande : {question}"}]},
            timeout=40)
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text") or None
    except Exception as exc:  # réseau, clé invalide… : repli sur le moteur local
        logger.warning("Assistant IA indisponible : %s", type(exc).__name__)
        return None


def _context(project, user):
    f = _facts(project, user)
    return json.dumps({
        "projet": {"code": project.code, "nom": project.name, "type": project.get_project_type_display(),
                   "versions": [project.base_version, project.target_version], "debut": str(project.start_date), "fin": str(project.end_date)},
        "avancement": {"prevu": f["planned"], "reel": f["real"]},
        "phases": [{"nom": p.name, "debut": str(p.start), "fin": str(p.end), "avancement": f["live"][p.pk]["progress"],
                    "statut": f["live"][p.pk]["status"]} for p in f["phases"]],
        "actions": [{"titre": t.title, "statut": t.status, "responsable": t.owner.display_name if t.owner_id else None,
                     "echeance": str(t.due) if t.due else None, "phase": t.phase} for t in f["tasks"][:150]],
        "charge": [{"membre": m["name"], "ouvertes": m["open"], "reste_h": m["remaining"]} for m in f["load"]],
        "alertes": [a["message"] for a in f["alerts"]],
        "budget": ({k: (str(v) if v is not None else None) for k, v in f["budget"].items() if k in ("budget", "consumed", "pending", "rate")}
                   if f["budget"] else None),
    }, ensure_ascii=False)


def route(text):
    q = text.casefold()
    if any(w in q for w in ("revue", "propos", "que dois-je", "que faire", "pilot", "binôme", "binome", "à ma place")):
        return "review"
    if "alerte" in q or "alerter" in q:
        return "alert"
    if "document" in q or "docs" in q or "pièce" in q:
        return "docs"
    if "replanif" in q or "décal" in q or "decal" in q:
        return "replan"
    if "budget" in q or "coût" in q or "cout" in q:
        return "budget"
    if "charge" in q or "surcharge" in q:
        return "workload"
    if "aujourd" in q or "ma journée" in q:
        return "today"
    if q.startswith("mes ") or "mes tâches" in q or "mes actions" in q:
        return "my_tasks"
    if any(w in q for w in ("relanc", "rappel", "remind")):
        return "remind"
    if any(w in q for w in ("rapport", "synthèse", "synthese", "point d'avancement", "météo", "meteo")):
        return "report"
    if any(w in q for w in ("analys", "risque", "recommand", "santé", "sante", "diagnostic")):
        return "analyze"
    if any(w in q for w in ("créer", "creer", "ajoute", "nouvelle tâche", "nouvelle tache")):
        return "create_task"
    if any(w in q for w in ("automati", "chaque", "programm")):
        return "automate"
    if any(w in q for w in ("vérif", "verif", "retard", "bloqu", "action", "tâche", "tache", "échéance")):
        return "check"
    return "ask"


# --------------------------------------------------------------------------- missions complémentaires
def _who(t):
    return t.owner.display_name if t.owner_id else "non affectée"


def _next_workday(d, n):
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def replan_proposals(project):
    today = _today()
    late = sorted([t for t in Action.objects.filter(project=project).select_related("owner")
                   if t.due and t.due < today and t.status != "done"], key=lambda t: t.due)
    load = {}
    out = []
    for t in late:
        days = max(1, round(float(t.raf or t.est or 4) / 7))
        key = t.owner_id or 0
        start = load.get(key, today)
        new_due = _next_workday(start, days)
        load[key] = new_due
        out.append({"id": t.id, "title": t.title, "owner": _who(t), "old": t.due, "new": new_due})
    return out


def my_tasks(project, user, today_only=False):
    today = _today()
    mine = [t for t in Action.objects.filter(project=project, owner=user).exclude(status="done")]
    prio = {"critical": 0, "high": 1, "normal": 2, "low": 3, "": 2}
    mine.sort(key=lambda t: (t.status != "blocked", t.due or today + timedelta(days=365), prio.get(t.prio or "", 2)))
    if today_only:
        mine = [t for t in mine if t.status in ("doing", "blocked") or (t.due and t.due <= today + timedelta(days=1))] or mine[:3]
    if not mine:
        return "Vous n'avez aucune action ouverte sur ce projet. 🎉", []
    lines = ["**Votre journée**" if today_only else f"**Vos {len(mine)} action(s) ouverte(s)**, par priorité :"]
    for i, t in enumerate(mine[:12], 1):
        flag = " ⛔ en retard" if t.due and t.due < today else (" 🧱 bloquée" if t.status == "blocked" else "")
        lines.append(f"{i}. {t.title} — {LABELS_FR.get(t.status, t.status)}" + (f", échéance {t.due:%d/%m}" if t.due else "") + flag)
    if today_only:
        lines.append("_Conseil : commencez par ce qui est bloqué ou en retard, puis saisissez votre temps en fin de journée._")
    return "\n".join(lines), []


def my_report(project, user):
    today = _today()
    since = today - timedelta(days=7)
    done = [t for t in Action.objects.filter(project=project, owner=user, status="done") if (t.done_at or t.due or since) >= since]
    open_ = list(Action.objects.filter(project=project, owner=user).exclude(status="done"))
    from django.db.models import Sum
    from .models import TimeEntry
    hours = TimeEntry.objects.filter(project=project, person=user, work_date__gte=since).aggregate(h=Sum("hours"))["h"] or 0
    lines = [f"**Mon point d'avancement — semaine du {since:%d/%m} au {today:%d/%m}**",
             f"- Réalisé : {len(done)} action(s)" + (" — " + ", ".join(t.title for t in done[:6]) if done else ""),
             f"- En cours / à faire : {len(open_)} action(s)" + (" — " + ", ".join(t.title for t in open_[:6]) if open_ else ""),
             f"- Temps saisi : {float(hours):g} h",
             f"- Points de blocage : " + (", ".join(t.title for t in open_ if t.status == "blocked") or "aucun")]
    return "\n".join(lines), []


def workload_text(project):
    today = _today()
    tasks = list(Action.objects.filter(project=project).select_related("owner"))
    load, weeks = workload(project, tasks, today)
    lines = ["**Plan de charge (8 semaines)**"]
    for m in load:
        peaks = [f"S{w['week']:%d/%m} {round(w['hours'] / w['capacity'] * 100)} %" for w in m["weeks"] if w["capacity"] and w["hours"] > w["capacity"] * 1.1]
        lines.append(f"- {m['name']} : {m['open']} action(s) ouverte(s), {m['remaining']} h restantes"
                     + (f" — ⚠️ surcharge {', '.join(peaks[:3])}" if peaks else (" — disponible" if not m["open"] else "")))
    return "\n".join(lines), []


def budget_text(project, user):
    if not _rights(user, project)["canSeeMoney"]:
        return "Votre profil n'a pas accès aux données financières de ce projet.", []
    b = budget_of(project)
    if not b["budget"]:
        return f"Aucun budget saisi. Consommé à ce jour : {float(b['consumed']):,.0f} € (temps validés × TJM).".replace(",", " "), []
    return (f"**Budget** : {float(b['budget']):,.0f} €\n- Consommé : {float(b['consumed']):,.0f} €\n- Engagé : {float(b['pending']):,.0f} €\n"
            f"- Reste : {float(b['remaining']):,.0f} € ({b['rate']} % utilisé)" + (
                f"\n- ⚠️ TJM manquant pour : {', '.join(b['missingRates'])}" if b["missingRates"] else "")).replace(",", " "), []


def docs_text(project, user):
    """Contrôle documentaire, comme le ferait un chef de projet."""
    from .models import Document
    from .workspace import DOC_TYPES
    qs = Document.objects.filter(project=project).defer("content", "extracted_text").select_related("uploaded_by")
    if not (user.role and user.role.internal):
        qs = qs.filter(client_visible=True)
    docs = list(qs.order_by("-uploaded_at"))
    if not docs:
        return "📂 **Aucun document** dans le projet. Je vous recommande de déposer au minimum le cahier des charges et la proposition."
    labels = dict(DOC_TYPES)
    by = {}
    for d in docs:
        by.setdefault(labels.get(d.type, d.type), []).append(d)
    lines = [f"📂 **{len(docs)} document(s)** dans le projet :"]
    for k, items in by.items():
        lines.append(f"- **{k}** : " + ", ".join(f"{d.name} (v{d.version})" for d in items[:4]) + (" …" if len(items) > 4 else ""))
    recent = [d for d in docs if d.uploaded_at and (_today() - d.uploaded_at).days <= 7]
    if recent:
        lines.append(f"🆕 Déposés cette semaine : " + ", ".join(d.name for d in recent[:5]))
    auto = [d for d in docs if (d.extraction or {}).get("autoClassified") and (d.extraction or {}).get("confidence", 100) < 50]
    if auto:
        lines.append("⚠️ Classement à vérifier (faible confiance) : " + ", ".join(d.name for d in auto[:5]))
    return "\n".join(lines)


LABELS_FR = {"todo": "À faire", "planned": "Planifiée", "doing": "En cours", "review": "En revue", "blocked": "Bloquée", "done": "Terminée"}


def recommendations(project, user):
    """Recommandations affichées à l'ouverture de l'assistant (3 à 5 points concrets)."""
    persona = persona_of(user)
    today = _today()
    tasks = list(Action.objects.filter(project=project).select_related("owner"))
    recos = []
    if persona in ("team",):
        mine = [t for t in tasks if t.owner_id == user.id and t.status != "done"]
        late = [t for t in mine if t.due and t.due < today]
        if late:
            recos.append(("crit", f"Vous avez {len(late)} action(s) en retard : commencez par « {late[0].title} ».", "today"))
        if any(t.status == "blocked" for t in mine):
            recos.append(("warn", "Une de vos actions est bloquée : signalez-le au chef de projet.", "my_tasks"))
        recos.append(("info", "Préparez votre point d'avancement de la semaine en un clic.", "my_report"))
        return recos[:5]
    late = [t for t in tasks if t.due and t.due < today and t.status != "done"]
    if late:
        recos.append(("crit", f"{len(late)} action(s) en retard : relancer les responsables et replanifier.", "remind" if persona != "client" else "check"))
    blocked = [t for t in tasks if t.status == "blocked"]
    if blocked:
        recos.append(("crit", f"{len(blocked)} action(s) bloquée(s) : organiser un point de déblocage.", "check"))
    unassigned = [t for t in tasks if not t.owner_id and t.status != "done"]
    if unassigned and persona in ("pm", "tl"):
        recos.append(("warn", f"{len(unassigned)} action(s) sans responsable : les affecter.", "check"))
    load, _ = workload(project, tasks, today)
    over = [m["name"] for m in load if any(w["capacity"] and w["hours"] > w["capacity"] * 1.1 for w in m["weeks"])]
    if over and persona in ("pm", "tl", "exec"):
        recos.append(("warn", f"Surcharge de {', '.join(over[:3])} : rééquilibrer la charge.", "workload" if persona == "tl" else "analyze"))
    from methodology.models import VPhase
    if not VPhase.objects.filter(project=project).exists() and persona == "pm":
        recos.append(("info", "Aucun planning macro : saisir les phases clés pour suivre le prévu / réel.", "analyze"))
    if persona in ("client", "sales", "exec"):
        recos.append(("info", "Obtenir la synthèse d'avancement à jour du projet.", "report"))
    if not recos:
        recos.append(("ok", "Le projet est sous contrôle : aucun retard ni blocage détecté.", "report"))
    return recos[:5]


def _do_remind_pm(project, user, note):
    if not project.pm_id:
        return "Ce projet n'a pas de chef de projet désigné."
    Notification.objects.create(user=project.pm, event="project_alert", title=f"[{project.code}] Relance de {user.display_name}"[:200],
                                body=f"{project.name} · {note or 'Point en attente de votre retour'} · via l'assistant · {project.id}")
    audit.record(user, f"Projet {project.code}", "Chef de projet relancé (via l'assistant)", "", note[:200], tenant=project.tenant)
    return f"🔔 Le chef de projet **{project.pm.display_name}** a été notifié."


# --------------------------------------------------------------------------- API
class AssistantMeView(APIView):
    """Assistant de l'utilisateur : profil IA, mode (licence Pilote ∩ réglage admin), missions."""

    def get(self, request):
        user = request.user
        mode = mode_of(user) if in_active_tenant(user) else "off"
        if mode == "off":
            return Response({"allowed": False, "mode": "off"})
        persona = PERSONAS[persona_of(user)]
        return Response({
            "allowed": True, "mode": mode, "modeLabel": MODES[mode], "persona": persona["name"], "pitch": persona["pitch"],
            "missions": [{"code": m, "icon": MISSIONS[m][0], "label": MISSIONS[m][1], "help": MISSIONS[m][2], "acts": m in ACTING}
                         for m in persona["missions"]],
            "llm": bool(os.environ.get("ANTHROPIC_API_KEY")) and conf_of(user.tenant)["llm"],
        })


class AssistantProjectsView(APIView):
    """État de l'assistant IA par projet (cartes « Mes projets ») : propositions en attente, dernière revue."""

    def get(self, request):
        user = request.user
        mode = mode_of(user) if in_active_tenant(user) else "off"
        if mode == "off":
            return Response({"allowed": False, "projects": {}})
        row = AppSetting.objects.filter(tenant=user.tenant, key="assistant_review").first()
        data = row.value if row and isinstance(row.value, dict) else {}
        reviewer = persona_of(user) in ("pm", "tl")
        out = {}
        for pid in visible_projects(user).values_list("id", flat=True):
            st = data.get(pid) or {}
            out[pid] = {"pending": len(st.get("pending", [])) if reviewer else 0,
                        "urgent": sum(1 for p in st.get("pending", []) if p.get("level") == "crit") if reviewer else 0,
                        "lastReview": st.get("at"), "actions": len(st.get("history", []))}
        return Response({"allowed": True, "mode": mode, "persona": PERSONAS[persona_of(user)]["name"], "projects": out})


class AssistantConfigView(APIView):
    """Réglage de l'administrateur : mode de l'assistant par profil, dans la limite de la licence du Pilote."""

    def _admin(self, request):
        if not request.user.is_app_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé aux administrateurs.", status.HTTP_403_FORBIDDEN)

    def get(self, request):
        self._admin(request)
        from accounts.models import Role
        from django.db.models import Q
        roles = Role.objects.filter(Q(tenant__isnull=True) | Q(tenant=request.user.tenant)).exclude(
            code__in=("superadmin", "support", "license_manager")).order_by("position")
        c = conf_of(request.user.tenant)
        return Response({
            "license": license_of(request.user.tenant), "modes": [{"code": k, "label": v} for k, v in MODES.items()],
            "llm": c["llm"], "llmConfigured": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "profiles": [{"code": r.code, "label": r.label, "internal": r.internal, "mode": c["profiles"].get(r.code, "off"),
                          "assistant": PERSONAS[ROLE_PERSONA.get(r.code, "team" if r.internal else "client")]["name"]} for r in roles],
        })

    def put(self, request):
        self._admin(request)
        lic = license_of(request.user.tenant)
        c = conf_of(request.user.tenant)
        for code, mode in (request.data.get("profiles") or {}).items():
            if mode in MODES:
                c["profiles"][str(code)[:20]] = mode if RANK[mode] <= RANK[lic["maxMode"]] else lic["maxMode"]
        if "llm" in request.data:
            c["llm"] = bool(request.data["llm"])
        AppSetting.objects.update_or_create(tenant=request.user.tenant, key="assistant", defaults={"value": c})
        audit.record(request.user, "Assistants IA", "Modes des assistants modifiés", "",
                     ", ".join(f"{k}:{v}" for k, v in c["profiles"].items()), tenant=request.user.tenant)
        return self.get(request)


class PilotAssistantLicenseView(APIView):
    """Licence « Assistants IA » d'une entreprise, accordée par le Pilote (activation et mode maximal)."""

    def _pilot(self, request):
        if not request.user.is_platform_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé au Pilote.", status.HTTP_403_FORBIDDEN)

    def get(self, request, tenant_id):
        self._pilot(request)
        from tenants.models import Tenant
        t = Tenant.objects.get(pk=tenant_id)
        return Response({"tenant": t.name, **license_of(t), "modes": [{"code": k, "label": v} for k, v in MODES.items()]})

    def put(self, request, tenant_id):
        self._pilot(request)
        from tenants.models import Tenant
        t = Tenant.objects.get(pk=tenant_id)
        v = {"enabled": bool(request.data.get("enabled")), "maxMode": request.data.get("maxMode") if request.data.get("maxMode") in MODES else "semi"}
        AppSetting.objects.update_or_create(tenant=t, key="assistant_license", defaults={"value": v})
        audit.record(request.user, f"Entreprise {t.name}", "Licence Assistants IA modifiée", "",
                     f"{'activée' if v['enabled'] else 'désactivée'} · max {v['maxMode']}", tenant=None)
        return self.get(request, tenant_id)


class ProjectAssistantView(APIView):
    def post(self, request, pk):
        project = _project(request.user, pk)
        user = request.user
        mode = mode_of(user)
        if mode == "off":
            raise ApiError("FORBIDDEN_PERMISSION", "L'assistant IA n'est pas activé pour votre profil (licence ou paramétrage).",
                           status.HTTP_403_FORBIDDEN)
        persona = persona_of(user)
        allowed = set(PERSONAS[persona]["missions"]) | {"ask", "intro"}
        allowed.add("review_decide")  # chacun ne valide que les propositions dont il est validateur (circuit)
        text = str(request.data.get("text") or "")[:1500]
        intent = request.data.get("intent") or route(text)
        if intent == "check" and persona == "team" and not request.data.get("intent"):
            intent = "my_tasks"
        if intent not in allowed:
            intent = "ask"
        # Semi-automatique : toute action est d'abord proposée, puis validée par un humain. Automatique : exécution directe.
        confirm = bool(request.data.get("confirm")) or mode == "auto"
        out = {"intent": intent, "mode": mode, "suggestions": []}

        team = [{"id": a.user_id, "name": a.user.display_name}
                for a in ProjectAccess.objects.filter(project=project, user__is_active=True).select_related("user")]
        if intent == "intro":
            out["recommendations"] = [{"level": lv, "text": tx, "mission": m} for lv, tx, m in recommendations(project, user)]
            out["reply"] = ""
            from .assistant_questions import questions_of
            qs = questions_of(project)
            out["questions"] = [q for q in qs if q["to"] == user.pk and q["status"] == "open"]
            if persona in ("pm", "tl"):
                from .assistant_review import cycle, state_of
                if mode == "auto":
                    # Mode automatique : l'assistant se lance à chaque ouverture, vérifie, agit et soumet ses décisions.
                    done, _ = cycle(project, "auto", force=True)
                    out["autoDone"] = done
                out["teamQuestions"] = qs[:20]
                st = state_of(project)
                out["pending"] = st["pending"]
                out["reviewAt"] = st["at"]
                out["history"] = st["history"][:15]
                out["team"] = team
            else:
                from .assistant_review import state_of
                from .ai_orchestrator import can_validate
                mine = [p for p in state_of(project)["pending"] if can_validate(user, project, p.get("validator") or "pm")]
                if mine:
                    out["pending"] = mine
                    out["team"] = team
        elif intent in ("review", "docs"):
            from .assistant_review import cycle, review
            from .ai_orchestrator import any_active
            if intent == "docs":
                props = [p for p in review(project) if p["kind"].startswith(("doc_", "req_"))]
                out["reply"] = docs_text(project, user)
                out["proposals"] = props
            else:
                if any_active(project) == "off":
                    props, done, pending = review(project), [], None
                else:
                    done, pending = cycle(project, force=True, manual=True)
                    props = pending
                pending = props if pending is None else pending
                crit = sum(1 for p in pending if p["level"] == "crit")
                lines = ["🧭 **Revue du projet terminée.**"]
                if done:
                    lines.append(f"**J'ai mené {len(done)} action(s) selon les circuits de validation** :")
                    lines += [f"- ✅ {d['result']}" for d in done]
                lines.append(f"**{len(pending)} proposition(s) en attente de validation**" + (f", dont **{crit} urgente(s)**" if crit else "")
                             + " : ajustez le responsable ou l'échéance si besoin, puis validez." if pending
                             else "Aucune proposition en attente : le projet est sous contrôle. ✅")
                out["reply"] = "\n".join(lines)
                out["proposals"] = pending
            out["team"] = team
        elif intent == "review_decide":
            from .assistant_review import decide
            accept = [str(x) for x in (request.data.get("accept") or [])]
            reject = [str(x) for x in (request.data.get("reject") or [])]
            done, st = decide(project, user, accept, reject, request.data.get("edits") or {},
                              via=f"validé par {user.display_name}", check=True)
            lines = [f"- ✅ {d['title']} → {d['result']}" for d in done]
            if reject:
                lines.append(f"- ✖ {len(reject)} proposition(s) écartée(s) (elles ne reviendront pas avant 7 jours si la situation persiste).")
            out["reply"] = ("**Décisions appliquées** :\n" + "\n".join(lines)) if lines else "Aucune proposition sélectionnée."
            out["proposals"] = st["pending"]
            out["history"] = st["history"][:15]
            out["team"] = team
        elif intent == "alert":
            title = str(request.data.get("title") or "").strip()
            if not title:
                out["reply"] = "Quelle alerte voulez-vous lancer ? Elle sera envoyée à tous les membres du projet (notification + e-mail)."
                out["form"] = "alert"
            elif not confirm:
                out["reply"] = f"**Proposition** : lancer l'alerte « {title} » à tous les membres du projet."
                out["confirm"] = {"intent": "alert", "label": "Valider : lancer l'alerte",
                                  "payload": {k: request.data.get(k) for k in ("title", "message", "level")}}
            else:
                from .assistant_review import execute
                level = request.data.get("level") if request.data.get("level") in ("info", "warning", "critical") else "warning"
                res = execute(project, user, {"do": "alert", "payload": {"title": title[:150], "level": level,
                                                                          "message": str(request.data.get("message") or "")[:1500]}},
                              via=PERSONAS[persona]["name"])
                out["reply"] = f"🚨 {res}"
        elif intent == "check":
            out["reply"], out["suggestions"] = check(project, user)
        elif intent == "report":
            reply, out["suggestions"] = report(project, user)
            out["reply"] = (_llm("Rédige un rapport d'avancement clair pour le client et la direction.", _context(project, user))
                            if conf_of(project.tenant)["llm"] and request.data.get("ai") else None) or reply
        elif intent == "analyze":
            out["reply"], out["suggestions"] = analyze(project, user)
        elif intent == "workload":
            out["reply"], out["suggestions"] = workload_text(project)
        elif intent == "my_tasks":
            out["reply"], _ = my_tasks(project, user)
        elif intent == "today":
            out["reply"], _ = my_tasks(project, user, today_only=True)
        elif intent == "my_report":
            out["reply"], _ = my_report(project, user)
        elif intent == "budget":
            out["reply"], _ = budget_text(project, user)
        elif intent == "remind":
            today = _today()
            ids = request.data.get("tasks")
            targets = [t for t in Action.objects.filter(project=project).select_related("owner")
                       if (t.id in ids if ids else (t.due and t.due < today and t.status != "done"))]
            if not targets:
                out["reply"] = "Aucune action en retard à relancer. ✅"
            elif not confirm:
                out["reply"] = f"**Proposition** : relancer {len(targets)} action(s) en retard :\n" + "\n".join(
                    f"- {t.title} → {(t.owner or project.pm).display_name if (t.owner or project.pm) else 'aucun destinataire'}" for t in targets[:15])
                out["confirm"] = {"intent": "remind", "label": f"Valider : envoyer {len(targets)} relance(s)", "payload": {"tasks": [t.id for t in targets]}}
            else:
                sent, mailed, skipped = send_reminders(project, user, targets, str(request.data.get("note") or "")[:300],
                                                       via=f"{PERSONAS[persona]['name']} ({'automatique' if mode == 'auto' else 'validé'})")
                out["reply"] = (f"📨 **{len(sent)} relance(s) envoyée(s)** ({mailed} par e-mail) :\n" + "\n".join(f"- {x}" for x in sent)
                                + (f"\nSans destinataire : {', '.join(skipped)}" if skipped else ""))
        elif intent == "replan":
            props = replan_proposals(project)
            if not props:
                out["reply"] = "Aucune action en retard : rien à replanifier. ✅"
            elif not confirm:
                out["reply"] = "**Proposition de replanification** (charge répartie par responsable) :\n" + "\n".join(
                    f"- {p['title']} ({p['owner']}) : {p['old']:%d/%m} → **{p['new']:%d/%m}**" for p in props[:15])
                out["confirm"] = {"intent": "replan", "label": f"Valider : replanifier {len(props)} action(s)", "payload": {}}
            else:
                for p in props:
                    Action.objects.filter(pk=p["id"], project=project).update(due=p["new"])
                audit.record(user, f"Projet {project.code}", "Actions replanifiées (via l'assistant)", "", f"{len(props)} action(s)", tenant=project.tenant)
                out["reply"] = f"🗓️ **{len(props)} action(s) replanifiée(s)** :\n" + "\n".join(f"- {p['title']} → {p['new']:%d/%m/%Y}" for p in props[:15])
        elif intent in ("create_task", "request"):
            title = str(request.data.get("title") or "").strip()
            team = [{"id": a.user_id, "name": a.user.display_name}
                    for a in ProjectAccess.objects.filter(project=project, user__is_active=True).select_related("user")]
            if not title:
                out["reply"] = ("Décrivez votre demande : elle sera transmise au chef de projet sous forme d'action." if intent == "request"
                                else "Indiquez le titre, le responsable et l'échéance de l'action.")
                out["form"] = "task"
                out["team"] = [] if intent == "request" else team
            elif not confirm:
                owner = next((m["name"] for m in team if str(m["id"]) == str(request.data.get("owner"))), project.pm.display_name if project.pm_id else "—")
                out["reply"] = f"**Proposition** : créer l'action « {title} », affectée à {owner}" + (
                    f", échéance {request.data.get('due')}" if request.data.get("due") else "") + "."
                out["confirm"] = {"intent": intent, "label": "Valider : créer l'action",
                                  "payload": {k: request.data.get(k) for k in ("title", "owner", "due", "phase")}}
            else:
                from django.utils.dateparse import parse_date
                owner = None if intent == "request" else request.data.get("owner")
                if owner and not ProjectAccess.objects.filter(project=project, user_id=owner).exists():
                    raise ApiError("VALIDATION_ERROR", "Le responsable doit être membre de l'équipe du projet.")
                t = Action.objects.create(tenant=project.tenant, project=project, id=_next_action_id(project),
                                          title=(f"[Demande client] {title}" if intent == "request" else title)[:300], status="todo",
                                          owner_id=owner or project.pm_id, due=parse_date(str(request.data.get("due") or "")) or None,
                                          phase=str(request.data.get("phase") or "")[:60], type="Client" if intent == "request" else "")
                audit.record(user, f"Tâche {t.id}", "Action créée (via l'assistant)", "", t.title, tenant=project.tenant)
                if t.owner_id and t.owner_id != user.id:
                    Notification.objects.create(user=t.owner, event="project_alert", title=f"[{project.code}] Nouvelle action : {t.title}"[:200],
                                                body=f"{project.name} · créée par {user.display_name} via l'assistant · {project.id}")
                out["reply"] = f"✅ Action **{t.title}** créée ({t.id}), affectée à {t.owner.display_name if t.owner_id else '—'}."
        elif intent == "remind_pm":
            note = str(request.data.get("note") or text or "")[:300]
            if not confirm:
                out["reply"] = f"**Proposition** : notifier le chef de projet ({project.pm.display_name if project.pm_id else '—'})" + (f" : « {note} »" if note else "") + "."
                out["confirm"] = {"intent": "remind_pm", "label": "Valider : relancer le chef de projet", "payload": {"note": note}}
            else:
                out["reply"] = _do_remind_pm(project, user, note)
        elif intent == "automate":
            rule = _automation(project)
            if "enabled" in request.data:
                rule = {**rule, "enabled": bool(request.data["enabled"]), "everyDays": max(1, min(14, int(request.data.get("everyDays") or 2))),
                        "by": user.display_name}
                row = AppSetting.objects.filter(tenant=project.tenant, key="assistant_auto").first()
                rules = row.value if row and isinstance(row.value, dict) else {}
                rules[project.id] = rule
                AppSetting.objects.update_or_create(tenant=project.tenant, key="assistant_auto", defaults={"value": rules})
                audit.record(user, f"Projet {project.code}", "Relances automatiques " + ("activées" if rule["enabled"] else "désactivées"),
                             "", f"tous les {rule['everyDays']} j", tenant=project.tenant)
                out["reply"] = (f"🤖 Relances automatiques **activées** tous les {rule['everyDays']} jour(s)." if rule["enabled"]
                                else "Relances automatiques **désactivées**.")
            else:
                out["reply"] = "Je peux relancer automatiquement les responsables des actions en retard." + (
                    f"\nÉtat : activé, tous les {rule.get('everyDays', 2)} j." if rule.get("enabled") else "\nÉtat : désactivé.")
                out["form"] = "automate"
            out["automation"] = rule
        else:
            ans = _llm(text, _context(project, user)) if conf_of(project.tenant)["llm"] and text else None
            out["reply"] = ans or ("Choisissez une mission ci-dessous, ou reformulez : « vérifier les actions », « rapport », "
                                   "« analyse », « relancer », « créer une action »…")
        return Response(out)
