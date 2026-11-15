// Tableau de validation des temps commun au chef de projet (valideur interne) et au client :
// regroupement par consultant, projet, semaine ou mois, filtres, détail des saisies et synthèse des heures
// par projet et sous-ligne × consultant pour faciliter la décision.
import { Fragment, useMemo, useState, type ReactNode } from "react";

export type VEntry = {
  id: number; date: string; person: string; personId: number | string; project: string; projectName?: string;
  line: string; task: string; hours: number; approvedBy?: string; locked?: string; step?: string; readOnly?: boolean;
};
type By = "person" | "project" | "week" | "month";

const MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];
const h = (v: number) => `${(Math.round(v * 100) / 100).toLocaleString("fr-FR")} h`;
const d = (s: string) => new Date(`${String(s).slice(0, 10)}T00:00:00`);
function monday(s: string) {
  const x = d(s);
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7));
  return x;
}
const iso = (x: Date) => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`;
const monthKey = (s: string) => String(s).slice(0, 7);
const monthLabel = (k: string) => `${MONTHS[Number(k.slice(5, 7)) - 1]} ${k.slice(0, 4)}`;
function weekLabel(k: string) {
  const a = d(k), b = d(k);
  b.setDate(b.getDate() + 6);
  return `Semaine du ${a.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" })} au ${b.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric" })}`;
}
const projLabel = (e: VEntry) => (e.projectName && e.projectName !== e.project ? `${e.project} — ${e.projectName}` : e.project);
const lineLabel = (e: VEntry) => e.line || "Sans sous-ligne";

export function ValidationBoard({ entries, busy, onApprove, onReject, intro, toolbar }: {
  entries: VEntry[]; busy: boolean; intro?: string; toolbar?: ReactNode;
  onApprove: (ids: number[]) => unknown; onReject: (id: number, comment: string) => unknown;
}) {
  const [by, setBy] = useState<By>("person");
  const [fPerson, setFPerson] = useState("");
  const [fProject, setFProject] = useState("");
  const [fMonth, setFMonth] = useState("");
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [synth, setSynth] = useState(true);
  const [refusing, setRefusing] = useState<{ id: number; comment: string } | null>(null);

  const people = useMemo(() => [...new Map(entries.map((e) => [String(e.personId), e.person])).entries()].sort((a, b) => a[1].localeCompare(b[1])), [entries]);
  const projects = useMemo(() => [...new Map(entries.map((e) => [e.project, projLabel(e)])).entries()].sort(), [entries]);
  const months = useMemo(() => [...new Set(entries.map((e) => monthKey(e.date)))].sort(), [entries]);
  const rows = entries.filter((e) => (!fPerson || String(e.personId) === fPerson) && (!fProject || e.project === fProject) && (!fMonth || monthKey(e.date) === fMonth));

  const groups = useMemo(() => {
    const m = new Map<string, { label: string; items: VEntry[] }>();
    for (const e of rows) {
      const k = by === "person" ? String(e.personId) : by === "project" ? e.project : by === "week" ? iso(monday(e.date)) : monthKey(e.date);
      const label = by === "person" ? e.person : by === "project" ? projLabel(e) : by === "week" ? weekLabel(k) : monthLabel(k);
      if (!m.has(k)) m.set(k, { label, items: [] });
      m.get(k)!.items.push(e);
    }
    return [...m.entries()].sort((a, b) => (by === "week" || by === "month" ? a[0].localeCompare(b[0]) : a[1].label.localeCompare(b[1].label)));
  }, [rows, by]);

  // Synthèse : projet › sous-ligne × consultant
  const synthesis = useMemo(() => {
    const cols = [...new Map(rows.map((e) => [String(e.personId), e.person])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
    const tree = new Map<string, { label: string; lines: Map<string, Map<string, number>> }>();
    for (const e of rows) {
      if (!tree.has(e.project)) tree.set(e.project, { label: projLabel(e), lines: new Map() });
      const lines = tree.get(e.project)!.lines;
      if (!lines.has(lineLabel(e))) lines.set(lineLabel(e), new Map());
      const cell = lines.get(lineLabel(e))!;
      cell.set(String(e.personId), (cell.get(String(e.personId)) ?? 0) + Number(e.hours));
    }
    return { cols, tree: [...tree.entries()].sort() };
  }, [rows]);

  const approvable = (items: VEntry[]) => items.filter((e) => !e.locked).map((e) => e.id);
  const total = (items: VEntry[]) => items.reduce((s, e) => s + Number(e.hours), 0);
  const allIds = approvable(rows);
  const sum = (m: Map<string, number>) => [...m.values()].reduce((a, b) => a + b, 0);

  const approveAll = () => {
    if (allIds.length > 1 && !window.confirm(`Valider les ${allIds.length} saisies affichées (${h(total(rows.filter((e) => !e.locked)))}) ?`)) return;
    void onApprove(allIds);
  };
  if (entries.length === 0) return <div className="vb">{toolbar}<p className="muted">✅ Aucun temps en attente de votre validation.</p></div>;
  return (
    <div className="vb">
      {intro && <p className="muted">{intro}</p>}
      <div className="vb-bar">
        <div className="vb-seg" role="tablist" aria-label="Afficher par">
          {([["person", "Par consultant"], ["project", "Par projet"], ["week", "Par semaine"], ["month", "Par mois"]] as [By, string][]).map(([k, l]) => (
            <button key={k} type="button" role="tab" aria-selected={by === k} className={by === k ? "on" : ""} onClick={() => setBy(k)}>{l}</button>
          ))}
        </div>
        <select className="inp" aria-label="Consultant" value={fPerson} onChange={(e) => setFPerson(e.target.value)}>
          <option value="">Tous les consultants</option>{people.map(([id, n]) => <option key={id} value={id}>{n}</option>)}
        </select>
        <select className="inp" aria-label="Projet" value={fProject} onChange={(e) => setFProject(e.target.value)}>
          <option value="">Tous les projets</option>{projects.map(([c, l]) => <option key={c} value={c}>{l}</option>)}
        </select>
        <select className="inp" aria-label="Période" value={fMonth} onChange={(e) => setFMonth(e.target.value)}>
          <option value="">Toutes les périodes</option>{months.map((m) => <option key={m} value={m}>{monthLabel(m)}</option>)}
        </select>
        {toolbar}
        <label className="vb-check"><input type="checkbox" checked={synth} onChange={(e) => setSynth(e.target.checked)} /> Synthèse</label>
        <span className="vb-sp" />
        <span className="muted">{rows.length} saisie(s) · <b>{h(total(rows))}</b></span>
        <button type="button" className="btn primary sm" disabled={busy || allIds.length === 0} onClick={approveAll}>✔ Tout valider ({allIds.length})</button>
      </div>

      {synth && (
        <div className="tbl-wrap vb-synth">
          <table className="tbl tight">
            <thead><tr><th>Projet › sous-ligne</th>{synthesis.cols.map(([id, n]) => <th key={id} className="r">{n}</th>)}<th className="r">Total</th></tr></thead>
            <tbody>
              {synthesis.tree.map(([code, p]) => {
                const pt = new Map<string, number>();
                p.lines.forEach((cells) => cells.forEach((v, k) => pt.set(k, (pt.get(k) ?? 0) + v)));
                return (
                  <Fragment key={code}>
                    <tr className="vb-proj"><td><b>{p.label}</b></td>{synthesis.cols.map(([id]) => <td key={id} className="r"><b>{pt.get(id) ? h(pt.get(id)!) : "—"}</b></td>)}<td className="r"><b>{h(sum(pt))}</b></td></tr>
                    {[...p.lines.entries()].sort().map(([ln, cells]) => (
                      <tr key={ln}><td style={{ paddingLeft: 22 }}>↳ {ln}</td>{synthesis.cols.map(([id]) => <td key={id} className="r">{cells.get(id) ? h(cells.get(id)!) : "—"}</td>)}<td className="r">{h(sum(cells))}</td></tr>
                    ))}
                  </Fragment>
                );
              })}
              <tr className="vb-total"><td><b>Total</b></td>{synthesis.cols.map(([id]) => <td key={id} className="r"><b>{h(total(rows.filter((e) => String(e.personId) === id)))}</b></td>)}<td className="r"><b>{h(total(rows))}</b></td></tr>
            </tbody>
          </table>
        </div>
      )}

      {groups.map(([k, g]) => {
        const ids = approvable(g.items);
        const locked = g.items.find((e) => e.locked)?.locked;
        const isOpen = !!open[k];
        const sub = by === "person" ? new Set(g.items.map((e) => e.project)).size + " projet(s)" : new Set(g.items.map((e) => e.personId)).size + " consultant(s)";
        return (
          <div key={k} className="vb-group">
            <div className="vb-group-h">
              <div><b>{g.label}</b> <span className="muted">· {g.items.length} saisie(s) · {sub}</span></div>
              <b className="vb-h">{h(total(g.items))}</b>
              <button type="button" className="btn sm" onClick={() => setOpen({ ...open, [k]: !isOpen })}>{isOpen ? "Masquer" : "Détail"}</button>
              <button type="button" className="btn sm primary" disabled={busy || ids.length === 0} title={locked} onClick={() => onApprove(ids)}>✔ Valider ({ids.length})</button>
            </div>
            {locked && <div className="notice" style={{ margin: "6px 0" }}>⏳ {locked}</div>}
            {isOpen && (
              <div className="tbl-wrap">
                <table className="tbl tight">
                  <thead><tr><th>Date</th>{by !== "person" && <th>Consultant</th>}{by !== "project" && <th>Projet</th>}<th>Sous-ligne</th><th>Tâche</th><th className="r">Heures</th><th>Étape / validé par</th><th>Décision</th></tr></thead>
                  <tbody>
                    {[...g.items].sort((a, b) => String(a.date).localeCompare(String(b.date))).map((e) => (
                      <tr key={e.id}>
                        <td>{d(e.date).toLocaleDateString("fr-FR", { weekday: "short", day: "2-digit", month: "2-digit" })}</td>
                        {by !== "person" && <td>{e.person}</td>}
                        {by !== "project" && <td>{projLabel(e)}</td>}
                        <td>{e.line || <span className="muted">—</span>}</td>
                        <td>{e.task}</td>
                        <td className="r">{h(Number(e.hours))}</td>
                        <td style={{ fontSize: 12 }}>{e.step && <div>{e.step}</div>}{e.approvedBy ? <div className="muted">Validé par {e.approvedBy}</div> : !e.step && <span className="muted">—</span>}</td>
                        <td>{refusing?.id === e.id ? (
                          <span style={{ display: "inline-flex", gap: 6 }}>
                            <input className="inp" style={{ minWidth: 200 }} autoFocus placeholder="Motif du refus (obligatoire)" aria-label="Motif du refus" value={refusing.comment} onChange={(ev) => setRefusing({ id: e.id, comment: ev.target.value })} />
                            <button type="button" className="btn sm" disabled={busy || !refusing.comment.trim()} onClick={() => { void onReject(e.id, refusing.comment.trim()); setRefusing(null); }}>Refuser</button>
                            <button type="button" className="btn sm ghost" onClick={() => setRefusing(null)}>Annuler</button>
                          </span>
                        ) : (
                          <span style={{ display: "inline-flex", gap: 6 }}>
                            <button type="button" className="btn sm primary" disabled={busy || !!e.locked} title={e.locked} onClick={() => onApprove([e.id])}>✔</button>
                            <button type="button" className="btn sm" disabled={busy || !!e.readOnly} onClick={() => setRefusing({ id: e.id, comment: "" })}>✖ Refuser</button>
                          </span>
                        )}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
