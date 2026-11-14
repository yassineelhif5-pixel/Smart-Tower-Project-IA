import { useEffect } from "react";

import { api } from "../../api/client";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Loading, useAction } from "../../components/ui";

type Row = {
  id: string; title: string; status: string; statusLabel: string; owner: string | null; due: string | null;
  doneAt: string | null; phase: string; lateDays: number;
};
type WeekActionsData = { weekStart: string; weekEnd: string; today: string; doing: Row[]; done: Row[]; late: Row[]; canEdit: boolean };

const fr = (s: string | null) => (s ? new Date(`${s}T00:00:00`).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" }) : "—");
const STATUSES: [string, string][] = [
  ["todo", "À faire"], ["planned", "Planifiée"], ["doing", "En cours"], ["review", "En revue"], ["blocked", "Bloquée"], ["done", "Terminée"],
];

/** Actions de la semaine (en cours, clôturées, en retard), synchronisées avec les modifications des tâches. */
export function WeekActions({ projectId, week }: { projectId: string; week: string }) {
  const d = useApi(
    () => api.get<WeekActionsData>(`/projects/${encodeURIComponent(projectId)}/week-actions?week=${week}`),
    [projectId, week],
  );
  const { run, busy } = useAction();
  const { reload } = d;
  useEffect(() => {
    const t = window.setInterval(reload, 30000);
    const onFocus = () => reload();
    window.addEventListener("focus", onFocus);
    return () => (window.clearInterval(t), window.removeEventListener("focus", onFocus));
  }, [reload]);

  if (d.error) return <ErrorNotice error={d.error} onRetry={d.reload} />;
  if (!d.data) return <Loading />;
  const w = d.data;
  const setStatus = (r: Row, status: string) =>
    run(() => api.patch(`/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(r.id)}`, { status }), "Statut mis à jour").then(
      () => d.reload(),
      () => undefined,
    );

  const column = (title: string, rows: Row[], tone: string, empty: string, extra: (r: Row) => string) => (
    <div className={`wa-col wa-${tone}`}>
      <div className="wa-h">
        <b>{title}</b>
        <span className="wa-count">{rows.length}</span>
      </div>
      {rows.length === 0 ? (
        <div className="wa-empty">{empty}</div>
      ) : (
        rows.map((r) => (
          <div key={r.id} className="wa-card">
            <b title={r.title}>{r.title}</b>
            <small>
              {r.owner ?? "Non affectée"}
              {r.phase ? ` · ${r.phase}` : ""} · {extra(r)}
            </small>
            {w.canEdit ? (
              <select className="inp wa-status" value={r.status} disabled={busy} aria-label={`Statut de ${r.title}`} onChange={(e) => setStatus(r, e.target.value)}>
                {STATUSES.map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
              </select>
            ) : (
              <span className="faint" style={{ fontSize: 11.5 }}>
                {r.statusLabel}
              </span>
            )}
          </div>
        ))
      )}
    </div>
  );

  return (
    <Card
      title="Actions de la semaine"
      sub={`Du ${fr(w.weekStart)} au ${fr(w.weekEnd)} · mis à jour automatiquement à chaque changement de statut des tâches.`}
      extra={
        <button className="btn ghost sm" type="button" onClick={d.reload} disabled={d.loading}>
          ↻ Actualiser
        </button>
      }
    >
      <div className="wa-grid">
        {column("En cours", w.doing, "doing", "Aucune action en cours cette semaine.", (r) => `échéance ${fr(r.due)}`)}
        {column("Clôturées", w.done, "done", "Aucune action clôturée cette semaine.", (r) => `clôturée le ${fr(r.doneAt ?? r.due)}`)}
        {column("En retard", w.late, "late", "Aucune action en retard. 👍", (r) => `${r.lateDays} j de retard (échéance ${fr(r.due)})`)}
      </div>
    </Card>
  );
}
