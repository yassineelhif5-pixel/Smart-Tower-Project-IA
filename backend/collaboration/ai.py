"""Assistants IA dans les discussions de tâche.

- Le créateur de la discussion (ou un valideur Collaboration) ajoute un assistant IA ou Maestro.
- Maestro analyse la tâche (titre, phase, type, derniers messages) et la confie :
  * à l'assistant IA du domaine quand c'est un travail de rédaction ou d'analyse qu'il sait préparer ;
  * sinon à la personne de l'équipe dont le profil correspond et la charge est la plus faible.
  L'affectation d'une personne suit le circuit « affectation » de l'Orchestrateur : appliquée directement si
  l'utilisateur peut la valider (ou circuit automatique), sinon proposée au valideur.
- Les assistants présents répondent aux messages (nom cité, sinon routage par domaine). Claude si la clé est
  configurée, sinon réponses du moteur local. Tout est tracé dans le journal d'orchestration du projet.
"""
import json
import logging
import os
import re

import requests
from django.contrib.auth import get_user_model
from django.utils import timezone

from aicalls.templates import ARCHI_HINTS, DOMAIN_OWNER, DOMAINS, VAGUE_TERMS
from configuration import audit
from configuration.notify import notify
from projects.ai_orchestrator import ROSTER, can_validate, log as journal_log, team_conf, validator_users
from projects.models import Action, ProjectAccess

logger = logging.getLogger(__name__)
User = get_user_model()

# Profils humains à privilégier par domaine (ordre de préférence).
ROLE_FOR = {"architecture": ["techlead", "consultant", "dev"], "technique": ["dev", "techlead", "consultant"],
            "qualite": ["testeur", "consultant", "dev"], "planning": ["cdp", "manager"], "budget": ["commercial", "cdp"],
            "client": ["cdp", "commercial"], "fonctionnel": ["consultant", "cdp"]}
# Travaux qu'un assistant IA sait préparer seul (un humain relit et valide).
AI_WORK = ["rédiger", "rediger", "rédaction", "redaction", "documenter", "documentation", "spécifier", "specifier", "spécification",
           "analyser", "analyse", "cahier", "synthèse", "synthese", "compte rendu", "compte-rendu", "plan de test", "stratégie de recette",
           "cas de test", "estimer", "estimation", "chiffrer", "chiffrage", "exigence", "user stor", "critères d'acceptation",
           "dossier d'architecture", "hld", "sfd", "dat", "note", "rapport", "recommandation"]
EXTRA_DOMAIN = {"fonctionnel": ["spécification", "specification", "sfd", "exigence", "user stor", "critères d'acceptation", "rédiger",
                               "atelier", "recueil", "expression de besoin", "règle métier", "processus"],
                "qualite": ["plan de test", "cas de test", "recette", "pv"], "architecture": ["hld", "dat", "architecture"],
                "budget": ["estimer", "estimation", "chiffr"]}


NOUN = {"architecture": "architecture", "technique": "technique", "qualite": "qualité et recette", "planning": "planning",
        "budget": "budget", "client": "relation client", "fonctionnel": "fonctionnel (AMOA)"}


class AiError(Exception):
    def __init__(self, code, message, http_status=400):
        super().__init__(message)
        self.code, self.message, self.http_status = code, message, http_status


def mate(code):
    r = ROSTER.get(code, {})
    return {"code": code, "name": r.get("name", code), "role": r.get("role", ""), "avatar": r.get("avatar", "🤖"),
            "color": r.get("color", "#4f46e5")}


def enabled_codes(project):
    conf = team_conf(project)
    if not conf["licensed"]:
        return set()
    return {c for c, a in conf["assistants"].items() if a["enabled"]} | {"maestro"}


def can_manage(user, discussion):
    from accounts.permissions import has_perm
    return discussion.created_by_id == user.pk or has_perm(user, "collaboration", "approve") or user.is_app_admin


def info(discussion, user):
    on = enabled_codes(discussion.project)
    members = [c for c in (discussion.ai_members or []) if c in ROSTER]
    order = ["maestro"] + [c for c in ROSTER if c != "maestro"]
    return {"licensed": bool(on), "canManage": bool(on) and can_manage(user, discussion),
            "members": [mate(c) for c in members],
            "available": [{**mate(c), "mission": ROSTER[c]["mission"]} for c in order if c in on and c not in members]}


# --------------------------------------------------------------------------- messages
def post(discussion, code, body, kind="message"):
    from .services import _create_message
    m = _create_message(discussion, None, body[:8000], kind=kind, external_author=f"{ROSTER.get(code, {}).get('name', code)} (IA)")
    m.ai_author = code
    m.save(update_fields=["ai_author"])
    return m


def system(discussion, body):
    from .services import _create_message
    return _create_message(discussion, None, body, kind="system")


def trace(discussion, kind, actor, text, assistant):
    try:
        journal_log(discussion.project, kind, actor, f"[Discussion « {discussion.title} »] {text}", assistant=assistant,
                    detail={"discussion": discussion.pk, "action": discussion.action_id})
    except Exception:
        logger.warning("Journal d'orchestration indisponible", exc_info=True)


# --------------------------------------------------------------------------- analyse de la tâche
def task_text(discussion, last=8):
    a = discussion.action
    parts = [discussion.title]
    if a is not None:  # le titre de la tâche compte double : il décrit le travail mieux que la conversation
        parts += [a.title, a.title, a.phase or "", a.type or "", a.block or ""]
    msgs = discussion.messages.filter(deleted_at__isnull=True, kind="message").order_by("-id")[:last]
    parts += [m.body for m in msgs]
    return " \n".join(p for p in parts if p)


def domain_of(text):
    low = text.casefold()
    scores = {}
    for d, kws in DOMAINS.items():
        words = kws + EXTRA_DOMAIN.get(d, [])
        scores[d] = sum(1 for k in words if re.search(rf"(?<!\w){re.escape(k)}", low))
    d, s = max(scores.items(), key=lambda x: x[1])
    return (d if s else "fonctionnel"), s


def is_ai_work(text):
    low = text.casefold()
    return any(re.search(rf"(?<!\w){re.escape(k)}", low) for k in AI_WORK)


def best_person(project, domain, exclude=()):
    members = list(User.objects.filter(project_accesses__project=project, is_active=True).exclude(pk__in=exclude).select_related("role"))
    members = [u for u in members if u.role and u.role.internal and u.role_id not in ("admin", "direction")]
    if not members:
        return None, ""
    load = {u.pk: Action.objects.filter(project=project, owner=u).exclude(status="done").count() for u in members}
    prefs = ROLE_FOR.get(domain, [])
    def rank(u):
        r = prefs.index(u.role_id) if u.role_id in prefs else len(prefs)
        return (r, load[u.pk], u.display_name)
    best = sorted(members, key=rank)[0]
    why = (f"profil {best.role.label}" + (" (le plus adapté)" if best.role_id in prefs else "")
           + f", {load[best.pk]} action(s) en cours")
    return best, why


def triage(discussion, by, force=False):
    """Maestro : analyse la tâche et la confie à la bonne IA ou à la bonne personne."""
    a = discussion.action
    project = discussion.project
    if a is None:
        post(discussion, "maestro", "Cette discussion n'est liée à aucune tâche : je peux orienter les questions vers le bon assistant, "
                                    "mais il n'y a rien à affecter.")
        return
    text = task_text(discussion)
    domain, score = domain_of(text)
    on = enabled_codes(project)
    owner_ai = DOMAIN_OWNER.get(domain)
    label = NOUN.get(domain, domain)
    trace(discussion, "cycle", "Maestro", f"Analyse de la tâche {a.id} : domaine {label}", "maestro")
    if is_ai_work(text) and owner_ai in on and owner_ai != "maestro":
        if owner_ai not in discussion.ai_members:
            discussion.ai_members = list(discussion.ai_members) + [owner_ai]
            discussion.save(update_fields=["ai_members"])
        a.history = list(a.history or []) + [{"at": timezone.now().isoformat(), "text": f"Prise en charge par {mate(owner_ai)['name']} (IA) via Maestro"}]
        a.save(update_fields=["history"])
        post(discussion, "maestro",
             f"J'ai analysé « {a.title} » (domaine : {label}) : c'est un travail de rédaction ou d'analyse que {mate(owner_ai)['name']} ({ROSTER[owner_ai]['role']}) "
             f"sait préparer. Je le lui confie ; {a.owner.display_name if a.owner_id else 'le chef de projet'} relira et validera.")
        trace(discussion, "execution", "Maestro", f"Tâche {a.id} confiée à {mate(owner_ai)['name']} (IA)", "maestro")
        contribute(discussion, owner_ai)
        return
    person, why = best_person(project, domain)
    if person is None:
        post(discussion, "maestro", "Je ne trouve personne d'interne dans l'équipe du projet pour cette tâche. Ajoutez des ressources au projet.")
        return
    if a.owner_id == person.pk:
        post(discussion, "maestro", f"J'ai analysé « {a.title} » ({label}). {person.display_name} en est déjà responsable : "
                                    f"c'est le bon choix ({why}).")
        return
    if a.owner_id and a.owner.is_active and not force:
        post(discussion, "maestro", f"J'ai analysé « {a.title} » : domaine {label}. Elle est déjà confiée à {a.owner.display_name}. "
                                    f"Le profil le plus adapté serait {person.display_name} ({why}). "
                                    "Écrivez « réaffecte » si vous voulez que je la lui transfère.")
        trace(discussion, "proposition", "Maestro", f"Réaffectation de {a.id} à {person.display_name} suggérée", "maestro")
        return
    circuit = team_conf(project)["circuits"].get("affectation", "pm")
    direct = circuit in ("auto", "ai") or can_validate(by, project, circuit)
    if direct:
        old = a.owner
        a.owner = person
        a.history = list(a.history or []) + [{"at": timezone.now().isoformat(),
                                               "text": f"Affectée à {person.display_name} par Maestro (demandé par {by.display_name})"}]
        a.save(update_fields=["owner", "history"])
        notify("action_assigned", [person], f"Action affectée : {a.title}",
               f"Maestro vous a affecté l'action {a.id} ({label}) depuis la discussion « {discussion.title} ».")
        audit.record(by, f"Tâche {a.id}", "Responsable changé (Maestro, discussion)", old.display_name if old else "",
                     person.display_name, tenant=project.tenant)
        post(discussion, "maestro", f"J'ai analysé « {a.title} » : domaine {label}. Je l'affecte à {person.display_name} ({why})"
                                    + (f", à la place de {old.display_name}" if old else "") + ". Il est prévenu.")
        trace(discussion, "execution", "Maestro", f"Tâche {a.id} affectée à {person.display_name}", "maestro")
        if not discussion.participants.filter(user=person).exists():
            from .models import DiscussionParticipant
            DiscussionParticipant.objects.get_or_create(tenant=discussion.tenant, discussion=discussion, user=person)
    else:
        validators = validator_users(project, circuit)
        notify("action_assigned", validators, f"Affectation proposée : {a.title}",
               f"Maestro propose d'affecter l'action {a.id} à {person.display_name} ({why}). Discussion « {discussion.title} ».")
        post(discussion, "maestro", f"J'ai analysé « {a.title} » : domaine {label}. Je propose {person.display_name} ({why}). "
                                    f"L'affectation demande la validation de {', '.join(u.display_name for u in validators) or 'chef de projet'} : je l'ai prévenu.")
        trace(discussion, "proposition", "Maestro", f"Affectation de {a.id} à {person.display_name} proposée", "maestro")


# --------------------------------------------------------------------------- contributions des assistants (moteur local)
def contribute(discussion, code, question=""):
    a = discussion.action
    title = a.title if a else discussion.title
    if llm(discussion, code, question or f"Prends en charge la tâche « {title} » : produis un premier livrable utile et dis ce qu'il faut valider."):
        return
    if code == "nova":
        vague = [w for w in VAGUE_TERMS if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", (title + " " + question).casefold())]
        body = (f"Je prends « {title} ». Premier jet :\n"
                f"• Objectif métier : ce que l'utilisateur doit pouvoir faire et pourquoi.\n"
                f"• Règles de gestion : RG-01 … (conditions, calculs, délais) — à compléter avec vous.\n"
                f"• Critères d'acceptation : « Étant donné … quand … alors … » pour le cas nominal et les erreurs.\n"
                f"• Hors périmètre : à confirmer.\n"
                + (f"Attention : « {vague[0]} » n'est pas mesurable, proposez une valeur cible.\n" if vague else "")
                + "Dites-moi le cas d'usage principal et je rédige la règle de gestion correspondante.")
    elif code in ("altair", "orion"):
        low = (title + " " + question).casefold()
        hints = [h for words, h in ARCHI_HINTS if any(w in low for w in words)]
        body = (f"Pour « {title} », points techniques à trancher :\n• Impacts sur l'existant et les interfaces.\n"
                "• Données concernées et sécurité (accès, chiffrement).\n• Stratégie de test et de déploiement.\n"
                + "".join(f"• Recommandation : {h}\n" for h in hints[:3]) + "Quelle contrainte technique est imposée ?")
    elif code == "vega":
        body = (f"Plan de test proposé pour « {title} » :\n• Cas nominal.\n• Valeurs limites et champs obligatoires.\n"
                "• Cas d'erreur et messages affichés.\n• Droits : un profil non autorisé est refusé.\n• Non-régression sur les écrans voisins.\n"
                "Je peux transformer ces cas en cahier de recette dès que les critères d'acceptation sont validés.")
    elif code == "atlas":
        late = a and a.due and a.status != "done" and a.due < timezone.localdate()
        body = (f"Point de pilotage sur « {title} » : responsable {a.owner.display_name if a and a.owner_id else 'non défini'}, "
                f"échéance {a.due.strftime('%d/%m/%Y') if a and a.due else 'non définie'}, statut {a.get_status_display() if a else '—'}."
                + (" Elle est en retard : je propose de replanifier ou de lever le blocage." if late else " Rien de bloquant côté planning."))
    elif code == "mercure":
        rate = None
        if a and a.owner_id:
            acc = ProjectAccess.objects.filter(project=discussion.project, user_id=a.owner_id).first()
            rate = acc.daily_rate if acc else None
        est = a.est if a else None
        cost = f"{float(est) / 8 * float(rate):.0f} €" if est and rate else "à chiffrer (estimation ou TJM manquant)"
        body = f"Impact budgétaire de « {title} » : estimation {est or '—'} h, TJM {rate or '—'} € → coût {cost}."
    elif code == "lyra":
        body = f"Proposition de message au client : « Nous avançons sur {title}. Nous reviendrons vers vous pour valider les points ouverts. » Je l'envoie après votre accord."
    else:
        body = "Je suis là pour orienter : citez un assistant (Nova, Altaïr, Vega…) ou demandez-moi « qui doit faire cette tâche ? »."
    post(discussion, code, body)
    trace(discussion, "reponse", mate(code)["name"], f"Contribution sur « {title[:80]} »", code)


def on_message(discussion, msg, by):
    """Réponse des assistants présents à un message humain."""
    members = [c for c in (discussion.ai_members or []) if c in enabled_codes(discussion.project)]
    if not members or msg.kind != "message" or msg.ai_author:
        return
    low = msg.body.casefold()
    named = [c for c in members if re.search(rf"(?<!\w){re.escape(mate(c)['name'].casefold())}(?!\w)", low)]
    if "maestro" in members and re.search(r"qui (doit|peut|va)|affect|réaffect|reaffect|à qui|a qui|répartis", low):
        triage(discussion, by, force=bool(re.search(r"réaffect|reaffect|transf", low)))
        return
    if named:
        targets = named
    else:
        domain, score = domain_of(msg.body)
        owner = DOMAIN_OWNER.get(domain)
        if owner in members and score:
            targets = [owner]
        elif len(members) == 1:
            targets = members
        elif "maestro" in members:
            post(discussion, "maestro", "Je n'ai pas identifié l'assistant concerné. Citez-le (" + ", ".join(mate(c)["name"] for c in members if c != "maestro")
                                        + ") ou demandez-moi « qui doit faire cette tâche ? ».")
            return
        else:
            return
    for code in targets[:2]:
        if code == "maestro":
            triage(discussion, by)
        else:
            contribute(discussion, code, msg.body)


# --------------------------------------------------------------------------- Claude (facultatif)
def llm(discussion, code, question):
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return False
    r = ROSTER.get(code, {})
    a = discussion.action
    history = [{"qui": (m.author.display_name if m.author_id else m.external_author or "système"), "texte": m.body[:600]}
               for m in discussion.messages.filter(deleted_at__isnull=True).select_related("author").order_by("-id")[:12]][::-1]
    context = {"projet": discussion.project.name, "discussion": discussion.title,
               "tache": {"titre": a.title, "statut": a.get_status_display(), "phase": a.phase, "responsable": a.owner.display_name if a.owner_id else None,
                         "echeance": str(a.due) if a.due else None} if a else None,
               "messages": history, "demande": question}
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": os.environ.get("ASSISTANT_MODEL", "claude-sonnet-4-5"), "max_tokens": 900,
                  "system": (f"Tu es {r.get('name')}, {r.get('role')} dans Project Control Tower. Mission : {r.get('mission')} "
                             "Tu participes à une discussion d'équipe sur une tâche. Réponds en français, comme un collègue expert : "
                             "concret, structuré, sans inventer de données ; propose un livrable ou une décision à valider."),
                  "messages": [{"role": "user", "content": json.dumps(context, ensure_ascii=False)}]},
            timeout=40)
        resp.raise_for_status()
        text = "".join(b.get("text", "") for b in resp.json().get("content", []) if b.get("type") == "text").strip()
    except Exception as exc:
        logger.warning("Discussion IA : Claude indisponible (%s)", type(exc).__name__)
        return False
    if not text:
        return False
    post(discussion, code, text)
    trace(discussion, "reponse", r.get("name", code), "Réponse (Claude)", code)
    return True


# --------------------------------------------------------------------------- ajout / retrait
def add(by, discussion, code):
    on = enabled_codes(discussion.project)
    if not on:
        raise AiError("FORBIDDEN_PERMISSION", "L'entreprise n'a pas de licence Assistants IA (à demander au Pilote).", 403)
    if not can_manage(by, discussion):
        raise AiError("FORBIDDEN_PERMISSION", "Seul le créateur de la discussion peut y ajouter une IA.", 403)
    if code not in ROSTER or code not in on:
        raise AiError("VALIDATION_ERROR", "Cet assistant n'est pas activé sur ce projet (Orchestrateur IA → paramètres).")
    if code in (discussion.ai_members or []):
        raise AiError("CONFLICT", "Cet assistant participe déjà à la discussion.", 409)
    discussion.ai_members = list(discussion.ai_members or []) + [code]
    discussion.save(update_fields=["ai_members"])
    m = mate(code)
    system(discussion, f"{by.display_name} a ajouté {m['name']} ({m['role']}) à la discussion.")
    audit.record(by, f"Projet {discussion.project.code}", "IA ajoutée à une discussion", "", f"{m['name']} · {discussion.title}",
                 tenant=by.tenant)
    trace(discussion, "cycle", by.display_name, f"{m['name']} ajouté à la discussion", code)
    if code == "maestro":
        triage(discussion, by)
    else:
        contribute(discussion, code)


def remove(by, discussion, code):
    if not can_manage(by, discussion):
        raise AiError("FORBIDDEN_PERMISSION", "Seul le créateur de la discussion peut retirer une IA.", 403)
    if code not in (discussion.ai_members or []):
        raise AiError("NOT_FOUND", "Cet assistant ne participe pas à la discussion.", 404)
    discussion.ai_members = [c for c in discussion.ai_members if c != code]
    discussion.save(update_fields=["ai_members"])
    system(discussion, f"{by.display_name} a retiré {mate(code)['name']} de la discussion.")
    trace(discussion, "modification", by.display_name, f"{mate(code)['name']} retiré de la discussion", code)
