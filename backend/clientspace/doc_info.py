"""Code technique unique des documents et panneau d'historique.

Chaque document généré ou intégré a un code technique stable et unique :
  DOC-CRA-<période>-<id>, DOC-FAC-<période>-<id>, DOC-RPT-<période>-<id> (rapport budgétaire), DOC-AUT-<période>-<id>,
  CMD-<id> (bon de commande), CTR-<id> (contrat de support), TPL-<id> (modèle de facture intégré).
GET /client-space/doc-info?ref=<id document | order:<id> | contract:<id> | template:<id>>
  → nom, type, client, personne, période, version, auteur, dates, taille, versions de la série, événements (journal
    d'audit : génération, régénération, consultations…) et code technique.
"""
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.errors import ApiError
from configuration.models import AuditEvent

from . import billing
from .models import ClientDocument, InvoiceTemplate, SupportContract

KIND_CODE = {"cra": "CRA", "invoice": "FAC"}
ST = {"pending": "en attente", "accepted": "acceptée", "rejected": "refusée", "delivered": "livrée"}
KIND_LABEL = {"cra": "Compte rendu d'activité", "invoice": "Facture", "budget": "Rapport budgétaire", "other": "Document"}


def doc_code(d):
    if d.meta.get("code"):
        return d.meta["code"]
    kind = KIND_CODE.get(d.kind) or ("RPT" if d.meta.get("category") == "budget" else "AUT")
    per = (d.period or (d.created_at.strftime("%Y-%m") if d.created_at else "")).replace("-", "")
    return f"DOC-{kind}-{per}-{d.pk}"


def _events(tenant, needles, entity=None, extra=None, limit=60):
    q = Q()
    for n in needles:
        if n:
            q |= Q(new_value__icontains=n) | Q(old_value__icontains=n)
    if extra is not None:
        q |= extra
    if not q:
        return []
    qs = AuditEvent.objects.filter(tenant=tenant).filter(q).select_related("actor").order_by("-at")[:limit]
    return [{"at": e.at, "by": e.actor.display_name if e.actor else "Système", "event": e.event,
             "detail": (e.new_value or e.old_value)[:160]} for e in qs]


def _size(n):
    n = int(n or 0)
    return f"{n / 1024:.1f} Ko" if n < 1024 * 1024 else f"{n / 1024 / 1024:.2f} Mo"


class DocInfoView(APIView):
    def get(self, request):
        from .views import _clients_for, _guard, _readable
        user = request.user
        ref = str(request.query_params.get("ref") or "")
        tenant = user.tenant
        if ref.startswith("order:"):
            from .client_portal import _orders, _projects
            oid = ref.split(":", 1)[1]
            ids = {p.id for p in _projects(user)}
            o = next((x for x in _orders(tenant) if x["id"] == oid and (set(x.get("projects") or []) & ids or user.is_app_admin)), None)
            if o is None:
                raise ApiError("NOT_FOUND", "Document introuvable.", status.HTTP_404_NOT_FOUND)
            hist = [{"at": o.get("at"), "by": o.get("by", ""), "event": "Commande créée", "detail": f"{o.get('item') or o.get('kindLabel')} × {o.get('quantity')}"}]
            hist += [{"at": h.get("at"), "by": h.get("by", ""), "event": f"Statut : {ST.get(h.get('to') or h.get('status'), h.get('to') or h.get('status'))}", "detail": h.get("comment", "")} for h in (o.get("history") or [])]
            return Response({"code": f"CMD-{oid.upper()}", "name": f"Bon de commande {oid.upper()}", "type": "Bon de commande",
                             "fields": [["Article", o.get("item") or o.get("kindLabel")], ["Quantité", f"{o.get('quantity')} {o.get('unit', '')}"],
                                        ["Projets", ", ".join(o.get("projectNames") or [])], ["Commandé par", o.get("by", "")], ["Statut", o.get("status", "")]],
                             "createdAt": o.get("at"), "versions": [], "events": sorted(hist, key=lambda x: str(x["at"]), reverse=True)})
        if ref.startswith("contract:"):
            _guard(user)
            c = get_object_or_404(SupportContract.objects.select_related("client", "updated_by"), pk=ref.split(":", 1)[1].lstrip("SC"),
                                  client__in=_clients_for(user))
            return Response({"code": f"CTR-{c.pk:06d}", "name": f"Contrat de support — {c.client.name}", "type": "Contrat de support",
                             "fields": [["Client", c.client.name], ["Niveaux", ", ".join(c.levels or [])],
                                        ["Période", f"{c.starts_on or '…'} → {c.ends_on or '…'}"], ["Modifié par", c.updated_by.display_name if c.updated_by else "—"]],
                             "createdAt": c.updated_at, "versions": [],
                             "events": _events(tenant, [], extra=Q(entity=f"Client {c.client.name}", event__icontains="support"))})
        if ref.startswith("template:"):
            if not user.is_app_admin:
                raise ApiError("FORBIDDEN_PERMISSION", "Réservé à l'administrateur.", status.HTTP_403_FORBIDDEN)
            t = get_object_or_404(InvoiceTemplate, pk=ref.split(":", 1)[1], tenant=tenant)
            return Response({"code": f"TPL-{t.pk:06d}", "name": t.name, "type": "Modèle de facture (intégré)",
                             "fields": [["Fichier", t.filename], ["Portée", t.get_scope_display()], ["Taille", _size(t.size_bytes)],
                                        ["Déposé par", t.uploaded_by.display_name if t.uploaded_by else "—"]],
                             "createdAt": t.created_at, "updatedAt": t.updated_at, "versions": [], "events": _events(tenant, [t.name])})
        qs = ClientDocument.objects.filter(tenant=tenant).select_related("client", "person")
        d = qs.filter(pk=ref).first()
        if d is None or not (user.is_app_admin or d.person_id == user.id or _readable(user).filter(pk=d.pk).exists()):
            raise ApiError("NOT_FOUND", "Document introuvable.", status.HTTP_404_NOT_FOUND)
        from .client_rates import hide_amounts
        hidden = d.kind == "cra" and hide_amounts(user, [d.client_id])
        series = qs.filter(kind=d.kind, client=d.client, person=d.person, period=d.period).order_by("-version") if d.kind in ("cra", "invoice") else [d]
        versions = [{"id": x.pk, "version": x.version, "name": x.name, "createdAt": x.created_at, "by": x.meta.get("generatedBy", ""),
                     "code": doc_code(x), "current": x.pk == d.pk} for x in series]
        names = [x.name for x in series] + [doc_code(x) for x in series]
        extra = None
        if d.person_id and d.period:
            extra = Q(entity=f"Client {d.client.name}", new_value__icontains=d.person.display_name) & Q(new_value__icontains=billing.label(d.period))
        cat = d.meta.get("category") if d.kind == "other" else d.kind
        fields = [["Type", KIND_LABEL.get(cat, "Document")], ["Client", d.client.name], ["Personne", d.person.display_name if d.person_id else "—"],
                  ["Période", billing.label(d.period) if d.period else "—"], ["Version", f"v{d.version}"], ["Numéro", d.number or "—"],
                  ["Projets", ", ".join(d.meta.get("projects", [])) or "—"], ["Généré par", d.meta.get("generatedBy", "—")],
                  ["Validé par", ", ".join(d.meta.get("approvers", [])) or "—"], ["Format", "PDF" if d.mime == "application/pdf" else "Word (.docx)"],
                  ["Taille", _size(d.size_bytes)]]
        if d.amount_ht is not None and not hidden:
            fields.append(["Montant HT", billing.eur(d.amount_ht)])
        if d.meta.get("noInvoice"):
            fields.append(["Facturation", d.meta["noInvoice"]])
        if d.meta.get("template"):
            fields.append(["Modèle", d.meta["template"]])
        return Response({"code": doc_code(d), "id": d.pk, "name": d.name, "type": KIND_LABEL.get(cat, "Document"), "fields": fields,
                         "createdAt": d.created_at, "updatedAt": d.updated_at, "versions": versions,
                         "events": _events(tenant, names, extra=extra)})
