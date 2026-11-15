"""Modèles de facture (administrateur).

GET    /client-space/invoice-templates               modèles, balises, personnes, sociétés et modèle appliqué à chacun
POST   /client-space/invoice-templates               {name, scope, persons, company, filename, content(base64)}
GET    /client-space/invoice-templates/sample        modèle d'exemple .docx
GET    /client-space/invoice-templates/<id>          téléchargement ; ?preview=<personId> : aperçu rempli avec des données fictives
PUT    /client-space/invoice-templates/<id>          modification (fichier facultatif)
DELETE /client-space/invoice-templates/<id>
"""
import base64
from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.errors import ApiError
from configuration import audit
from projects.access import in_active_tenant

from . import docx, invoice_templates as it
from .models import InvoiceTemplate

User = get_user_model()
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
SCOPE_LABEL = dict(InvoiceTemplate.SCOPES)


def _admin(user):
    if not in_active_tenant(user) or not user.is_app_admin:
        raise ApiError("FORBIDDEN_PERMISSION", "Réservé à l'administrateur.", status.HTTP_403_FORBIDDEN)
    return user.tenant


def _row(t):
    return {"id": t.pk, "name": t.name, "scope": t.scope, "scopeLabel": SCOPE_LABEL[t.scope], "company": t.company,
            "persons": [{"id": u.pk, "name": u.display_name} for u in t.persons.all()], "filename": t.filename, "size": t.size_bytes,
            "uploadedBy": t.uploaded_by.display_name if t.uploaded_by else "", "updatedAt": t.updated_at,
            "tags": it.check(bytes(t.content)) if t.content else []}


def _file(name, content):
    r = HttpResponse(content, content_type=DOCX)
    r["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(name)}"
    return r


def _apply(tenant, t, data, by, creating):
    name = str(data.get("name", t.name or "")).strip()[:120]
    scope = data.get("scope", t.scope)
    if scope not in SCOPE_LABEL:
        raise ApiError("VALIDATION_ERROR", "Portée inconnue.", status.HTTP_400_BAD_REQUEST)
    company = str(data.get("company", t.company or "")).strip()[:120]
    persons = data.get("persons")
    if scope == "company" and not company:
        raise ApiError("VALIDATION_ERROR", "Indiquez la société concernée.", status.HTTP_400_BAD_REQUEST)
    if data.get("content"):
        try:
            content = base64.b64decode(str(data["content"]).split(",")[-1])
        except Exception:
            raise ApiError("VALIDATION_ERROR", "Fichier illisible.", status.HTTP_400_BAD_REQUEST)
        try:
            it.check(content)
        except it.TemplateError as e:
            raise ApiError("VALIDATION_ERROR", str(e), status.HTTP_400_BAD_REQUEST)
        t.content, t.size_bytes = content, len(content)
        t.filename = str(data.get("filename") or "modele.docx")[:255]
    elif creating:
        raise ApiError("VALIDATION_ERROR", "Déposez un fichier Word (.docx).", status.HTTP_400_BAD_REQUEST)
    ids = None
    if persons is not None or creating:
        ids = [int(x) for x in (persons or []) if str(x).isdigit()]
    if scope in ("person", "group") and ids is not None:
        if not ids:
            raise ApiError("VALIDATION_ERROR", "Choisissez au moins une personne.", status.HTTP_400_BAD_REQUEST)
        if scope == "person" and len(ids) != 1:
            raise ApiError("VALIDATION_ERROR", "Un modèle « Personne » vise une seule personne ; utilisez « Groupe » pour plusieurs.", status.HTTP_400_BAD_REQUEST)
    t.name = name or {"person": "Modèle personnel", "group": "Modèle de groupe", "company": f"Modèle {company}", "default": "Modèle par défaut"}[scope]
    t.scope, t.company = scope, (company if scope == "company" else "")
    t.uploaded_by, t.tenant = by, tenant
    t.save()
    if scope in ("person", "group"):
        if ids is not None:
            t.persons.set(User.objects.filter(tenant=tenant, pk__in=ids))
    else:
        t.persons.clear()
    audit.record(by, "Facturation", "Modèle de facture " + ("ajouté" if creating else "modifié"), "", f"{t.name} · {SCOPE_LABEL[scope]}")
    return t


class InvoiceTemplatesView(APIView):
    def get(self, request):
        tenant = _admin(request.user)
        people = list(User.objects.filter(tenant=tenant, is_active=True).select_related("role").order_by("first_name", "last_name"))
        out = []
        for u in people:
            if u.role and not u.role.internal:
                continue
            t, rule = it.template_for(tenant, u)
            out.append({"id": u.pk, "name": u.display_name, "company": u.company, "external": u.external,
                        "dailyRate": u.daily_rate, "template": t.name if t else "Modèle intégré", "rule": rule})
        companies = sorted({u.company.strip() for u in people if u.company.strip()}, key=str.lower)
        return Response({"templates": [_row(t) for t in InvoiceTemplate.objects.filter(tenant=tenant).prefetch_related("persons")],
                         "placeholders": [{"key": k, "label": l} for k, l in it.PLACEHOLDERS], "people": out, "companies": companies,
                         "scopes": [{"code": c, "label": l} for c, l in InvoiceTemplate.SCOPES]})

    def post(self, request):
        tenant = _admin(request.user)
        t = _apply(tenant, InvoiceTemplate(), request.data or {}, request.user, True)
        return Response(_row(t), status=status.HTTP_201_CREATED)


class InvoiceTemplateSampleView(APIView):
    def get(self, request):
        _admin(request.user)
        return _file("modele-facture-exemple.docx", it.sample())


class InvoiceTemplateDetailView(APIView):
    def get(self, request, pk):
        tenant = _admin(request.user)
        t = get_object_or_404(InvoiceTemplate, pk=pk, tenant=tenant)
        if not request.query_params.get("preview"):
            return _file(t.filename, bytes(t.content))
        person = User.objects.filter(tenant=tenant, pk=request.query_params["preview"]).first() or request.user
        ctx = {"numero": "FAC-AAAA-0000", "date_facture": "01/12/2026", "echeance": "31/12/2026", "periode": "novembre 2026", "version": 1,
               "client": "Client exemple", "client_ville": "Paris", "consultant": person.display_name,
               "role": person.role.label if person.role else "", "societe_consultant": person.company or tenant.name,
               "prestataire": tenant.name, "prestataire_adresse": tenant.address or "", "prestataire_ville": tenant.city or "",
               "siret": "000 000 000 00000", "tva_intra": "FR00000000000", "forme_juridique": "SAS", "capital": "10 000 €",
               "email_prestataire": tenant.contact_email or "", "projets": "PRJ", "jours": "20,00", "tjm": "500,00 €",
               "total_ht": "10 000,00 €", "tva_taux": "20,00", "total_tva": "2 000,00 €", "total_ttc": "12 000,00 €",
               "iban": "FR76 0000 0000 0000", "mentions": "Paiement à 30 jours."}
        tables = {"lignes": docx.table([["Désignation", "Quantité (j)", "Prix unitaire HT", "Montant HT"], ["Prestation PRJ — Projet exemple", "20,00", "500,00 €", "10 000,00 €"],
                                        ["Total HT", "20,00", "", "10 000,00 €"]], [4800, 1400, 1700, 1700], total=True),
                  "totaux": docx.table([["", "Montant"], ["Total HT", "10 000,00 €"], ["TVA 20 %", "2 000,00 €"], ["Total TTC", "12 000,00 €"]], [7900, 1700], total=True)}
        return _file(f"apercu-{t.filename}", it.render(bytes(t.content), ctx, tables))

    def put(self, request, pk):
        tenant = _admin(request.user)
        t = get_object_or_404(InvoiceTemplate, pk=pk, tenant=tenant)
        return Response(_row(_apply(tenant, t, request.data or {}, request.user, False)))

    def delete(self, request, pk):
        tenant = _admin(request.user)
        t = get_object_or_404(InvoiceTemplate, pk=pk, tenant=tenant)
        audit.record(request.user, "Facturation", "Modèle de facture supprimé", t.name, "")
        t.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
