"""Comptes rendus de réunion : dépôt par tous les profils, lecture (texte / OCR), extraction et validation.

1. Dépôt : n'importe quel membre du projet dépose son CR (Word, PDF, PowerPoint, texte, image scannée → OCR navigateur).
2. Analyse (à la demande) : participants, ordre du jour, décisions, actions (responsable, échéance, statut),
   risques et prochaine réunion sont repérés dans le texte (outils gratuits, sans service externe).
3. Validation : l'utilisateur corrige ce qui a été lu puis valide → réunion enregistrée, actions créées ou mises à jour.
   Un profil qui ne peut pas créer d'actions envoie ses propositions au chef de projet (validation humaine).
"""
import difflib
import io
import re
import secrets
import unicodedata
import zipfile
from datetime import date, timedelta
from xml.etree import ElementTree

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.errors import ApiError
from configuration import audit
from configuration.models import Notification

from .models import Action, Document, Meeting
from .workspace import _next_action_id, _project, _rights

MAX_ITEMS = 80


# --------------------------------------------------------------------------- texte structuré (lignes)
def _norm(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s.replace("’", "'")).strip()


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _docx_lines(data):
    root = ElementTree.fromstring(data)
    body = root.find(f"{W}body")
    out = []

    def para(p):
        txt = "".join((t.text or "") if t.tag == f"{W}t" else ("\t" if t.tag == f"{W}tab" else "") for t in p.iter()
                      if t.tag in (f"{W}t", f"{W}tab")).strip()
        if txt and p.find(f"{W}pPr/{W}numPr") is not None:
            txt = f"- {txt}"
        return txt

    for el in (body if body is not None else []):
        if el.tag == f"{W}p":
            t = para(el)
            if t:
                out.append(t)
        elif el.tag == f"{W}tbl":
            for tr in el.iter(f"{W}tr"):
                cells = [" ".join(para(p) for p in tc.iter(f"{W}p")).strip(" -") for tc in tr.findall(f"{W}tc")]
                if any(cells):
                    out.append(" | ".join(cells))
            out.append("")
    return out


def lines_of(doc):
    """Lignes du document : paragraphes, puces et lignes de tableau (« a | b | c ») pour Word / PowerPoint / ODT."""
    content = bytes(doc.content) if doc.content is not None else b""
    ext = (doc.ext or "").lower()
    try:
        if ext in ("docx", "pptx", "odt") and content:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                if ext == "docx":
                    return _docx_lines(z.read("word/document.xml"))
                if ext == "pptx":
                    out = []
                    for n in sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                                    key=lambda n: int(re.findall(r"\d+", n)[-1])):
                        for p in ElementTree.fromstring(z.read(n)).iter(f"{A}p"):
                            t = "".join(x.text or "" for x in p.iter(f"{A}t")).strip()
                            if t:
                                out.append(t)
                    return out
                root = ElementTree.fromstring(z.read("content.xml"))
                out = []
                for el in root.iter():
                    if el.tag.endswith("}p") or el.tag.endswith("}h"):
                        t = "".join(el.itertext()).strip()
                        if t:
                            out.append(t)
                return out
    except Exception:  # fichier illisible : on se rabat sur le texte extrait au dépôt
        pass
    return [ln.rstrip() for ln in (doc.extracted_text or "").splitlines()]


# --------------------------------------------------------------------------- dates
MONTHS = {"janvier": 1, "janv": 1, "fevrier": 2, "fevr": 2, "fev": 2, "mars": 3, "avril": 4, "avr": 4, "mai": 5, "juin": 6,
          "juillet": 7, "juil": 7, "aout": 8, "septembre": 9, "sept": 9, "octobre": 10, "oct": 10, "novembre": 11, "nov": 11,
          "decembre": 12, "dec": 12, "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
          "august": 8, "september": 9, "october": 10, "november": 11, "december": 12}
DATE_RE = re.compile(
    r"(?P<iso>\b(20\d\d)-(\d{1,2})-(\d{1,2})\b)"
    r"|(?P<num>\b(\d{1,2})[/.\-](\d{1,2})(?:[/.\-](\d{2,4}))?\b)"
    r"|(?P<txt>\b(\d{1,2})(?:er)?\s+(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?(?:\s+(20\d\d))?\b)"
    r"|(?P<week>\b(?:s|sem\.?|semaine)\s?(\d{1,2})\b)"
    r"|(?P<rel>fin de semaine|fin de la semaine|semaine prochaine|demain|fin du mois|fin de mois)", re.I)
DUE_HINT = re.compile(r"(pour le|pour|avant le|avant|d'ici le|d'ici|echeance|deadline|date limite|au plus tard|delai|le)\s*:?\s*$")


def _mk(y, m, d):
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _year_fix(d, ref):
    # Sans année : on prend celle de la réunion ; une date très antérieure appartient à l'année suivante.
    if d and ref and d < ref - timedelta(days=60):
        return _mk(d.year + 1, d.month, d.day)
    return d


def dates_in(text, ref):
    """[(position, date)] des dates trouvées dans un texte (ref = date de la réunion pour les dates relatives)."""
    ref = ref or timezone.localdate()
    out = []
    n = _norm(text)
    for m in DATE_RE.finditer(n):
        d = None
        if m.group("iso"):
            d = _mk(int(m.group(2)), int(m.group(3)), int(m.group(4)))
        elif m.group("num"):
            dd, mm, yy = int(m.group(6)), int(m.group(7)), m.group(8)
            if not (1 <= mm <= 12 and 1 <= dd <= 31):
                continue
            if yy:
                y = int(yy) + (2000 if len(yy) == 2 else 0)
                d = _mk(y, mm, dd)
            else:
                d = _year_fix(_mk(ref.year, mm, dd), ref)
        elif m.group("txt"):
            dd, mon, yy = int(m.group(10)), MONTHS[m.group(11).lower()], m.group(12)
            d = _mk(int(yy), mon, dd) if yy else _year_fix(_mk(ref.year, mon, dd), ref)
        elif m.group("week"):
            wk = int(m.group(14))
            if 1 <= wk <= 53:
                try:
                    d = date.fromisocalendar(ref.year, wk, 5)
                    d = date.fromisocalendar(ref.year + 1, wk, 5) if d < ref - timedelta(days=60) else d
                except ValueError:
                    d = None
        elif m.group("rel"):
            r = m.group("rel")
            if r == "demain":
                d = ref + timedelta(days=1)
            elif "prochaine" in r:
                d = ref + timedelta(days=7 - ref.weekday() + 4)
            elif "mois" in r:
                d = (date(ref.year + (ref.month == 12), ref.month % 12 + 1, 1) - timedelta(days=1))
            else:
                d = ref + timedelta(days=max(0, 4 - ref.weekday()))
        if d and 2000 < d.year < 2100:
            out.append((m.start(), m.end(), d, n[max(0, m.start() - 22):m.start()]))
    return out


# --------------------------------------------------------------------------- personnes
class People:
    """Rapprochement des noms lus dans le CR avec les utilisateurs (membres du projet en priorité)."""

    def __init__(self, project):
        from .project_alerts import members_of
        User = get_user_model()
        members = members_of(project)
        ids = {u.pk for u in members}
        others = [u for u in User.objects.filter(tenant=project.tenant, is_active=True).exclude(pk__in=ids)]
        self.members = members
        self.users = members + others
        self.member_ids = ids
        self.alias = {}
        firsts = {}
        for u in self.users:
            full = _norm(u.display_name)
            parts = [p for p in re.split(r"[\s\-]+", full) if p]
            for a in {full, " ".join(reversed(parts)), _norm(u.username), _norm(u.email.split("@")[0]) if u.email else ""}:
                if a and len(a) >= 3:
                    self.alias.setdefault(a, u)
            if parts:
                firsts.setdefault(parts[0], []).append(u)
                if len(parts) > 1:
                    firsts.setdefault(parts[-1], []).append(u)
                    ini = "".join(p[0] for p in parts)
                    firsts.setdefault(f"#{ini}", []).append(u)
                    firsts.setdefault(f"#{parts[0][0]}{parts[-1][:2]}", []).append(u)  # trigramme « JDU »
        # Prénom (ou nom) seul : accepté s'il désigne un seul utilisateur, en privilégiant les membres du projet.
        for k, us in firsts.items():
            mem = [u for u in us if u.pk in ids]
            pick = mem if len(mem) == 1 else (us if len(us) == 1 else [])
            if pick and len(k.lstrip("#")) >= 2:
                self.alias.setdefault(k, pick[0])

    def match(self, raw):
        """Utilisateur correspondant à un nom écrit (« J. Dupont », « Jean », « JDU », « jean.dupont@… »)."""
        r = _norm(raw).strip(" .:-()@")
        if not r:
            return None
        r = re.sub(r"\(.*?\)", "", r).strip()
        if r in self.alias:
            return self.alias[r]
        if re.fullmatch(r"[a-z]{2,3}", r) and f"#{r}" in self.alias and raw.strip(" ()@").isupper():
            return self.alias[f"#{r}"]
        m = re.fullmatch(r"([a-z])\.?\s+([a-z\-]{2,})", r)  # « J. Dupont »
        if m:
            c = [u for u in self.users if _norm(u.display_name).endswith(m.group(2)) and _norm(u.display_name).startswith(m.group(1))]
            if len(c) == 1:
                return c[0]
        best, score = None, 0.0
        for a, u in self.alias.items():
            if a.startswith("#") or len(a) < 5:
                continue
            s = difflib.SequenceMatcher(None, r, a).ratio()
            if s > score:
                best, score = u, s
        return best if score >= 0.86 else None

    def find_in(self, text):
        """Premier utilisateur cité dans une phrase (nom complet, puis prénom unique)."""
        n = f" {_norm(text)} "
        hits = []
        for a, u in self.alias.items():
            if a.startswith("#") or len(a) < 3:
                continue
            i = n.find(f" {a} ")
            if i >= 0:
                hits.append((-len(a), i, u))
        return sorted(hits, key=lambda h: (h[0], h[1]))[0][2] if hits else None


# --------------------------------------------------------------------------- analyse du CR
SECTIONS = {
    "participants": ["participants", "presents", "personnes presentes", "presence", "invites", "attendees", "assistance",
                     "destinataires", "liste de diffusion", "etaient presents"],
    "absents": ["absents", "excuses", "absent"],
    "agenda": ["ordre du jour", "agenda", "sujets abordes", "points abordes", "points a l'ordre du jour"],
    "decisions": ["decisions", "releve de decisions", "decisions prises", "arbitrages", "validations", "decision"],
    "actions": ["actions", "action", "plan d'actions", "plan d'action", "actions a mener", "a faire", "todo", "to do", "next steps",
                "prochaines etapes", "suite a donner", "suites a donner", "taches", "actions a suivre", "suivi des actions",
                "liste des actions"],
    "risks": ["risques", "points de vigilance", "alertes", "points bloquants", "blocages", "difficultes", "risques et alertes"],
    "next": ["prochaine reunion", "prochain point", "prochain comite", "prochaine seance", "prochain copil"],
    "notes": ["compte rendu", "discussion", "echanges", "synthese", "contexte", "notes", "points divers", "divers",
              "deroulement", "resume"],
}
INLINE = [("actions", re.compile(r"^\s*(?:\[?actions?\]?|todo|to do|[àa] faire|☐|\[ \])\s*[:\-–]\s*", re.I)),
          ("decisions", re.compile(r"^\s*(?:\[?d[ée]cisions?\]?|d[ée]cid[ée]|valid[ée]|accord)\s*[:\-–]\s*", re.I)),
          ("risks", re.compile(r"^\s*(?:\[?risques?\]?|alerte|vigilance|point bloquant)\s*[:\-–]\s*", re.I))]
BULLET = re.compile(r"^\s*(?:[-*•▪◦·●○➢➤→>]|\d{1,2}[.)]|[a-z][.)])\s+", re.I)
OWNER_LABEL = re.compile(r"(?:responsable|resp\.?|porteur|pilote|qui|owner|assigne a|attribue a|acteur|par)\s*[:=]\s*"
                         r"([^,;|()\n]+?)(?=\s*(?:[,;|()]|echeance|pour le|avant|d'ici|statut|$))", re.I)
STATUS_WORDS = [("done", r"\b(fait|termine|terminee|realise|realisee|clos|close|cloture|done|ok)\b"),
                ("blocked", r"\b(bloque|bloquee|blocked)\b"), ("doing", r"\b(en cours|in progress|demarre)\b")]
TYPE_WORDS = [("Comité de pilotage", ["copil", "comite de pilotage"]), ("Comité technique", ["cotech", "comite technique"]),
              ("Lancement", ["kick-off", "kick off", "kickoff", "lancement"]), ("Point hebdomadaire", ["hebdo", "point hebdomadaire"]),
              ("Atelier", ["atelier", "workshop"]), ("Recette", ["recette"]), ("Daily", ["daily", "stand-up", "standup"]),
              ("Revue de sprint", ["revue de sprint", "sprint review"]), ("Rétrospective", ["retrospective", "retro"])]
COL = {"title": ["action", "actions", "libelle", "description", "sujet", "tache", "quoi", "objet", "intitule"],
       "owner": ["responsable", "resp", "resp.", "porteur", "qui", "owner", "acteur", "pilote", "assigne"],
       "due": ["echeance", "date", "delai", "pour le", "deadline", "date limite", "quand", "date cible"],
       "status": ["statut", "etat", "status", "avancement"]}


def _heading(line):
    """(section, reste) si la ligne est un titre de section (« Décisions : … », « 3. Plan d'actions »)."""
    raw = re.sub(r"^[#\s]*(?:[ivx]+|\d{1,2}(?:\.\d+)*)?[.)\-–]?\s*", "", line.strip(), flags=re.I)
    head, _, rest = raw.partition(":")
    n = _norm(head).strip(" .-–*_")
    if not n or len(n) > 45:
        return None
    for sec, words in SECTIONS.items():
        if n in words or any(n.startswith(w + " ") and len(n) <= len(w) + 18 for w in words):
            if not rest.strip() and not raw.rstrip().endswith(":") and len(n.split()) > 4:
                return None
            return sec, rest.strip()
    return None


def _strip_prefix(text):
    for _, rx in INLINE:
        m = rx.match(text)
        if m:
            return text[m.end():]
    return text


def _clean(text):
    t = _strip_prefix(BULLET.sub("", text).strip())
    return re.sub(r"\s{2,}", " ", t).strip(" -–—:;|,.")


def _status_of(text):
    n = _norm(text)
    for code, rx in STATUS_WORDS:
        if re.search(rx, n):
            return code
    return None


class Reader:
    def __init__(self, project, doc):
        self.project, self.doc = project, doc
        self.people = People(project)
        self.lines = [ln for ln in lines_of(doc)]
        self.ref = None

    # --- en-tête
    def meeting(self):
        head = [ln for ln in self.lines[:25] if ln.strip()]
        when = None
        for ln in head:
            if re.search(r"\b(date|le|reunion du|du)\b", _norm(ln)) or len(ln) < 80:
                ds = dates_in(ln, timezone.localdate())
                if ds:
                    when = ds[0][2]
                    break
        self.ref = when or self.doc.uploaded_at or timezone.localdate()
        title = re.sub(r"\.(docx?|pdf|pptx?|odt|txt|png|jpe?g)$", "", self.doc.name, flags=re.I)
        for ln in head[:6]:
            if re.search(r"compte[ -]rendu|\bcr\b|reunion|comite|copil|cotech|atelier|point", _norm(ln)) and len(ln) <= 140:
                title = re.sub(r"\s+", " ", ln.strip(" #*_"))
                break
        n = _norm(" ".join(head) + " " + self.doc.name)
        kind = next((label for label, words in TYPE_WORDS if any(w in n for w in words)), "Réunion")
        return {"title": title[:300], "date": when.isoformat() if when else (self.doc.uploaded_at.isoformat() if self.doc.uploaded_at else None),
                "type": kind}

    # --- corps
    def parse(self):
        meta = self.meeting()
        sec = None
        out = {k: [] for k in ("participants", "absents", "agenda", "decisions", "actions", "risks", "next", "notes")}
        table_cols = None  # colonnes du tableau d'actions en cours
        for raw in self.lines:
            line = raw.strip()
            if not line:
                table_cols = None
                continue
            if " | " in line:  # ligne de tableau
                cells = [c.strip() for c in line.split(" | ")]
                cols = self._header(cells)
                if cols:
                    table_cols = cols
                    if "title" in cols and ("owner" in cols or "due" in cols):
                        sec = "actions"
                    continue
                if table_cols and sec == "actions":
                    self._table_action(cells, table_cols, out, raw)
                    continue
                h = _heading(cells[0])
                if h and len(cells) >= 2 and not any(_heading(c) for c in cells[1:]):
                    out[h[0]].append(" ".join(cells[1:]))
                    continue
                line = " — ".join(c for c in cells if c)
            h = _heading(line)
            if h:
                sec, rest = h
                if rest:
                    out[sec].append(rest)
                continue
            n = _norm(line)
            inline = next((s for s, rx in INLINE if rx.match(line)), None)
            if inline:
                out[inline].append(line)
                continue
            if re.match(r"^(date|lieu|heure|redige par|redacteur|diffusion|objet|projet|client|version)\s*:", n):
                continue
            out[sec or "notes"].append(line)
        return meta, out

    def _header(self, cells):
        cols = {}
        for i, c in enumerate(cells):
            n = _norm(c).strip(" .:")
            for k, words in COL.items():
                if k not in cols and (n in words or any(n.startswith(w + " ") for w in words)):
                    cols[k] = i
                    break
        known = sum(1 for c in cells if any(_norm(c).strip(" .:") in w for w in COL.values()))
        return cols if len(cols) >= 2 and known >= len([c for c in cells if c]) / 2 else None

    def _table_action(self, cells, cols, out, raw):
        def cell(k):
            i = cols.get(k)
            return cells[i] if i is not None and i < len(cells) else ""
        title = cell("title") or next((c for i, c in enumerate(cells) if i not in cols.values() and len(c) > 6), "")
        if title:
            out["actions"].append({"title": title, "owner": cell("owner"), "due": cell("due"), "status": cell("status"), "raw": raw})

    # --- actions
    def action(self, item):
        if isinstance(item, dict):
            raw = item["raw"]
            title = _clean(item["title"])
            owner_raw = item["owner"]
            u = None
            for part in re.split(r"[,/;&]| et ", owner_raw or ""):
                u = self.people.match(part)
                if u:
                    break
            ds = dates_in(item["due"] or "", self.ref)
            due = ds[0][2] if ds else None
            st = _status_of(item.get("status") or "")
            return self._row(title, u, owner_raw if not u else "", due, st, raw)
        raw = item
        text = _strip_prefix(BULLET.sub("", item).strip())
        owner_raw, u = "", None
        m = OWNER_LABEL.search(_norm(text))
        if m:
            owner_raw = m.group(1).strip()
            u = self.people.match(owner_raw)
        if not u:
            cands = [m.group(1) for m in re.finditer(r"@([\w.\-]+)", text)]
            cands += [m.group(1) for m in re.finditer(r"\(([^()]{2,40})\)", text)]
            cands += [s for s in re.split(r"\s+[–—-]\s+", text)[1:]]
            cands += [m.group(1) for m in re.finditer(r"^([A-Z][\w\-]+(?:\s[A-Z][\w\-]+)?)\s*[:–—]", text)]
            for c in cands:
                cand = self.people.match(c)
                if cand:
                    u, owner_raw = cand, ""
                    break
            if not u and not owner_raw:
                at = re.search(r"@([\w.\-]+)", text) or re.search(r"\(([A-ZÉ][\w\-]+(?:\s[A-ZÉ][\w\-]+)?)\)", text)
                owner_raw = at.group(1) if at else ""
        if not u:
            u = self.people.find_in(text)
        ds = dates_in(text, self.ref)
        due = None
        for _, _, d, before in ds:
            if DUE_HINT.search(before):
                due = d
        if not due and ds:
            due = ds[-1][2]
        # Titre : sans responsable, échéance, statut entre parenthèses.
        title = re.sub(r"(?i)\b(responsable|resp\.?|porteur|pilote|qui|owner|assign[ée] à|attribu[ée] à|acteur)\s*[:=]\s*[^,;|()]+", "", text)
        title = re.sub(r"(?i)\b(pour le|avant le|d'ici le|d'ici|échéance|echeance|deadline|date limite|au plus tard le|délai)\s*:?\s*"
                       r"(\d{1,2}[/.\-]\d{1,2}(?:[/.\-]\d{2,4})?|\d{4}-\d{2}-\d{2}|\d{1,2}(?:er)?\s+\w+(?:\s+\d{4})?|s\d{1,2}|semaine\s\d{1,2}|fin de semaine|semaine prochaine|fin du mois)", "", title)
        title = re.sub(r"@[\w.\-]+", "", title)
        if owner_raw:
            title = title.replace(f"({owner_raw})", "")
        title = re.sub(r"(?i)[\s,;:–-]*(fin de (la )?semaine|semaine prochaine|fin du mois|fin de mois|demain)\s*\.?$", "", title.strip())
        # Parenthèses et segments « – … » qui ne sont qu'un nom, une date ou un statut : retirés du libellé.
        title = re.sub(r"\(([^()]{1,40})\)", lambda mm: "" if self._meta(mm.group(1)) else mm.group(0), title)
        segs = re.split(r"\s+[–—-]\s+", title)
        title = " – ".join([segs[0]] + [s for s in segs[1:] if not self._meta(s)])
        title = re.sub(r"(?i)[\s,;:–-]+(fait|faite|termin[ée]e?|ok|done|en cours|bloqu[ée]e?|r[ée]alis[ée]e?)\s*\.?$", "", title.strip())
        title = _clean(re.sub(r"\s{2,}", " ", title))
        return self._row(title, u, "" if u else owner_raw, due, _status_of(text), raw)

    def _meta(self, s):
        """Fragment sans contenu propre : nom de personne, date / semaine, statut."""
        s = s.strip(" .,;:")
        if not s:
            return True
        if self.people.match(s):
            return True
        rest = DATE_RE.sub("", _norm(s)).strip(" .,:;")
        rest = re.sub(r"^(le|pour le|avant le|echeance|au)\s*", "", rest).strip()
        if dates_in(s, self.ref) and len(rest) < 3:
            return True
        return bool(_status_of(s)) and len(s) <= 14

    def _row(self, title, u, owner_raw, due, st, raw):
        conf = 40 + (25 if u else 0) + (20 if due else 0) + (15 if len(title) >= 12 else 0)
        return {"title": title[:300], "ownerId": u.pk if u else None, "ownerName": u.display_name if u else None,
                "ownerRaw": (owner_raw or "")[:80], "ownerIsMember": bool(u and u.pk in self.people.member_ids),
                "due": due.isoformat() if due else None, "status": st, "source": raw.strip()[:300], "confidence": min(conf, 100)}

    # --- résultat
    def result(self):
        from .excel_import import meaningful
        meta, out = self.parse()
        participants, external = [], []
        for ln in out["participants"]:
            for part in re.split(r"[,;/|•—–]| et |\t", ln):
                p = BULLET.sub("", part).strip(" .-–:")
                if len(p) < 2 or len(p) > 60 or _norm(p) in ("oui", "non", "x", "present", "presente", "absent", "absente",
                                                             "excuse", "excusee", "nom", "societe", "fonction", "role"):
                    continue
                p = re.sub(r"\s*\((?:[^()]*)\)", "", p).strip()
                u = self.people.match(p)
                if u and u.pk not in [x["id"] for x in participants]:
                    participants.append({"id": u.pk, "name": u.display_name})
                elif not u and p not in external and not _heading(p):
                    external.append(p)
        open_ = list(Action.objects.filter(project=self.project).exclude(status="done").only("id", "title", "owner_id", "due", "status"))
        actions, seen = [], set()
        for item in out["actions"][:MAX_ITEMS]:
            a = self.action(item)
            key = _norm(a["title"])
            if len(key) < 4 or key in seen or not meaningful(a["title"]):
                continue
            seen.add(key)
            # Action déjà suivie dans le projet ? → mise à jour plutôt qu'un doublon.
            best, score = None, 0.0
            for t in open_:
                s = difflib.SequenceMatcher(None, key, _norm(t.title)).ratio()
                if s > score:
                    best, score = t, s
            if best and score >= 0.85:
                a.update({"existingId": best.id, "existingTitle": best.title, "existingDue": best.due.isoformat() if best.due else None,
                          "existingStatus": best.status, "mode": "update"})
            else:
                a["mode"] = "create"
            a["key"] = f"a{len(actions)}"
            a["include"] = True
            actions.append(a)
        nxt = None
        for ln in out["next"] + [ln for ln in out["notes"] if "prochain" in _norm(ln)]:
            ds = dates_in(ln, self.ref)
            if ds:
                nxt = ds[0][2].isoformat()
                break

        def texts(items):
            res = []
            for x in items[:MAX_ITEMS]:
                t = _clean(_strip_prefix(x))
                if len(t) >= 4 and t not in res:
                    res.append(t[:500])
            return res
        warn = []
        if not any(ln.strip() for ln in self.lines):
            warn.append("Aucun texte lisible dans ce document. Pour un scan ou une photo, relancez l'analyse avec l'OCR.")
        elif not actions and not out["decisions"]:
            warn.append("Aucune action ni décision repérée automatiquement : ajoutez-les à la main avant de valider.")
        unknown = sorted({a["ownerRaw"] for a in actions if a["ownerRaw"] and not a["ownerId"]})
        if unknown:
            warn.append("Responsables non reconnus : " + ", ".join(unknown) + " (choisissez la personne dans la liste).")
        return {"meeting": {**meta, "participants": participants, "external": external[:40], "nextMeeting": nxt},
                "agenda": texts(out["agenda"]), "decisions": texts(out["decisions"]), "risks": texts(out["risks"]),
                "notes": "\n".join(texts(out["notes"])[:60]), "actions": actions, "warnings": warn,
                "lines": len([ln for ln in self.lines if ln.strip()])}


# --------------------------------------------------------------------------- API
def _doc(user, pk, doc_id):
    project = _project(user, pk)
    d = get_object_or_404(Document, project=project, pk=doc_id)
    if not (user.role and user.role.internal) and not d.client_visible:
        raise ApiError("NOT_FOUND", "Document introuvable.", status.HTTP_404_NOT_FOUND)
    return project, d


class MinutesAnalyseView(APIView):
    """POST : lecture du CR (texte du fichier, ou texte OCR envoyé par le navigateur) → propositions à valider."""

    def post(self, request, pk, doc_id):
        project, d = _doc(request.user, pk, doc_id)
        ocr = str(request.data.get("ocrText") or "").strip()
        if ocr:
            # Texte reconnu par l'OCR du navigateur (scan, photo, PDF image) ou corrigé par l'utilisateur : il fait foi
            # pour l'analyse et devient le texte consultable / recherchable du document.
            d.extracted_text = ocr[:200_000]
            d.extraction = {**(d.extraction or {}), "source": str(request.data.get("source") or "OCR (Tesseract)")[:60],
                            "words": len(ocr.split())}
            d.save(update_fields=["extracted_text", "extraction"])
        r = Reader(project, d)
        if ocr:
            r.lines = ocr.splitlines()
        res = r.result()
        rights = _rights(request.user, project)
        from .project_alerts import members_of
        members = sorted(members_of(project), key=lambda u: u.display_name)
        prev = (d.extraction or {}).get("minutes")
        return Response({**res, "document": {"id": d.id, "name": d.name, "ext": d.ext}, "previous": prev,
                         "members": [{"id": u.pk, "name": u.display_name, "role": u.role.label if u.role_id else ""} for u in members],
                         "canCreate": rights["canManageTasks"],
                         "validator": project.pm.display_name if project.pm_id else "le chef de projet"})


class MinutesApplyView(APIView):
    """POST : enregistre ce que l'utilisateur a validé (réunion, décisions, actions)."""

    def post(self, request, pk, doc_id):
        project, d = _doc(request.user, pk, doc_id)
        user = request.user
        data = request.data or {}
        m = data.get("meeting") or {}
        rights = _rights(user, project)
        User = get_user_model()
        tenant_users = {u.pk: u for u in User.objects.filter(tenant=project.tenant, is_active=True)}
        decisions = [str(x).strip()[:500] for x in (data.get("decisions") or []) if str(x).strip()][:MAX_ITEMS]
        risks = [str(x).strip()[:500] for x in (data.get("risks") or []) if str(x).strip()][:MAX_ITEMS]
        agenda = [str(x).strip()[:500] for x in (data.get("agenda") or []) if str(x).strip()][:MAX_ITEMS]
        items = [a for a in (data.get("actions") or []) if a.get("include", True) and str(a.get("title") or "").strip()][:MAX_ITEMS]
        when = parse_date(str(m.get("date") or "")) or d.uploaded_at or timezone.localdate()

        created, updated, proposed, notified = [], [], [], 0
        if rights["canManageTasks"]:
            for a in items:
                owner = tenant_users.get(int(a["owner"])) if str(a.get("owner") or "").isdigit() else None
                due = parse_date(str(a.get("due") or ""))
                st = a.get("status") if a.get("status") in ("todo", "doing", "blocked", "done") else None
                t = Action.objects.filter(project=project, pk=a.get("existingId")).first() if a.get("mode") == "update" and a.get("existingId") else None
                if t:
                    fields = []
                    if owner and t.owner_id != owner.pk:
                        t.owner_id = owner.pk
                        fields.append("owner")
                    if due and t.due != due:
                        t.due = due
                        fields.append("due")
                    if st and st != t.status:
                        t.status = st
                        fields.append("status")
                        if st == "done":
                            t.done_at = timezone.now()
                            fields.append("done_at")
                    if fields:
                        t.save(update_fields=fields)
                    updated.append(t)
                else:
                    t = Action.objects.create(tenant=project.tenant, project=project, id=_next_action_id(project),
                                              title=str(a["title"]).strip()[:300], status=st or "todo",
                                              owner_id=owner.pk if owner else None, due=due)
                    created.append(t)
                if t.owner_id and t.owner_id != user.pk:
                    Notification.objects.create(
                        user_id=t.owner_id, event="project_alert",
                        title=f"[{project.code}] 📝 Action issue du CR : {t.title}"[:200],
                        body=(f"{user.display_name} a validé le compte rendu « {d.name} » : action {t.id}"
                              + (f", échéance le {t.due:%d/%m/%Y}" if t.due else "") + f" · #DOC:{d.id} · {project.id}")[:2000])
                    notified += 1
        else:
            # Profil sans droit de création : chaque action devient une proposition à valider par le chef de projet.
            from .assistant_review import add_pending
            for a in items:
                owner = tenant_users.get(int(a["owner"])) if str(a.get("owner") or "").isdigit() else None
                due = parse_date(str(a.get("due") or ""))
                if a.get("mode") == "update" and a.get("existingId") and due:
                    add_pending(project, {
                        "kind": "minutes", "level": "info", "do": "set_due", "key": f"cr-{d.id}-{a.get('existingId')}",
                        "title": f"Échéance de « {a.get('existingTitle') or a['title']} » au {due:%d/%m} (CR)",
                        "why": f"Compte rendu « {d.name} » déposé par {user.display_name}.",
                        "effect": f"Nouvelle échéance le {due:%d/%m/%Y}.", "payload": {"task": a["existingId"]},
                        "edit": {"due": due.isoformat()}, "assistant": "atlas"})
                else:
                    add_pending(project, {
                        "kind": "minutes", "level": "info", "do": "create_task", "key": f"cr-{d.id}-{_norm(a['title'])[:40]}",
                        "title": f"Créer l'action « {str(a['title'])[:120]} » (CR)",
                        "why": f"Action relevée dans le compte rendu « {d.name} » par {user.display_name}"
                               + (f" : « {str(a.get('source') or '')[:160]} »" if a.get("source") else "."),
                        "effect": f"Action affectée à {owner.display_name if owner else 'à définir'}"
                                  + (f", échéance le {due:%d/%m/%Y}." if due else "."),
                        "payload": {"title": str(a["title"]).strip()[:300]},
                        "edit": {"owner": owner.pk if owner else None, "due": due.isoformat() if due else None},
                        "assistant": "atlas"})
                proposed.append(a["title"])

        meeting = None
        if data.get("createMeeting", True):
            meeting = Meeting.objects.create(
                tenant=project.tenant, id=f"MT{secrets.token_hex(5).upper()}", project=project,
                type=str(m.get("type") or "Réunion")[:80], title=str(m.get("title") or d.name)[:300], date=when,
                organizer=user, external=[str(x)[:120] for x in (m.get("external") or [])][:60], agenda=agenda,
                notes="\n".join(filter(None, [str(data.get("notes") or "")[:20000],
                                              ("Risques / points de vigilance :\n- " + "\n- ".join(risks)) if risks else "",
                                              (f"Prochaine réunion : {m['nextMeeting']}" if m.get("nextMeeting") else "")])),
                decisions=decisions, doc=d, client_visible=d.client_visible, status="done")
            ids = [int(x) for x in (m.get("participants") or []) if str(x).isdigit() and int(x) in tenant_users]
            if ids:
                meeting.attendees.set(ids)
            if created or updated:
                meeting.actions.set(created + updated)

        summary = {"at": timezone.now().isoformat(), "by": user.display_name, "byId": user.pk,
                   "meeting": meeting.id if meeting else None, "created": [t.id for t in created], "updated": [t.id for t in updated],
                   "proposed": len(proposed), "decisions": len(decisions), "risks": len(risks)}
        d.extraction = {**(d.extraction or {}), "minutes": summary}
        if d.type != "minutes":
            d.type = "minutes"
        d.save(update_fields=["extraction", "type"])
        audit.record(user, f"Projet {project.code}", "Compte rendu validé", "",
                     f"{d.name} : {len(created)} action(s) créée(s), {len(updated)} mise(s) à jour, {len(proposed)} proposée(s), "
                     f"{len(decisions)} décision(s)", tenant=project.tenant)
        if decisions or created:
            from .project_alerts import notify_members
            body = (f"Compte rendu « {d.name} » validé par {user.display_name} : {len(decisions)} décision(s), "
                    f"{len(created)} action(s) créée(s), {len(updated)} mise(s) à jour.")
            if decisions:
                body += " Décisions : " + " ; ".join(decisions[:5])
            notify_members(project, user, f"📝 CR validé : {m.get('title') or d.name}"[:150], body,
                           internal_only=not d.client_visible, email=False, ref=f"#DOC:{d.id}")
        return Response({**summary, "createdActions": [{"id": t.id, "title": t.title} for t in created],
                         "updatedActions": [{"id": t.id, "title": t.title} for t in updated], "proposedTitles": proposed,
                         "notifiedOwners": notified, "validator": project.pm.display_name if project.pm_id else None})
