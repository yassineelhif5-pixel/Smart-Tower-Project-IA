import { useState } from "react";

import { calendarApi, type Query } from "../../api/collab";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Icon, Loading, Pill } from "../../components/ui";
import type { Conflict } from "../../types/collab";
import { CONFLICT_LABEL, suggestionText } from "./CalendarConflicts";
import { fmtDay } from "./calendarUtils";

/** Indicateurs calculés par le serveur à partir des données réelles du périmètre de l'utilisateur. */
export function CalendarDashboard({
  params,
  onOpen,
  onApply,
}: {
  params: Query;
  onOpen: (id: number) => void;
  onApply: (c: Conflict) => Promise<boolean>;
}) {
  const key = JSON.stringify(params);
  const dash = useApi(() => calendarApi.dashboard(params), [key]);
  const conflicts = useApi(() => calendarApi.conflicts(params), [key]);
  const [ignored, setIgnored] = useState<Set<string>>(new Set());

  if (dash.error) return <ErrorNotice error={dash.error} onRetry={dash.reload} />;
  if (!dash.data) return <Loading />;
  const d = dash.data;
  const sig = (c: Conflict) => `${c.type}:${c.events.join(",")}:${c.users.join(",")}`;
  const visible = (conflicts.data ?? []).filter((c) => !ignored.has(sig(c)));
  const maxUser = Math.max(1, ...d.workloadByUser.map((w) => w.total));
  const maxTeam = Math.max(1, ...d.workloadByTeam.map((w) => w.total));

  return (
    <div className="cal-dash">
      <div className="kpis">
        <Kpi label="Planifiés" value={d.planned} />
        <Kpi label="Terminés" value={d.done} tone="ok" />
        <Kpi label="En cours" value={d.inProgress} />
        <Kpi label="Bloqués" value={d.blocked} tone={d.blocked ? "warn" : undefined} />
        <Kpi label="En retard" value={d.late} tone={d.late ? "crit" : undefined} />
        <Kpi label="À venir (14 j)" value={d.upcoming} />
        <Kpi label="Avancement moyen" value={`${d.progressRate} %`} />
        <Kpi label="Respect des délais" value={d.onTimeRate == null ? "—" : `${d.onTimeRate} %`} />
      </div>
      <div className="grid g2">
        <Card title="Conflits de planning" sub="Signalés, jamais corrigés automatiquement : à vous de décider.">
          {conflicts.error && <ErrorNotice error={conflicts.error} onRetry={conflicts.reload} />}
          {!conflicts.data && !conflicts.error && <Loading />}
          {conflicts.data && !visible.length && <p className="muted">Aucun conflit sur la période.</p>}
          <ul className="conflicts">
            {visible.slice(0, 30).map((c) => (
              <li key={sig(c)} className={c.severity}>
                <Icon name="alert" size={16} />
                <div>
                  <div>
                    <Pill tone={c.severity === "critical" ? "crit" : "warn"}>{CONFLICT_LABEL[c.type]}</Pill>{" "}
                    <b>{c.title}</b>
                  </div>
                  <p>{c.explanation}</p>
                  <div className="btns">
                    {c.events[0] && (
                      <button className="btn sm ghost" onClick={() => onOpen(c.events[0])}>
                        Ouvrir
                      </button>
                    )}
                    {c.suggestion && c.suggestion.action !== "assign" && (
                      <button
                        className="btn sm"
                        onClick={() =>
                          void onApply(c).then((ok) => {
                            if (ok) {
                              conflicts.reload();
                              dash.reload();
                            }
                          })
                        }
                      >
                        Appliquer — {suggestionText(c)}
                      </button>
                    )}
                    <button className="btn sm ghost" onClick={() => setIgnored(new Set(ignored).add(sig(c)))}>
                      Ignorer
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Retards par projet">
          {!d.delaysByProject.length ? (
            <p className="muted">Aucun élément planifié.</p>
          ) : (
            <table className="tbl tight">
              <thead>
                <tr>
                  <th>Projet</th>
                  <th className="r">En retard</th>
                  <th className="r">Total</th>
                  <th className="r">Retard moyen</th>
                </tr>
              </thead>
              <tbody>
                {d.delaysByProject.map((p) => (
                  <tr key={p.project.id}>
                    <td>
                      <b>{p.project.code}</b> <span className="muted">{p.project.name}</span>
                    </td>
                    <td className="r">{p.late ? <b className="t-crit">{p.late}</b> : 0}</td>
                    <td className="r">{p.total}</td>
                    <td className="r">{p.avgDelayDays ? `${p.avgDelayDays} j` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card
          title="Charge par collaborateur"
          sub="Heures planifiées sur la période ; rouge : jours au-delà de la capacité."
        >
          <Bars rows={d.workloadByUser} max={maxUser} />
        </Card>
        <Card title="Charge par équipe">
          <Bars rows={d.workloadByTeam} max={maxTeam} />
        </Card>
        <Card title="Jalons à venir">
          {!d.milestones.length ? (
            <p className="muted">Aucun jalon à venir sur la période.</p>
          ) : (
            <ul className="plain">
              {d.milestones.map((m) => (
                <li key={m.id}>
                  <button className="link" onClick={() => onOpen(m.id)}>
                    ◆ {m.title}
                  </button>{" "}
                  <span className="muted mono">
                    {fmtDay(m.date)} {m.project ?? ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

function Kpi({ label, value, tone }: { label: string; value: number | string; tone?: "ok" | "warn" | "crit" }) {
  return (
    <div className={`kpi ${tone ?? ""}`}>
      <label>{label}</label>
      <strong>{value}</strong>
    </div>
  );
}

function Bars({ rows, max }: { rows: { key: string; label: string; total: number; overDays: number }[]; max: number }) {
  if (!rows.length) return <p className="muted">Aucune charge estimée sur la période.</p>;
  return (
    <ul className="hbars">
      {rows.map((r) => (
        <li key={r.key}>
          <span className="hb-l">{r.label}</span>
          <span className="hb-t">
            <i className={r.overDays ? "over" : ""} style={{ width: `${(r.total / max) * 100}%` }} />
          </span>
          <span className="hb-v mono">
            {r.total.toFixed(1)} h{r.overDays ? <b className="t-crit"> · {r.overDays} j</b> : null}
          </span>
        </li>
      ))}
    </ul>
  );
}
