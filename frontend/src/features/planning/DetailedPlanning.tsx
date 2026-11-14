import { api } from "../../api/client";
import { Card } from "../../components/ui";

export type Alert = { level: "crit" | "warn" | "info"; kind: string; message: string; ref: string };
type PTask = {
  id: string; title: string; status: string; statusLabel: string; owner: string | null; start: string | null; due: string | null;
  est: number; spent: number; raf: number | null; progress: number; late: boolean; lateDays: number;
};
type Load = {
  id: number; name: string; tasks: number; open: number; done: number; doing: number; late: number; remaining: number; spent: number;
  progress: number | null; weeks: { week: string; hours: number; capacity: number }[];
};
export type PlanningData = {
  today: string; weeks: string[];
  groups: { phase: string; live: { progress?: number; status?: string; tasks?: number; done?: number }; tasks: PTask[] }[];
  workload: Load[]; alerts: Alert[]; doing: PTask[];
};

export const planningApi = (id: string) => api.get<PlanningData>(`/projects/${encodeURIComponent(id)}/planning`);

const toD = (s: string) => new Date(`${String(s).slice(0, 10)}T00:00:00`);
const fr = (s: string | null) => (s ? toD(s).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" }) : "—");
const ICON = { crit: "⛔", warn: "⚠️", info: "ℹ️" } as const;

/** Bandeau d'alertes (délais dépassés, glissements, blocages, surcharge, budget). */
export function PlanningAlerts({ alerts, max = 6 }: { alerts: Alert[]; max?: number }) {
  if (!alerts.length)
    return (
      <div className="callout ok" role="status">
        ✅ Aucun dépassement de délai : le planning est tenu.
      </div>
    );
  const crit = alerts.filter((a) => a.level === "crit").length;
  return (
    <div className={`pl-alerts ${crit ? "crit" : "warn"}`} role="alert">
      <b>
        {crit ? `${crit} alerte(s) critique(s)` : `${alerts.length} point(s) d’attention`} sur le planning
      </b>
      <ul>
        {alerts.slice(0, max).map((a) => (
          <li key={`${a.kind}-${a.ref}-${a.message}`} className={`pl-a-${a.level}`}>
            <span aria-hidden="true">{ICON[a.level]}</span> {a.message}
          </li>
        ))}
        {alerts.length > max && <li className="faint">… et {alerts.length - max} autre(s)</li>}
      </ul>
    </div>
  );
}

/** Planning détaillé sous le planning macro : en cours, Gantt des tâches par phase, plan de charge. */
export function DetailedPlanning({ data: p }: { data: PlanningData }) {
  const all = p.groups.flatMap((g) => g.tasks);
  const dates = all.flatMap((t) => [t.start, t.due]).filter(Boolean) as string[];
  dates.push(p.today);
  const min = toD(dates.reduce((a, b) => (a < b ? a : b))).getTime() - 3 * 86400000;
  const max = toD(dates.reduce((a, b) => (a > b ? a : b))).getTime() + 4 * 86400000;
  const pos = (s: string) => ((toD(s).getTime() - min) / (max - min)) * 100;
  const today = pos(p.today);

  return (
    <>
      <Card title="Tâches en cours" sub="Qui fait quoi en ce moment.">
        {p.doing.length === 0 ? (
          <div className="empty">Aucune tâche en cours.</div>
        ) : (
          <div className="pl-doing">
            {p.doing.map((t) => (
              <div key={t.id} className={`pl-chip pl-${t.status}${t.late ? " late" : ""}`}>
                <b>{t.title}</b>
                <small>
                  {t.owner ?? "Non affectée"} · {t.statusLabel} · échéance {fr(t.due)}
                  {t.late ? ` · ${t.lateDays} j de retard` : ""}
                </small>
                <div className="bar">
                  <i style={{ width: `${t.progress}%` }} />
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title="Planning détaillé" sub="Tâches par phase : période, responsable et avancement (temps passé / charge estimée). En rouge : délai dépassé.">
        {all.length === 0 ? (
          <div className="empty">Aucune tâche : ajoutez-en dans Mes projets › Tâches et rattachez-les aux phases.</div>
        ) : (
          <div className="pl-gantt">
            {p.groups.map((g) => (
              <div key={g.phase} className="pl-group">
                <div className="pl-group-h">
                  <b>{g.phase}</b>
                  {g.live?.tasks ? (
                    <small>
                      {g.live.done}/{g.live.tasks} tâches · {g.live.progress} %
                    </small>
                  ) : (
                    <small className="faint">{g.tasks.length} tâche(s)</small>
                  )}
                </div>
                {g.tasks.map((t) => {
                  const s = t.start ?? t.due ?? p.today;
                  const e = t.due ?? t.start ?? p.today;
                  return (
                    <div key={t.id} className="pl-row">
                      <div className="pl-label">
                        <span className={`pl-dot pl-${t.status}`} />
                        <span className="pl-title" title={t.title}>
                          {t.title}
                        </span>
                        <small>{t.owner ?? "—"}</small>
                      </div>
                      <div className="pl-track">
                        {today >= 0 && today <= 100 && <i className="gt-today" style={{ left: `${today}%` }} />}
                        <span
                          className={`pl-bar pl-${t.status}${t.late ? " late" : ""}`}
                          style={{ left: `${pos(s)}%`, width: `${Math.max(1.5, pos(e) - pos(s) + 100 / ((max - min) / 86400000))}%` }}
                          title={`${t.title} · ${t.owner ?? "non affectée"} · ${fr(t.start)} → ${fr(t.due)} · ${t.progress} %`}
                        >
                          <em style={{ width: `${t.progress}%` }} />
                        </span>
                        <span className="pl-pct" style={{ left: `calc(${Math.min(92, pos(e) + 100 / ((max - min) / 86400000))}% + 4px)` }}>
                          {t.progress} %{t.late ? ` · +${t.lateDays} j` : ""}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title="Plan de charge" sub="Charge restante des tâches ouvertes répartie par semaine, face à la capacité de chacun (Capacité du projet, sinon heures/jour × 5).">
        {p.workload.length === 0 ? (
          <div className="empty">Aucun membre affecté au projet.</div>
        ) : (
          <div className="tbl-wrap">
            <table className="tbl tight pl-load">
              <thead>
                <tr>
                  <th>Membre</th>
                  <th>Avancement</th>
                  <th className="r">Reste</th>
                  {p.weeks.map((w) => (
                    <th key={w} className="r">
                      S{fr(w)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {p.workload.map((m) => (
                  <tr key={m.id}>
                    <td>
                      <b>{m.name}</b>
                      <small className="muted" style={{ display: "block" }}>
                        {m.open} ouverte(s) · {m.doing} en cours{m.late ? ` · ${m.late} en retard` : ""}
                      </small>
                    </td>
                    <td style={{ minWidth: 120 }}>
                      <div className="bar">
                        <i style={{ width: `${m.progress ?? 0}%` }} />
                      </div>
                      <small className="muted">
                        {m.progress ?? 0} % · {m.done}/{m.tasks} · {m.spent} h passées
                      </small>
                    </td>
                    <td className="r">{m.remaining} h</td>
                    {m.weeks.map((w) => {
                      const ratio = w.capacity ? w.hours / w.capacity : 0;
                      const cls = ratio > 1.1 ? "over" : ratio > 0.8 ? "full" : ratio > 0 ? "ok" : "";
                      return (
                        <td key={w.week} className={`r pl-cell ${cls}`} title={`${w.hours} h / ${w.capacity} h de capacité`}>
                          {w.hours ? `${Math.round(ratio * 100)} %` : "·"}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="pl-legend">
          <span className="pl-cell ok">≤ 80 %</span>
          <span className="pl-cell full">80–110 %</span>
          <span className="pl-cell over">&gt; 110 % surcharge</span>
        </div>
      </Card>
    </>
  );
}
