// Rapport de consommation budgétaire mensuelle : ressources affectées (jours × TJM) et assistants intelligents.
import { useState } from "react";

import { API_BASE, api } from "../../api/client";
import { useApi } from "../../api/useApi";
import { useToast } from "../../components/ui";

type Money = string;
type Res = { person: number; name: string; role: string; external: boolean; rate: string | null; noRate: boolean; byMonth: Record<string, { days: string; amount: Money }>; days: string; amount: Money };
type Ai = { code: string; name: string; price: Money; byMonth: Record<string, { units: number; cost: Money }>; units: number; cost: Money };
type Data = { months: string[]; monthLabels: Record<string, string>; projects: { code: string; name: string; client: string; status: string }[];
  resources: Res[]; ai: Ai[]; totals: Record<string, { resources: Money; ai: Money; total: Money; cumulative: Money; days: string }>;
  summary: { resources: Money | null; ai: Money | null; total: Money | null; budget: Money | null; remaining: Money | null; rate: number | null }; amountsHidden?: boolean };

const eur = (v: string | number | null) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }));
const fr = (v: string | number) => Number(v).toLocaleString("fr-FR", { maximumFractionDigits: 2 });
const short = (l: string) => l.replace(/^(\w{3,4})\w*\s(\d{4})$/u, (_m, a, y) => `${a}. ${y.slice(2)}`);

export function BudgetReport() {
  const all = useApi(() => api.get<{ projects: { id: string; name: string }[] }>("/client-portal/orders"));
  const [sel, setSel] = useState<string[]>([]);
  const [months, setMonths] = useState(6);
  const [st, setSt] = useState("all");
  const q = `projects=${encodeURIComponent(sel.join(",") || "all")}&months=${months}&status=${st}`;
  const r = useApi(() => api.get<Data>(`/client-portal/budget-report?${q}`), [q]);
  const toast = useToast();
  const [showDays, setShowDays] = useState(false);
  const projects = all.data?.projects ?? [];
  const d = r.data;
  const download = async (kind: "docx" | "csv", save = false) => {
    const res = await fetch(`${API_BASE}/client-portal/budget-report?${q}&as=${kind}${save ? "&save=1" : ""}`, { credentials: "include" });
    if (!res.ok) { toast("Téléchargement impossible"); return; }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(await res.blob());
    a.download = `rapport-budgetaire-${new Date().toISOString().slice(0, 10)}.${kind}`;
    a.click();
    if (save) toast("Rapport archivé dans la documentation");
  };
  const toggle = (id: string) => setSel(sel.includes(id) ? sel.filter((x) => x !== id) : [...sel, id]);
  return (
    <section className="cs-card">
      <div className="vb-bar">
        <b>Rapport de consommation budgétaire</b>
        <select className="inp" style={{ width: "auto" }} aria-label="Période" value={months} onChange={(e) => setMonths(Number(e.target.value))}>
          {[3, 6, 12].map((m) => <option key={m} value={m}>{m} derniers mois</option>)}
        </select>
        <select className="inp" style={{ width: "auto" }} aria-label="Statut des projets" value={st} onChange={(e) => setSt(e.target.value)}>
          <option value="all">Tous les projets</option><option value="active">Projets actifs</option><option value="inactive">Projets inactifs</option>
        </select>
        <label className="vb-check"><input type="checkbox" checked={showDays} onChange={(e) => setShowDays(e.target.checked)} /> Afficher les jours</label>
        <span className="vb-sp" />
        <button type="button" className="btn sm" onClick={() => void download("csv")}>CSV</button>
        <button type="button" className="btn sm" onClick={() => void download("docx")}>Télécharger (.docx)</button>
        <button type="button" className="btn sm primary" title="Un seul client dans la sélection" onClick={() => void download("docx", true)}>Générer et archiver</button>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 12px", margin: "8px 0" }}>
        <span className="muted">Projets :</span>
        {projects.map((p) => <label key={p.id} className="vb-check"><input type="checkbox" checked={sel.includes(p.id)} onChange={() => toggle(p.id)} /> {p.name}</label>)}
        {sel.length > 0 && <button type="button" className="btn sm ghost" onClick={() => setSel([])}>Tous</button>}
      </div>
      {r.error ? <p className="muted">{(r.error as Error).message}</p> : !d ? <p className="muted">Chargement…</p> : (
        <>
          {d.amountsHidden && <p className="notice">Les TJM et montants ne sont pas affichés pour ce client : le rapport présente les jours et les unités consommés.</p>}
          <div className="cs-kpis" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 8, margin: "6px 0 12px" }}>
            {([["Ressources", d.summary.resources], ["Assistants IA", d.summary.ai], ["Total consommé", d.summary.total], ["Budget validé", d.summary.budget], ["Reste", d.summary.remaining]] as [string, Money | null][]).map(([l, v]) => (
              <div key={l} style={{ border: "1px solid var(--line, #e2e8f0)", borderRadius: 10, padding: "8px 10px" }}>
                <div className="muted" style={{ fontSize: 12 }}>{l}</div>
                <b style={{ fontSize: 18, color: l === "Reste" && v !== null && Number(v) < 0 ? "#b91c1c" : undefined }}>{eur(v)}</b>
                {l === "Total consommé" && d.summary.rate !== null && <div className="muted" style={{ fontSize: 12 }}>{d.summary.rate} % du budget</div>}
              </div>
            ))}
          </div>
          <div className="tbl-wrap">
            <table className="tbl tight">
              <thead><tr><th>Ligne</th><th className="r">TJM / prix</th>{d.months.map((m) => <th key={m} className="r">{short(d.monthLabels[m])}</th>)}<th className="r">Total</th></tr></thead>
              <tbody>
                <tr className="vb-proj"><td colSpan={d.months.length + 3}><b>Ressources affectées</b></td></tr>
                {d.resources.map((x) => (
                  <tr key={x.person}>
                    <td>{x.name} <span className="muted" style={{ fontSize: 12 }}>{x.role}{x.external ? " · externe" : ""}</span></td>
                    <td className="r">{x.rate === null ? <span className="muted">interne</span> : x.rate === "variable" || x.rate === "masqué" ? <span className="muted">{x.rate}</span> : eur(x.rate)}</td>
                    {d.months.map((m) => <td key={m} className="r">{Number(x.byMonth[m].days) ? <>{d.amountsHidden ? `${fr(x.byMonth[m].days)} j` : eur(x.byMonth[m].amount)}{showDays && !d.amountsHidden && <div className="muted" style={{ fontSize: 11 }}>{fr(x.byMonth[m].days)} j</div>}</> : <span className="muted">—</span>}</td>)}
                    <td className="r"><b>{d.amountsHidden ? `${fr(x.days)} j` : eur(x.amount)}</b>{showDays && !d.amountsHidden && <div className="muted" style={{ fontSize: 11 }}>{fr(x.days)} j</div>}</td>
                  </tr>
                ))}
                <tr className="vb-proj"><td colSpan={d.months.length + 3}><b>Assistants intelligents</b></td></tr>
                {d.ai.length === 0 && <tr><td colSpan={d.months.length + 3} className="muted">Aucune utilisation sur la période.</td></tr>}
                {d.ai.map((x) => (
                  <tr key={x.code}>
                    <td>{x.name}</td><td className="r">{eur(x.price)} / u</td>
                    {d.months.map((m) => <td key={m} className="r">{x.byMonth[m].units ? <>{eur(x.byMonth[m].cost)}<div className="muted" style={{ fontSize: 11 }}>{x.byMonth[m].units} u</div></> : <span className="muted">—</span>}</td>)}
                    <td className="r"><b>{eur(x.cost)}</b><div className="muted" style={{ fontSize: 11 }}>{x.units} u</div></td>
                  </tr>
                ))}
                <tr className="vb-total"><td><b>Total du mois</b></td><td />{d.months.map((m) => <td key={m} className="r"><b>{eur(d.totals[m].total)}</b></td>)}<td className="r"><b>{eur(d.summary.total)}</b></td></tr>
                <tr><td>Cumul</td><td />{d.months.map((m) => <td key={m} className="r">{eur(d.totals[m].cumulative)}</td>)}<td /></tr>
                {d.summary.budget !== null && <tr><td>Reste sur budget</td><td />{d.months.map((m) => <td key={m} className="r" style={{ color: Number(d.summary.budget) - Number(d.totals[m].cumulative) < 0 ? "#b91c1c" : undefined }}>{eur(Number(d.summary.budget) - Number(d.totals[m].cumulative))}</td>)}<td /></tr>}
              </tbody>
            </table>
          </div>
          <p className="muted" style={{ fontSize: 12 }}>Ressources : jours envoyés en validation (hors brouillons et refus) × TJM (projet, client ou profil). Assistants : unités consommées × prix unitaire. Projets : {d.projects.map((p) => p.code).join(", ")}.</p>
        </>
      )}
    </section>
  );
}
