"""Moteur de conversation des appels IA.

- Maestro reçoit chaque prise de parole, choisit l'assistant qui répond (nom cité, puis domaine), propose d'inviter
  un assistant absent et trace tout dans le journal d'orchestration du projet.
- Avec ANTHROPIC_API_KEY, l'assistant répond via Claude (JSON : parole, sections mises à jour, carte de choix).
- Sans clé (ou en cas d'erreur), un moteur local mène l'entretien section par section : il écrit les réponses dans
  le document, détecte les formulations non mesurables, propose des choix d'architecture et lit les fichiers déposés.
"""
import json
import logging
import os
import re
import secrets

import requests
from django.utils import timezone

from projects.ai_orchestrator import REQ_RE, ROSTER, TOPICS, log as journal_log

from .templates import (ARCHI_CHOICES, ARCHI_HINTS, CALL_ROLES, DOC_TYPE_LABEL, DOMAIN_LABEL, DOMAIN_OWNER, DOMAINS,
                        TEMPLATES, VAGUE_TERMS)

logger = logging.getLogger(__name__)
PROMPT_VERSION = "call-v1"
ACKS = ["C'est noté.", "Très clair, merci.", "Parfait, je l'écris.", "Entendu.", "Merci, c'est précis."]


# --------------------------------------------------------------------------- utilitaires
def now():
    return timezone.now().isoformat()


def new_id(prefix):
    return f"{prefix}{secrets.token_hex(4)}"


def name_of(code):
    return ROSTER.get(code, {}).get("name", code)


def first_name(user):
    return (user.first_name or user.display_name or "").split(" ")[0]


def init_sections(doc_type):
    tpl = TEMPLATES.get(doc_type)
    if not tpl:
        return []
    return [{"key": k, "title": t, "question": q, "content": "", "status": "empty", "author": "", "updatedAt": None, "history": []}
            for k, t, q in tpl["sections"]]


def section(call, key):
    return next((s for s in call.sections if s["key"] == key), None)


def write_section(call, key, text, author, replace=False):
    s = section(call, key)
    text = (text or "").strip()
    if not s or not text:
        return None
    s["history"] = ([{"at": now(), "content": s["content"], "author": s["author"]}] + s.get("history", []))[:5]
    s["content"] = text if (replace or not s["content"]) else f"{s['content'].rstrip()}\n{text}"
    s["status"] = "draft"
    s["author"] = author
    s["updatedAt"] = now()
    return s


def say(call, speaker, text, kind="speech", name=None):
    turn = {"id": new_id("t"), "at": now(), "speaker": speaker, "name": name or name_of(speaker), "text": text, "kind": kind}
    call.turns.append(turn)
    return turn


def add_card(call, by, ctype, question, options, section_key=None, meta=None, to="user"):
    card = {"id": new_id("c"), "by": by, "type": ctype, "question": question,
            "options": [{"id": f"o{i}", "label": label, "hint": hint, "recommended": rec} for i, (label, hint, rec) in enumerate(options)],
            "section": section_key, "meta": meta or {}, "to": to, "status": "open", "answer": None, "answeredBy": None, "at": now()}
    call.cards.append(card)
    return card


def trace(call, kind, actor, text, assistant=None):
    try:
        journal_log(call.project, kind, actor, f"[Appel {call.id}] {text}", assistant=assistant, detail={"call": call.id})
    except Exception:  # le journal ne doit jamais casser l'appel
        logger.warning("Journal d'orchestration indisponible", exc_info=True)


def sentences(text):
    parts = re.split(r"(?<=[.!?;])\s+|\n+", text or "")
    return [p.strip(" -•\t") for p in parts if len(p.strip()) > 3]


def vague_in(text):
    low = f" {(text or '').casefold()} "
    return [w for w in VAGUE_TERMS if re.search(rf"(?<![\w]){re.escape(w)}(?![\w])", low)]


# --------------------------------------------------------------------------- entretien (curseur de section)
def current(call):
    i = call.state.get("cursor")
    return call.sections[i] if isinstance(i, int) and 0 <= i < len(call.sections) else None


def next_question(call):
    cur = call.state.get("cursor")
    start = cur + 1 if isinstance(cur, int) else 0
    for i in range(start, len(call.sections)):
        s = call.sections[i]
        if s.get("question") and s["status"] == "empty":
            call.state["cursor"] = i
            return s
    for i, s in enumerate(call.sections):  # sections sautées
        if s.get("question") and s["status"] == "empty":
            call.state["cursor"] = i
            return s
    call.state["cursor"] = None
    return None


def ask_next(call, lead, prefix=""):
    s = next_question(call)
    if s is None:
        say(call, lead, f"{prefix} J'ai couvert toutes les sections du document. Voulez-vous le relire, compléter un point, "
                        "ou clôturer l'appel pour le déposer dans le projet ?".strip())
        if not any(c["meta"].get("kind") == "close" and c["status"] == "open" for c in call.cards):
            add_card(call, "maestro", "validation", "Clôturer l'appel et déposer le document ?",
                     [("Clôturer et déposer", "Le document est enregistré en brouillon, versionné, dans le projet", True),
                      ("Continuer l'échange", "", False),
                      ("Arrêter sans document", "L'échange reste consultable ; le document pourra être généré plus tard", False)],
                     meta={"kind": "close"})
        return
    say(call, lead, f"{prefix} {s['question']}".strip())
    if lead in ("altair", "orion") and s["key"] in ARCHI_CHOICES and not any(c["meta"].get("section") == s["key"] for c in call.cards):
        question, options = ARCHI_CHOICES[s["key"]]
        add_card(call, lead, "choice", question, options, s["key"], meta={"kind": "archi", "section": s["key"]})


def summary_text(call):
    filled = [s["title"] for s in call.sections if s["status"] not in ("empty", "skipped")]
    empty = [s["title"] for s in call.sections if s["status"] in ("empty", "skipped") and s.get("question")]
    open_cards = [c for c in call.cards if c["status"] == "open"]
    parts = [f"{len(filled)} section(s) rédigée(s) sur {len(call.sections)}."]
    if empty:
        parts.append("Il reste : " + ", ".join(empty[:4]) + ("…" if len(empty) > 4 else "") + ".")
    if open_cards:
        parts.append(f"{len(open_cards)} choix attendent votre réponse à l'écran.")
    return " ".join(parts)


# --------------------------------------------------------------------------- démarrage
def start(call, user, specs_doc=None):
    call.sections = init_sections(call.doc_type)
    call.state = {"cursor": None, "req": 0, "adr": 0, "prompt": PROMPT_VERSION, "ack": 0}
    lead = call.lead
    label = DOC_TYPE_LABEL.get(call.doc_type, "le document")
    others = [name_of(c) for c in call.assistants if c not in ("maestro", lead)]
    say(call, "maestro", f"Bonjour {first_name(user)}. Je suis Maestro, j'orchestre cet appel. {name_of(lead)} va rédiger "
                         f"{'la ' if label in ('SFD',) else 'le '}{label} avec vous"
                         + (f", avec l'aide de {', '.join(others)}" if others else "")
                         + ". Je trace chaque choix ; vous pouvez parler ou écrire à tout moment.")
    role = ROSTER.get(lead, {}).get("role", "")
    say(call, lead, f"Bonjour {first_name(user)}, je suis {name_of(lead)}, {role[:1].lower() + role[1:]}. "
                    f"Objectif : {call.objective or call.doc_title}. Je pose une question à la fois et j'écris au fur et à mesure.")
    if specs_doc is not None:
        add_card(call, lead, "choice", f"Je pars de l'expression de besoin « {specs_doc.name} » déjà déposée ?",
                 [("Oui, lis-la", "Exigences reprises, formulations floues signalées", True),
                  ("Non, on part de zéro", "", False)], meta={"kind": "use_doc", "docId": specs_doc.id})
    ask_next(call, lead)
    trace(call, "cycle", "Maestro", f"Appel ouvert : {name_of(lead)} rédige « {call.doc_title} » ({', '.join(name_of(c) for c in call.assistants)})", "maestro")


# --------------------------------------------------------------------------- routage par Maestro
def route(call, text):
    low = text.casefold()
    for code in call.assistants:
        if code != "maestro" and re.search(rf"\b{re.escape(name_of(code).casefold())}\b", low):
            return code, None
    if "?" not in text:  # une affirmation répond à la question en cours : elle reste chez l'assistant principal
        return call.lead, None
    scores = {d: sum(1 for k in kws if re.search(rf"(?<!\w){re.escape(k)}", low)) for d, kws in DOMAINS.items()}
    domain, score = max(scores.items(), key=lambda x: x[1])
    if score == 0:
        return call.lead, None
    owner = DOMAIN_OWNER[domain]
    lead_domain = CALL_ROLES.get(call.lead, {}).get("domain")
    if owner == call.lead or lead_domain == domain:
        return call.lead, None
    if owner in call.assistants:
        return owner, domain
    return call.lead, (domain, owner)


def user_turn(call, user, text, enabled):
    text = (text or "").strip()[:2000]
    if not text:
        return
    say(call, "user", text, name=user.display_name)
    low = text.casefold()
    lead = call.lead
    if any(k in low for k in ("récap", "recap", "résume", "resume", "où en est", "ou en est")):
        say(call, "maestro", summary_text(call))
        return
    if re.search(r"\b(suivant|passons|on passe|question suivante|je ne sais pas)\b", low):
        s = current(call)
        if s:
            write_section(call, "questions", f"À compléter : {s['title']}", lead)
            s["status"] = "skipped"
        ask_next(call, lead, "D'accord, on y reviendra.")
        return
    target, extra = route(call, text)
    if isinstance(extra, tuple):  # domaine d'un assistant absent : Maestro propose de l'inviter
        domain, owner = extra
        if not any(c["meta"].get("kind") == "invite" and c["meta"].get("code") == owner and c["status"] == "open" for c in call.cards):
            if owner in enabled:
                add_card(call, "maestro", "invite", f"Ce point touche à {DOMAIN_LABEL[domain]}. J'invite {name_of(owner)} ({ROSTER[owner]['role']}) ?",
                         [(f"Inviter {name_of(owner)}", ROSTER[owner]["mission"], True), ("Continuer sans", "", False)],
                         meta={"kind": "invite", "code": owner, "text": text})
                say(call, "maestro", f"Ce point concerne plutôt {name_of(owner)}. Je vous propose de l'inviter ; en attendant, {name_of(lead)} le note.")
            else:
                say(call, "maestro", f"{name_of(owner)} n'est pas activé sur ce projet (licence ou paramétrage). "
                                     "Je note la question pour le chef de projet.")
            write_section(call, "questions", f"À voir ({DOMAIN_LABEL[domain]}) : {text}", "maestro")
            trace(call, "question", "Maestro", f"Sujet {DOMAIN_LABEL[domain]} : proposition d'inviter {name_of(owner)}", "maestro")
        s = current(call)
        say(call, lead, "Je le note en question ouverte." + (f" Je reprends : {s['question']}" if s else ""))
        return
    elif target != lead:
        trace(call, "cycle", "Maestro", f"Maestro confie la question à {name_of(target)}", "maestro")
    if llm_turn(call, target, user, text):
        return
    if target == lead:
        interview(call, user, text)
    else:
        specialist(call, target, text)
        s = current(call)
        if s:
            say(call, lead, f"Merci {name_of(target)}. Je reprends : {s['question']}")


# --------------------------------------------------------------------------- moteur local
def interview(call, user, text):
    lead = call.lead
    s = current(call) or section(call, "questions")
    if s is None:
        return
    if text.rstrip().endswith("?"):  # question posée à l'assistant (moteur local) : notée, puis on reprend l'entretien
        write_section(call, "questions", f"Question de {user.display_name} : {text}", lead)
        say(call, lead, "Bonne question. Je la note dans les questions ouvertes pour la trancher avec la bonne personne."
                        + (f" Je reprends : {s['question']}" if s.get("question") else ""))
        return
    if s["key"] == "exigences":
        for sent in sentences(text):
            call.state["req"] = call.state.get("req", 0) + 1
            write_section(call, "exigences", f"EF-{call.state['req']:02d} : {sent}", lead)
    else:
        write_section(call, s["key"], text, lead)
    trace(call, "reponse", user.display_name, f"Réponse écrite dans « {s['title']} »", lead)
    if lead in ("altair", "orion"):
        hints_from(call, text, lead)
    vague = vague_in(text)
    prefix = ACKS[call.state.get("ack", 0) % len(ACKS)]
    call.state["ack"] = call.state.get("ack", 0) + 1
    vague = [w for w in vague if not any(c["meta"].get("word") == w and c["status"] == "open" for c in call.cards)]
    if vague:
        w = vague[0]
        suggestions = VAGUE_TERMS.get(w) or []
        add_card(call, lead, "choice", f"« {w} » n'est pas mesurable en recette. Quelle formulation retenez-vous ?",
                 [(x, "", i == 0) for i, x in enumerate(suggestions)] + [("Je précise moi-même", "Dites-le ou écrivez-le", False)],
                 s["key"], meta={"kind": "vague", "word": w, "section": s["key"]})
        prefix = f"{prefix} Un point d'attention : « {w} » ne se vérifie pas en recette, je vous propose des formulations à l'écran."
    ask_next(call, lead, prefix)


def hints_from(call, text, author):
    low = (text or "").casefold()
    added = []
    existing = (section(call, "recommandations") or {}).get("content", "")
    for words, hint in ARCHI_HINTS:
        if any(w in low for w in words) and hint not in existing and hint not in added:
            added.append(hint)
    for h in added:
        write_section(call, "recommandations", f"• {h}", author)
    return added


def specialist(call, code, text):
    low = text.casefold()
    if code in ("altair", "orion"):
        added = hints_from(call, text, code)
        if section(call, "recommandations") is None:
            write_section(call, "questions", f"[{name_of(code)}] Point technique à instruire : {text}", code)
        say(call, code, ("Recommandation : " + added[0]) if added else
            "Je note ce point technique ; il faudra le trancher dans le dossier d'architecture.")
    elif code == "mercure":
        write_section(call, "questions", f"[Mercure] Impact budgétaire à chiffrer : {text}", code)
        say(call, code, "Je note l'impact budgétaire. Je le chiffrerai avec le chef de projet après l'appel, à partir du TJM de l'équipe.")
    elif code == "vega":
        target = "acceptation" if section(call, "acceptation") else "questions"
        write_section(call, target, f"[Vega] {text}", code)
        say(call, code, "Pour la recette, chaque exigence doit avoir un critère vérifiable. Je l'ajoute aux critères d'acceptation.")
    elif code == "atlas":
        write_section(call, "questions", f"[Atlas] Contrainte de planning : {text}", code)
        say(call, code, "Je note la contrainte de délai ; je l'intégrerai au planning et je vous alerterai si un jalon est menacé.")
    elif code == "lyra":
        write_section(call, "questions", f"[Lyra] À valider avec le client : {text}", code)
        say(call, code, "Je prépare ce point pour le client ; il sera dans la synthèse que je lui enverrai.")
    else:
        interview_target = section(call, "questions")
        if interview_target:
            write_section(call, "questions", f"[{name_of(code)}] {text}", code)
        say(call, code, "C'est noté, je l'intègre.")
    trace(call, "reponse", name_of(code), f"{name_of(code)} répond : {text[:120]}", code)


def apply_document(call, doc, by_name):
    lead = call.lead
    text = doc.extracted_text or ""
    call.files.append({"id": doc.id, "name": doc.name, "words": len(text.split()), "at": now()})
    say(call, "user", f"📎 {doc.name}", kind="file", name=by_name)
    if not text.strip():
        say(call, lead, f"Je n'ai pas pu lire de texte dans « {doc.name} ». S'il s'agit d'un scan, relancez la lecture OCR.")
        return
    found = []
    for m in REQ_RE.finditer(text):
        sent = " ".join(m.group(0).split())
        if 20 <= len(sent) <= 300 and sent not in found:
            found.append(sent)
    if call.doc_type == "sfd":
        if section(call, "contexte") and section(call, "contexte")["status"] == "empty":
            write_section(call, "contexte", f"Repris de « {doc.name} » : {' '.join(text.split())[:400]}", lead)
        for sent in found[:30]:
            call.state["req"] = call.state.get("req", 0) + 1
            write_section(call, "exigences", f"EF-{call.state['req']:02d} : {sent}", lead)
        vague_cards = 0
        for sent in found:
            v = vague_in(sent)
            v = [w for w in v if not any(c["meta"].get("word") == w and c["status"] == "open" for c in call.cards)]
            if v and vague_cards < 3:
                vague_cards += 1
                add_card(call, lead, "choice", f"« {sent[:160]} » : que signifie concrètement « {v[0]} » ?",
                         [(x, "", i == 0) for i, x in enumerate(VAGUE_TERMS.get(v[0]) or [])] + [("Je précise moi-même", "", False)],
                         "exigences", meta={"kind": "vague", "word": v[0], "section": "exigences"})
        low = text.casefold()
        missing = [label for _, (kw, label) in TOPICS.items() if not any(k in low for k in kw)]
        for label in missing:
            write_section(call, "questions", f"Non couvert par « {doc.name} » : {label}", lead)
        say(call, lead, f"J'ai lu « {doc.name} » : {len(found)} exigence(s) reprise(s) dans la section Exigences, "
                        f"{vague_cards} formulation(s) à préciser à l'écran, et {len(missing)} sujet(s) non couvert(s) notés en questions ouvertes.")
    else:
        added = hints_from(call, text, lead) if section(call, "recommandations") else []
        if section(call, "contexte") and section(call, "contexte")["status"] == "empty":
            write_section(call, "contexte", f"Repris de « {doc.name} » : {' '.join(text.split())[:400]}", lead)
        say(call, lead, f"J'ai lu « {doc.name} » ({len(text.split())} mots). "
                        + (f"J'en tire {len(added)} recommandation(s) technique(s). " if added else "")
                        + (f"J'y repère {len(found)} exigence(s) qui cadrent l'architecture." if found else ""))
    trace(call, "execution", name_of(lead), f"Document lu en appel : {doc.name} ({len(found)} exigence(s))", lead)


def answer_card(call, user, card, option_id, free_text, enabled):
    """Applique la réponse à une carte. Renvoie "close" si l'utilisateur demande la clôture."""
    opt = next((o for o in card["options"] if o["id"] == option_id), None)
    label = (free_text or "").strip() or (opt["label"] if opt else "")
    card.update(status="answered", answer=label, answeredBy=user.display_name, answeredAt=now())
    kind = card["meta"].get("kind")
    lead = call.lead
    trace(call, "validation", user.display_name, f"« {card['question'][:140]} » → {label}", card["by"])
    if kind == "close":
        if option_id == "o0":
            return "close"
        if option_id == "o2":
            return "stop"
        say(call, "maestro", "Très bien, on continue.")
        return None
    if kind == "vague":
        if opt and opt["label"] == "Je précise moi-même" and not free_text:
            say(call, lead, f"D'accord. Dites-moi ce que « {card['meta']['word']} » veut dire pour vous, en chiffres si possible.")
            call.state["cursor"] = next((i for i, s in enumerate(call.sections) if s["key"] == card["meta"]["section"]), call.state.get("cursor"))
            return None
        write_section(call, card["meta"]["section"], f"Critère mesurable (« {card['meta']['word']} ») : {label}", lead)
        say(call, lead, f"Merci. « {card['meta']['word']} » devient : {label}.")
    elif kind == "use_doc":
        if option_id == "o0":
            from projects.models import Document
            doc = Document.objects.filter(project=call.project, pk=card["meta"].get("docId")).first()
            if doc:
                apply_document(call, doc, user.display_name)
        else:
            say(call, lead, "Très bien, on part de zéro.")
    elif kind == "archi":
        call.state["adr"] = call.state.get("adr", 0) + 1
        hint = opt["hint"] if opt else ""
        write_section(call, card["meta"]["section"], f"Option retenue : {label}." + (f" {hint}." if hint else ""), card["by"])
        write_section(call, "decisions", f"ADR-{call.state['adr']:02d} : {card['question']} → {label}"
                                         + (f" (motif : {hint})" if hint else "") + f". Validé par {user.display_name}.", card["by"])
        say(call, card["by"], f"Décision notée : {label}. Je l'inscris en ADR-{call.state['adr']:02d}.")
    elif kind == "invite":
        code = card["meta"].get("code")
        if option_id == "o0" and code in enabled and code not in call.assistants:
            call.assistants = call.assistants + [code]
            say(call, "maestro", f"J'invite {name_of(code)}.")
            say(call, code, f"Bonjour, je suis {name_of(code)}, {ROSTER[code]['role'][:1].lower() + ROSTER[code]['role'][1:]}. Je prends votre question.")
            trace(call, "cycle", "Maestro", f"{name_of(code)} rejoint l'appel", "maestro")
            if not llm_turn(call, code, user, card["meta"].get("text", "")):
                specialist(call, code, card["meta"].get("text", ""))
        else:
            say(call, "maestro", "D'accord, on continue sans.")
    elif kind == "llm":
        if not llm_turn(call, card["by"], user, f"Mon choix pour « {card['question']} » : {label}"):
            write_section(call, card.get("section") or "questions", f"{card['question']} → {label}", card["by"])
            say(call, card["by"], f"C'est noté : {label}.")
    return None


# --------------------------------------------------------------------------- Claude (facultatif)
def llm_turn(call, code, user, text):
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key or not text:
        return False
    info = ROSTER.get(code, {})
    keys = [s["key"] for s in call.sections]
    system = (
        f"Tu es {info.get('name', code)}, {info.get('role', '')} de Project Control Tower. Mission : {info.get('mission', '')}\n"
        f"Tu participes à un appel vocal en français avec {user.display_name} sur le projet {call.project.name}. "
        f"Le document en cours est « {call.doc_title} ». Parle comme un collègue expert : 2 à 4 phrases courtes, à l'oral, "
        "une seule question à la fois, reformule avant d'écrire, ne prends aucune décision structurante sans proposer un choix. "
        "N'invente aucune donnée du projet ; signale ton incertitude. Écris le détail dans le document, pas à l'oral.\n"
        "Réponds UNIQUEMENT par un objet JSON : {\"speech\": texte oral, \"updates\": [{\"key\": clé de section, \"content\": "
        "contenu COMPLET de la section en texte}], \"card\": null ou {\"question\": texte, \"options\": [{\"label\": texte, "
        "\"hint\": texte, \"recommended\": booléen}]}, \"next\": clé de la prochaine section à traiter ou null}. "
        f"Clés de section autorisées : {', '.join(keys) or 'aucune'}."
    )
    payload = {
        "sections": [{"key": s["key"], "titre": s["title"], "contenu": s["content"][:3000]} for s in call.sections],
        "fichiers_lus": [f["name"] for f in call.files],
        "derniers_echanges": [{"qui": t["name"], "texte": t["text"][:600]} for t in call.turns[-14:]],
        "message": text,
    }
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": os.environ.get("ASSISTANT_MODEL", "claude-sonnet-4-5"), "max_tokens": 1800, "system": system,
                  "messages": [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]},
            timeout=45)
        r.raise_for_status()
        raw = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
        data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except Exception as exc:  # réseau, clé, JSON invalide : repli sur le moteur local
        logger.warning("Appel IA : Claude indisponible (%s), moteur local utilisé", type(exc).__name__)
        return False
    for u in data.get("updates") or []:
        if isinstance(u, dict) and u.get("key") in keys:
            write_section(call, u["key"], str(u.get("content", ""))[:20000], code, replace=True)
    card = data.get("card")
    if isinstance(card, dict) and card.get("question") and isinstance(card.get("options"), list):
        add_card(call, code, "choice", str(card["question"])[:300],
                 [(str(o.get("label", ""))[:120], str(o.get("hint", ""))[:200], bool(o.get("recommended"))) for o in card["options"][:4]
                  if isinstance(o, dict) and o.get("label")], meta={"kind": "llm"})
    if data.get("next") in keys:
        call.state["cursor"] = keys.index(data["next"])
    say(call, code, str(data.get("speech") or "C'est noté.")[:1500])
    call.state["llm"] = call.state.get("llm", 0) + 1
    trace(call, "reponse", name_of(code), f"{name_of(code)} (Claude) a répondu et mis à jour {len(data.get('updates') or [])} section(s)", code)
    return True
