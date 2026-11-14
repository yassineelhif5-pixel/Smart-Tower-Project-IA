import { Fragment, useEffect, useState } from "react";

import { api } from "../../api/client";
import { ErrorNotice, Loading } from "../../components/ui";

type Week = { week: string; hours: number; capacity: number; byProject: Record<string, number> };
type Person = {
  id: number; name: string; role: string; capacity: number; open: number; late: number; peak: number; weeks: Week[];
  projects: { id: string; name: string; open: number; late: number; hours: number }[];
};
type Data = { weeks: string[]; people: Person[]; hoursPerDay: number; projects: { id: string; name: string; code: string }[]; scope: string[] };

const PALETTE = ["#4f46e5", "#0ea5e9", "#16a34a", "#d97706", "#db2777", "#7c3aed", "#0f766e", "#b91c1c", "#64748b"];
const heat = (pct: number) => (pct > 110 ? "#fecaca" : pct > 90 ? "#fde68a" : pct > 50 ? "#bbf7d0" : pct > 0 ? "#e0f2fe" : "transparent");

/** Plan de charge de toute l'équipe, tous projets confondus (8 semaines). */
export function TeamWorkload() {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [only, setOnly] = useState<string[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [weeks, setWeeks] = useState(8);

  useEffect(() => {
    setData(null);
    api.get<Data>(`/team-workload?weeks=${weeks}${only.length ? `&projects=${only.map(encodeURIComponent).join(",")}` : ""}`).then(setData, setError);
  }, [only, weeks]);

  if (error) return <ErrorNotice error={error as never} onRetry={() => setOnly([...only])} />;
  if (!data) return <Loading />;
  const color = (pid: string) => (pid === "_other" ? "#94a3b8" : PALETTE[Math.max(0, data.projects.findIndex((p) => p.id === pid)) % (PALETTE.length - 1)]);
  const over = data.people.filter((p) => p.peak > 100).length;
  const free = data.people.filter((p) => p.peak < 50).length;

  return (
    <div className="tw">
      <div className="tw-filters">
        <b>Périmètre :</b>
        <label className={`pf-check${only.length === 0 ? " on" : ""}`}>
          <input type="checkbox" checked={only.length === 0} onChange={() => setOnly([])} />
          <span><b>Tous mes projets</b></span>
        </label>
        {data.projects.map((p) => (
          <label key={p.id} className={`pf-check${only.includes(p.id) ? " on" : ""}`}>
            <input type="checkbox" checked={only.includes(p.id)} onChange={() => setOnly(only.includes(p.id) ? only.filter((x) => x !== p.id) : [...only, p.id])} />
            <span><b><i className="pf-dot" style={{ background: color(p.id) }} />{p.name}</b><small>{p.code}</small></span>
          </label>
        ))}
        <label className="tw-weeks">
          Horizon
          <select className="inp sm" value={weeks} onChange={(e) => setWeeks(Number(e.target.value))}>
            {[4, 8, 12, 16].map((w) => <option key={w} value={w}>{w} semaines</option>)}
          </select>
        </label>
      </div>

      <div className="tw-kpis">
        <div><b>{data.people.length}</b><small>personnes</small></div>
        <div className={over ? "crit" : ""}><b>{over}</b><small>en surcharge (&gt; 100 %)</small></div>
        <div><b>{free}</b><small>disponibles (&lt; 50 %)</small></div>
        <div><b>{data.people.reduce((n, p) => n + p.late, 0)}</b><small>actions en retard</small></div>
      </div>

      {data.people.length === 0 ? (
        <div className="empty">Aucun membre dans le périmètre choisi.</div>
      ) : (
        <div className="tbl-wrap">
          <table className="tbl tw-tbl">
            <thead>
              <tr>
                <th>Membre</th>
                {data.weeks.map((w) => <th key={w} className="r">S. {new Date(w).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" })}</th>)}
                <th className="r">Pic</th>
              </tr>
            </thead>
            <tbody>
              {data.people.map((p) => (
                <Fragment key={p.id}>
                  <tr className="tw-row" onClick={() => setOpen(open === p.id ? null : p.id)}>
                    <td className="cell-main">
                      <b>{open === p.id ? "▾" : "▸"} {p.name}</b>
                      <small>{p.role} · {p.capacity} h/sem. · {p.open} action(s){p.late ? <span className="crit"> · {p.late} en retard</span> : ""}</small>
                    </td>
                    {p.weeks.map((w) => {
                      const pct = w.capacity ? Math.round((w.hours / w.capacity) * 100) : 0;
                      return (
                        <td key={w.week} className="tw-cell" style={{ background: heat(pct) }}
                          title={`${w.hours} h / ${w.capacity} h (${pct} %)\n` + Object.entries(w.byProject).map(([k, v]) => `${p.projects.find((x) => x.id === k)?.name ?? k} : ${v} h`).join("\n")}>
                          <div className="tw-stack">
                            {Object.entries(w.byProject).map(([k, v]) => (
                              <i key={k} style={{ width: `${Math.min(100, (v / Math.max(w.capacity, w.hours, 1)) * 100)}%`, background: color(k) }} />
                            ))}
                          </div>
                          <span>{w.hours ? `${w.hours} h` : "—"}</span>
                          {pct > 0 && <small>{pct} %</small>}
                        </td>
                      );
                    })}
                    <td className={`r tw-peak${p.peak > 100 ? " crit" : ""}`}><b>{p.peak} %</b></td>
                  </tr>
                  {open === p.id && (
                    <tr className="tw-detail">
                      <td colSpan={data.weeks.length + 2}>
                        <div className="tw-projs">
                          {p.projects.map((x) => (
                            <span key={x.id} className="tw-proj">
                              <i style={{ background: color(x.id) }} />
                              <b>{x.name}</b> · {x.open} action(s) · {x.hours} h restantes{x.late ? <span className="crit"> · {x.late} en retard</span> : ""}
                            </span>
                          ))}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="pf-legend">
        <span><i style={{ background: "#e0f2fe" }} /> &lt; 50 %</span>
        <span><i style={{ background: "#bbf7d0" }} /> 50–90 %</span>
        <span><i style={{ background: "#fde68a" }} /> 90–110 %</span>
        <span><i style={{ background: "#fecaca" }} /> &gt; 110 % (surcharge)</span>
        <span>Les barres colorées montrent la répartition par projet ; « Autres projets » = projets hors de votre périmètre.</span>
      </div>
    </div>
  );
}
