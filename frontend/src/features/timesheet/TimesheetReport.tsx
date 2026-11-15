// Reporting standard des saisies : projet × consultant × mois, état de validation et état du CRA.
// Le collaborateur peut générer lui-même son CRA quand toutes ses saisies du mois sont validées.
import { useMemo, useState } from "react";

import { API_BASE, api } from "../../api/client";
import { useApi } from "../../api/useApi";
import { Card, useAction } from "../../components/ui";

type Row = { project: string; projectName: string; client: string; clientName: string; person: number; personName: string; period: string; periodLabel: string;
  hours: string; days: string; entries: number; counts: Record<string, number>; state: string; stateLabel: string;
  cra: string; craLabel: string; craId: string | null; craNumber: string; mine: boolean; canGenerate: boolean };

const STATE: Record<string, [string, string]> = {
  draft: ["Brouillon", "#64748b"], pending: ["Validation interne", "#b45309"], client: ["Chez le client", "#7c3aed"],
  approved: ["Validé", "#15803d"], rejected: ["Refusé", "#b91c1c"],
};
const CRA: Record<string, [string, string]> = {
  generated: ["Généré", "#15803d"], ready: ["Prêt à générer", "#2563eb"], waiting: ["En attente des validations", "#b45309"],
  blocked: ["Saisies à envoyer / corriger", "#b91c1c"], none: ["—", "#64748b"],
};
const fr = (v: string | number) => Number(v).toLocaleString("fr-FR", { maximumFractionDigits: 2 });
const chip = (label: string, color: string) => <span style={{ display: "inline-block", padding: "1px 8px", borderRadius: 999, fontSize: 12, background: `${color}1a`, color, whiteSpace: "nowrap" }}>{label}</span>;

export function TimesheetReport() {
  const [months, setMonths] = useState(3);
  const r = useApi(() => api.get<{ rows: Row[] }>(`/timesheets/report?months=${months}`), [months]);
  const { run, busy } = useAction();
  const [f, setF] = useState({ period: "", project: "", person: "", state: "", cra: "", mine: false });
  const rows = r.data?.rows ?? [];
  const opts = useMemo(() => ({
    periods: [...new Map(rows.map((x) => [x.period, x.periodLabel])).entries()],
    projects: [...new Map(rows.map((x) => [x.project, x.projectName])).entries()].sort(),
    people: [...new Map(rows.map((x) => [String(x.person), x.personName])).entries()].sort((a, b) => a[1].localeCompare(b[1])),
  }), [rows]);
  const shown = rows.filter((x) => (!f.period || x.period === f.period) && (!f.project || x.project === f.project) && (!f.person || String(x.person) === f.person)
    && (!f.state || x.state === f.state) && (!f.cra || x.cra === f.cra) && (!f.mine || x.mine));
  const tot = shown.reduce((a, x) => ({ h: a.h + Number(x.hours), d: a.d + Number(x.days), n: a.n + x.entries }), { h: 0, d: 0, n: 0 });
  const generate = (x: Row) => {
    if (!window.confirm(`Générer votre CRA ${x.clientName} de ${x.periodLabel} ? Une fois généré, vos saisies du mois ne seront plus modifiables.`)) return;
    void run(() => api.post("/timesheets/report/generate-cra", { client: x.client, period: x.period }), "CRA généré : une notification vous a été envoyée").then(() => r.reload(), () => undefined);
  };
  const csv = () => {
    const head = ["Mois", "Projet", "Client", "Consultant", "Saisies", "Heures", "Jours", "Validation", "CRA"];
    const lines = shown.map((x) => [x.periodLabel, `${x.project} — ${x.projectName}`, x.clientName, x.personName, x.entries, fr(x.hours), fr(x.days), x.stateLabel, x.craLabel]);
    const body = [head, ...lines].map((l) => l.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(";")).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(["﻿" + body], { type: "text/csv;charset=utf-8" }));
    a.download = `reporting-saisies-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
  };
  const sel = (k: keyof typeof f, label: string, items: [string, string][]) => (
    <select className="inp" aria-label={label} style={{ width: "auto" }} value={String(f[k])} onChange={(e) => setF({ ...f, [k]: e.target.value })}>
      <option value="">{label}</option>{items.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  );
  return (
    <Card title="Reporting des saisies" sub="Par projet, consultant et mois : volume saisi, état de validation et état de génération du CRA.">
      <div className="vb-bar" style={{ marginBottom: 10 }}>
        <select className="inp" aria-label="Profondeur" style={{ width: "auto" }} value={months} onChange={(e) => setMonths(Number(e.target.value))}>
          {[1, 3, 6, 12].map((m) => <option key={m} value={m}>{m === 1 ? "Mois en cours" : `${m} derniers mois`}</option>)}
        </select>
        {sel("period", "Tous les mois", opts.periods)}
        {sel("project", "Tous les projets", opts.projects.map(([c, n]) => [c, `${c} — ${n}`]))}
        {sel("person", "Tous les consultants", opts.people)}
        {sel("state", "Toute validation", Object.entries(STATE).map(([k, v]) => [k, v[0]]))}
        {sel("cra", "Tout état de CRA", Object.entries(CRA).filter(([k]) => k !== "none").map(([k, v]) => [k, v[0]]))}
        <label className="vb-check"><input type="checkbox" checked={f.mine} onChange={(e) => setF({ ...f, mine: e.target.checked })} /> Mes saisies</label>
        <span className="vb-sp" />
        <button type="button" className="btn sm" onClick={csv} disabled={!shown.length}>Exporter (CSV)</button>
      </div>
      {!r.data ? <p className="muted">Chargement…</p> : shown.length === 0 ? <p className="muted">Aucune saisie sur la période.</p> : (
        <div className="tbl-wrap">
          <table className="tbl tight">
            <thead><tr><th>Mois</th><th>Projet</th><th>Consultant</th><th className="r">Saisies</th><th className="r">Heures</th><th className="r">Jours</th><th>Validation</th><th>CRA</th><th /></tr></thead>
            <tbody>
              {shown.map((x) => (
                <tr key={`${x.project}|${x.person}|${x.period}`}>
                  <td style={{ whiteSpace: "nowrap" }}>{x.periodLabel}</td>
                  <td><b>{x.project}</b> <span className="muted">{x.projectName}</span></td>
                  <td>{x.personName}</td>
                  <td className="r">{x.entries}</td>
                  <td className="r">{fr(x.hours)}</td>
                  <td className="r">{fr(x.days)}</td>
                  <td title={x.stateLabel}>{chip(STATE[x.state]?.[0] ?? x.state, STATE[x.state]?.[1] ?? "#64748b")}<div className="muted" style={{ fontSize: 11 }}>{x.stateLabel.split(" · ")[1] ?? (x.state === "pending" ? x.stateLabel.replace(/^[^(]*/, "") : "")}</div></td>
                  <td>{chip(CRA[x.cra]?.[0] ?? x.cra, CRA[x.cra]?.[1] ?? "#64748b")}
                    <div className="muted" style={{ fontSize: 11 }}>{x.cra === "generated" ? <>{x.craLabel.replace(/^Généré — /, "")} {x.craId && <a href={`${API_BASE}/timesheets/history/cra/${encodeURIComponent(x.craId)}`}>· télécharger</a>}</> : x.cra === "ready" && !x.mine ? "à générer par le consultant ou automatiquement" : ""}</div>
                  </td>
                  <td>{x.canGenerate && <button type="button" className="btn sm primary" disabled={busy} onClick={() => generate(x)}>Générer mon CRA</button>}</td>
                </tr>
              ))}
              <tr className="vb-total"><td colSpan={3}><b>Total ({shown.length} ligne(s))</b></td><td className="r"><b>{tot.n}</b></td><td className="r"><b>{fr(tot.h)}</b></td><td className="r"><b>{fr(tot.d)}</b></td><td colSpan={3} /></tr>
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
