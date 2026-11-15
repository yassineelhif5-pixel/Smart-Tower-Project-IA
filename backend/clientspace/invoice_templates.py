"""Modèles de facture .docx paramétrables par l'administrateur.

Le modèle est un document Word ordinaire contenant des balises {{balise}}. À la génération d'une facture (déclenchée par
la génération du CRA), le modèle de la personne est choisi dans cet ordre : modèle de la personne, d'un groupe dont elle
fait partie, de sa société (intervenant externe rattaché), modèle par défaut du tenant, puis modèle intégré.
Un paragraphe ne contenant que {{lignes}} ou {{totaux}} est remplacé par le tableau correspondant.
"""
import io
import re
import zipfile
from xml.sax.saxutils import escape, unescape

from . import docx
from .models import InvoiceTemplate

PLACEHOLDERS = [
    ("numero", "Numéro de facture"), ("date_facture", "Date de facture"), ("echeance", "Date d'échéance"),
    ("periode", "Mois facturé"), ("version", "Version du CRA"), ("client", "Client facturé"), ("client_ville", "Ville du client"),
    ("consultant", "Nom de la personne"), ("role", "Profil de la personne"), ("societe_consultant", "Société de rattachement de la personne"),
    ("prestataire", "Votre entreprise"), ("prestataire_adresse", "Adresse"), ("prestataire_ville", "Ville / pays"),
    ("siret", "SIRET"), ("tva_intra", "N° TVA intracommunautaire"), ("forme_juridique", "Forme juridique"), ("capital", "Capital"),
    ("email_prestataire", "E-mail de contact"), ("projets", "Projets facturés"), ("jours", "Jours facturés"), ("tjm", "TJM HT"),
    ("total_ht", "Total HT"), ("tva_taux", "Taux de TVA"), ("total_tva", "Montant de TVA"), ("total_ttc", "Total TTC"),
    ("iban", "IBAN"), ("mentions", "Mentions légales"),
    ("lignes", "Tableau des prestations (seul dans son paragraphe)"), ("totaux", "Tableau HT / TVA / TTC (seul dans son paragraphe)"),
]
TABLE_KEYS = {"lignes", "totaux"}
MAX_BYTES = 1_500_000
TAG = re.compile(r"\{\{\s*([a-zA-Z_]+)\s*\}\}")
PARA = re.compile(r"<w:p[ >].*?</w:p>|<w:p/>", re.S)
TEXT = re.compile(r"(<w:t(?:\s[^>]*)?>)(.*?)(</w:t>)", re.S)


class TemplateError(Exception):
    pass


def check(content):
    if len(content) > MAX_BYTES:
        raise TemplateError("Le modèle dépasse 1,5 Mo.")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            if "word/document.xml" not in z.namelist():
                raise TemplateError("Ce fichier n'est pas un document Word (.docx).")
            xml = z.read("word/document.xml").decode("utf-8")
    except zipfile.BadZipFile:
        raise TemplateError("Ce fichier n'est pas un document Word (.docx).")
    found = set()
    for para in PARA.findall(xml):
        found |= set(TAG.findall("".join(unescape(t[1]) for t in TEXT.findall(para))))
    return sorted(found)


def template_for(tenant, person):
    """Modèle applicable à la personne et la règle qui l'a choisi."""
    qs = InvoiceTemplate.objects.filter(tenant=tenant)
    t = qs.filter(scope="person", persons=person).order_by("-updated_at").first()
    if t:
        return t, "personne"
    t = qs.filter(scope="group", persons=person).order_by("-updated_at").first()
    if t:
        return t, "groupe"
    if person.company:
        t = qs.filter(scope="company", company__iexact=person.company.strip()).order_by("-updated_at").first()
        if t:
            return t, "société"
    t = qs.filter(scope="default").order_by("-updated_at").first()
    if t:
        return t, "défaut"
    return None, "intégré"


def _para(para, ctx, tables):
    texts = TEXT.findall(para)
    if not texts:
        return para
    joined = "".join(unescape(t[1]) for t in texts)
    if "{{" not in joined:
        return para
    only = TAG.fullmatch(joined.strip())
    if only and only.group(1) in TABLE_KEYS:
        return tables.get(only.group(1), "")
    new = TAG.sub(lambda m: str(ctx.get(m.group(1), m.group(0))), joined)
    first = [True]

    def put(m):
        if first[0]:
            first[0] = False
            return f'<w:t xml:space="preserve">{escape(new)}</w:t>'
        return '<w:t xml:space="preserve"></w:t>'
    return TEXT.sub(put, para)


def render(content, ctx, tables):
    src = zipfile.ZipFile(io.BytesIO(content))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for item in src.infolist():
            data = src.read(item.filename)
            n = item.filename
            if n == "word/document.xml" or re.fullmatch(r"word/(header|footer)\d*\.xml", n):
                xml = data.decode("utf-8")
                tb = tables if n == "word/document.xml" else {}
                xml = PARA.sub(lambda m: _para(m.group(0), ctx, tb), xml)
                data = xml.encode("utf-8")
            z.writestr(item, data)
    return out.getvalue()


def sample():
    """Modèle d'exemple à télécharger, reprenant toutes les balises."""
    blocks = [docx.p("FACTURE N° {{numero}}", "Title"),
              docx.p("{{prestataire}} — {{prestataire_adresse}} — {{prestataire_ville}}", size=18),
              docx.p("{{forme_juridique}} au capital de {{capital}} · SIRET {{siret}} · TVA {{tva_intra}} · {{email_prestataire}}", size=18),
              docx.p(""),
              docx.p("Facturé à : {{client}}, {{client_ville}}", bold=True),
              docx.p("Date : {{date_facture}} · Échéance : {{echeance}} · Période : {{periode}}"),
              docx.p("Objet : prestations de {{consultant}} ({{role}}, {{societe_consultant}}) — {{jours}} jour(s) à {{tjm}} — projets {{projets}} — CRA version {{version}}."),
              docx.p("{{lignes}}"),
              docx.p("{{totaux}}"),
              docx.p("Total à payer : {{total_ttc}} (HT {{total_ht}} + TVA {{tva_taux}} % {{total_tva}})", bold=True),
              docx.p("IBAN : {{iban}}", size=18),
              docx.p("{{mentions}}", size=16, color="64748B")]
    return docx.build("Modèle de facture", blocks)
