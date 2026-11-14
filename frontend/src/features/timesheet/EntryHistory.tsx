// Historique des saisies : affichage par jour ou par mois (regroupé par personne quand on voit plusieurs personnes).
import { Fragment, useState } from "react";

import { Card } from "../../components/ui";
import type { TimeEntryRow } from "../../types/api";

const STATUS: Record<string, string> = { draft: "Brouillon", pending: "À valider", client: "Chez le client", approved: "Validé", rejected: "Refusé" };
const ORDER = ["approved", "client", "pending", "draft", "rejected"];
const fmt = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/0$/, "").replace(".", ","));
type Mode = "day" | "month";
type Group = { key: string; label: string; sub: string; person: string; rows: TimeEntryRow[]; total: number; by: Record<string, number>; days: number };

function group(rows: TimeEntryRow[], mode: Mode, withPerson: boolean): Group[] {
  const map = new Map<string, Group>();
  for (const r of rows) {
    const period = mode === "day" ? r.workDate : r.workDate.slice(0, 7);
    const key = `${period}|${withPerson ? r.user : ""}`;
    let g = map.get(key);
    if (!g) {
      const d = new Date(`${mode === "day" ? r.workDate : `${period}-01`}T00:00:00`);
      const label = mode === "day" ? d.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long", year: "numeric" })
        : d.toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
      g = { key, label: label.charAt(0).toUpperCase() + label.slice(1), sub: period, person: r.userName, rows: [], total: 0, by: {}, days: 0 };
      map.set(key, g);
    }
    g.rows.push(r);
    const a = Number(r.amount);
    if (r.status !== "rejected") g.total += a;
    g.by[r.status] = (g.by[r.status] ?? 0) + a;
  }
  const out = [...map.values()];
  for (const g of out) g.days = new Set(g.rows.map((r) => r.workDate)).size;
  return out.sort((a, b) => (a.sub < b.sub ? 1 : a.sub > b.sub ? -1 : a.person.localeCompare(b.person)));
}

export function EntryHistory({ rows, title, withPerson }: { rows: TimeEntryRow[]; title: string; withPerson: boolean }) {
  const [mode, setModeState] = useState<Mode>(() => { try { return localStorage.getItem("pct.histMode") === "month" ? "month" : "day"; } catch { return "day"; } });
  const [open, setOpen] = useState<string | null>(null);
  const setMode = (m: Mode) => { setModeState(m); setOpen(null); try { localStorage.setItem("pct.histMode", m); } catch { /* préférence locale */ } };
  const unit = rows[0]?.unit === "day" ? "j" : "h";
  const groups = group(rows, mode, withPerson).slice(0, mode === "day" ? 60 : 24);
  return (
    <Card title={title} sub={mode === "day" ? "Une ligne par jour : projets saisis, total et état." : "Une ligne par mois : jours saisis, total et répartition par état. Cliquez pour le détail."}
      extra={
        <div className="sh-seg" role="tablist" aria-label="Affichage de l'historique">
          <button type="button" role="tab" aria-selected={mode === "day"} className={mode === "day" ? "on" : ""} onClick={() => setMode("day")}>Par jour</button>
          <button type="button" role="tab" aria-selected={mode === "month"} className={mode === "month" ? "on" : ""} onClick={() => setMode("month")}>Par mois</button>
        </div>
      }>
      <div className="tbl-wrap">
        <table className="tbl tight eh">
          <thead>
            <tr>
              <th>{mode === "day" ? "Jour" : "Mois"}</th>
              {withPerson && <th>Personne</th>}
              <th>{mode === "day" ? "Projets" : "Jours saisis"}</th>
              <th className="r">Total</th>
              <th>État</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => (
              <Fragment key={g.key}>
                <tr className={mode === "month" ? "eh-click" : ""} onClick={() => mode === "month" && setOpen(open === g.key ? null : g.key)}>
                  <td><b>{g.label}</b></td>
                  {withPerson && <td>{g.person}</td>}
                  <td>
                    {mode === "day"
                      ? g.rows.map((r) => <span key={r.id} className="eh-proj">{r.projectName} <b>{fmt(Number(r.amount))} {unit}</b></span>)
                      : <>{g.days} jour(s) · {new Set(g.rows.map((r) => r.projectName)).size} projet(s) <span className="eh-more">{open === g.key ? "▾" : "▸"} détail</span></>}
                  </td>
                  <td className="r"><b>{fmt(g.total)} {unit}</b></td>
                  <td>
                    {ORDER.filter((s) => g.by[s]).map((s) => (
                      <span key={s} className={`ts-chip ${s}`}>{STATUS[s]}{Object.keys(g.by).length > 1 ? ` ${fmt(g.by[s])} ${unit}` : ""}</span>
                    ))}
                  </td>
                </tr>
                {open === g.key && (
                  <tr className="eh-detail">
                    <td colSpan={withPerson ? 5 : 4}>
                      <table className="tbl tight">
                        <tbody>
                          {g.rows.slice().sort((a, b) => (a.workDate < b.workDate ? -1 : 1)).map((r) => (
                            <tr key={r.id}>
                              <td>{new Date(`${r.workDate}T00:00:00`).toLocaleDateString("fr-FR", { weekday: "short", day: "2-digit", month: "2-digit" })}</td>
                              <td>{r.projectName}</td>
                              <td className="r">{fmt(Number(r.amount))} {unit}</td>
                              <td><span className={`ts-chip ${r.status}`}>{STATUS[r.status]}</span>{r.approvedBy ? <small className="muted"> · {r.approvedBy}</small> : null}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {groups.length === 0 && <tr><td colSpan={withPerson ? 5 : 4} className="muted">Aucune saisie pour le moment.</td></tr>}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
