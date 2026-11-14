import { BudgetReport } from "../features/budget/BudgetReport";
import { AiUsageReport } from "../features/aiusage/AiUsageReport";
import { useEffect, useRef, useState } from "react";

import { api, API_BASE } from "../api/client";
import { useApi } from "../api/useApi";
import { Card, ErrorNotice, Loading, PageHead } from "../components/ui";
import { AssistantButton } from "../features/assistant/ProjectAssistant";
import { PlanningAlerts, planningApi } from "../features/planning/DetailedPlanning";
import type { Me } from "../types/api";

type Phase = {
  id: number; name: string; start: string | null; end: string | null; forecastEnd: string | null; realEnd: string | null;
  status: string; statusLabel: string; progress: number; plannedProgress: number | null; gap: number | null;
  owner: string | null; slipDays: number; tasks: number; tasksDone: number; live: boolean;
};
type Report = {
  generatedAt: string; today: string;
  project: { id: string; code: string; name: string; client: string; pm: string | null; start: string | null; end: string | null;
    typeLabel: string; baseVersion: string; targetVersion?: string; methodology: { kind: string; label: string; features: string[] } };
  progress: { planned: number | null; real: number | null; gap: number | null };
  phases: Phase[]; milestones: { title: string; date: string; status: string }[];
  tasks: { total: number; done: number; rate: number | null; late: number; byStatus: Record<string, number>; statusLabels: Record<string, string>;
    lateList: { id: string; title: string; due: string; owner: string | null }[] };
  hours: string | number;
  evolution?: { week: string; planned: number | null; real: number | null }[];
  budget?: { budget: string | null; consumed: string; pending: string; remaining: string | null; rate: number | null };
};

const DAY = 86400000;
const toD = (s: string) => new Date(`${String(s).slice(0, 10)}T00:00:00`);
const fr = (s: string | null) => (s ? toD(s).toLocaleDateString("fr-FR") : "—");
const money = (v: string | null | undefined) =>
  v === null || v === undefined ? "—" : Number(v).toLocaleString("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const STATUS_COLOR: Record<string, string> = { done: "#10b981", late: "#ef4444", doing: "#6366f1", todo: "#94a3b8", skipped: "#cbd5e1" };

function projectFromHash() {
  const [, id] = window.location.hash.replace("#", "").split("/");
  return id ? decodeURIComponent(id) : "";
}

export function ReportingPage({ me }: { me: Me }) {
  const projects = useApi(() => api.get<{ id: string; code: string; name: string }[]>("/projects"));
  const [pid, setPid] = useState(projectFromHash);
  useEffect(() => {
    if (projects.data && !projects.data.some((p) => p.id === pid)) setPid(projects.data[0]?.id ?? "");
  }, [projects.data, pid]);
  useEffect(() => {
    if (pid) window.history.replaceState(null, "", `#reporting/${encodeURIComponent(pid)}`);
  }, [pid]);
  const report = useApi(() => (pid && projects.data?.some((p) => p.id === pid) ? api.get<Report>(`/projects/${encodeURIComponent(pid)}/report`) : Promise.resolve(null)), [pid, projects.data]);

  return (
    <div className="page">
      <PageHead
        eyebrow={me.tenant?.name ?? ""}
        title="Reporting d’avancement"
        sub="Planning macro (prévu / réel), avancement, tâches, jalons et budget. Calculé à partir de l’état actuel du projet ; exportable en PDF ou en image."
        right={
          projects.data && projects.data.length > 0 && (
            <select className="inp" aria-label="Projet" value={pid} onChange={(e) => setPid(e.target.value)}>
              {projects.data.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.code} — {p.name}
                </option>
              ))}
            </select>
          )
        }
      />
      {projects.error && <ErrorNotice error={projects.error} onRetry={projects.reload} />}
      {projects.data && projects.data.length === 0 && <div className="empty">Aucun projet dans votre périmètre.</div>}
      {report.error && <ErrorNotice error={report.error} onRetry={report.reload} />}
      {pid && !report.data && !report.error && <Loading />}
      {report.data && <ReportView r={report.data} />}
      {report.data && pid && <BudgetReport key={pid} projectId={pid} />}
      {report.data && pid && <AiUsageReport key={`ai-${pid}`} projectId={pid} />}
    </div>
  );
}

function ReportView({ r }: { r: Report }) {
  const ganttRef = useRef<SVGSVGElement>(null);
  const planning = useApi(() => planningApi(r.project.id), [r.project.id]);
  const monthAgo = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
  const [range, setRange] = useState({ from: monthAgo, to: r.today });
  const period = useApi(
    () =>
      api.get<{ from: string; to: string; done: { id: string; title: string; owner: string | null; phase: string; due: string | null; doneAt: string | null; est: number; onTime: boolean }[]; hours: { person: string; hours: number }[] }>(
        `/projects/${encodeURIComponent(r.project.id)}/period?from=${range.from}&to=${range.to}`,
      ),
    [r.project.id, range.from, range.to],
  );
  const excelHref = `${API_BASE}/projects/${encodeURIComponent(r.project.id)}/export.xlsx?from=${range.from}&to=${range.to}`;
  const [exporting, setExporting] = useState(false);
  const evoRef = useRef<SVGSVGElement>(null);
  const svgImage = async (svg: SVGSVGElement) => {
    const xml = new XMLSerializer().serializeToString(svg);
    const img = new Image();
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error("image"));
      img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(xml)}`;
    });
    return { img, w: svg.viewBox.baseVal.width, h: svg.viewBox.baseVal.height };
  };
  /** Image complète de l'état du projet : en-tête, indicateurs, alertes, Gantt, évolution, tâches en cours. */
  const exportPng = async () => {
    setExporting(true);
    try {
      const W = 1200, M = 40, scale = 2;
      const gantt = ganttRef.current ? await svgImage(ganttRef.current) : null;
      const evo = evoRef.current ? await svgImage(evoRef.current) : null;
      const doing = planning.data?.doing ?? [];
      const alerts = planning.data?.alerts ?? [];
      const gh = gantt ? (gantt.h * (W - 2 * M)) / gantt.w : 0;
      const eh = evo ? (evo.h * (W - 2 * M)) / evo.w : 0;
      const H = 190 + Math.min(alerts.length, 6) * 22 + 40 + (gantt ? gh + 50 : 0) + (evo ? eh + 50 : 0) + 50 + Math.max(1, doing.length) * 26 + 60;
      const canvas = document.createElement("canvas");
      canvas.width = W * scale;
      canvas.height = H * scale;
      const c = canvas.getContext("2d")!;
      c.scale(scale, scale);
      c.fillStyle = "#ffffff";
      c.fillRect(0, 0, W, H);
      const font = "Inter, Segoe UI, Arial, sans-serif";
      const text = (t: string, x: number, y: number, size = 14, color = "#0f172a", weight = "400") => {
        c.font = `${weight} ${size}px ${font}`;
        c.fillStyle = color;
        c.fillText(t, x, y);
      };
      c.fillStyle = "#4f46e5";
      c.fillRect(0, 0, W, 6);
      text(`${r.project.code} · ${r.project.client}`.toUpperCase(), M, 40, 12, "#4f46e5", "700");
      text(r.project.name, M, 72, 28, "#0f172a", "800");
      text(`${r.project.typeLabel} · ${r.project.methodology.label} · Chef de projet : ${r.project.pm ?? "—"} · Situation au ${fr(r.today)}`, M, 98, 13, "#64748b");
      const kpis: [string, string][] = [
        ["Avancement prévu", `${r.progress.planned ?? "—"} %`],
        ["Avancement réel", `${r.progress.real ?? "—"} %`],
        ["Tâches terminées", `${r.tasks.done}/${r.tasks.total}`],
        r.budget ? ["Budget consommé", r.budget.rate !== null ? `${r.budget.rate} %` : money(r.budget.consumed)] : ["Tâches en retard", String(r.tasks.late)],
      ];
      const kw = (W - 2 * M - 3 * 16) / 4;
      kpis.forEach(([l, v], i) => {
        const x = M + i * (kw + 16);
        c.fillStyle = "#f6f7fb";
        c.fillRect(x, 118, kw, 62);
        text(l.toUpperCase(), x + 14, 140, 10.5, "#64748b", "700");
        text(v, x + 14, 168, 22, i === 1 && (r.progress.gap ?? 0) < 0 ? "#dc2626" : "#0f172a", "800");
      });
      let y = 210;
      if (alerts.length) {
        text("Alertes", M, y, 15, "#dc2626", "700");
        y += 8;
        alerts.slice(0, 6).forEach((a) => {
          y += 22;
          text(`${a.level === "crit" ? "●" : "○"} ${a.message}`, M + 6, y, 12.5, a.level === "crit" ? "#dc2626" : "#b45309");
        });
        y += 30;
      }
      if (gantt) {
        text("Planning macro : prévu / réel", M, y, 15, "#0f172a", "700");
        c.drawImage(gantt.img, M, y + 12, W - 2 * M, gh);
        y += gh + 50;
      }
      if (evo) {
        text("Évolution de l’avancement (prévu / réel)", M, y, 15, "#0f172a", "700");
        c.drawImage(evo.img, M, y + 12, W - 2 * M, eh);
        y += eh + 50;
      }
      text(`Tâches en cours (${doing.length})`, M, y, 15, "#0f172a", "700");
      y += 10;
      if (!doing.length) {
        y += 24;
        text("Aucune tâche en cours.", M + 6, y, 12.5, "#64748b");
      }
      doing.forEach((t) => {
        y += 26;
        text(`• ${t.title}`, M + 6, y, 13, t.late ? "#dc2626" : "#0f172a", "600");
        text(`${t.owner ?? "Non affectée"} · ${t.statusLabel} · échéance ${fr(t.due)} · ${t.progress} %${t.late ? ` · ${t.lateDays} j de retard` : ""}`, M + 420, y, 12, "#64748b");
      });
      text(`Généré le ${new Date().toLocaleString("fr-FR")} · Project Control Tower`, M, H - 20, 11, "#94a3b8");
      const a = document.createElement("a");
      a.download = `etat-projet-${r.project.code}-${r.today}.png`;
      a.href = canvas.toDataURL("image/png");
      a.click();
    } finally {
      setExporting(false);
    }
  };
  const gap = r.progress.gap;
  return (
    <>
      <div className="btns rp-actions no-print">
        <button className="btn primary" type="button" onClick={() => window.print()} title="Choisissez « Enregistrer au format PDF » dans la fenêtre d’impression">
          ⤓ Exporter en PDF
        </button>
        <button className="btn" type="button" disabled={exporting || !planning.data} onClick={exportPng}>
          {exporting ? "Export…" : "⤓ Exporter en image (PNG)"}
        </button>
        <a className="btn" href={excelHref} title="Classeur structuré : synthèse, phases, actions, réalisées sur la période, retards, charge, temps, budget, documents">
          ⤓ Exporter en Excel
        </a>
      </div>
      <div className="rp-sheet" id="report-sheet">
        <div className="rp-title">
          <div>
            <span className="eyebrow">
              {r.project.code} · {r.project.client}
            </span>
            <h2 className="pj-title">
              {r.project.name} <span className="no-print"><AssistantButton projectId={r.project.id} projectName={r.project.name} /></span>
            </h2>
            <p className="muted">
              {r.project.typeLabel}
              {r.project.baseVersion || r.project.targetVersion ? ` (${r.project.baseVersion || "—"} → ${r.project.targetVersion || "—"})` : ""} · {r.project.methodology.label} · Chef de projet : {r.project.pm ?? "—"} ·{" "}
              {fr(r.project.start)} → {fr(r.project.end)}
            </p>
          </div>
          <small className="muted">Situation au {fr(r.today)}</small>
        </div>
        <div className="kpis pj-kpis">
          <div className="kpi">
            <label>Avancement prévu</label>
            <strong>{r.progress.planned ?? "—"} %</strong>
            <small>selon les dates</small>
          </div>
          <div className={`kpi${gap !== null && gap < -10 ? " crit" : gap !== null && gap < 0 ? " warn" : " ok"}`}>
            <label>Avancement réel</label>
            <strong>{r.progress.real ?? "—"} %</strong>
            <small>{gap === null ? "—" : gap >= 0 ? `+${gap} pts d’avance` : `${gap} pts de retard`}</small>
          </div>
          <div className={`kpi${r.tasks.late ? " warn" : ""}`}>
            <label>Tâches</label>
            <strong>
              {r.tasks.done}/{r.tasks.total}
            </strong>
            <small>{r.tasks.late} en retard</small>
          </div>
          {r.budget ? (
            <div className={`kpi${r.budget.rate !== null && r.budget.rate > 100 ? " crit" : ""}`}>
              <label>Budget consommé</label>
              <strong>{r.budget.rate !== null ? `${r.budget.rate} %` : money(r.budget.consumed)}</strong>
              <small>
                {money(r.budget.consumed)} / {money(r.budget.budget)}
              </small>
            </div>
          ) : (
            <div className="kpi">
              <label>Temps passé</label>
              <strong>{Number(r.hours)} h</strong>
              <small>saisies validées et à valider</small>
            </div>
          )}
        </div>
        {planning.data && <PlanningAlerts alerts={planning.data.alerts} max={8} />}
        <Card title="Planning macro : prévu / réel" sub="Barre claire : planning prévu. Barre colorée : réalisé (avancement réel). Hachures : glissement. Losanges : jalons.">
          {r.phases.length === 0 ? (
            <div className="empty">Aucune phase : le chef de projet saisit le planning macro dans Pilotage › Planning macro.</div>
          ) : (
            <div className="rp-gantt">
              <GanttSvg r={r} svgRef={ganttRef} />
            </div>
          )}
        </Card>
        {r.evolution && r.evolution.length > 1 && (
          <Card title="Évolution de l’avancement" sub="Courbe violette : prévu (selon les dates). Courbe verte : réel (tâches clôturées). Mise à jour à chaque clôture de tâche.">
            <div className="rp-gantt">
              <EvolutionSvg points={r.evolution} today={r.today} svgRef={evoRef} />
            </div>
          </Card>
        )}
        <Card title={`Tâches en cours (${planning.data?.doing.length ?? 0})`}>
          {!planning.data ? (
            <Loading />
          ) : planning.data.doing.length === 0 ? (
            <div className="empty">Aucune tâche en cours.</div>
          ) : (
            <table className="tbl tight">
              <thead>
                <tr>
                  <th>Tâche</th>
                  <th>Qui</th>
                  <th>Statut</th>
                  <th>Échéance</th>
                  <th className="r">Avancement</th>
                </tr>
              </thead>
              <tbody>
                {planning.data.doing.map((t) => (
                  <tr key={t.id}>
                    <td>
                      <b>{t.title}</b>
                    </td>
                    <td>{t.owner ?? "—"}</td>
                    <td>{t.statusLabel}</td>
                    <td className={t.late ? "t-crit" : ""}>
                      {fr(t.due)}
                      {t.late ? ` (+${t.lateDays} j)` : ""}
                    </td>
                    <td className="r">{t.progress} %</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card
          title="Actions réalisées sur la période"
          sub="Filtrez par dates : la liste, les temps passés et l’export Excel suivent la période choisie."
          extra={
            <div className="rp-range no-print">
              <label>
                Du <input className="inp" type="date" value={range.from} max={range.to} onChange={(e) => e.target.value && setRange({ ...range, from: e.target.value })} />
              </label>
              <label>
                au <input className="inp" type="date" value={range.to} min={range.from} onChange={(e) => e.target.value && setRange({ ...range, to: e.target.value })} />
              </label>
            </div>
          }
        >
          {!period.data ? (
            <Loading />
          ) : (
            <>
              <p className="muted" style={{ margin: "0 0 10px", fontSize: 12.5 }}>
                Du {fr(period.data.from)} au {fr(period.data.to)} : <b>{period.data.done.length}</b> action(s) réalisée(s),{" "}
                <b>{period.data.done.filter((d) => d.onTime).length}</b> dans les délais ·{" "}
                {period.data.hours.reduce((a, h) => a + h.hours, 0)} h saisies
                {period.data.hours.length ? ` (${period.data.hours.map((h) => `${h.person} ${h.hours} h`).join(", ")})` : ""}
              </p>
              {period.data.done.length === 0 ? (
                <div className="empty">Aucune action clôturée sur cette période.</div>
              ) : (
                <table className="tbl tight">
                  <thead>
                    <tr>
                      <th>Action</th>
                      <th>Responsable</th>
                      <th>Phase</th>
                      <th>Échéance</th>
                      <th>Clôturée le</th>
                      <th>Délai</th>
                    </tr>
                  </thead>
                  <tbody>
                    {period.data.done.map((d) => (
                      <tr key={d.id}>
                        <td>
                          <b>{d.title}</b>
                        </td>
                        <td>{d.owner ?? "—"}</td>
                        <td>{d.phase || "—"}</td>
                        <td>{fr(d.due)}</td>
                        <td>{fr(d.doneAt)}</td>
                        <td className={d.onTime ? "t-ok" : "t-warn"}>{d.due ? (d.onTime ? "Respecté" : "Dépassé") : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
        </Card>
        {r.phases.length > 0 && (
          <Card title="Écart par phase">
            <table className="tbl tight">
              <thead>
                <tr>
                  <th>Phase</th>
                  <th>Responsable</th>
                  <th>Prévu</th>
                  <th>Fin réestimée</th>
                  <th className="r">Prévu %</th>
                  <th className="r">Réel %</th>
                  <th className="r">Écart</th>
                  <th>Tâches</th>
                  <th>Statut</th>
                </tr>
              </thead>
              <tbody>
                {r.phases.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <b>{p.name}</b>
                    </td>
                    <td>{p.owner ?? "—"}</td>
                    <td>
                      {fr(p.start)} → {fr(p.end)}
                    </td>
                    <td className={p.slipDays > 0 ? "t-crit" : ""}>
                      {fr(p.forecastEnd)}
                      {p.slipDays > 0 ? ` (+${p.slipDays} j)` : ""}
                    </td>
                    <td className="r">{p.plannedProgress ?? "—"} %</td>
                    <td className="r">{p.progress} %</td>
                    <td className={`r ${p.gap !== null && p.gap < 0 ? "t-crit" : "t-ok"}`}>{p.gap === null ? "—" : `${p.gap > 0 ? "+" : ""}${p.gap}`}</td>
                    <td>{p.live ? `${p.tasksDone}/${p.tasks}` : <span className="faint">saisie manuelle</span>}</td>
                    <td>
                      <span style={{ color: STATUS_COLOR[p.status] }}>● </span>
                      {p.statusLabel}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
        <div className="grid g2">
          <Card title="Tâches par statut">
            {Object.entries(r.tasks.byStatus).map(([k, n]) => (
              <div key={k} className="rp-bar">
                <span>{r.tasks.statusLabels[k]}</span>
                <div className="bar">
                  <i style={{ width: `${r.tasks.total ? (n / r.tasks.total) * 100 : 0}%`, background: k === "blocked" ? "#ef4444" : k === "done" ? "#10b981" : undefined }} />
                </div>
                <b>{n}</b>
              </div>
            ))}
          </Card>
          <Card title="Points d’attention">
            {r.tasks.lateList.length === 0 && r.milestones.length === 0 ? (
              <div className="empty">Aucune tâche en retard.</div>
            ) : (
              <ul className="plain rp-list">
                {r.tasks.lateList.map((t) => (
                  <li key={t.id}>
                    <span className="t-crit">En retard</span> {t.title} — échéance {fr(t.due)} {t.owner ? `· ${t.owner}` : ""}
                  </li>
                ))}
                {r.milestones.map((m) => (
                  <li key={`${m.title}${m.date}`}>
                    <span className="t-warn">◆ Jalon</span> {m.title} — {fr(m.date)}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
        <p className="muted rp-foot">Généré le {new Date(r.generatedAt).toLocaleString("fr-FR")} · Project Control Tower</p>
      </div>
    </>
  );
}

/** Gantt en SVG (exportable en image) : planning prévu, réalisé, glissement, jalons et ligne du jour. */
function GanttSvg({ r, svgRef }: { r: Report; svgRef: React.RefObject<SVGSVGElement | null> }) {
  const dates = [
    ...r.phases.flatMap((p) => [p.start, p.end, p.forecastEnd]),
    ...r.milestones.map((m) => m.date),
    r.project.start, r.project.end, r.today,
  ].filter(Boolean) as string[];
  const min = toD(dates.reduce((a, b) => (a < b ? a : b)));
  const max = toD(dates.reduce((a, b) => (a > b ? a : b)));
  const from = new Date(min.getFullYear(), min.getMonth(), 1).getTime();
  const to = new Date(max.getFullYear(), max.getMonth() + 1, 1).getTime();
  const L = 230, W = 1000, row = 34, head = 30;
  const rows = r.phases.length + (r.milestones.length ? 1 : 0);
  const H = head + rows * row + 12;
  const x = (s: string | number) => L + (((typeof s === "number" ? s : toD(s).getTime()) - from) / (to - from)) * (W - L - 10);
  const months: number[] = [];
  for (let d = new Date(from); d.getTime() < to; d = new Date(d.getFullYear(), d.getMonth() + 1, 1)) months.push(d.getTime());
  const font = "Inter, Segoe UI, Arial, sans-serif";
  return (
    <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} width="100%" xmlns="http://www.w3.org/2000/svg" fontFamily={font} role="img" aria-label="Gantt prévu / réel">
      <rect x="0" y="0" width={W} height={H} fill="#ffffff" />
      {months.map((m, i) => (
        <g key={m}>
          <line x1={x(m)} y1={0} x2={x(m)} y2={H} stroke="#e6e8f0" />
          <text x={x(m) + 4} y={19} fontSize="10.5" fill="#64748b" fontWeight="600">
            {new Date(m).toLocaleDateString("fr-FR", { month: "short", year: months.length > 12 || i === 0 ? "2-digit" : undefined }).toUpperCase()}
          </text>
        </g>
      ))}
      <line x1={0} y1={head} x2={W} y2={head} stroke="#d5d9e4" />
      {r.phases.map((p, i) => {
        const y = head + i * row;
        const late = p.forecastEnd && p.end && p.forecastEnd > p.end;
        const color = STATUS_COLOR[p.status] ?? "#6366f1";
        return (
          <g key={p.id}>
            {i % 2 === 1 && <rect x={0} y={y} width={W} height={row} fill="#f8fafc" />}
            <text x={10} y={y + 15} fontSize="12" fontWeight="700" fill="#0f172a">
              {p.name.length > 30 ? `${p.name.slice(0, 29)}…` : p.name}
            </text>
            <text x={10} y={y + 28} fontSize="10" fill="#64748b">
              {p.progress} % réel · {p.plannedProgress ?? "—"} % prévu{p.live ? ` · ${p.tasksDone}/${p.tasks} tâches` : ""}
            </text>
            {p.start && p.end && (
              <>
                <rect x={x(p.start)} y={y + 6} width={Math.max(3, x(p.end) + (W - L) / ((to - from) / DAY) - x(p.start))} height={10} rx={3} fill="#c7d2fe" />
                <rect x={x(p.start)} y={y + 18} width={Math.max(2, (x(p.realEnd ?? p.end) + (W - L) / ((to - from) / DAY) - x(p.start)) * (p.progress / 100))} height={10} rx={3} fill={color} />
                {late && (
                  <rect x={x(p.end)} y={y + 18} width={Math.max(2, x(p.forecastEnd!) - x(p.end))} height={10} rx={3} fill="none" stroke="#ef4444" strokeDasharray="3 2" />
                )}
              </>
            )}
          </g>
        );
      })}
      {r.milestones.length > 0 && (
        <g>
          <text x={10} y={head + r.phases.length * row + 20} fontSize="12" fontWeight="700" fill="#0f172a">
            Jalons
          </text>
          {r.milestones.map((m) => {
            const cx = x(m.date);
            const cy = head + r.phases.length * row + 16;
            return (
              <g key={`${m.title}${m.date}`}>
                <rect x={cx - 6} y={cy - 6} width={12} height={12} fill="#f59e0b" transform={`rotate(45 ${cx} ${cy})`} />
                <title>{`${m.title} · ${fr(m.date)}`}</title>
              </g>
            );
          })}
        </g>
      )}
      <line x1={x(r.today)} y1={head - 6} x2={x(r.today)} y2={H - 6} stroke="#7c3aed" strokeWidth={2} />
      <text x={x(r.today) + 4} y={H - 8} fontSize="10" fill="#7c3aed" fontWeight="700">
        Aujourd’hui
      </text>
    </svg>
  );
}


/** Courbes d'avancement prévu / réel par semaine (SVG exportable). */
function EvolutionSvg({ points, today, svgRef }: { points: { week: string; planned: number | null; real: number | null }[]; today: string; svgRef: React.RefObject<SVGSVGElement | null> }) {
  const W = 1000, H = 260, L = 44, R = 16, T = 14, B = 34;
  const x = (i: number) => L + (i / Math.max(1, points.length - 1)) * (W - L - R);
  const y = (v: number) => T + (1 - v / 100) * (H - T - B);
  const path = (key: "planned" | "real") =>
    points
      .map((p, i) => (p[key] === null ? null : `${x(i)},${y(p[key]!)}`))
      .filter(Boolean)
      .join(" ");
  const ti = points.findIndex((p) => p.week > today) - 1;
  const step = Math.max(1, Math.ceil(points.length / 12));
  return (
    <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} width="100%" xmlns="http://www.w3.org/2000/svg" fontFamily="Inter, Segoe UI, Arial, sans-serif" role="img" aria-label="Évolution de l’avancement">
      <rect width={W} height={H} fill="#ffffff" />
      {[0, 25, 50, 75, 100].map((v) => (
        <g key={v}>
          <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="#e6e8f0" />
          <text x={L - 8} y={y(v) + 4} fontSize="10.5" textAnchor="end" fill="#64748b">
            {v} %
          </text>
        </g>
      ))}
      {points.map((p, i) =>
        i % step === 0 ? (
          <text key={p.week} x={x(i)} y={H - 12} fontSize="10" textAnchor="middle" fill="#64748b">
            {new Date(`${p.week}T00:00:00`).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" })}
          </text>
        ) : null,
      )}
      {ti >= 0 && <line x1={x(ti)} x2={x(ti)} y1={T} y2={H - B} stroke="#7c3aed" strokeDasharray="4 3" />}
      <polyline points={path("planned")} fill="none" stroke="#6366f1" strokeWidth={2.5} strokeDasharray="6 4" />
      <polyline points={path("real")} fill="none" stroke="#10b981" strokeWidth={3} />
      {points.map((p, i) => (p.real !== null ? <circle key={i} cx={x(i)} cy={y(p.real)} r={3} fill="#10b981" /> : null))}
      <g transform={`translate(${L + 10},${T + 8})`}>
        <rect width="190" height="40" rx="6" fill="#ffffff" stroke="#e6e8f0" />
        <line x1="10" x2="34" y1="14" y2="14" stroke="#6366f1" strokeWidth="2.5" strokeDasharray="6 4" />
        <text x="40" y="18" fontSize="11" fill="#0f172a">Prévu</text>
        <line x1="10" x2="34" y1="30" y2="30" stroke="#10b981" strokeWidth="3" />
        <text x="40" y="34" fontSize="11" fill="#0f172a">Réel (tâches clôturées)</text>
      </g>
    </svg>
  );
}
