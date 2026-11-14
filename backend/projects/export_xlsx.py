"""Export Excel structuré de l'état d'un projet (openpyxl), avec filtre de période pour les actions réalisées.

Onglets : Synthèse, Alertes, Phases, Actions, Réalisées (période), En cours, En retard, Équipe & charge,
Temps (période), Budget (profils financiers), Documents. Chaque tableau a un filtre automatique et des
en-têtes figés ; dates et nombres sont typés pour être triés et filtrés dans Excel.
"""
import io
from datetime import date, timedelta

from django.db.models import Sum
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ACTION_STATUSES, Action, Document, TimeEntry
from .planning_view import LABELS, project_alerts, workload
from .workspace import DOC_TYPES, _project, _rights, budget_of, live_phases

ACCENT = "4F46E5"


def _period(request, project, today):
    start = parse_date(str(request.query_params.get("from") or "")) or (project.start_date or today - timedelta(days=30))
    end = parse_date(str(request.query_params.get("to") or "")) or today
    if end < start:
        start, end = end, start
    return start, end


def done_in_period(project, start, end, user=None):
    qs = Action.objects.filter(project=project, status="done").select_related("owner")
    return [t for t in qs if start <= (t.done_at or t.due or date.min) <= end]


class ProjectPeriodView(APIView):
    """Actions réalisées et temps passés sur une période (filtre de dates du reporting)."""

    def get(self, request, pk):
        project = _project(request.user, pk)
        today = timezone.localdate()
        start, end = _period(request, project, today)
        done = done_in_period(project, start, end)
        hours = (TimeEntry.objects.filter(project=project, work_date__range=(start, end)).exclude(approval_status="rejected")
                 .values("person__first_name", "person__last_name", "person__username").annotate(h=Sum("hours")))
        return Response({
            "from": start, "to": end,
            "done": [{"id": t.id, "title": t.title, "owner": t.owner.display_name if t.owner_id else None, "phase": t.phase,
                      "due": t.due, "doneAt": t.done_at or t.due, "est": float(t.est or 0),
                      "onTime": bool(t.due and (t.done_at or t.due) <= t.due)} for t in sorted(done, key=lambda t: t.done_at or t.due)],
            "hours": [{"person": (f"{h['person__first_name']} {h['person__last_name']}".strip() or h["person__username"]),
                       "hours": float(h["h"] or 0)} for h in hours],
        })


class ProjectExcelView(APIView):
    def get(self, request, pk):
        from openpyxl import Workbook
        from openpyxl.chart import BarChart, LineChart, Reference
        from openpyxl.formatting.rule import CellIsRule
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter

        from methodology.models import VPhase

        project = _project(request.user, pk)
        rights = _rights(request.user, project)
        today = timezone.localdate()
        start, end = _period(request, project, today)
        phases = list(VPhase.objects.filter(project=project).select_related("owner").order_by("order", "id"))
        live = live_phases(project, phases, today)
        tasks = list(Action.objects.filter(project=project).select_related("owner").order_by("due", "id"))
        load, weeks = workload(project, tasks, today)
        alerts = project_alerts(project, today, live, tasks, load, with_budget=rights["canSeeMoney"])

        wb = Workbook()
        head_fill = PatternFill("solid", fgColor=ACCENT)
        head_font = Font(bold=True, color="FFFFFF")
        title_font = Font(bold=True, size=16, color="0F172A")
        sub_font = Font(size=10, color="64748B")
        thin = Side(style="thin", color="E2E8F0")
        border = Border(bottom=thin)
        red = PatternFill("solid", fgColor="FEE2E2")
        green = PatternFill("solid", fgColor="DCFCE7")
        amber = PatternFill("solid", fgColor="FEF3C7")

        def sheet(ws, title, headers, rows, widths=None, subtitle=None):
            ws.title = title[:31]
            ws["A1"] = f"{project.code} — {project.name}"
            ws["A1"].font = title_font
            ws["A2"] = subtitle or f"{title} · situation au {today:%d/%m/%Y}"
            ws["A2"].font = sub_font
            r0 = 4
            for c, h in enumerate(headers, 1):
                cell = ws.cell(row=r0, column=c, value=h)
                cell.fill, cell.font = head_fill, head_font
                cell.alignment = Alignment(vertical="center", wrap_text=True)
            for i, row in enumerate(rows, r0 + 1):
                for c, v in enumerate(row, 1):
                    cell = ws.cell(row=i, column=c, value=v)
                    cell.border = border
                    if isinstance(v, date):
                        cell.number_format = "DD/MM/YYYY"
            ws.freeze_panes = ws.cell(row=r0 + 1, column=1)
            if rows:
                ws.auto_filter.ref = f"A{r0}:{get_column_letter(len(headers))}{r0 + len(rows)}"
            for c, w in enumerate(widths or [18] * len(headers), 1):
                ws.column_dimensions[get_column_letter(c)].width = w
            ws.row_dimensions[r0].height = 30
            return r0

        # ---- Synthèse
        ws = wb.active
        ws.title = "Synthèse"
        ws["A1"] = f"État du projet — {project.name}"
        ws["A1"].font = Font(bold=True, size=18, color=ACCENT)
        ws["A2"] = f"Généré le {timezone.localtime():%d/%m/%Y %H:%M} · période analysée du {start:%d/%m/%Y} au {end:%d/%m/%Y}"
        ws["A2"].font = sub_font
        weight = lambda t: float(t.est or 0) or 1.0  # noqa: E731
        total_w = sum(weight(t) for t in tasks)
        real = round(sum(weight(t) for t in tasks if t.status == "done") / total_w * 100) if total_w else 0
        from .workspace import _planned_pct
        pw = [(p, max(1, (p.end - p.start).days)) for p in phases if p.start and p.end]
        planned = round(sum(w * (_planned_pct(p.start, p.end, today) or 0) for p, w in pw) / sum(w for _, w in pw)) if pw else (
            _planned_pct(project.start_date, project.end_date, today) or 0)
        info = [
            ("Projet", f"{project.code} — {project.name}"), ("Client", project.client.name),
            ("Type", project.get_project_type_display()),
            ("Versions", f"{project.base_version or '—'} → {project.target_version or '—'}"),
            ("Méthode", project.method or "—"), ("Chef de projet", project.pm.display_name if project.pm_id else "—"),
            ("Tech Lead", project.tl.display_name if project.tl_id else "—"),
            ("Début", project.start_date), ("Fin", project.end_date), ("", ""),
            ("Avancement prévu (%)", planned), ("Avancement réel (%)", real), ("Écart (points)", real - planned),
            ("Tâches", len(tasks)), ("Terminées", sum(1 for t in tasks if t.status == "done")),
            ("En cours", sum(1 for t in tasks if t.status in ("doing", "review"))),
            ("Bloquées", sum(1 for t in tasks if t.status == "blocked")),
            ("En retard", sum(1 for t in tasks if t.due and t.due < today and t.status != "done")),
            (f"Réalisées du {start:%d/%m} au {end:%d/%m}", len(done_in_period(project, start, end))),
            ("Alertes", len(alerts)),
        ]
        for i, (k, v) in enumerate(info, 4):
            ws.cell(row=i, column=1, value=k).font = Font(bold=True, color="334155")
            c = ws.cell(row=i, column=2, value=v)
            if isinstance(v, date):
                c.number_format = "DD/MM/YYYY"
        ws["B16"].fill = red if real - planned < -10 else (amber if real - planned < 0 else green)
        ws.column_dimensions["A"].width = 30
        ws.column_dimensions["B"].width = 48
        # Graphique statuts
        ws["D4"], ws["E4"] = "Statut", "Tâches"
        for c in ("D4", "E4"):
            ws[c].fill, ws[c].font = head_fill, head_font
        for i, (code, label) in enumerate(ACTION_STATUSES, 5):
            ws.cell(row=i, column=4, value=label)
            ws.cell(row=i, column=5, value=sum(1 for t in tasks if t.status == code))
        ch = BarChart()
        ch.title, ch.y_axis.title = "Tâches par statut", "Nombre"
        ch.add_data(Reference(ws, min_col=5, min_row=4, max_row=4 + len(ACTION_STATUSES)), titles_from_data=True)
        ch.set_categories(Reference(ws, min_col=4, min_row=5, max_row=4 + len(ACTION_STATUSES)))
        ch.height, ch.width, ch.legend = 7, 14, None
        ws.add_chart(ch, "G4")
        ws.column_dimensions["D"].width = 16

        # ---- Alertes
        sheet(wb.create_sheet(), "Alertes", ["Niveau", "Type", "Alerte"],
              [[{"crit": "Critique", "warn": "Attention", "info": "Information"}[a["level"]], a["kind"], a["message"]] for a in alerts],
              [12, 16, 90])

        # ---- Phases (prévu / réel)
        rows = []
        for p in phases:
            lv = live[p.pk]
            pp = _planned_pct(p.start, p.end, today)
            rows.append([p.name, p.owner.display_name if p.owner_id else "", p.start, p.end, p.forecast_end,
                         ((p.forecast_end - p.end).days if p.forecast_end and p.end else 0),
                         pp, lv["progress"], (lv["progress"] - pp) if pp is not None else None,
                         dict(VPhase._meta.get_field("status").choices).get(lv["status"], lv["status"]),
                         f"{lv.get('done', 0)}/{lv.get('tasks', 0)}" if lv.get("live") else "manuel"])
        ws = wb.create_sheet()
        r0 = sheet(ws, "Phases", ["Phase", "Responsable", "Début", "Fin prévue", "Fin réestimée", "Glissement (j)",
                                  "Prévu %", "Réel %", "Écart", "Statut", "Tâches"], rows, [28, 20, 12, 12, 13, 13, 9, 9, 9, 14, 10])
        if rows:
            rng = f"I{r0 + 1}:I{r0 + len(rows)}"
            ws.conditional_formatting.add(rng, CellIsRule(operator="lessThan", formula=["0"], fill=red))
            ws.conditional_formatting.add(rng, CellIsRule(operator="greaterThanOrEqual", formula=["0"], fill=green))
            lc = BarChart()
            lc.type, lc.title = "bar", "Avancement prévu / réel par phase (%)"
            lc.add_data(Reference(ws, min_col=7, max_col=8, min_row=r0, max_row=r0 + len(rows)), titles_from_data=True)
            lc.set_categories(Reference(ws, min_col=1, min_row=r0 + 1, max_row=r0 + len(rows)))
            lc.height, lc.width = 8, 16
            ws.add_chart(lc, "M4")

        def task_rows(items):
            return [[t.id, t.title, t.phase or "", t.owner.display_name if t.owner_id else "", LABELS.get(t.status, t.status),
                     t.prio or "", t.start_date, t.due, t.done_at, float(t.est or 0) or None,
                     (today - t.due).days if t.due and t.due < today and t.status != "done" else 0] for t in items]
        task_head = ["Réf.", "Action", "Phase", "Responsable", "Statut", "Priorité", "Début", "Échéance", "Clôturée le", "Charge (h)", "Retard (j)"]
        task_w = [16, 48, 18, 20, 12, 10, 12, 12, 12, 10, 10]

        ws = wb.create_sheet()
        r0 = sheet(ws, "Actions", task_head, task_rows(tasks), task_w, "Toutes les actions du projet · utilisez les filtres d'en-tête")
        if tasks:
            ws.conditional_formatting.add(f"K{r0 + 1}:K{r0 + len(tasks)}", CellIsRule(operator="greaterThan", formula=["0"], fill=red))
        done = done_in_period(project, start, end)
        sheet(wb.create_sheet(), "Réalisées (période)", task_head, task_rows(done), task_w,
              f"Actions clôturées du {start:%d/%m/%Y} au {end:%d/%m/%Y} ({len(done)})")
        sheet(wb.create_sheet(), "En cours", task_head, task_rows([t for t in tasks if t.status in ("doing", "review", "blocked")]), task_w)
        late = sorted([t for t in tasks if t.due and t.due < today and t.status != "done"], key=lambda t: t.due)
        ws = wb.create_sheet()
        r0 = sheet(ws, "En retard", task_head, task_rows(late), task_w)
        for i in range(len(late)):
            for c in range(1, len(task_head) + 1):
                ws.cell(row=r0 + 1 + i, column=c).fill = red

        # ---- Équipe & charge
        heads = ["Membre", "Actions", "Ouvertes", "En cours", "En retard", "Terminées", "Avancement %", "Reste (h)", "Temps passé (h)"] + \
                [f"S {w:%d/%m} (%)" for w in weeks]
        rows = [[m["name"], m["tasks"], m["open"], m["doing"], m["late"], m["done"], m["progress"], m["remaining"], m["spent"]] +
                [round(w["hours"] / w["capacity"] * 100) if w["capacity"] else None for w in m["weeks"]] for m in load]
        ws = wb.create_sheet()
        r0 = sheet(ws, "Équipe & charge", heads, rows, [24, 9, 9, 9, 9, 9, 12, 10, 13] + [11] * len(weeks),
                   "Plan de charge : charge des actions ouvertes / capacité hebdomadaire (en %)")
        if rows:
            rng = f"J{r0 + 1}:{get_column_letter(len(heads))}{r0 + len(rows)}"
            ws.conditional_formatting.add(rng, CellIsRule(operator="greaterThan", formula=["110"], fill=red))
            ws.conditional_formatting.add(rng, CellIsRule(operator="between", formula=["80", "110"], fill=amber))
            ws.conditional_formatting.add(rng, CellIsRule(operator="between", formula=["1", "79"], fill=green))

        # ---- Temps (période)
        entries = list(TimeEntry.objects.filter(project=project, work_date__range=(start, end)).select_related("person", "action")
                       .order_by("work_date"))
        status_lbl = {"pending": "À valider", "approved": "Validé", "rejected": "Refusé"}
        sheet(wb.create_sheet(), "Temps (période)", ["Date", "Personne", "Action", "Heures", "Statut"],
              [[e.work_date, e.person.display_name, e.action.title if e.action_id else "", float(e.hours), status_lbl.get(e.approval_status, "")]
               for e in entries], [12, 24, 48, 9, 12], f"Temps saisis du {start:%d/%m/%Y} au {end:%d/%m/%Y}")

        # ---- Budget
        if rights["canSeeMoney"]:
            b = budget_of(project)
            ws = wb.create_sheet()
            r0 = sheet(ws, "Budget", ["Membre", "TJM (€)", "Heures validées", "Jours validés", "Consommé (€)", "Heures à valider", "Engagé (€)"],
                       [[x["user"], float(x["dailyRate"] or 0) or None, float(x["hoursApproved"]), float(x["daysApproved"]),
                         float(x["cost"]), float(x["hoursPending"]), float(x["engaged"])] for x in b["rows"]],
                       [24, 10, 14, 12, 14, 15, 13])
            base = r0 + len(b["rows"]) + 2
            for i, (k, v) in enumerate([("Budget validé (€)", b["budget"]), ("Consommé (€)", b["consumed"]), ("Engagé (€)", b["pending"]),
                                        ("Reste (€)", b["remaining"]), ("Taux (%)", b["rate"])]):
                ws.cell(row=base + i, column=1, value=k).font = Font(bold=True)
                ws.cell(row=base + i, column=2, value=float(v) if v is not None else None)
            for row in ws.iter_rows(min_row=r0 + 1, min_col=2, max_col=7):
                for c in row:
                    if c.column in (2, 5, 7):
                        c.number_format = '#,##0 "€"'

        # ---- Documents
        docs = Document.objects.filter(project=project).defer("content", "extracted_text").select_related("uploaded_by")
        if not (request.user.role and request.user.role.internal):
            docs = docs.filter(client_visible=True)
        sheet(wb.create_sheet(), "Documents", ["Document", "Type", "Version", "Déposé par", "Date", "Visible client"],
              [[d.name, dict(DOC_TYPES).get(d.type, d.type), d.version, d.uploaded_by.display_name if d.uploaded_by_id else "",
                d.uploaded_at, "Oui" if d.client_visible else "Non"] for d in docs], [40, 30, 9, 20, 12, 12])

        # ---- Évolution (courbe)
        from .workspace import _evolution
        evo = _evolution(project, phases, tasks, today)
        if evo:
            ws = wb.create_sheet()
            r0 = sheet(ws, "Évolution", ["Semaine", "Prévu %", "Réel %"],
                       [[parse_date(str(p["week"])), p["planned"], p["real"]] for p in evo], [12, 10, 10])
            lc = LineChart()
            lc.title, lc.y_axis.title = "Évolution de l'avancement", "%"
            lc.add_data(Reference(ws, min_col=2, max_col=3, min_row=r0, max_row=r0 + len(evo)), titles_from_data=True)
            lc.set_categories(Reference(ws, min_col=1, min_row=r0 + 1, max_row=r0 + len(evo)))
            lc.height, lc.width = 9, 20
            ws.add_chart(lc, "E4")

        buf = io.BytesIO()
        wb.save(buf)
        resp = HttpResponse(buf.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = f'attachment; filename="etat-projet-{project.code}-{today:%Y%m%d}.xlsx"'
        return resp
