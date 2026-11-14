"""Lecture automatique des documents déposés et classification par mots-clés (outils gratuits uniquement).

- Extraction du texte : PDF (pypdf), Word / Excel / PowerPoint (lecture XML de la bibliothèque standard),
  texte brut. Les images sont lues par OCR dans le navigateur (Tesseract.js) qui envoie le texte reconnu.
- Classification : chaque type de document a des mots-clés (liste par défaut, modifiable par l'administrateur
  dans le réglage AppSetting « doc_keywords ») ; le type ayant le meilleur score est proposé.
- Informations extraites : dates, montants, e-mails, téléphones, références, versions.
"""
import io
import re
import unicodedata
import zipfile
from xml.etree import ElementTree

MAX_TEXT = 200_000

DEFAULT_KEYWORDS = {
    "proposal": ["proposition commerciale", "offre", "devis", "proposition technique", "chiffrage", "tarif", "validité de l'offre",
                 "conditions commerciales", "notre proposition", "propale"],
    "contract": ["contrat", "bon de commande", "avenant", "conditions générales", "signature", "parties", "résiliation",
                 "durée du contrat", "purchase order", "annexe contractuelle"],
    "specs": ["cahier des charges", "expression de besoin", "besoin", "périmètre", "objectifs du projet", "contexte",
              "exigences", "cdc", "rfp", "appel d'offres"],
    "sfd": ["spécifications fonctionnelles", "sfd", "règle de gestion", "cas d'utilisation", "use case", "user story",
            "parcours utilisateur", "maquette", "écran", "critères d'acceptation"],
    "std": ["spécifications techniques", "architecture", "dat", "conception technique", "api", "base de données",
            "schéma", "infrastructure", "sécurité", "hld", "lld", "déploiement"],
    "planning": ["planning", "jalon", "macro planning", "gantt", "échéancier", "phase", "lot", "calendrier", "roadmap"],
    "minutes": ["compte rendu", "compte-rendu", "réunion", "ordre du jour", "participants", "décisions", "relevé de décisions",
                "actions à mener", "comité de pilotage", "copil", "point hebdomadaire"],
    "test": ["recette", "cahier de recette", "cas de test", "pv de recette", "procès-verbal", "anomalie", "vabf", "vsr",
             "test d'intégration", "non-régression", "réserve"],
    "delivery": ["livrable", "manuel utilisateur", "guide", "documentation", "release note", "notes de version",
                 "mode opératoire", "installation"],
    "invoice": ["facture", "montant ht", "montant ttc", "tva", "échéance de paiement", "iban", "numéro de facture",
                "règlement", "net à payer"],
}


def _norm(text):
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def keywords_for(tenant):
    from configuration.models import AppSetting
    row = AppSetting.objects.filter(tenant=tenant, key="doc_keywords").first()
    custom = row.value if row and isinstance(row.value, dict) else {}
    return {code: [str(k) for k in custom.get(code, words)] for code, words in DEFAULT_KEYWORDS.items()}


def _xml_text(data, tags=None):
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return ""
    return " ".join(t.strip() for t in root.itertext() if t and t.strip())


def extract_text(content, ext, mime=""):
    """Texte d'un fichier. Ne lève jamais : un format illisible renvoie une chaîne vide."""
    ext = (ext or "").lower()
    try:
        if ext in ("txt", "csv", "md", "json", "xml", "html", "htm") or mime.startswith("text/"):
            for enc in ("utf-8", "cp1252", "latin-1"):
                try:
                    return content.decode(enc)[:MAX_TEXT]
                except UnicodeDecodeError:
                    continue
        if ext in ("docx", "xlsx", "pptx", "odt"):
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                names = z.namelist()
                if ext == "docx":
                    parts = [n for n in names if n.startswith("word/") and n.endswith(".xml")
                             and ("document" in n or "header" in n or "footer" in n)]
                elif ext == "xlsx":
                    parts = [n for n in names if n == "xl/sharedStrings.xml" or n.startswith("xl/worksheets/sheet")]
                elif ext == "pptx":
                    parts = sorted(n for n in names if n.startswith("ppt/slides/slide") and n.endswith(".xml"))
                else:
                    parts = ["content.xml"] if "content.xml" in names else []
                return " ".join(_xml_text(z.read(n)) for n in parts)[:MAX_TEXT]
        if ext == "pdf" or mime == "application/pdf":
            try:
                from pypdf import PdfReader
            except ImportError:
                return ""
            reader = PdfReader(io.BytesIO(content))
            out = []
            for page in reader.pages[:200]:
                out.append(page.extract_text() or "")
                if sum(len(x) for x in out) > MAX_TEXT:
                    break
            return "\n".join(out)[:MAX_TEXT]
    except Exception:  # fichier corrompu ou protégé : pas de texte
        return ""
    return ""


def classify(text, name, keywords):
    """Type proposé d'après les mots-clés trouvés dans le nom et le contenu (le nom compte double)."""
    body, title = _norm(text or ""), _norm(name or "")
    scores = {}
    for code, words in keywords.items():
        found = []
        score = 0
        for w in words:
            nw = _norm(w)
            if not nw:
                continue
            n = body.count(nw) + 2 * title.count(nw)
            if n:
                found.append(w)
                score += min(n, 5) * (2 if " " in nw else 1)
        if score:
            scores[code] = {"score": score, "keywords": found[:8]}
    if not scores:
        return None, 0, [], {}
    best = max(scores, key=lambda c: scores[c]["score"])
    total = sum(v["score"] for v in scores.values())
    confidence = round(scores[best]["score"] / total * 100)
    return best, confidence, scores[best]["keywords"], scores


DATE_RE = re.compile(r"\b(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2} (?:janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre) \d{4})\b", re.I)
AMOUNT_RE = re.compile(r"(\d{1,3}(?:[  .]\d{3})*(?:,\d{2})?|\d+(?:[.,]\d{2})?)\s?(?:€|eur\b|euros?\b|k€)", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+33\s?|0)[1-9](?:[ .-]?\d{2}){4}")
REF_RE = re.compile(r"\b(?:réf(?:érence)?|ref|n°|numéro|devis|facture|commande|contrat)\b\.?\s*(?:n°)?\s*[:.]?\s*([A-Z0-9][A-Z0-9/_-]{2,24})", re.I)
VERSION_RE = re.compile(r"\b(?:version|v)\s?(\d+(?:\.\d+){0,3})\b", re.I)


def _uniq(items, limit=8):
    out = []
    for i in items:
        i = i.strip()
        if i and i not in out:
            out.append(i)
        if len(out) >= limit:
            break
    return out


def extract_info(text):
    text = text or ""
    return {
        "dates": _uniq(DATE_RE.findall(text)),
        "amounts": _uniq(m.group(0) for m in AMOUNT_RE.finditer(text)),
        "emails": _uniq(EMAIL_RE.findall(text)),
        "phones": _uniq(PHONE_RE.findall(text), 5),
        "references": _uniq(r for r in REF_RE.findall(text) if any(c.isdigit() for c in r)),
        "versions": _uniq(VERSION_RE.findall(text), 5),
        "words": len(text.split()),
        "excerpt": " ".join(text.split())[:400],
    }


def analyse(content, ext, mime, name, tenant, ocr_text=""):
    text = extract_text(content, ext, mime)
    source = "texte du fichier"
    if len(text.strip()) < 20 and ocr_text:
        text, source = ocr_text[:MAX_TEXT], "OCR (Tesseract)"
    elif len(text.strip()) < 20:
        source = "aucun texte lisible"
    best, confidence, found, scores = classify(text, name, keywords_for(tenant))
    return text, {
        "source": source, "suggestedType": best, "confidence": confidence, "matchedKeywords": found,
        "scores": {k: v["score"] for k, v in scores.items()}, **extract_info(text),
    }
