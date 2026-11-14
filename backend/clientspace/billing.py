"""CRA et factures mensuels : un CRA + une facture par consultant, par client et par mois, tous projets du client confondus.

Générés automatiquement quand toutes les saisies du mois sont validées (circuit complet : valideur interne, puis client si
l'entreprise l'exige) et que le mois est terminé ; régénérés en nouvelle version si une saisie change ensuite (le numéro de
facture est conservé). Valorisation : jours × TJM du consultant sur le projet (à défaut, TJM du niveau de support).
"""
import calendar
import hashlib
import json
import secrets
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from configuration.models import AppSetting
from planning.services import hours_per_day
from projects.models import Client, ProjectAccess, TimeEntry

from . import docx
from .models import LEVEL_ROLE, ClientDocument, SupportContract

MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
Q2 = Decimal("0.01")
BILLING_KEY, SEQ_KEY, RUN_KEY = "billing", "invoice_sequence", "billing_run_state"
DEFAULTS = {"vatRate": 20, "paymentDays": 30, "prefix": "FAC", "siret": "", "vatNumber": "", "legalForm": "", "capital": "",
            "iban": "", "auto": True,
            "legalNotice": ("Paiement à {days} jours date de facture, par virement. Pas d'escompte pour paiement anticipé. "
                            "En cas de retard de paiement : pénalités au taux égal à trois fois le taux d'intérêt légal et indemnité "
                            "forfaitaire de 40 € pour frais de recouvrement (articles L441-10 et D441-5 du Code de commerce).")}


class BillingError(Exception):
    pass


def settings_of(tenant):
    row = AppSetting.objects.filter(tenant=tenant, key=BILLING_KEY).first()
    v = row.value if row and isinstance(row.value, dict) else {}
    return {**DEFAULTS, **{k: v[k] for k in DEFAULTS if k in v}}


def save_settings(tenant, data):
    conf = settings_of(tenant)
    for k in DEFAULTS:
        if k in data:
            conf[k] = data[k]
    conf["vatRate"] = float(conf["vatRate"] or 0)
    conf["paymentDays"] = int(conf["paymentDays"] or 30)
    conf["auto"] = bool(conf["auto"])
    AppSetting.objects.update_or_create(tenant=tenant, key=BILLING_KEY, defaults={"value": conf})
    return conf


def bounds(period):
    y, m = (int(x) for x in period.split("-"))
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def label(period):
    y, m = (int(x) for x in period.split("-"))
    return f"{MONTHS[m - 1]} {y}"


def entries(tenant, person_id, client, period):
    first, last = bounds(period)
    return (TimeEntry.objects.filter(tenant=tenant, person_id=person_id, project__client=client, work_date__range=(first, last))
            .exclude(approval_status="rejected").select_related("project", "action", "approved_by"))


def state(tenant, person_id, client, period):
    qs = list(entries(tenant, person_id, client, period))
    counts = defaultdict(int)
    for e in qs:
        counts[e.approval_status] += 1
    return qs, dict(counts)


def rate_for(person, project):
    acc = ProjectAccess.objects.filter(project=project, user=person).first()
    if acc and acc.daily_rate is not None:
        return acc.daily_rate
    contract = SupportContract.objects.filter(client_id=project.client_id, enabled=True).first()
    if contract:
        level = next((lv for lv, role in LEVEL_ROLE.items() if role == person.role_id), None)
        if level and contract.rates.get(level) not in (None, ""):
            return Decimal(str(contract.rates[level]))
    return None


def client_users(tenant, client, projects=()):
    User = get_user_model()
    ids = set(User.objects.filter(tenant=tenant, is_active=True, client_id=client.pk, role__internal=False).values_list("pk", flat=True))
    ids |= set(ProjectAccess.objects.filter(project__in=projects, user__is_active=True, user__role__internal=False).values_list("user_id", flat=True))
    return list(User.objects.filter(pk__in=ids))


def readers_for(tenant, client, person, projects):
    """Consultant, chefs de projet, commerciaux du client et des projets, comptes du client."""
    User = get_user_model()
    ids = {person.pk}
    ids |= {p.pm_id for p in projects if p.pm_id}
    ids |= set(client.sales.values_list("pk", flat=True))
    ids |= set(ProjectAccess.objects.filter(project__in=projects, user__role_id="commercial", user__is_active=True).values_list("user_id", flat=True))
    ids |= {u.pk for u in client_users(tenant, client, projects)}
    return list(User.objects.filter(pk__in=ids, is_active=True))


def _next_number(tenant, prefix, year):
    row, _ = AppSetting.objects.select_for_update().get_or_create(tenant=tenant, key=SEQ_KEY, defaults={"value": {}})
    seq = dict(row.value or {})
    n = int(seq.get(str(year), 0)) + 1
    seq[str(year)] = n
    row.value = seq
    row.save(update_fields=["value"])
    return f"{prefix}-{year}-{n:04d}"


def eur(x):
    return f"{Decimal(x).quantize(Q2):,.2f} €".replace(",", " ").replace(".", ",")


def num(x):
    return f"{Decimal(x).quantize(Q2):.2f}".replace(".", ",")


def generate(tenant, person, client, period, by=None, force=False):
    """Génère (ou régénère) le CRA et la facture. `force` autorise un mois non terminé, jamais des saisies non validées."""
    qs, counts = state(tenant, person.pk, client, period)
    if not qs:
        raise BillingError("Aucune saisie de temps sur ce mois pour ce client.")
    waiting = counts.get("pending", 0) + counts.get("client", 0)
    if waiting:
        raise BillingError(f"{waiting} saisie(s) restent à valider (chef de projet ou client).")
    first, last = bounds(period)
    if not force and timezone.localdate() <= last:
        raise BillingError("Le mois n'est pas terminé.")
    hpd = hours_per_day(tenant) or Decimal("8")
    projects = sorted({e.project for e in qs}, key=lambda p: p.code)
    per_project = {}
    days_rows, tasks = [], defaultdict(lambda: Decimal("0"))
    approvers = set()
    for e in sorted(qs, key=lambda e: (e.work_date, e.project.code)):
        pp = per_project.setdefault(e.project.pk, {"project": e.project, "hours": Decimal("0"), "rate": rate_for(person, e.project)})
        pp["hours"] += e.hours
        days_rows.append([e.work_date.strftime("%a %d/%m").replace("Mon", "lun.").replace("Tue", "mar.").replace("Wed", "mer.")
                          .replace("Thu", "jeu.").replace("Fri", "ven.").replace("Sat", "sam.").replace("Sun", "dim."),
                          e.project.code, (e.action.title if e.action_id else ("Réunion" if e.is_meeting else "Activité générale"))[:70],
                          num(e.hours), num(e.hours / hpd)])
        tasks[(e.project.code, e.action.title if e.action_id else "Activité générale")] += e.hours
        if e.approved_by_id:
            approvers.add(e.approved_by.display_name)
    lines, total_ht, total_days = [], Decimal("0"), Decimal("0")
    missing_rate = []
    for pp in per_project.values():
        d = (pp["hours"] / hpd).quantize(Q2)
        rate = pp["rate"]
        if rate is None:
            missing_rate.append(pp["project"].code)
        amount = (d * rate).quantize(Q2) if rate is not None else Decimal("0")
        lines.append((pp["project"], d, rate, amount))
        total_ht += amount
        total_days += d
    if missing_rate:
        raise BillingError(f"TJM manquant pour {person.display_name} sur : {', '.join(missing_rate)} (Projet → Équipe → TJM).")
    digest = hashlib.sha256(json.dumps([[r for r in days_rows], [str(l[2]) for l in lines]], default=str).encode()).hexdigest()[:16]
    existing = ClientDocument.objects.filter(client=client, person=person, period=period, kind="cra").order_by("-version").first()
    if existing and existing.meta.get("hash") == digest:
        return existing, ClientDocument.objects.filter(client=client, person=person, period=period, kind="invoice").order_by("-version").first(), False
    conf = settings_of(tenant)
    vat = Decimal(str(conf["vatRate"]))
    total_vat = (total_ht * vat / 100).quantize(Q2)
    total_ttc = total_ht + total_vat
    version = (existing.version + 1) if existing else 1
    today = timezone.localdate()
    role = person.role.label if person.role else ""
    validation = "Validé par : " + (", ".join(sorted(approvers)) or "circuit automatique")
    readers = readers_for(tenant, client, person, projects)
    with transaction.atomic():
        old_inv = ClientDocument.objects.filter(client=client, person=person, period=period, kind="invoice").order_by("-version").first()
        number = old_inv.number if old_inv else _next_number(tenant, conf["prefix"] or "FAC", first.year)
        # --- CRA
        cra_blocks = [docx.p(f"Compte rendu d'activité — {label(period).capitalize()}", "Title"),
                      docx.p(f"Consultant : {person.display_name}{f' ({role})' if role else ''}", bold=True),
                      docx.p(f"Client : {client.name} · Prestataire : {tenant.name} · Période : du {first:%d/%m/%Y} au {last:%d/%m/%Y}"),
                      docx.p(f"{validation} · Version {version} · Facture associée : {number}", color="64748B", size=18),
                      docx.p("Synthèse par projet", "Heading1"),
                      docx.table([["Projet", "Jours", "TJM HT", "Montant HT"]]
                                 + [[f"{p.code} — {p.name}", num(d), eur(r), eur(a)] for p, d, r, a in lines]
                                 + [["Total", num(total_days), "", eur(total_ht)]], [4800, 1400, 1700, 1700], total=True),
                      docx.p("Récapitulatif de l'activité par tâche", "Heading1"),
                      docx.table([["Projet", "Tâche / activité", "Heures", "Jours"]]
                                 + [[k[0], k[1][:80], num(h), num(h / hpd)] for k, h in sorted(tasks.items(), key=lambda x: -x[1])],
                                 [1600, 5400, 1300, 1300]),
                      docx.p("Détail jour par jour", "Heading1"),
                      docx.table([["Date", "Projet", "Tâche", "Heures", "Jours"]] + days_rows, [1500, 1600, 4300, 1100, 1100], small=True),
                      docx.p(f"Total du mois : {num(total_days)} jour(s) — {eur(total_ht)} HT", bold=True),
                      docx.p("Visa du consultant : ____________________    Visa du chef de projet : ____________________    Visa du client : ____________________", size=18)]
        cra_bytes = docx.build(f"CRA {person.display_name} {label(period)}", cra_blocks)
        # --- Facture
        seller = [tenant.name, tenant.address, " ".join(x for x in [tenant.city, tenant.country] if x),
                  f"{conf['legalForm']}" + (f" au capital de {conf['capital']}" if conf["capital"] else ""),
                  f"SIRET : {conf['siret']}" if conf["siret"] else "", f"TVA intracommunautaire : {conf['vatNumber']}" if conf["vatNumber"] else "",
                  tenant.contact_email]
        due = today + timedelta(days=int(conf["paymentDays"]))
        inv_blocks = [docx.p(f"FACTURE N° {number}", "Title"),
                      *[docx.p(x, size=18) for x in seller if x and x.strip()],
                      docx.p(""),
                      docx.p(f"Facturé à : {client.name}" + (f", {client.city}" if client.city else ""), bold=True),
                      docx.p(f"Date de facture : {today:%d/%m/%Y} · Échéance : {due:%d/%m/%Y} · Période : {label(period)}"),
                      docx.p(f"Objet : prestations de {person.display_name}{f' ({role})' if role else ''} — compte rendu d'activité joint (version {version})."),
                      docx.table([["Désignation", "Quantité (j)", "Prix unitaire HT", "Montant HT"]]
                                 + [[f"Prestation {p.code} — {p.name}", num(d), eur(r), eur(a)] for p, d, r, a in lines]
                                 + [["Total HT", num(total_days), "", eur(total_ht)]], [4800, 1400, 1700, 1700], total=True),
                      docx.table([["", "Montant"], ["Total HT", eur(total_ht)], [f"TVA {num(vat)} %", eur(total_vat)], ["Total TTC", eur(total_ttc)]],
                                 [7900, 1700], total=True),
                      docx.p(f"IBAN : {conf['iban']}" if conf["iban"] else "", size=18),
                      docx.p(conf["legalNotice"].replace("{days}", str(conf["paymentDays"])), size=16, color="64748B")]
        inv_bytes = docx.build(f"Facture {number}", inv_blocks)
        common = {"tenant": tenant, "client": client, "person": person, "period": period, "version": version, "days": total_days,
                  "amount_ht": total_ht, "vat_rate": vat, "amount_ttc": total_ttc}
        meta = {"hash": digest, "projects": [p.code for p in projects], "generatedBy": by.display_name if by else "automatique",
                "approvers": sorted(approvers), "number": number}
        slug = person.display_name.replace(" ", "-")
        cra = ClientDocument.objects.create(id=f"CD{secrets.token_hex(6).upper()}", kind="cra", content=cra_bytes, size_bytes=len(cra_bytes),
                                            name=f"{period}_CRA_{slug}_{client.pk}_v{version}.docx", meta=meta, number=number, **common)
        inv = ClientDocument.objects.create(id=f"CD{secrets.token_hex(6).upper()}", kind="invoice", content=inv_bytes, size_bytes=len(inv_bytes),
                                            name=f"{period}_Facture_{number}_{slug}_v{version}.docx", meta={**meta, "cra": cra.pk, "due": str(due)},
                                            number=number, **common)
        cra.readers.set(readers)
        inv.readers.set(readers)
    from configuration import audit
    audit.record(by, f"Client {client.name}", "CRA et facture générés", "", f"{person.display_name} · {label(period)} · {number} v{version}",
                 tenant=tenant)
    from projects.timesheet_reminders import _send
    for u in readers:
        _send(u, f"CRA et facture de {label(period)} disponibles — {person.display_name}",
              f"Le compte rendu d'activité de {person.display_name} pour {client.name} ({label(period)}, {num(total_days)} j, "
              f"{eur(total_ht)} HT) et la facture {number} sont disponibles dans l'Espace client"
              + (" (nouvelle version)" if version > 1 else "") + ".")
    return cra, inv, True


def try_generate(tenant, person_id, client_id, period, by=None):
    """Génération automatique si le mois est complet et entièrement validé ; silencieuse sinon."""
    if not settings_of(tenant)["auto"]:
        return None
    User = get_user_model()
    person = User.objects.filter(pk=person_id).select_related("role").first()
    client = Client.objects.filter(pk=client_id, tenant=tenant).first()
    if person is None or client is None:
        return None
    try:
        return generate(tenant, person, client, period, by)
    except BillingError:
        return None


def run_monthly(tenant, today=None):
    """Une fois par jour : génère les CRA du mois précédent (et rattrape ceux de l'avant-dernier mois)."""
    today = today or timezone.localdate()
    row, _ = AppSetting.objects.get_or_create(tenant=tenant, key=RUN_KEY, defaults={"value": {}})
    if (row.value or {}).get("last") == today.isoformat():
        return []
    row.value = {"last": today.isoformat()}
    row.save(update_fields=["value"])
    done = []
    first_this = today.replace(day=1)
    for back in (1, 2):
        ref = (first_this - timedelta(days=1)) if back == 1 else ((first_this - timedelta(days=1)).replace(day=1) - timedelta(days=1))
        period = f"{ref:%Y-%m}"
        a, b = bounds(period)
        combos = (TimeEntry.objects.filter(tenant=tenant, work_date__range=(a, b)).exclude(approval_status="rejected")
                  .values_list("person_id", "project__client_id").distinct())
        for person_id, client_id in combos:
            res = try_generate(tenant, person_id, client_id, period)
            if res and res[2]:
                done.append((person_id, client_id, period))
    return done
