"""Import Excel de projets et d'actions, assisté par l'Orchestrateur IA (Maestro).

1. analyse : lecture du classeur (toutes les feuilles), détection de la ligne d'en-tête, du rôle de chaque feuille
   (actions / projets / à ignorer) et proposition d'une matrice de mappage colonne → champ, avec un niveau de confiance ;
2. preview : à partir du mappage (éventuellement corrigé par le chef de projet), plan d'import par projet
   (projet existant mis à jour ou nouveau projet, actions créées / mises à jour, responsables reconnus ou non) ;
3. apply : exécution après validation du chef de projet.
Le fichier est renvoyé à chaque étape : rien n'est stocké côté serveur avant la validation.
"""
import csv
import io
import json
import re
import unicodedata
from collections import Counter, OrderedDict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import has_perm
from config.errors import ApiError
from configuration import audit

from .access import in_active_tenant, visible_projects
from .models import PROJECT_TYPES, Action, Project, ProjectAccess

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 20000

FIELDS = OrderedDict([
    ("project", "Projet (nom ou code)"), ("ref", "Référence / ID de l'action"), ("title", "Titre de l'action"), ("description", "Description"),
    ("owner", "Responsable / assigné"), ("status", "Statut"), ("progress", "Avancement (%)"),
    ("start", "Date de début"), ("due", "Échéance / date de fin"), ("estimate", "Estimation (charge)"),
    ("phase", "Phase / lot"), ("priority", "Priorité"),
    ("p_name", "Projet : nom"), ("p_code", "Projet : code"), ("p_client", "Projet : client"), ("p_pm", "Projet : chef de projet"),
    ("p_start", "Projet : début"), ("p_end", "Projet : fin"), ("p_method", "Projet : méthodologie"),
    ("ignore", "— Ignorer —"),
])
SYN = {
    "ref": ["id", "ref", "reference", "référence", "id action", "n action", "numero", "numéro", "code action", "identifiant"],
    "project": ["projet", "project", "programme", "chantier", "code projet", "nom projet", "nom du projet"],
    "title": ["tache", "tâche", "action", "titre", "libelle", "libellé", "intitule", "intitulé", "task", "activite", "activité", "sujet", "item", "nom"],
    "description": ["description", "detail", "détail", "commentaire", "remarque", "notes", "note"],
    "owner": ["responsable", "assigne", "assigné", "affecte", "affecté", "owner", "ressource", "acteur", "porteur", "assignee", "qui", "intervenant"],
    "status": ["statut", "etat", "état", "status"],
    "progress": ["avancement", "progress", "%", "pourcentage", "realise", "réalisé"],
    "start": ["debut", "début", "date debut", "date de debut", "start", "demarrage", "démarrage"],
    "due": ["fin", "echeance", "échéance", "date fin", "date de fin", "due", "deadline", "date limite", "livraison", "date prevue", "date prévue"],
    "estimate": ["charge", "estimation", "estime", "estimé", "effort", "jh", "j/h", "jours", "heures", "duree", "durée", "hours", "days"],
    "phase": ["phase", "lot", "etape", "étape", "jalon", "sprint", "workstream"],
    "priority": ["priorite", "priorité", "priority", "prio", "urgence"],
    "p_client": ["client"], "p_pm": ["chef de projet", "cdp", "pm", "project manager"], "p_method": ["methodologie", "méthodologie", "methode", "méthode", "method"],
}


def _norm(v):
    v = unicodedata.normalize("NFKD", str(v or "")).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9%/ ]", " ", v)).strip()


# --------------------------------------------------------------------------- lecture du classeur
def read_book(upload):
    name = upload.name.lower()
    if upload.size > MAX_BYTES:
        raise ApiError("VALIDATION_ERROR", "Fichier trop volumineux (10 Mo maximum).")
    raw = upload.read()
    if name.endswith(".csv"):
        text = raw.decode("utf-8-sig", errors="replace")
        dialect = csv.Sniffer().sniff(text[:4000], delimiters=";,\t") if text.strip() else csv.excel
        return {"CSV": [list(r) for r in csv.reader(io.StringIO(text), dialect)][:MAX_ROWS]}
    if name.endswith(".xls"):
        raise ApiError("VALIDATION_ERROR", "Ancien format .xls : enregistrez le fichier au format .xlsx puis réessayez.")
    if not name.endswith((".xlsx", ".xlsm")):
        raise ApiError("VALIDATION_ERROR", "Format accepté : .xlsx, .xlsm ou .csv.")
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise ApiError("VALIDATION_ERROR", "Classeur illisible ou protégé par mot de passe.") from exc
    book = OrderedDict()
    for ws in wb.worksheets:
        rows = []
        for r in ws.iter_rows(values_only=True):
            rows.append(list(r))
            if len(rows) >= MAX_ROWS:
                break
        while rows and not any(c not in (None, "") for c in rows[-1]):
            rows.pop()
        book[ws.title] = rows
    return book


def _header_row(rows):
    """Première ligne (parmi les 15 premières) avec au moins 2 libellés texte et des données dessous."""
    best, score = 0, -1
    for i, r in enumerate(rows[:15]):
        texts = [c for c in r if isinstance(c, str) and c.strip() and not re.fullmatch(r"[\d.,/ -]+", c.strip())]
        s = len(texts) * 2 + sum(1 for c in r if isinstance(c, str) and any(w in _norm(c) for ws in SYN.values() for w in ws))
        if len(texts) >= 2 and s > score:
            best, score = i, s
    return best


def _guess_field(header, values):
    h = _norm(header)
    if not h:
        return "ignore", 0
    scores = {}
    for f, words in SYN.items():
        for w in words:
            w = _norm(w)
            if h == w:
                scores[f] = max(scores.get(f, 0), 95)
            elif re.search(rf"\b{re.escape(w)}\b", h):
                scores[f] = max(scores.get(f, 0), 75)
    # Indices tirés des valeurs.
    vals = [v for v in values if v not in (None, "")][:30]
    if vals:
        dates = sum(1 for v in vals if isinstance(v, (date, datetime)) or (isinstance(v, str) and re.fullmatch(r"\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}", v.strip())))
        nums = sum(1 for v in vals if isinstance(v, (int, float, Decimal)) or (isinstance(v, str) and re.fullmatch(r"[\d.,]+", v.strip())))
        emails = sum(1 for v in vals if isinstance(v, str) and "@" in v)
        if dates / len(vals) > 0.6:
            for f in ("start", "due"):
                if f in scores:
                    scores[f] += 10
            if not ({"start", "due", "p_start", "p_end"} & scores.keys()):
                scores["due"] = 50
        if emails / len(vals) > 0.5:
            scores["owner"] = max(scores.get("owner", 0), 85)
        if nums / len(vals) > 0.8 and "estimate" in scores:
            scores["estimate"] += 10
        if nums / len(vals) > 0.8 and "title" in scores:
            scores["title"] -= 40
    if "description" in scores and "title" in scores and h.startswith("description"):
        scores.pop("title")
    if not scores:
        return "ignore", 0
    f = max(scores, key=scores.get)
    return f, min(99, scores[f])


def analyse_sheet(name, rows):
    if not rows:
        return {"name": name, "rows": 0, "headerRow": 0, "columns": [], "role": "ignore", "roleConfidence": 90, "estimateUnit": "d"}
    hr = _header_row(rows)
    header = rows[hr] if hr < len(rows) else []
    body = [r for r in rows[hr + 1:] if any(c not in (None, "") for c in r)]
    width = max((len(r) for r in rows[hr:hr + 50]), default=0)
    cols, used = [], {}
    for i in range(width):
        h = header[i] if i < len(header) else None
        vals = [r[i] if i < len(r) else None for r in body]
        f, conf = _guess_field(h if h is not None else "", vals)
        cols.append({"index": i, "header": str(h) if h not in (None, "") else f"Colonne {i + 1}",
                     "sample": [_cell(v) for v in vals if v not in (None, "")][:3], "field": f, "confidence": conf})
    # Un champ n'est utilisé qu'une fois : on garde la colonne la plus sûre.
    for c in sorted(cols, key=lambda c: -c["confidence"]):
        if c["field"] == "ignore":
            continue
        if c["field"] in used:
            c["field"], c["confidence"] = "ignore", 0
        else:
            used[c["field"]] = c
    fields = set(used)
    if "title" in fields:
        role, rc = "actions", 90
    elif "project" in fields and (fields & {"start", "due", "p_client", "p_pm", "p_method", "description"}):
        role, rc = "projects", 75
        for c in cols:  # sur une feuille de projets, les colonnes génériques deviennent des champs projet
            c["field"] = {"project": "p_name", "start": "p_start", "due": "p_end", "owner": "p_pm"}.get(c["field"], c["field"])
    elif "project" in fields:
        role, rc = "actions", 50
    else:
        role, rc = "ignore", 60
    est = used.get("estimate")
    unit = "d"
    if est is not None:
        h = _norm(est["header"])
        nums = [_num(v) for v in [r[est["index"]] if est["index"] < len(r) else None for r in body]]
        nums = sorted(n for n in nums if n is not None)
        unit = "h" if re.search(r"\b(h|heure|heures|hours)\b", h) else "d" if re.search(r"\b(j|jh|jour|jours|days|j/h)\b", h) else (
            "h" if nums and nums[len(nums) // 2] > 10 else "d")
    return {"name": name, "rows": len(body), "headerRow": hr, "columns": cols, "role": role, "roleConfidence": rc, "estimateUnit": unit}


def _cell(v):
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v)[:80]


def _num(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float, Decimal)):
        return float(v)
    try:
        return float(str(v).replace(",", ".").replace("%", "").strip())
    except ValueError:
        return None


def _date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and 20000 < v < 80000:  # numéro de série Excel
        from datetime import timedelta
        return date(1899, 12, 30) + timedelta(days=int(v))
    s = str(v or "").strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _status(v, progress):
    s = _norm(v)
    if progress is not None and progress >= 100 or any(w in s for w in ("termine", "fait", "done", "clos", "ferme", "livre", "valide", "ok")):
        return "done"
    if any(w in s for w in ("bloque", "blocked", "attente")):
        return "blocked"
    if any(w in s for w in ("revue", "review", "recette", "validation", "test")):
        return "review"
    if any(w in s for w in ("cours", "doing", "wip", "demarre", "progress")) or (progress or 0) > 0:
        return "doing"
    if any(w in s for w in ("planifi", "planned", "prevu")):
        return "planned"
    return "todo"


# --------------------------------------------------------------------------- correspondances
def _users(tenant):
    return list(get_user_model().objects.filter(tenant=tenant, is_active=True).select_related("role"))


def match_user(users, raw):
    s = _norm(raw)
    if not s:
        return None
    for u in users:
        if u.email and s == _norm(u.email):
            return u
    for u in users:
        if s in (_norm(u.username), _norm(u.display_name), _norm(f"{u.last_name} {u.first_name}")):
            return u
    parts = s.split()
    for u in users:  # « Prénom N. » ou nom seul
        full = _norm(u.display_name)
        if len(parts) >= 1 and all(p.rstrip(".") and any(w.startswith(p.rstrip(".")) for w in full.split()) for p in parts):
            return u
    return None


def _ratio(a, b):
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio()


def match_project_info(projects, label):
    """Projet existant correspondant → (projet, raison, score %) ou (None, None, 0)."""
    s = _norm(label)
    if not s:
        return None, None, 0
    for p in projects:
        if s == _norm(p.code) or s == _norm(p.id):
            return p, "code identique", 100
    for p in projects:
        if s == _norm(p.name):
            return p, "nom identique", 100
    best, score = None, 0.0
    for p in projects:
        r = _ratio(s, _norm(p.name))
        if len(s) >= 5 and (s in _norm(p.name) or _norm(p.name) in s):
            r = max(r, 0.9)
        if r > score:
            best, score = p, r
    if best and score >= 0.85:
        return best, f"nom proche ({round(score * 100)} %)", round(score * 100)
    return None, None, 0


def match_project(projects, label):
    return match_project_info(projects, label)[0]


def _action_index(project):
    acts = list(Action.objects.filter(project=project))
    return acts, {a.id.casefold(): a for a in acts}, {_norm(a.title): a for a in acts}


def match_action(index, row):
    """Action existante du projet correspondant à la ligne → (action, raison) ; mise à jour au lieu d'une création."""
    acts, by_id, by_title = index
    ref = str(row.get("ref") or "").strip().casefold()
    if ref and ref in by_id:
        return by_id[ref], "référence identique"
    t = _norm(row["title"])
    if t in by_title:
        return by_title[t], "titre identique"
    best, score = None, 0.0
    for a in acts:
        r = _ratio(t, _norm(a.title))
        if r > score:
            best, score = a, r
    if best and score >= 0.88 and len(t) >= 6:
        return best, f"titre proche ({round(score * 100)} %)"
    return None, None


FIELD_LABELS = {"owner_id": "responsable", "status": "statut", "start_date": "début", "due": "échéance", "est": "charge",
                "phase": "phase", "prio": "priorité"}


def _changes(a, row):
    est = Decimal(str(row["estHours"])) if row["estHours"] is not None else None
    out = []
    for attr, val in (("owner_id", row["owner"]), ("status", row["status"]), ("start_date", row["start"]), ("due", row["due"]),
                      ("est", est), ("phase", row["phase"]), ("prio", row["prio"])):
        if val in (None, ""):
            continue
        cur = getattr(a, attr)
        if attr == "est":
            same = cur is not None and Decimal(str(cur)) == val
        else:
            same = cur == val
        if not same:
            out.append(attr)
    return out


JUNK_TITLES = {"null", "none", "nan", "n a", "na", "nd", "n d", "tbd", "tbc", "total", "sous total", "total general", "xxx", "x",
               "test", "a definir", "vide", "rien", "aucun", "aucune", "idem", "id", "ok", "ko", "todo", "to do", "divers", "autre", "autres",
               "titre", "tache", "action", "libelle", "intitule", "description"}


def meaningful(title, header=""):
    """Titre d'action exploitable : ni vide, ni formule, ni nombre/date, ni libellé générique (« TBD », « Total »…)."""
    t = str(title or "").strip()
    if not t or t.startswith(("=", "#")):
        return False
    n = _norm(t)
    if n in JUNK_TITLES or (header and n == _norm(header)):
        return False
    if re.fullmatch(r"[\d\s.,/:%+-]*", t):
        return False
    letters = sum(1 for ch in n if ch.isalpha())
    return letters >= 3 and len(n) >= 4


# --------------------------------------------------------------------------- plan d'import
def plan(book, mapping, user, projects, stats=None):
    """Regroupe les lignes par projet cible selon le mappage → plan détaillé (sans rien écrire)."""
    stats = stats if stats is not None else {}
    stats.setdefault("ignored", 0)
    stats.setdefault("examples", [])
    users = _users(user.tenant)
    from planning.services import hours_per_day
    hpd = float(mapping.get("hoursPerDay") or hours_per_day(user.tenant) or 8)
    groups = OrderedDict()
    proj_info = {}
    merge = mapping.get("merge") or None  # {"target": projectId | "new", "name": "..."} : tout dans un même projet
    for sname, sm in (mapping.get("sheets") or {}).items():
        rows = book.get(sname)
        if rows is None or sm.get("role") == "ignore":
            continue
        hr = int(sm.get("headerRow") or 0)
        cols = {int(k): v for k, v in (sm.get("columns") or {}).items() if v and v != "ignore"}
        inv = {v: k for k, v in cols.items()}
        body = [r for r in rows[hr + 1:] if any(c not in (None, "") for c in r)]
        get = lambda r, f: (r[inv[f]] if f in inv and inv[f] < len(r) else None)  # noqa: E731
        if sm.get("role") == "projects":
            for r in body:
                label = get(r, "p_name") or get(r, "p_code")
                if label in (None, ""):
                    continue
                proj_info[_norm(label)] = {"name": str(get(r, "p_name") or label).strip()[:200], "code": str(get(r, "p_code") or "").strip()[:20],
                                           "client": str(get(r, "p_client") or "").strip(), "pm": str(get(r, "p_pm") or "").strip(),
                                           "start": _date(get(r, "p_start")), "end": _date(get(r, "p_end")),
                                           "method": str(get(r, "p_method") or "").strip()[:20]}
            continue
        unit = sm.get("estimateUnit") or "d"
        strategy = sm.get("strategy") or ("column" if "project" in inv else "sheet")
        for r in body:
            title = get(r, "title")
            if not meaningful(title, header=(rows[hr][inv["title"]] if "title" in inv and inv["title"] < len(rows[hr]) else "")):
                if any(c not in (None, "") for c in r):
                    stats["ignored"] += 1
                    if title not in (None, "") and len(stats["examples"]) < 6:
                        stats["examples"].append(str(title)[:40])
                continue
            if merge:
                label = merge.get("name") or "Import"
            elif strategy == "column" and "project" in inv:
                label = str(get(r, "project") or "").strip() or sname
            elif strategy == "single":
                label = sm.get("projectName") or sname
            else:
                label = sname
            est = _num(get(r, "estimate"))
            progress = _num(get(r, "progress"))
            if progress is not None and progress <= 1 and "progress" in inv:
                progress = progress * 100 if isinstance(get(r, "progress"), float) else progress
            owner_raw = get(r, "owner")
            owner = match_user(users, owner_raw) if owner_raw not in (None, "") else None
            g = groups.setdefault(_norm(label) or "import", {"label": str(label)[:200], "sheets": set(), "rows": []})
            g["sheets"].add(sname)
            g["rows"].append({
                "title": str(title).strip()[:300], "description": str(get(r, "description") or "").strip()[:4000],
                "ref": str(get(r, "ref") or "").strip()[:20],
                "owner": owner.pk if owner else None, "ownerName": owner.display_name if owner else None,
                "ownerRaw": str(owner_raw).strip() if owner_raw not in (None, "") else "",
                "status": _status(get(r, "status"), progress), "start": _date(get(r, "start")), "due": _date(get(r, "due")),
                "estHours": round(est * (1 if unit == "h" else hpd), 2) if est is not None else None,
                "phase": str(get(r, "phase") or "").strip()[:60], "prio": str(get(r, "priority") or "").strip()[:20],
            })
    targets = mapping.get("targets") or {}
    out = []
    for key, g in groups.items():
        info = proj_info.get(key, {})
        override = targets.get(key)
        existing = None
        if merge and merge.get("target") not in (None, "", "new"):
            existing = next((p for p in projects if p.id == merge["target"]), None)
        elif override and override not in ("new", "skip"):
            existing = next((p for p in projects if p.id == override), None)
        how, score = ("choisi par vous", 100) if existing else (None, 0)
        if merge and existing:
            how = "regroupement choisi"
        if not existing and not override and not merge:
            existing, how, score = match_project_info(projects, g["label"])
            if not existing and info.get("code"):
                existing, how, score = match_project_info(projects, info["code"])
        action = "skip" if override == "skip" else ("update" if existing else "create")
        rows = g["rows"]
        index = _action_index(existing) if existing else ([], {}, {})
        for r in rows:
            a, why = match_action(index, r) if existing else (None, None)
            r["match"] = {"id": a.id, "title": a.title, "how": why} if a else None
            r["changes"] = [FIELD_LABELS[c] for c in _changes(a, r)] if a else []
        update_only = bool(((mapping.get("groupOptions") or {}).get(key) or {}).get("updateOnly"))
        unknown = sorted({r["ownerRaw"] for r in rows if r["ownerRaw"] and not r["owner"]})
        out.append({
            "key": key, "label": g["label"], "sheets": sorted(g["sheets"]), "action": action,
            "target": {"id": existing.id, "name": existing.name, "code": existing.code} if existing else None,
            "newName": info.get("name") or g["label"], "newCode": info.get("code") or "",
            "projectType": dict(PROJECT_TYPES).get(guess_type(info.get("name") or g["label"])) if action == "create" else None, "info": {k: (v.isoformat() if isinstance(v, date) else v) for k, v in info.items()},
            "actions": len(rows), "match": {"how": how, "score": score} if existing else None, "updateOnly": update_only,
            "toCreate": 0 if update_only else sum(1 for r in rows if not r["match"]),
            "toUpdate": sum(1 for r in rows if r["match"] and r["changes"]),
            "unchanged": sum(1 for r in rows if r["match"] and not r["changes"]),
            "ignored": sum(1 for r in rows if not r["match"]) if update_only else 0,
            "owners": sorted({r["ownerName"] for r in rows if r["ownerName"]}), "unknownOwners": unknown,
            "estHours": round(sum(r["estHours"] or 0 for r in rows), 1),
            "done": sum(1 for r in rows if r["status"] == "done"),
            "sample": [{**r, "start": r["start"].isoformat() if r["start"] else None, "due": r["due"].isoformat() if r["due"] else None} for r in rows[:150]],
            "_rows": rows,
        })
    return out


def recommendations(sheets, groups, projects, stats=None):
    recs = []
    if stats and stats.get("ignored"):
        recs.append(f"{stats['ignored']} ligne(s) ignorée(s) : titre d'action vide ou non significatif"
                    + (f" (ex. {', '.join(repr(e) for e in stats['examples'][:4])})" if stats.get("examples") else "") + ".")
    act = [s for s in sheets if s["role"] == "actions"]
    prj = [s for s in sheets if s["role"] == "projects"]
    recs.append(f"J'ai lu {len(sheets)} feuille(s) : {len(act)} feuille(s) d'actions, {len(prj)} feuille(s) de projets"
                + (f", {len(sheets) - len(act) - len(prj)} à ignorer." if len(sheets) - len(act) - len(prj) else "."))
    for s in sheets:
        low = [c for c in s["columns"] if c["field"] != "ignore" and c["confidence"] < 60]
        if low:
            recs.append(f"Feuille « {s['name']} » : vérifiez le mappage de " + ", ".join(f"« {c['header']} »" for c in low[:4]) + " (confiance faible).")
        if s["role"] == "actions" and not any(c["field"] == "title" for c in s["columns"]):
            recs.append(f"Feuille « {s['name']} » : aucune colonne de titre d'action détectée ; indiquez-la dans la matrice.")
    new = [g for g in groups if g["action"] == "create"]
    upd = [g for g in groups if g["action"] == "update"]
    typed = [g for g in new if g.get("projectType")]
    if typed:
        recs.append("Type de projet déduit du nom : " + " ; ".join(f"« {g['newName']} » → {g['projectType']}" for g in typed[:5]) + ".")
    if len(new) > 1:
        recs.append(f"Je propose de créer {len(new)} nouveaux projets ({', '.join(g['newName'] for g in new[:4])}"
                    + ("…" if len(new) > 4 else "") + "). Si ce sont des lots d'un même projet, choisissez « Tout regrouper dans un seul projet ».")
    elif len(new) == 1 and not upd:
        recs.append(f"Je propose de créer le projet « {new[0]['newName']} » ; vous pouvez aussi rattacher les actions à un projet existant.")
    if upd:
        for g in upd[:5]:
            m = g.get("match") or {}
            recs.append(f"Projet existant détecté : « {g['label']} » → {g['target']['name']} ({m.get('how') or 'correspondance'}). "
                        f"{g['toUpdate']} action(s) déjà créée(s) seront mises à jour, {g['unchanged']} sont déjà à jour"
                        + (f", {g['toCreate']} nouvelle(s) seront ajoutées." if g["toCreate"] else ".")
                        + (" Mode « mise à jour seulement » : aucune nouvelle action ne sera créée." if g.get("updateOnly") else ""))
    unknown = sorted({o for g in groups for o in g["unknownOwners"]})
    if unknown:
        recs.append(f"{len(unknown)} responsable(s) non reconnu(s) parmi les utilisateurs : {', '.join(unknown[:6])}. "
                    "Leurs actions seront créées sans responsable (affectation à faire ensuite).")
    return recs


def questions(sheets):
    qs = []
    for s in sheets:
        if s["role"] == "ignore" and s["rows"]:
            qs.append(f"La feuille « {s['name']} » ({s['rows']} lignes) ne ressemble ni à une liste d'actions ni à une liste de projets : faut-il l'ignorer ?")
        if s["role"] == "actions" and not any(c["field"] == "project" for c in s["columns"]):
            qs.append(f"La feuille « {s['name']} » n'a pas de colonne projet : s'agit-il d'un seul projet (nommé « {s['name']} ») ou faut-il la rattacher à un projet existant ?")
    return qs


# --------------------------------------------------------------------------- application
def _new_project(user, name, code, info, options=None, key=""):
    """Nouveau projet. options = {"pmIsMe": bool, "client": {"mode": "same"|"each", "code": str, "perGroup": {clé: code}}}."""
    options = options or {}
    from configuration.views import has_project_role, own_company_client
    from .models import Client
    tenant = user.tenant
    base = (code or slugify(name).replace("-", "")).upper()[:16] or "IMPORT"
    pid, n = base[:20], 1
    while Project.objects.filter(pk=pid).exists() or Project.objects.filter(tenant=tenant, code__iexact=pid).exists():
        n += 1
        pid = f"{base[:16]}{n}"
    client = None
    copt = options.get("client") or {}
    chosen = copt.get("code") if copt.get("mode", "same") == "same" else (copt.get("perGroup") or {}).get(key)
    if chosen and chosen != OWN:
        client = Client.objects.filter(tenant=tenant, code=chosen).first()
    elif not chosen and info.get("client"):
        client = Client.objects.filter(tenant=tenant, name__iexact=info["client"]).first()
    client = client or own_company_client(tenant, user)
    if options.get("pmIsMe", True):
        pm = user  # projet placé sous la responsabilité directe du chef de projet qui importe
    else:
        pm = match_user(_users(tenant), info["pm"]) if info.get("pm") else None
    ptype = guess_type(name)
    p = Project.objects.create(tenant=tenant, id=pid, code=pid, name=name[:200], client=client, method=info.get("method") or "",
                               **({"project_type": ptype} if ptype else {}),
                               descr="Projet créé par import Excel (Orchestrateur IA).", pm=pm,
                               start_date=_date(info.get("start")) if info.get("start") else None,
                               end_date=_date(info.get("end")) if info.get("end") else None)
    for m in {user.pk: user, **({pm.pk: pm} if pm else {})}.values():
        ProjectAccess.objects.get_or_create(tenant=tenant, project=p, user=m, defaults={"can_edit": True, "granted_by": user})
    audit.record(user, f"Projet {p.code}", "Projet créé (import Excel)", "", f"{p.name} · {client.name}")
    return p


OWN = "__own__"


def can_create_projects(user):
    """L'import peut créer des projets : administrateur, droit « créer un projet » ou profil chef de projet."""
    from configuration.views import has_project_role
    return user.is_app_admin or has_perm(user, "project", "create") or has_project_role(user, "pm")


def guess_type(name):
    """Type de projet déduit du nom : « migration » → Migration ; « nouveau / nouvelle » → Nouveau projet (from scratch)."""
    n = _norm(name)
    if re.search(r"\bmigr", n):
        return "migration"
    if re.search(r"\bnouve(au|aux|l|lle|lles)\b", n):
        return "new"
    return None


def clients_of(user):
    from .models import Client
    tenant = user.tenant
    own = Client.objects.filter(tenant=tenant, name__iexact=tenant.name).first()
    rows = [{"code": c.code, "name": c.name} for c in Client.objects.filter(tenant=tenant).order_by("name")]
    if own is None:
        rows.insert(0, {"code": OWN, "name": f"{tenant.name} (entreprise connectée)"})
    return rows, own.code if own else OWN


def apply(groups, user, projects, options=None, progress=None):
    from .workspace import _rights
    report = []
    can_create = can_create_projects(user)
    with transaction.atomic():
        for g in groups:
            if g["action"] == "skip":
                continue
            if g["action"] == "update":
                p = next((x for x in projects if x.id == g["target"]["id"]), None)
                if p is None or not _rights(user, p)["canManageTasks"]:
                    report.append({"project": g["label"], "error": "Vous ne pouvez pas modifier les actions de ce projet."})
                    continue
                created_project = False
            else:
                if not can_create:
                    report.append({"project": g["label"], "error": "Vous n'avez pas le droit de créer un projet : rattachez ces actions à un projet existant."})
                    continue
                p = _new_project(user, g.get("newName") or g["label"], g.get("newCode") or "", g.get("info") or {}, options, g["key"])
                created_project = True
            index = _action_index(p)
            c = u = same = skipped = 0
            members = set(ProjectAccess.objects.filter(project=p).values_list("user_id", flat=True))
            new_members = {r["owner"] for r in g["_rows"] if r["owner"] and r["owner"] not in members}
            ProjectAccess.objects.bulk_create([ProjectAccess(tenant=p.tenant, project=p, user_id=uid, can_edit=True, granted_by=user)
                                               for uid in new_members], ignore_conflicts=True)
            stem = re.sub(r"[^A-Z0-9]", "", p.code.upper())[:12] or "T"
            taken = set(Action.objects.filter(id__startswith=f"{stem}-").values_list("id", flat=True))
            seq = len(index[0])
            to_create, comments, to_update, upd_fields = [], [], [], set()
            today = timezone.localdate()
            for i, r in enumerate(g["_rows"]):
                est = Decimal(str(r["estHours"])) if r["estHours"] is not None else None
                a = match_action(index, r)[0] if not created_project else None
                if a is None and g.get("updateOnly"):
                    skipped += 1
                    continue
                if a:
                    fields = []
                    for attr, val in (("owner_id", r["owner"]), ("status", r["status"]), ("start_date", r["start"]), ("due", r["due"]),
                                      ("est", est), ("phase", r["phase"]), ("prio", r["prio"])):
                        if val not in (None, "") and getattr(a, attr) != val:
                            setattr(a, attr, val)
                            fields.append(attr)
                    if r["status"] == "done" and not a.done_at:
                        a.done_at = today
                        fields.append("done_at")
                    if fields:
                        if a not in to_update:
                            to_update.append(a)
                        upd_fields.update(fields)
                        u += 1
                    else:
                        same += 1
                else:
                    seq += 1
                    while f"{stem}-{seq}" in taken:
                        seq += 1
                    aid = f"{stem}-{seq}"
                    taken.add(aid)
                    a = Action(tenant=p.tenant, project=p, id=aid, title=r["title"], status=r["status"], owner_id=r["owner"],
                               start_date=r["start"], due=r["due"], phase=r["phase"], prio=r["prio"],
                               **({"est": est} if est is not None else {}), **({"done_at": today} if r["status"] == "done" else {}))
                    to_create.append(a)
                    if r["description"]:
                        comments.append((a, r["description"]))
                    index[0].append(a)
                    index[1][a.id.casefold()] = a
                    index[2][_norm(a.title)] = a
                    c += 1
                if progress and (i + 1) % 50 == 0:
                    progress(g, i + 1, len(g["_rows"]))
            for k in range(0, len(to_create), 500):
                Action.objects.bulk_create(to_create[k:k + 500])
                if progress:
                    progress(g, min(k + 500, len(to_create)), len(to_create), "saving")
            if comments:
                from .models import ActionComment
                ActionComment.objects.bulk_create([ActionComment(tenant=p.tenant, action=a, author=user, at=today.isoformat(), internal=True, body=d)
                                                   for a, d in comments], batch_size=500)
            if to_update:
                Action.objects.bulk_update(to_update, sorted(upd_fields), batch_size=300)
            audit.record(user, f"Projet {p.code}", "Import Excel", "", f"{c} action(s) créée(s), {u} mise(s) à jour")
            try:
                from .ai_orchestrator import log
                log(p, "execution", "Maestro", f"Import Excel validé par {user.display_name} : "
                    + ("projet créé, " if created_project else "") + f"{c} action(s) créée(s), {u} mise(s) à jour"
                    + (f" ; responsables non reconnus : {', '.join(g['unknownOwners'][:5])}" if g["unknownOwners"] else ""), "maestro")
            except Exception:  # noqa: BLE001
                pass
            report.append({"project": p.name, "projectId": p.id, "created": created_project, "actionsCreated": c, "actionsUpdated": u,
                           "actionsUnchanged": same, "actionsSkipped": skipped,
                           "unknownOwners": g["unknownOwners"], "client": p.client.name, "pm": p.pm.display_name if p.pm_id else None,
                           "rows": len(g["_rows"]), "projectType": p.get_project_type_display() if p.project_type else None})
    return report


def _strip(groups):
    return [{k: v for k, v in g.items() if k != "_rows"} for g in groups]


# --------------------------------------------------------------------------- import en arrière-plan
JOBS_KEY = "import_jobs"


def _jobs_save(tenant, job):
    from configuration.models import AppSetting
    with transaction.atomic():
        row, _ = AppSetting.objects.select_for_update().get_or_create(tenant=tenant, key=JOBS_KEY, defaults={"value": {}})
        jobs = row.value if isinstance(row.value, dict) else {}
        jobs[job["id"]] = job
        # On garde les 20 derniers imports.
        keep = sorted(jobs.values(), key=lambda j: j["startedAt"], reverse=True)[:20]
        row.value = {j["id"]: j for j in keep}
        row.save(update_fields=["value", "updated_at"])


def jobs_of(user):
    from configuration.models import AppSetting
    row = AppSetting.objects.filter(tenant=user.tenant, key=JOBS_KEY).first()
    jobs = row.value if row and isinstance(row.value, dict) else {}
    return sorted([j for j in jobs.values() if j.get("userId") == user.pk], key=lambda j: j["startedAt"], reverse=True)


def start_job(user, filename, groups, projects, options, ignored):
    import secrets
    import threading
    job = {"id": f"IMP{secrets.token_hex(4).upper()}", "userId": user.pk, "file": filename, "status": "running",
           "startedAt": timezone.now().isoformat(), "endedAt": None, "total": len(groups), "done": 0,
           "current": groups[0]["label"], "rows": sum(len(g["_rows"]) for g in groups), "ignoredRows": ignored, "report": []}
    _jobs_save(user.tenant, job)
    threading.Thread(target=_run_job, args=(job, user.pk, groups, [p.pk for p in projects], options), daemon=True).start()
    return job


def _run_job(job, user_id, groups, project_ids, options):
    from django.db import close_old_connections
    from configuration.models import Notification
    try:
        user = get_user_model().objects.select_related("role", "tenant").get(pk=user_id)
        projects = list(Project.objects.filter(pk__in=project_ids))
        for i, g in enumerate(groups):
            job["current"] = g["label"]
            _jobs_save(user.tenant, job)
            try:
                job["report"] += apply([g], user, projects, options)
            except Exception as exc:  # noqa: BLE001
                job["report"].append({"project": g["label"], "error": f"Erreur pendant l'import ({type(exc).__name__})."})
            job["done"] = i + 1
            _jobs_save(user.tenant, job)
        ok = [r for r in job["report"] if not r.get("error")]
        ko = [r for r in job["report"] if r.get("error")]
        job.update({"status": "done" if not ko else ("partial" if ok else "failed"), "endedAt": timezone.now().isoformat(), "current": None})
        _jobs_save(user.tenant, job)
        created = sum(r.get("actionsCreated", 0) for r in ok)
        updated = sum(r.get("actionsUpdated", 0) for r in ok)
        title = (f"📥 Import Excel terminé : {len(ok)} projet(s), {created} action(s) créée(s), {updated} mise(s) à jour"
                 if not ko else f"📥 Import Excel {'partiel' if ok else 'en échec'} : {len(ok)} projet(s) importé(s), {len(ko)} en échec")
        body = " ; ".join((f"{r['project']} : {r['error']}" if r.get("error") else
                           f"{r['project']} ({'créé' if r.get('created') else 'mis à jour'}, {r.get('actionsCreated', 0)} créée(s), {r.get('actionsUpdated', 0)} mise(s) à jour)")
                          for r in job["report"][:8])
        if job.get("ignoredRows"):
            body += f" ; {job['ignoredRows']} ligne(s) ignorée(s) (titre vide ou non significatif)"
        first = next((r.get("projectId") for r in ok if r.get("projectId")), None)
        Notification.objects.create(user=user, event="project_alert", title=title[:200],
                                    body=(f"{job['file']} · {body}" + (f" · {first}" if first else ""))[:2000])
        try:
            from configuration import notify
            from configuration.models import NotificationChannel
            ch = NotificationChannel.objects.filter(tenant=user.tenant, kind="email", enabled=True).first()
            if ch and user.email:
                notify.send_email(ch, [user.email], title, f"Fichier : {job['file']}\n\n" + body.replace(" ; ", "\n"))
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        job.update({"status": "failed", "endedAt": timezone.now().isoformat(), "error": type(exc).__name__})
        try:
            _jobs_save(get_user_model().objects.get(pk=user_id).tenant, job)
        except Exception:  # noqa: BLE001
            pass
    finally:
        close_old_connections()


class ExcelImportJobsView(APIView):
    """Imports en arrière-plan de l'utilisateur (suivi de l'avancement)."""

    def get(self, request):
        from .excel_access import can_import
        if not in_active_tenant(request.user) or not can_import(request.user):
            return Response({"jobs": []})
        return Response({"jobs": jobs_of(request.user)[:10]})


class ExcelImportView(APIView):
    """POST multipart : file + step (analyse | preview | apply) + mapping (JSON)."""

    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        user = request.user
        if not in_active_tenant(user):
            raise ApiError("FORBIDDEN_PERMISSION", "Accès réservé aux utilisateurs d'une entreprise.", status.HTTP_403_FORBIDDEN)
        from .excel_access import can_import
        if not can_import(user):
            raise ApiError("FORBIDDEN_PERMISSION", "Le module d'import Excel n'est pas autorisé pour votre profil (à demander à l'administrateur).",
                           status.HTTP_403_FORBIDDEN)
        f = request.FILES.get("file")
        if f is None:
            raise ApiError("VALIDATION_ERROR", "Choisissez un fichier Excel (.xlsx) ou CSV.")
        book = read_book(f)
        step = request.data.get("step") or "analyse"
        projects = list(Project.objects.filter(tenant=user.tenant) if user.is_app_admin else visible_projects(user))
        if step == "analyse":
            sheets = [analyse_sheet(n, rows) for n, rows in book.items()]
            mapping = {"sheets": {s["name"]: {"role": s["role"], "headerRow": s["headerRow"], "estimateUnit": s["estimateUnit"],
                                              "columns": {str(c["index"]): c["field"] for c in s["columns"]},
                                              "strategy": "column" if any(c["field"] == "project" for c in s["columns"]) else "sheet"}
                                 for s in sheets}}
            stats = {}
            groups = plan(book, mapping, user, projects, stats)
            return Response({"file": f.name, "sheets": sheets, "mapping": mapping, "groups": _strip(groups), "ignoredRows": stats["ignored"],
                             "fields": FIELDS, "recommendations": recommendations(sheets, groups, projects, stats),
                             "questions": questions(sheets), "canCreate": can_create_projects(user),
                             "projects": [{"id": p.id, "code": p.code, "name": p.name} for p in projects],
                             "clients": clients_of(user)[0], "defaultClient": clients_of(user)[1], "me": user.display_name})
        try:
            mapping = json.loads(request.data.get("mapping") or "{}")
        except ValueError as exc:
            raise ApiError("VALIDATION_ERROR", "Mappage invalide.") from exc
        stats = {}
        groups = plan(book, mapping, user, projects, stats)
        if step == "preview":
            sheets = [analyse_sheet(n, rows) for n, rows in book.items()]
            return Response({"groups": _strip(groups), "ignoredRows": stats["ignored"],
                             "recommendations": recommendations(sheets, groups, projects, stats)})
        if step == "apply_bg":
            todo = [g for g in groups if g["action"] != "skip" and g["_rows"]]
            if not todo:
                raise ApiError("VALIDATION_ERROR", "Aucune action à importer avec ce mappage.")
            job = start_job(user, f.name, todo, projects, mapping.get("options") or {}, stats["ignored"])
            return Response(job, status=status.HTTP_202_ACCEPTED)
        if step == "apply":
            if not groups:
                raise ApiError("VALIDATION_ERROR", "Aucune action à importer avec ce mappage.")
            only = request.data.get("only")
            if only:  # import projet par projet (progression affichée à l'écran)
                groups = [g for g in groups if g["key"] == only]
                if not groups:
                    raise ApiError("VALIDATION_ERROR", "Projet introuvable dans le plan d'import.")
            report = apply(groups, user, projects, mapping.get("options") or {})
            return Response({"report": report})
        raise ApiError("VALIDATION_ERROR", "Étape inconnue.")
