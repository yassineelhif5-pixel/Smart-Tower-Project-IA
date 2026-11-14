"""Envoi du reporting projet par e-mail : contenu au choix, HTML moderne, Gantt et évolution intégrés, pièces jointes.

- options : modules disponibles, membres (destinataires rapides), documents joignables, historique des envois ;
- POST mode « preview » : rendu HTML ; « send » : envoi par le canal e-mail de l'entreprise ; « eml » : brouillon .eml
  à ouvrir dans la messagerie (Outlook, Thunderbird…) ;
- chaque envoi est historisé (et notifié dans la cloche de l'expéditeur), le mail reste consultable.
"""
import base64
import html
import re
import secrets
from datetime import timedelta

from django.core.mail import get_connection
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.errors import ApiError
from configuration import audit
from configuration.models import AppSetting, Notification, NotificationChannel, ServiceSecret

from .models import Action, Defect, Document, Issue, ProjectAccess, Risk

MODULES = [
    ("synthese", "📊", "Synthèse & météo du projet", "Avancement réel / prévu, écart, météo, dates, chef de projet."),
    ("gantt", "🗓️", "Planning Gantt", "Image du planning macro (phases ou lots) intégrée au mail."),
    ("evolution", "📈", "Courbe d'évolution", "Avancement prévu / réel semaine par semaine (image)."),
    ("phases", "🎯", "Phases clés / lots", "Dates, état et avancement de chaque phase."),
    ("late", "⛔", "Actions en retard", "Responsable, échéance, jours de retard."),
    ("doing", "🔄", "Actions en cours", "Ce qui avance en ce moment."),
    ("upcoming", "⏭️", "Prochaines échéances", "Actions à échéance dans les 15 prochains jours."),
    ("done", "✅", "Actions terminées (7 jours)", "Ce qui a été livré récemment."),
    ("budget", "💶", "Budget & consommation", "Budget, consommé, engagé, reste (profils autorisés)."),
    ("risks", "⚠️", "Risques", "Risques ouverts, criticité, plan d'action."),
    ("defects", "🐞", "Anomalies", "Anomalies ouvertes par sévérité."),
    ("issues", "🧩", "Points ouverts", "Problèmes / décisions en attente."),
    ("alerts", "🚨", "Alertes ouvertes", "Alertes lancées par l'équipe et non clôturées."),
    ("team", "👥", "Équipe & charge", "Membres, actions ouvertes, en retard."),
    ("documents", "📂", "Documents récents", "Documents déposés ces 30 derniers jours."),
]
HISTORY_KEY, KEEP = "mail_reports", 40
EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
MAX_ATTACH = 15 * 1024 * 1024

e = html.escape


def _fr(d):
    return d.strftime("%d/%m/%Y") if d else "—"


def _weather(report, late):
    real, planned = report["progress"]["real"], report["progress"]["planned"]
    gap = (real - planned) if real is not None and planned is not None else 0
    if gap >= -5 and late <= 2:
        return "☀️", "Sous contrôle", "#16a34a"
    if gap >= -15 and late <= 8:
        return "⛅", "À surveiller", "#d97706"
    return "🌧️", "En difficulté", "#dc2626"


# --------------------------------------------------------------------------- collecte
def collect(request, project, modules):
    from .project_alerts import alert_details
    from .workspace import ProjectReportView, _rights, budget_of
    today = timezone.localdate()
    rep = ProjectReportView().get(request, project.pk).data
    tasks = list(Action.objects.filter(project=project).select_related("owner"))
    late = sorted([t for t in tasks if t.due and t.due < today and t.status != "done"], key=lambda t: t.due)
    d = {"project": project, "report": rep, "tasks": tasks, "late": late, "today": today}
    if "doing" in modules:
        d["doing"] = sorted([t for t in tasks if t.status in ("doing", "review")], key=lambda t: (t.due is None, t.due))
    if "upcoming" in modules:
        d["upcoming"] = sorted([t for t in tasks if t.due and today <= t.due <= today + timedelta(days=15) and t.status != "done"], key=lambda t: t.due)
    if "done" in modules:
        d["done"] = [t for t in tasks if t.status == "done" and t.done_at and t.done_at >= today - timedelta(days=7)]
    if "budget" in modules and _rights(request.user, project)["canSeeMoney"]:
        d["budget"] = budget_of(project)
    if "risks" in modules:
        d["risks"] = list(Risk.objects.filter(project=project).exclude(status__in=["Clos", "Fermé", "closed", "done"]).select_related("owner")[:20])
    if "defects" in modules:
        d["defects"] = list(Defect.objects.filter(project=project).exclude(status__in=["Clos", "Fermé", "Résolu", "closed", "done"]).select_related("owner")[:25])
    if "issues" in modules:
        d["issues"] = list(Issue.objects.filter(project=project).select_related("owner")[:20])
    if "alerts" in modules:
        d["alerts"] = [a for a in alert_details(project.tenant).values() if a.get("project") == project.id and not a.get("closed")]
    if "team" in modules:
        d["team"] = [(a.user, sum(1 for t in tasks if t.owner_id == a.user_id and t.status != "done"),
                      sum(1 for t in late if t.owner_id == a.user_id))
                     for a in ProjectAccess.objects.filter(project=project).select_related("user", "user__role")]
    if "documents" in modules:
        d["documents"] = list(Document.objects.filter(project=project, uploaded_at__gte=today - timedelta(days=30))
                              .defer("content", "extracted_text").order_by("-uploaded_at")[:15])
    return d


# --------------------------------------------------------------------------- rendu HTML (compatible messageries : tables + styles en ligne)
FONT = "font-family:Segoe UI,Helvetica,Arial,sans-serif;"


def _bar(pct, color, planned=None):
    pct = max(0, min(100, pct or 0))
    marker = (f'<div style="position:relative;height:0"><div style="position:absolute;left:{max(0, min(100, planned))}%;top:-14px;'
              f'width:2px;height:14px;background:#0f172a"></div></div>') if planned is not None else ""
    return (f'<div style="background:#e2e8f0;border-radius:99px;height:10px;overflow:hidden">'
            f'<div style="width:{pct}%;height:10px;background:{color};border-radius:99px"></div></div>{marker}')


def _table(headers, rows, empty="Aucun élément."):
    if not rows:
        return f'<p style="margin:6px 0;color:#94a3b8;font-size:13px">{e(empty)}</p>'
    th = "".join(f'<th style="text-align:left;padding:7px 10px;font-size:11.5px;text-transform:uppercase;letter-spacing:.04em;color:#64748b;border-bottom:2px solid #e2e8f0">{e(h)}</th>' for h in headers)
    trs = ""
    for i, r in enumerate(rows):
        bg = "#f8fafc" if i % 2 else "#ffffff"
        trs += "<tr>" + "".join(f'<td style="padding:7px 10px;font-size:13px;color:#0f172a;border-bottom:1px solid #f1f5f9;background:{bg}">{c}</td>' for c in r) + "</tr>"
    return f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;{FONT}"><tr>{th}</tr>{trs}</table>'


def _section(icon, title, body, count=None):
    badge = f' <span style="background:#eef2ff;color:#4338ca;border-radius:99px;padding:2px 9px;font-size:12px">{count}</span>' if count is not None else ""
    return (f'<tr><td style="padding:18px 28px 4px"><h3 style="margin:0 0 8px;font-size:15.5px;color:#0f172a;{FONT}">{icon} {e(title)}{badge}</h3>'
            f'{body}</td></tr>')


def _pill(text, color):
    return f'<span style="display:inline-block;padding:2px 9px;border-radius:99px;font-size:11.5px;font-weight:600;background:{color}1a;color:{color}">{e(text)}</span>'


PHASE_COLORS = {"done": "#16a34a", "doing": "#2563eb", "late": "#dc2626", "todo": "#64748b", "skipped": "#94a3b8"}


def render_project(d, modules, images, cid):
    p, rep, today = d["project"], d["report"], d["today"]
    real = rep["progress"]["real"] if rep["progress"]["real"] is not None else rep["tasks"]["rate"] or 0
    planned = rep["progress"]["planned"]
    icon, label, wcolor = _weather(rep, len(d["late"]))
    out = (f'<tr><td style="padding:22px 28px 0"><table role="presentation" width="100%" style="border-collapse:collapse"><tr>'
           f'<td style="border-left:5px solid #4f46e5;padding:4px 14px"><div style="font-size:12px;color:#64748b;{FONT}">{e(p.code)} · {e(p.client.name)}</div>'
           f'<div style="font-size:20px;font-weight:700;color:#0f172a;{FONT}">{e(p.name)}</div></td>'
           f'<td align="right" style="{FONT}"><span style="font-size:26px">{icon}</span><br><span style="font-size:12px;font-weight:700;color:{wcolor}">{label}</span></td>'
           f'</tr></table></td></tr>')
    if "synthese" in modules:
        kpi = lambda v, l, c="#0f172a": (f'<td width="25%" style="padding:6px"><div style="background:#f8fafc;border-radius:12px;padding:12px;text-align:center;{FONT}">'  # noqa: E731
                                         f'<div style="font-size:22px;font-weight:800;color:{c}">{v}</div><div style="font-size:11.5px;color:#64748b">{l}</div></div></td>')
        gap = (real - planned) if planned is not None else None
        out += (f'<tr><td style="padding:12px 22px 0"><table role="presentation" width="100%" style="border-collapse:collapse"><tr>'
                + kpi(f"{real} %", "Avancement réel", "#4f46e5") + kpi(f"{planned if planned is not None else '—'} %", "Avancement prévu")
                + kpi(f"{gap:+d} pts" if gap is not None else "—", "Écart", "#16a34a" if (gap or 0) >= 0 else "#dc2626")
                + kpi(str(len(d["late"])), "Actions en retard", "#dc2626" if d["late"] else "#16a34a")
                + "</tr></table>"
                f'<div style="padding:10px 6px 0">{_bar(real, "#4f46e5", planned)}</div>'
                f'<p style="margin:10px 6px 0;font-size:12.5px;color:#475569;{FONT}">{e(rep["project"]["typeLabel"])} · du {_fr(p.start_date)} au {_fr(p.end_date)}'
                f' · Chef de projet : {e(p.pm.display_name if p.pm_id else "—")} · {rep["tasks"]["done"]}/{rep["tasks"]["total"]} actions terminées</p></td></tr>')
    if "gantt" in modules and images.get("gantt"):
        out += _section("🗓️", "Planning Gantt", f'<img src="{images["gantt"]}" alt="Planning Gantt" width="100%" style="display:block;width:100%;max-width:100%;border:1px solid #e2e8f0;border-radius:10px">')
    if "evolution" in modules and images.get(f"evo-{p.id}"):
        out += _section("📈", "Évolution prévu / réel", f'<img src="{images[f"evo-{p.id}"]}" alt="Évolution" width="100%" style="display:block;width:100%;border:1px solid #e2e8f0;border-radius:10px">')
    if "phases" in modules:
        rows = [[f'<b>{e(ph["name"])}</b>', f'{_fr(ph["start"])} → {_fr(ph.get("realEnd") or ph["end"])}',
                 _pill(ph["statusLabel"], PHASE_COLORS.get(ph["status"], "#64748b")), f'<div style="width:110px">{_bar(ph["progress"], PHASE_COLORS.get(ph["status"], "#64748b"))}</div><small>{ph["progress"]} %</small>']
                for ph in rep["phases"]]
        out += _section("🎯", "Phases clés", _table(["Phase", "Dates", "État", "Avancement"], rows, "Pas de planning macro saisi."), len(rows))
    who = lambda t: e(t.owner.display_name) if t.owner_id else '<span style="color:#94a3b8">Non affectée</span>'  # noqa: E731
    if "late" in modules:
        rows = [[f"<b>{e(t.title)}</b>", who(t), _fr(t.due), f'<b style="color:#dc2626">+{(today - t.due).days} j</b>'] for t in d["late"][:25]]
        out += _section("⛔", "Actions en retard", _table(["Action", "Responsable", "Échéance", "Retard"], rows, "Aucune action en retard. ✅"), len(d["late"]))
    if "doing" in modules:
        rows = [[f"<b>{e(t.title)}</b>", who(t), _fr(t.due)] for t in d.get("doing", [])[:25]]
        out += _section("🔄", "Actions en cours", _table(["Action", "Responsable", "Échéance"], rows), len(d.get("doing", [])))
    if "upcoming" in modules:
        rows = [[f"<b>{e(t.title)}</b>", who(t), _fr(t.due)] for t in d.get("upcoming", [])[:25]]
        out += _section("⏭️", "Prochaines échéances (15 jours)", _table(["Action", "Responsable", "Échéance"], rows), len(d.get("upcoming", [])))
    if "done" in modules:
        rows = [[f"<b>{e(t.title)}</b>", who(t), _fr(t.done_at)] for t in d.get("done", [])[:25]]
        out += _section("✅", "Actions terminées ces 7 derniers jours", _table(["Action", "Responsable", "Terminée le"], rows), len(d.get("done", [])))
    if "budget" in modules and d.get("budget"):
        b = d["budget"]
        money = lambda v: f"{float(v):,.0f} €".replace(",", " ") if v is not None else "—"  # noqa: E731
        rate = b.get("rate")
        out += _section("💶", "Budget", (
            _table(["Budget", "Consommé", "Engagé", "Reste"], [[f"<b>{money(b['budget'])}</b>", money(b["consumed"]), money(b["pending"]), money(b["remaining"])]])
            + (f'<div style="padding:10px 0 0">{_bar(rate, "#dc2626" if rate >= 100 else "#d97706" if rate >= 85 else "#16a34a")}'
               f'<small style="color:#475569;{FONT}">{rate} % consommé + engagé</small></div>' if rate is not None else "")))
    if "risks" in modules:
        rows = [[f"<b>{e(r.title)}</b>", f"{(r.prob or 0) * (r.imp or 0)}", e(r.owner.display_name) if r.owner_id else "—", e(r.mitigation[:140] or "—")] for r in d.get("risks", [])]
        out += _section("⚠️", "Risques ouverts", _table(["Risque", "Criticité", "Porteur", "Plan d'action"], rows, "Aucun risque ouvert."), len(rows))
    if "defects" in modules:
        rows = [[f"<b>{e(x.title)}</b>", _pill(x.sev or "—", "#dc2626" if (x.sev or "").lower() in ("bloquant", "critique", "majeur") else "#d97706"), e(x.status or "—"),
                 e(x.owner.display_name) if x.owner_id else "—"] for x in d.get("defects", [])]
        out += _section("🐞", "Anomalies ouvertes", _table(["Anomalie", "Sévérité", "Statut", "Responsable"], rows, "Aucune anomalie ouverte."), len(rows))
    if "issues" in modules:
        rows = [[f"<b>{e(x.title)}</b>", e(x.kind or "—"), e(x.prio or "—"), _fr(x.due)] for x in d.get("issues", [])]
        out += _section("🧩", "Points ouverts", _table(["Point", "Type", "Priorité", "Échéance"], rows, "Aucun point ouvert."), len(rows))
    if "alerts" in modules:
        rows = [[f"<b>{e(a['title'])}</b>", _pill(a["levelLabel"], "#dc2626" if a["level"] == "critical" else "#d97706" if a["level"] == "warning" else "#2563eb"),
                 e(a.get("message", "")[:160] or "—"), e(a["by"])] for a in d.get("alerts", [])]
        out += _section("🚨", "Alertes ouvertes", _table(["Alerte", "Niveau", "Message", "Lancée par"], rows, "Aucune alerte ouverte."), len(rows))
    if "team" in modules:
        rows = [[f"<b>{e(u.display_name)}</b>", e(u.role.label if u.role else "—"), str(o), f'<b style="color:{"#dc2626" if l else "#16a34a"}">{l}</b>'] for u, o, l in d.get("team", [])]
        out += _section("👥", "Équipe & charge", _table(["Membre", "Profil", "Actions ouvertes", "En retard"], rows), len(rows))
    if "documents" in modules:
        from .workspace import DOC_TYPES
        rows = [[f"<b>{e(x.name)}</b>", e(dict(DOC_TYPES).get(x.type, x.type)), f"v{x.version}", _fr(x.uploaded_at)] for x in d.get("documents", [])]
        out += _section("📂", "Documents récents (30 jours)", _table(["Document", "Type", "Version", "Déposé le"], rows, "Aucun document récent."), len(rows))
    return out + '<tr><td style="padding:14px 28px 0"><div style="border-top:1px dashed #e2e8f0"></div></td></tr>'


def render_email(datas, modules, images, sender, message, subject):
    today = timezone.localdate()
    intro = f'<p style="margin:0;font-size:14px;line-height:1.6;color:#334155;{FONT}">{e(message).replace(chr(10), "<br>")}</p>' if message else ""
    body = "".join(render_project(d, modules, images, f"g{i}") for i, d in enumerate(datas))
    return f"""<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{e(subject)}</title></head>
<body style="margin:0;padding:0;background:#f1f5f9;{FONT}">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f1f5f9;padding:24px 0"><tr><td align="center">
<table role="presentation" width="760" cellspacing="0" cellpadding="0" style="max-width:760px;width:100%;background:#ffffff;border-radius:18px;overflow:hidden;box-shadow:0 6px 24px rgba(15,23,42,.08)">
<tr><td style="background:linear-gradient(135deg,#0f172a,#4f46e5 60%,#0ea5e9);background-color:#4338ca;padding:26px 28px">
<div style="font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#c7d2fe;{FONT}">Smart Tower · Reporting projet</div>
<div style="font-size:24px;font-weight:800;color:#ffffff;margin-top:4px;{FONT}">{e(subject)}</div>
<div style="font-size:13px;color:#e0e7ff;margin-top:6px;{FONT}">Situation au {_fr(today)} · {len(datas)} projet(s) · envoyé par {e(sender)}</div>
</td></tr>
{f'<tr><td style="padding:22px 28px 0">{intro}</td></tr>' if intro else ''}
{body}
<tr><td style="padding:18px 28px 26px;font-size:11.5px;color:#94a3b8;{FONT}">Ce reporting a été généré par Smart Tower (Project Control Tower). Les chiffres reflètent l'état du projet au moment de l'envoi.</td></tr>
</table></td></tr></table></body></html>"""


def html_to_text(h):
    t = re.sub(r"<(br|/tr|/p|/h3|/div)[^>]*>", "\n", h)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"[ \t]+", " ", html.unescape(t)).strip()


# --------------------------------------------------------------------------- historique
def _history(tenant):
    row = AppSetting.objects.filter(tenant=tenant, key=HISTORY_KEY).first()
    return row, (row.value if row and isinstance(row.value, list) else [])


def save_history(tenant, entry):
    row, items = _history(tenant)
    items = [entry] + items[: KEEP - 1]
    if row:
        row.value = items
        row.save(update_fields=["value", "updated_at"])
    else:
        AppSetting.objects.create(tenant=tenant, key=HISTORY_KEY, value=items)


# --------------------------------------------------------------------------- vues
def _projects(request, ids):
    from .workspace import _project
    out = []
    for pk in ids[:10]:
        try:
            out.append(_project(request.user, pk))
        except Exception:  # noqa: BLE001
            continue
    if not out:
        raise ApiError("VALIDATION_ERROR", "Sélectionnez au moins un projet accessible.")
    return out


class MailReportOptionsView(APIView):
    def get(self, request):
        from .workspace import _rights
        projects = _projects(request, [i for i in str(request.query_params.get("ids") or "").split(",") if i])
        money = any(_rights(request.user, p)["canSeeMoney"] for p in projects)
        members = {}
        for a in ProjectAccess.objects.filter(project__in=projects, user__is_active=True).select_related("user", "user__role"):
            if a.user.email:
                members[a.user.email] = {"name": a.user.display_name, "email": a.user.email, "role": a.user.role.label if a.user.role else ""}
        docs = [{"id": d.pk, "name": f"{d.name}{'.' + d.ext if d.ext and not d.name.lower().endswith('.' + d.ext) else ''}",
                 "project": d.project_id, "size": d.size_bytes, "type": d.type}
                for d in Document.objects.filter(project__in=projects).defer("content", "extracted_text").order_by("-uploaded_at")[:60]
                if d.size_bytes]
        _, hist = _history(request.user.tenant)
        channel = NotificationChannel.objects.filter(tenant=request.user.tenant, kind="email", enabled=True).exists()
        names = ", ".join(p.name for p in projects)
        return Response({
            "modules": [{"code": c, "icon": i, "label": l, "help": h, "available": c != "budget" or money} for c, i, l, h in MODULES],
            "defaults": ["synthese", "gantt", "evolution", "phases", "late", "doing"],
            "members": sorted(members.values(), key=lambda m: m["name"]), "documents": docs, "channel": channel,
            "subject": f"Reporting {names} — {_fr(timezone.localdate())}"[:200],
            "projects": [{"id": p.id, "name": p.name, "code": p.code} for p in projects],
            "history": [{k: v for k, v in h.items() if k != "html"} for h in hist if h.get("byId") == request.user.pk or request.user.is_app_admin][:15],
        })


class MailReportView(APIView):
    def post(self, request):
        user = request.user
        data = request.data
        mode = data.get("mode") or "preview"
        projects = _projects(request, data.get("projects") or [])
        modules = [m for m in (data.get("modules") or []) if m in {c for c, *_ in MODULES}]
        if not modules:
            raise ApiError("VALIDATION_ERROR", "Choisissez au moins un élément à envoyer.")
        subject = (str(data.get("subject") or "").strip() or "Reporting projet")[:200]
        message = str(data.get("message") or "")[:3000]
        to = [x.strip() for x in data.get("to") or [] if str(x).strip()]
        cc = [x.strip() for x in data.get("cc") or [] if str(x).strip()]
        bad = [x for x in to + cc if not EMAIL_RE.match(x)]
        if bad:
            raise ApiError("VALIDATION_ERROR", f"Adresse(s) e-mail invalide(s) : {', '.join(bad[:5])}.")
        if mode == "send" and not to:
            raise ApiError("VALIDATION_ERROR", "Indiquez au moins un destinataire.")
        if len(to) + len(cc) > 30:
            raise ApiError("VALIDATION_ERROR", "30 destinataires maximum.")
        # Images générées par le navigateur (data:image/png;base64,…).
        raw_images = {k: v for k, v in (data.get("images") or {}).items() if isinstance(v, str) and v.startswith("data:image/png;base64,")}
        datas = [collect(request, p, modules) for p in projects]
        if mode == "preview":
            return Response({"html": render_email(datas, modules, raw_images, user.display_name, message, subject)})

        # Images intégrées (CID) + pièces jointes.
        cids, inline = {}, []
        for k, v in raw_images.items():
            try:
                blob = base64.b64decode(v.split(",", 1)[1])
            except Exception:  # noqa: BLE001
                continue
            cid = f"{k}-{secrets.token_hex(4)}@smarttower"
            cids[k] = f"cid:{cid}"
            inline.append((cid, blob, k))
        html_body = render_email(datas, modules, cids, user.display_name, message, subject)
        attach = data.get("attach") or {}
        files, total = [], 0
        for cid, blob, k in inline:
            if (k == "gantt" and attach.get("gantt")) or (k.startswith("evo-") and attach.get("evolution")):
                files.append((f"{'planning-gantt' if k == 'gantt' else 'evolution-' + k[4:]}.png", blob, "image/png"))
        for pid in attach.get("excel") or []:
            p = next((x for x in projects if x.id == pid), None)
            if p:
                from .export_xlsx import ProjectExcelView
                resp = ProjectExcelView().get(request, p.id)
                files.append((f"reporting-{p.code}.xlsx", resp.content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
        if attach.get("documents"):
            for doc in Document.objects.filter(project__in=projects, pk__in=attach["documents"]):
                if doc.content is None:
                    continue
                name = doc.name if not doc.ext or doc.name.lower().endswith(f".{doc.ext}") else f"{doc.name}.{doc.ext}"
                files.append((name, bytes(doc.content), doc.mime or "application/octet-stream"))
        total = sum(len(b) for _, b, _ in files) + sum(len(b) for _, b, _ in inline)
        if total > MAX_ATTACH:
            raise ApiError("VALIDATION_ERROR", f"Pièces jointes trop volumineuses ({total // 1048576} Mo) : 15 Mo maximum.")

        channel = NotificationChannel.objects.filter(tenant=user.tenant, kind="email", enabled=True).first()
        sender = (channel.settings.get("from_address") if channel else None) or user.email or "no-reply@smarttower.local"
        from email.message import EmailMessage as MimeMessage
        from email.utils import formatdate, make_msgid
        msg = MimeMessage()
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = ", ".join(to)
        if cc:
            msg["Cc"] = ", ".join(cc)
        if user.email:
            msg["Reply-To"] = user.email
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="smarttower")
        msg.set_content(html_to_text(html_body))
        msg.add_alternative(html_body, subtype="html")
        html_part = msg.get_payload()[1]
        for cid, blob, k in inline:
            html_part.add_related(blob, "image", "png", cid=f"<{cid}>", filename=f"{k}.png")
        for name, blob, mime in files:
            main, _, sub = (mime or "application/octet-stream").partition("/")
            msg.add_attachment(blob, maintype=main, subtype=sub or "octet-stream", filename=name)
        entry = {"id": f"M{secrets.token_hex(4).upper()}", "at": timezone.now().isoformat(), "by": user.display_name, "byId": user.pk,
                 "to": to, "cc": cc, "subject": subject, "projects": [p.name for p in projects], "projectIds": [p.id for p in projects],
                 "modules": modules, "attachments": [n for n, _, _ in files], "mode": mode, "status": "draft" if mode == "eml" else "sent",
                 "html": render_email(datas, modules, raw_images, user.display_name, message, subject)[:600000]}
        if mode == "eml":
            msg["X-Unsent"] = "1"  # Outlook ouvre le fichier comme un brouillon prêt à envoyer
            raw = msg.as_bytes()
            save_history(user.tenant, entry)
            resp = HttpResponse(raw, content_type="message/rfc822")
            resp["Content-Disposition"] = f'attachment; filename="reporting-{timezone.localdate().isoformat()}.eml"'
            return resp
        if channel is None:
            raise ApiError("VALIDATION_ERROR", "Le canal e-mail de l'entreprise n'est pas activé (Configuration › Notifications). "
                                               "Utilisez « Ouvrir dans ma messagerie » ou demandez à l'administrateur d'activer l'envoi.")
        conf = channel.settings
        try:
            connection = get_connection("django.core.mail.backends.smtp.EmailBackend", host=conf.get("host"), port=int(conf.get("port") or 587),
                                        username=conf.get("username") or None, password=ServiceSecret.value_of(channel.tenant_id, "smtp_password"),
                                        use_tls=conf.get("security", "starttls") == "starttls", use_ssl=conf.get("security") == "ssl", timeout=20)
            connection.open()
            connection.connection.sendmail(sender, to + cc, msg.as_bytes())
            connection.close()
        except Exception as exc:  # noqa: BLE001
            entry.update({"status": "failed", "error": type(exc).__name__})
            save_history(user.tenant, entry)
            raise ApiError("VALIDATION_ERROR", f"Envoi impossible ({type(exc).__name__}) : vérifiez le serveur SMTP dans Configuration › Notifications.") from exc
        save_history(user.tenant, entry)
        Notification.objects.create(
            user=user, event="project_alert", title=f"📧 Reporting envoyé : {subject}"[:200],
            body=(f"À : {', '.join(to)}" + (f" · Cc : {', '.join(cc)}" if cc else "") + f" · {len(modules)} rubrique(s), {len(files)} pièce(s) jointe(s)"
                  f" · #MAIL:{entry['id']} · {projects[0].id}")[:2000])
        for p in projects:
            audit.record(user, f"Projet {p.code}", "Reporting envoyé par e-mail", "", f"{subject} → {', '.join(to)[:300]}", tenant=user.tenant)
        return Response({k: v for k, v in entry.items() if k != "html"})


class MailReportDetailView(APIView):
    def get(self, request, mail_id):
        _, hist = _history(request.user.tenant)
        m = next((h for h in hist if h["id"] == mail_id), None)
        if m is None or not (m.get("byId") == request.user.pk or request.user.is_app_admin):
            raise ApiError("NOT_FOUND", "E-mail introuvable.", status.HTTP_404_NOT_FOUND)
        return Response(m)
