import { calendarApi } from "../../api/collab";
import { useApi } from "../../api/useApi";
import { ErrorNotice, Loading, Pill } from "../../components/ui";
import { fmtDay } from "./calendarUtils";

/** Portefeuille : santé du planning de chaque projet visible (retards, jalons à venir, fin prévisionnelle). */
export function CalendarPortfolioView({ onProject }: { onProject: (id: string) => void }) {
  const p = useApi(calendarApi.portfolio);
  if (p.error) return <ErrorNotice error={p.error} onRetry={p.reload} />;
  if (!p.data) return <Loading />;
  if (!p.data.length) return <div className="empty">Aucun projet dans votre périmètre.</div>;
  return (
    <div className="tbl-wrap">
      <table className="tbl">
        <thead>
          <tr>
            <th>Projet</th>
            <th>Client</th>
            <th>Chef de projet</th>
            <th>Période</th>
            <th className="r">Avancement</th>
            <th className="r">Éléments</th>
            <th className="r">En retard</th>
            <th>Prochains jalons</th>
            <th>Santé</th>
          </tr>
        </thead>
        <tbody>
          {p.data.map((r) => (
            <tr key={r.id} className="click" onClick={() => onProject(r.id)}>
              <td>
                <b>{r.code}</b>
                <div className="muted">{r.name}</div>
              </td>
              <td>{r.client}</td>
              <td>{r.pm ?? "—"}</td>
              <td className="mono">
                {r.start ? fmtDay(r.start) : "—"} → {r.end ? fmtDay(r.end) : "—"}
                {r.forecastEnd && r.end && r.forecastEnd > r.end && (
                  <div className="t-crit">prév. {fmtDay(r.forecastEnd)}</div>
                )}
              </td>
              <td className="r">
                <div className="bar-mini" aria-label={`${r.progress} %`}>
                  <i style={{ width: `${r.progress}%` }} />
                </div>
                {r.progress} %
              </td>
              <td className="r">{r.events}</td>
              <td className="r">{r.late ? <b className="t-crit">{r.late}</b> : 0}</td>
              <td>
                {r.milestones.slice(0, 2).map((m) => (
                  <div key={m.title + m.date}>
                    ◆ {m.title} <span className="muted mono">{fmtDay(m.date)}</span>
                  </div>
                ))}
                {!r.milestones.length && <span className="muted">—</span>}
              </td>
              <td>
                <Pill tone={r.health === "ok" ? "ok" : "crit"}>
                  {r.health === "ok" ? "Dans les temps" : "À surveiller"}
                </Pill>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
