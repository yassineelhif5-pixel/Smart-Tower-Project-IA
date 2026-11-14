"""Équipe d'assistants IA d'un projet et Assistant Orchestrateur.

- Les assistants IA sont des ressources du projet : le chef de projet choisit ceux qui travaillent sur son projet
  et leur mode (automatique / semi-automatique), dans la limite de la licence accordée par le Pilote.
- Chaque proposition d'un assistant suit un circuit de validation paramétrable par type de décision : exécution
  directe par l'IA, validation par l'Orchestrateur IA, ou validation humaine (chef de projet, tech lead, client, admin).
- L'Orchestrateur trace tout : propositions, routage, validations, refus, exécutions, questions/réponses,
  corrections apportées par les humains et modifications de paramétrage.
"""
import re
import secrets

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.errors import ApiError
from configuration import audit
from configuration.models import AppSetting, Notification

from .models import Document, ProjectAccess

# Assistants IA : nom, rôle, mission, avatar. Chacun reste strictement dans son rôle.
ROSTER = {
    "atlas": {"name": "Atlas", "role": "Chef de projet IA", "avatar": "🧭", "color": "#4f46e5",
              "mission": "Pilote le projet : retards, priorités, affectations, replanification, relances et alertes."},
    "nova": {"name": "Nova", "role": "Assistante fonctionnelle IA (AMOA)", "avatar": "📐", "color": "#0ea5e9",
             "mission": "Analyse les besoins et documents, détecte les ambiguïtés et manques, pose les questions métier, propose exigences et ateliers."},
    "altair": {"name": "Altaïr", "role": "Architecte IA", "avatar": "🏛️", "color": "#1e3a8a",
               "mission": "Conçoit l'architecture cible avec l'équipe, recommande les choix techniques et rédige le HLD et les décisions d'architecture."},
    "orion": {"name": "Orion", "role": "Tech Lead IA", "avatar": "🛠️", "color": "#7c3aed",
              "mission": "Surveille les blocages techniques et la charge de l'équipe, propose déblocages et rééquilibrages."},
    "vega": {"name": "Vega", "role": "Responsable qualité & recette IA", "avatar": "🧪", "color": "#16a34a",
             "mission": "Veille à la stratégie de recette : cahier de recette, PV, actions de test avant les jalons."},
    "mercure": {"name": "Mercure", "role": "Contrôleur budgétaire IA", "avatar": "💶", "color": "#d97706",
                "mission": "Suit la consommation du budget et alerte avant dépassement."},
    "lyra": {"name": "Lyra", "role": "Relation client IA", "avatar": "🤝", "color": "#db2777",
             "mission": "Prépare les synthèses client et relaie les demandes du client au chef de projet."},
    "maestro": {"name": "Maestro", "role": "Assistant Orchestrateur", "avatar": "🎼", "color": "#0f172a",
                "mission": "Coordonne les assistants et les humains, applique les circuits de validation et tient le journal."},
}
DEFAULT_ON = {"atlas", "nova", "orion", "maestro"}

# Quel assistant porte quel type de proposition.
KIND_OWNER = {"late": "atlas", "assign": "atlas", "nudge": "atlas", "phase": "atlas", "alert_open": "atlas", "ask": "atlas",
              "blocked": "orion", "rebalance": "orion", "budget": "mercure", "doc_missing": "nova", "doc_date": "nova",
              "req_ambiguity": "nova", "req_missing": "nova", "req_story": "nova", "test_missing": "vega",
              "minutes": "atlas"}

# Types de décision et circuits de validation.
CATEGORIES = {
    "question": "Questions aux membres", "notification": "Rappels et notifications", "alerte": "Alertes à l'équipe",
    "affectation": "Affectations / changements de responsable", "planning": "Replanification / échéances",
    "blocage": "Gestion des blocages", "action": "Création d'actions", "besoin": "Exigences et besoins (AMOA)",
}
DO_CATEGORY = {"ask": "question", "nudge": "notification", "notify_pm": "notification", "alert": "alerte",
               "assign": "affectation", "late": "planning", "set_due": "planning", "blocked": "blocage",
               "mark_blocked": "blocage", "create_task": "action", "req_task": "besoin", "req_ask": "question"}
VALIDATORS = {"auto": "Exécution directe par l'IA", "ai": "Validé par l'Orchestrateur IA (Maestro)",
              "pm": "Chef de projet (humain)", "tl": "Tech lead (humain)", "client": "Client (humain)",
              "admin": "Administrateur (humain)"}
DEFAULT_CIRCUITS = {"question": "auto", "notification": "auto", "alerte": "ai", "affectation": "pm", "planning": "pm",
                    "blocage": "pm", "action": "pm", "besoin": "client"}

CONF_KEY, JOURNAL_KEY, JOURNAL_KEEP = "ai_project_team", "ai_journal", 400


# --------------------------------------------------------------------------- paramétrage
def _setting(tenant, key):
    row = AppSetting.objects.filter(tenant=tenant, key=key).first()
    return row, (row.value if row and isinstance(row.value, dict) else {})


def _put(tenant, key, row, value):
    if row:
        row.value = value
        row.save(update_fields=["value", "updated_at"])
    else:
        AppSetting.objects.create(tenant=tenant, key=key, value=value)


def license_mode(tenant):
    from .assistant import RANK, license_of, pm_mode_of
    lic = license_of(tenant)
    return lic, RANK, pm_mode_of(tenant)


def team_conf(project):
    """Assistants du projet (actif, mode) et circuits de validation, plafonnés par la licence."""
    lic, rank, pm_mode = license_mode(project.tenant)
    _, data = _setting(project.tenant, CONF_KEY)
    conf = data.get(project.id) or {}
    saved = conf.get("assistants") or {}
    default_mode = pm_mode if pm_mode != "off" else "semi"
    assistants = {}
    for code in ROSTER:
        a = saved.get(code) or {"enabled": code in DEFAULT_ON, "mode": default_mode}
        mode = a.get("mode") if a.get("mode") in ("auto", "semi") else "semi"
        if rank[mode] > rank[lic["maxMode"]]:
            mode = lic["maxMode"] if lic["maxMode"] != "off" else "semi"
        assistants[code] = {"enabled": bool(a.get("enabled")) and lic["enabled"], "mode": mode}
    circuits = {**DEFAULT_CIRCUITS, **{k: v for k, v in (conf.get("circuits") or {}).items() if k in CATEGORIES and v in VALIDATORS}}
    return {"licensed": lic["enabled"], "maxMode": lic["maxMode"], "assistants": assistants, "circuits": circuits}


def any_active(project):
    c = team_conf(project)
    on = [a for a in c["assistants"].values() if a["enabled"]]
    if not on:
        return "off"
    return "auto" if any(a["mode"] == "auto" for a in on) else "semi"


def route(project, prop, conf=None):
    """Circuit de validation d'une proposition → validateur effectif ('auto', 'ai', 'pm', 'tl', 'client', 'admin')."""
    conf = conf or team_conf(project)
    owner = prop.get("assistant") or KIND_OWNER.get(prop.get("kind"), "atlas")
    cat = DO_CATEGORY.get(prop.get("do"), "action")
    v = conf["circuits"].get(cat, "pm")
    mode = conf["assistants"].get(owner, {}).get("mode", "semi")
    if v in ("auto", "ai") and mode != "auto":
        v = "pm"  # un assistant semi-automatique ne décide jamais seul
    if v == "ai" and not conf["assistants"]["maestro"]["enabled"]:
        v = "auto"
    if v == "tl" and not project.tl_id:
        v = "pm"
    return v, cat


def can_validate(user, project, validator):
    if user.is_app_admin:
        return True
    if validator == "pm":
        return project.pm_id == user.pk
    if validator == "tl":
        return project.tl_id == user.pk or project.pm_id == user.pk
    if validator == "client":
        return bool(user.role and not user.role.internal) or project.pm_id == user.pk
    return False


def validator_users(project, validator):
    if validator == "pm":
        return [project.pm] if project.pm else []
    if validator == "tl":
        return [project.tl or project.pm] if (project.tl or project.pm) else []
    if validator == "client":
        users = [a.user for a in ProjectAccess.objects.filter(project=project, user__is_active=True).select_related("user", "user__role")
                 if a.user.role and not a.user.role.internal]
        return users or ([project.pm] if project.pm else [])
    if validator == "admin":
        from django.contrib.auth import get_user_model
        return list(get_user_model().objects.filter(tenant=project.tenant, is_active=True, role_id="admin")[:3])
    return []


# --------------------------------------------------------------------------- journal d'orchestration
def log(project, kind, actor, text, assistant=None, detail=None, target=None):
    """kind : proposition, routage, validation, refus, execution, question, reponse, correction, modification, cycle."""
    row, data = _setting(project.tenant, JOURNAL_KEY)
    items = data.get(project.id, [])
    items.insert(0, {"id": secrets.token_hex(4), "at": timezone.now().isoformat(), "kind": kind, "actor": actor,
                     "assistant": assistant, "text": str(text)[:600], "detail": detail or {}, "target": target})
    data[project.id] = items[:JOURNAL_KEEP]
    _put(project.tenant, JOURNAL_KEY, row, data)


def journal(project):
    _, data = _setting(project.tenant, JOURNAL_KEY)
    return data.get(project.id, [])


# --------------------------------------------------------------------------- Nova : analyse des besoins (AMOA)
REQ_RE = re.compile(r"[^.!?\n]*\b(doit|doivent|devra|devront|il faut|exigence|obligatoire|permettre de|le système|l'application|l'utilisateur pourra)\b[^.!?\n]*[.!?]?", re.I)
VAGUE = ["rapide", "rapidement", "simple", "facile", "intuitif", "convivial", "performant", "etc", "tbd", "à définir", "a definir",
         "éventuellement", "si possible", "plus tard", "optimisé", "moderne", "sécurisé", "ergonomique", "flexible"]
TOPICS = {
    "acceptation": (["critère d'acceptation", "critères d'acceptation", "recette", "validé si"], "les critères d'acceptation (comment valider chaque exigence)"),
    "acteurs": (["utilisateur", "profil", "rôle", "acteur"], "les acteurs / profils utilisateurs concernés"),
    "volumétrie": (["volume", "nombre d'utilisateurs", "volumétrie", "simultané"], "la volumétrie (utilisateurs, données, transactions)"),
    "performance": (["temps de réponse", "performance", "seconde"], "les exigences de performance mesurables"),
    "données": (["donnée", "reprise", "migration", "import"], "les données à reprendre / migrer et leurs règles"),
    "planning": (["date", "jalon", "livraison", "délai"], "les jalons et contraintes de délai"),
}


def nova_build(project, pm):
    """Analyse des documents de besoin : exigences repérées, formulations vagues, sujets non couverts."""
    from .assistant_questions import questions_of
    docs = list(Document.objects.filter(project=project, type__in=["specs", "proposal", "minutes", "sfd"]).order_by("-uploaded_at")[:6])
    asked = {q.get("kind") for q in questions_of(project)}
    props = []
    if not docs:
        return props
    text = "\n".join((d.extracted_text or "") for d in docs)
    low = text.casefold()
    reqs = []
    for m in REQ_RE.finditer(text):
        sent = " ".join(m.group(0).split())
        if 25 <= len(sent) <= 300 and sent not in reqs:
            reqs.append(sent)
    vague = []
    for r in reqs:
        words = [w for w in VAGUE if re.search(rf"\b{re.escape(w)}\b", r.casefold())]
        if words:
            vague.append((r, words))
    names = ", ".join(d.name for d in docs[:3])
    for r, words in vague[:3]:
        key = f"vague-{abs(hash(r)) % 10**8}"
        if f"req:{key}" in asked:
            continue
        props.append({"kind": "req_ambiguity", "assistant": "nova", "level": "warn", "do": "req_ask", "key": key,
                      "title": f"Clarifier une exigence floue ({', '.join(words)})",
                      "why": f"Dans {names} : « {r[:220]} ». Le terme « {words[0]} » n'est pas mesurable : risque de litige en recette.",
                      "effect": "Question posée au client (ou au chef de projet) pour obtenir une formulation mesurable.",
                      "payload": {"qkind": f"req:{key}",
                                  "question": f"Exigence à préciser : « {r[:300]} ». Que signifie concrètement « {words[0]} » "
                                              "(valeur cible, mesure, exemple) ? Comment sera-t-elle validée en recette ?"}})
    missing = [label for _, (kw, label) in TOPICS.items() if not any(k in low for k in kw)]
    if missing and "req:missing" not in asked:
        props.append({"kind": "req_missing", "assistant": "nova", "level": "info", "do": "req_ask", "key": "missing",
                      "title": f"Compléter le besoin : {len(missing)} sujet(s) non couvert(s)",
                      "why": f"Les documents de besoin ({names}) ne traitent pas : " + " ; ".join(missing) + ".",
                      "effect": "Questions de cadrage envoyées au client pour compléter l'expression de besoin.",
                      "payload": {"qkind": "req:missing",
                                  "question": "Pour compléter l'expression de besoin, pouvez-vous préciser : " + " ; ".join(missing) + " ?"}})
    if reqs:
        props.append({"kind": "req_story", "assistant": "nova", "level": "info", "do": "req_task", "key": f"reqs-{len(reqs)}",
                      "title": f"Formaliser {len(reqs)} exigence(s) repérée(s) dans les documents",
                      "why": f"{len(reqs)} exigence(s) détectée(s) dans {names}, par exemple : « {reqs[0][:160]} ».",
                      "effect": "Action « Rédiger les exigences et critères d'acceptation » pour le chef de projet, avec la liste en description.",
                      "payload": {"title": f"Rédiger les exigences et critères d'acceptation ({len(reqs)} repérées)",
                                  "requirements": reqs[:25]},
                      "edit": {"owner": pm.id if pm else None}})
    if len(missing) >= 3 and "req:atelier" not in asked:
        props.append({"kind": "req_missing", "assistant": "nova", "level": "info", "do": "req_task", "key": "atelier",
                      "title": "Organiser un atelier de recueil du besoin",
                      "why": "Plusieurs sujets structurants ne sont pas couverts : un atelier avec le client est plus efficace qu'un échange écrit.",
                      "effect": "Action « Atelier de recueil du besoin » pour le chef de projet sous 5 jours ouvrés.",
                      "payload": {"title": "Atelier de recueil du besoin avec le client"}, "edit": {"owner": pm.id if pm else None}})
    return props


def vega_build(project, tasks, docs_types, pm, today):
    props = []
    open_ = [t for t in tasks if t.status != "done"]
    done_ratio = (len(tasks) - len(open_)) / len(tasks) if tasks else 0
    if done_ratio >= 0.5 and "test" not in docs_types:
        props.append({"kind": "test_missing", "assistant": "vega", "level": "warn", "do": "create_task", "key": "plan",
                      "title": "Préparer le cahier de recette",
                      "why": f"{round(done_ratio * 100)} % des actions sont terminées et aucun cahier de recette / PV n'est déposé.",
                      "effect": "Action « Rédiger le cahier de recette » pour le chef de projet sous 5 jours ouvrés.",
                      "payload": {"title": "Rédiger le cahier de recette"}, "edit": {"owner": pm.id if pm else None}})
    if not any("recette" in (t.title or "").casefold() or "test" in (t.title or "").casefold() for t in tasks) and len(tasks) >= 3:
        props.append({"kind": "test_missing", "assistant": "vega", "level": "info", "do": "create_task", "key": "tests",
                      "title": "Planifier les actions de test",
                      "why": "Aucune action de test ou de recette n'est planifiée dans le projet.",
                      "effect": "Action « Planifier les tests et la recette » pour le chef de projet.",
                      "payload": {"title": "Planifier les tests et la recette"}, "edit": {"owner": pm.id if pm else None}})
    return props


# --------------------------------------------------------------------------- API
def _overview(project, user):
    from .assistant_review import state_of
    from .workspace import _rights
    conf = team_conf(project)
    st = state_of(project)
    items = journal(project)
    pending = []
    for p in st["pending"]:
        v = p.get("validator") or route(project, p, conf)[0]
        pending.append({**p, "validator": v, "validatorLabel": VALIDATORS.get(v, v),
                        "assistantName": ROSTER.get(p.get("assistant") or KIND_OWNER.get(p["kind"], "atlas"), {}).get("name"),
                        "canValidate": can_validate(user, project, v)})
    stats = {}
    for e in items:
        a = e.get("assistant")
        if a:
            s = stats.setdefault(a, {"actions": 0, "proposals": 0, "last": None})
            s["last"] = s["last"] or e["at"]
            if e["kind"] == "execution":
                s["actions"] += 1
            if e["kind"] == "proposition":
                s["proposals"] += 1
    r = _rights(user, project)
    team = [{"id": a.user_id, "name": a.user.display_name}
            for a in ProjectAccess.objects.filter(project=project, user__is_active=True).select_related("user")]
    return {
        "licensed": conf["licensed"], "maxMode": conf["maxMode"],
        "canConfigure": bool(r["isPm"] or user.is_app_admin),
        "roster": [{"code": c, **ROSTER[c], **conf["assistants"][c], "stats": stats.get(c, {"actions": 0, "proposals": 0, "last": None}),
                    "pending": sum(1 for p in pending if (p.get("assistant") or KIND_OWNER.get(p["kind"])) == c)} for c in ROSTER],
        "circuits": conf["circuits"], "categories": CATEGORIES, "validators": VALIDATORS,
        "pending": pending, "journal": items[:200], "team": team, "lastCycle": st.get("at"),
    }


class OrchestratorView(APIView):
    """GET : vue d'orchestration. PUT : assistants affectés au projet + circuits. POST : lancer un cycle / décider."""

    def _project(self, request, pk):
        from .workspace import _project
        project = _project(request.user, pk)
        if not team_conf(project)["licensed"]:
            raise ApiError("FORBIDDEN_PERMISSION", "L'entreprise n'a pas de licence Assistants IA (à demander au Pilote).",
                           status.HTTP_403_FORBIDDEN)
        return project

    def get(self, request, pk):
        project = self._project(request, pk)
        return Response(_overview(project, request.user))

    def put(self, request, pk):
        project = self._project(request, pk)
        if not (project.pm_id == request.user.pk or request.user.is_app_admin):
            raise ApiError("FORBIDDEN_PERMISSION", "Seul le chef de projet ou l'administrateur paramètre les assistants du projet.",
                           status.HTTP_403_FORBIDDEN)
        old = team_conf(project)
        row, data = _setting(project.tenant, CONF_KEY)
        conf = data.get(project.id) or {}
        changes = []
        if isinstance(request.data.get("assistants"), dict):
            saved = conf.get("assistants") or {}
            for code, a in request.data["assistants"].items():
                if code not in ROSTER or not isinstance(a, dict):
                    continue
                new = {"enabled": bool(a.get("enabled")), "mode": a.get("mode") if a.get("mode") in ("auto", "semi") else "semi"}
                o = old["assistants"][code]
                if new["enabled"] != o["enabled"] or new["mode"] != o["mode"]:
                    changes.append(f"{ROSTER[code]['name']} : {'actif' if o['enabled'] else 'inactif'}/{o['mode']} → "
                                   f"{'actif' if new['enabled'] else 'inactif'}/{new['mode']}")
                saved[code] = new
            conf["assistants"] = saved
        if isinstance(request.data.get("circuits"), dict):
            circ = {k: v for k, v in request.data["circuits"].items() if k in CATEGORIES and v in VALIDATORS}
            for k, v in circ.items():
                if old["circuits"].get(k) != v:
                    changes.append(f"Circuit « {CATEGORIES[k]} » : {VALIDATORS[old['circuits'].get(k, 'pm')]} → {VALIDATORS[v]}")
            conf["circuits"] = {**(conf.get("circuits") or {}), **circ}
        data[project.id] = conf
        _put(project.tenant, CONF_KEY, row, data)
        if changes:
            log(project, "modification", request.user.display_name, "Paramétrage modifié : " + " ; ".join(changes), "maestro")
            audit.record(request.user, f"Projet {project.code}", "Assistants IA du projet paramétrés", "", " ; ".join(changes)[:500],
                         tenant=project.tenant)
        return Response(_overview(project, request.user))

    def post(self, request, pk):
        project = self._project(request, pk)
        action = request.data.get("action")
        from .assistant_review import cycle, decide
        if action == "run":
            mode = any_active(project)
            if mode == "off":
                raise ApiError("VALIDATION_ERROR", "Aucun assistant actif sur ce projet.")
            log(project, "cycle", request.user.display_name, "Orchestration lancée manuellement", "maestro")
            done, pending = cycle(project, mode, force=True, manual=True)
            out = _overview(project, request.user)
            out["done"] = done
            return Response(out)
        if action == "decide":
            accept = [str(x) for x in request.data.get("accept") or []]
            reject = [str(x) for x in request.data.get("reject") or []]
            done, _ = decide(project, request.user, accept, reject, request.data.get("edits") or {},
                             via=f"validé par {request.user.display_name}", check=True)
            out = _overview(project, request.user)
            out["done"] = done
            return Response(out)
        raise ApiError("VALIDATION_ERROR", "Action inconnue.")


def notify_validators(project, props):
    """Prévient chaque validateur humain des propositions qui l'attendent."""
    by_v = {}
    for p in props:
        if p.get("validator") in ("pm", "tl", "client", "admin"):
            by_v.setdefault(p["validator"], []).append(p)
    for v, items in by_v.items():
        for u in validator_users(project, v):
            Notification.objects.create(
                user=u, event="project_alert",
                title=f"[{project.code}] 🎼 {len(items)} proposition(s) des assistants IA à valider"[:200],
                body=(" ; ".join(f"{ROSTER.get(p.get('assistant') or 'atlas', ROSTER['atlas'])['name']} : {p['title']}" for p in items[:4])
                      + f" · Ouvrez l'Orchestrateur IA du projet · {project.id}")[:2000])
