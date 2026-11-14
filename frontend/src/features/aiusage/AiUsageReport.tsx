// Consommation des assistants IA : utilisé, quota et reste par assistant et par mois, coût, facture de consommation.
import { useState } from "react";

import { api, API_BASE, ApiError } from "../../api/client";
import { useApi } from "../../api/useApi";
import { ErrorNotice, Loading, useAction } from "../../components/ui";
import "./aiusage.css";

type Month = { used: number; scopeUsed: number; quota: number; remaining: number; over: number; cost: string };
type Assistant = { code: string; name: string; role: string; avatar: string; color: string; quota: number; price: string; byMonth: Record<string, Month>; total: number; cost: string; sources: Record<string, number> };
type Usage = {
  audience: string; months: string[]; assistants: Assistant[]; byProject: { id: string; name: string; units: number }[];
  sources: Record<string, string>; docWeight: number;
  invoice: { month: string; lines: { assistant: string; name: string; units: number; price: string; amount: string }[]; ht: string; vatRate: number; vat: string; ttc: string };
  projects: { id: string; code: string; name: string }[] | null; canConfigure: boolean; clientQuota: boolean;
  pricing: { assistants: Record<string, { quota: number; price: string }>; vatRate: number } | null;
};

const eur = (v: string | number) => Number(v).toLocaleString("fr-FR", { style: "currency", currency: "EUR" });
const mLabel = (m: string) => new Date(`${m}-01T00:00:00`).toLocaleDateString("fr-FR", { month: "short", year: "2-digit" });
const mLong = (m: string) => new Date(`${m}-01T00:00:00`).toLocaleDateString("fr-FR", { month: "long", year: "numeric" });

export function AiUsageReport({ projectId }: { projectId?: string }) {
  const [months, setMonths] = useState(6);
  const [month, setMonth] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [edit, setEdit] = useState(false);
  const q = new URLSearchParams({ months: String(months), ...(projectId ? { project: projectId } : {}), ...(month ? { month } : {}) }).toString();
  const r = useApi(() => api.get<Usage>(`/ai-usage?${q}`), [q]);
  const { run, busy } = useAction();
  if (r.error instanceof ApiError && (r.error.status === 403 || r.error.status === 404)) return null;
  if (r.error) return <ErrorNotice error={r.error} onRetry={r.reload} />;
  if (!r.data) return <Loading label="Calcul de la consommation IA…" />;
  const d = r.data;
  const cur = month || d.months[d.months.length - 1];
  const list = showAll ? d.assistants : d.assistants.filter((a) => a.total > 0 || (a.byMonth[cur]?.scopeUsed ?? 0) > 0);
  const max = Math.max(1, ...d.assistants.flatMap((a) => d.months.map((m) => Math.max(a.byMonth[m]?.used ?? 0, a.quota))));
  const download = async () => {
    const res = await fetch(`${API_BASE}/ai-usage/invoice?${new URLSearchParams({ month: cur, ...(projectId ? { project: projectId } : {}) })}`, { credentials: "include" });
    if (!res.ok) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(await res.blob());
    a.download = `consommation_ia_${cur}.docx`;
    a.click();
  };
  const savePrice = (code: string, field: "quota" | "price", value: string) =>
    void run(() => api.put(`/ai-usage?${q}`, { assistants: { [code]: { [field]: Number(value) } } }), "Paramètre IA enregistré").then(() => r.reload(), () => undefined);

  return (
    <section className="aiu card" aria-label="Consommation des assistants IA">
      <header className="aiu-h">
        <div>
          <h3>🤖 Consommation des assistants IA</h3>
          <small>Interactions par assistant : réponses en appel IA, messages en discussion, actions d’orchestration ; un document rédigé compte pour {d.docWeight}. Quota mensuel {d.clientQuota ? "propre au client" : "de l’entreprise"}.</small>
        </div>
        <div className="aiu-filters">
          <select className="inp" aria-label="Période" value={months} onChange={(e) => setMonths(Number(e.target.value))}>
            <option value={3}>3 derniers mois</option><option value={6}>6 derniers mois</option><option value={12}>12 derniers mois</option>
          </select>
          <select className="inp" aria-label="Mois détaillé" value={cur} onChange={(e) => setMonth(e.target.value)}>
            {d.months.slice().reverse().map((m) => <option key={m} value={m}>{mLong(m)}</option>)}
          </select>
          <label className="aiu-all"><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> Tous les assistants</label>
        </div>
      </header>

      <div className="aiu-cards">
        {list.map((a) => {
          const m = a.byMonth[cur] ?? { used: 0, scopeUsed: 0, quota: a.quota, remaining: a.quota, over: 0, cost: "0" };
          const pct = a.quota ? Math.min(100, (m.scopeUsed / a.quota) * 100) : 100;
          return (
            <article key={a.code} className="aiu-card" style={{ ["--c" as string]: a.color }}>
              <div className="aiu-id"><span className="aiu-av">{a.avatar}</span><div><b>{a.name}</b><small>{a.role}</small></div></div>
              <div className="aiu-nums">
                <div><small>Consommé</small><b>{m.used}</b></div>
                <div><small>Reste</small><b className={m.remaining === 0 ? "crit" : pct > 80 ? "warn" : "ok"}>{m.remaining}</b></div>
                <div><small>Quota</small><b>{m.quota}</b></div>
              </div>
              <div className={`aiu-gauge ${m.over ? "over" : pct > 80 ? "warn" : ""}`} title={`${Math.round(pct)} % du quota`}><i style={{ width: `${pct}%` }} /></div>
              <small className="aiu-meta">{m.over ? `Dépassement : ${m.over} · ` : ""}{eur(m.cost)} HT en {mLong(cur)}{m.scopeUsed !== m.used ? ` · ${m.scopeUsed} sur tout le périmètre` : ""}</small>
              <div className="aiu-spark" aria-label={`Évolution de ${a.name}`}>
                {d.months.map((mm) => {
                  const v = a.byMonth[mm]?.used ?? 0;
                  return <i key={mm} className={mm === cur ? "cur" : ""} style={{ height: `${Math.max(3, (v / max) * 100)}%` }} title={`${mLabel(mm)} : ${v} / ${a.byMonth[mm]?.quota ?? a.quota}`} onClick={() => setMonth(mm)} />;
                })}
                <s style={{ bottom: `${(a.quota / max) * 100}%` }} title={`Quota ${a.quota}`} />
              </div>
            </article>
          );
        })}
        {list.length === 0 && <p className="muted">Aucune consommation IA sur la période.</p>}
      </div>

      <div className="aiu-tables">
        <table className="tbl">
          <thead><tr><th>Assistant</th>{d.months.map((m) => <th key={m} className={`num ${m === cur ? "cur" : ""}`}>{mLabel(m)}</th>)}<th className="num">Total</th><th className="num">Coût</th></tr></thead>
          <tbody>
            {list.map((a) => (
              <tr key={a.code}>
                <td>{a.avatar} {a.name}</td>
                {d.months.map((m) => { const x = a.byMonth[m]; return <td key={m} className={`num ${m === cur ? "cur" : ""}`}><b>{x?.used ?? 0}</b><small className={x && x.remaining === 0 ? "crit" : ""}> / reste {x?.remaining ?? a.quota}</small></td>; })}
                <td className="num"><b>{a.total}</b></td><td className="num">{eur(a.cost)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="aiu-side">
          <div className="aiu-inv">
            <b>🧾 Facture de consommation — {mLong(cur)}</b>
            {d.invoice.lines.length ? (
              <table className="tbl tight">
                <tbody>
                  {d.invoice.lines.map((l) => <tr key={l.assistant}><td>{l.name}</td><td className="num">{l.units} × {eur(l.price)}</td><td className="num">{eur(l.amount)}</td></tr>)}
                  <tr className="tot"><td>Total HT</td><td /><td className="num">{eur(d.invoice.ht)}</td></tr>
                  <tr><td>TVA {d.invoice.vatRate} %</td><td /><td className="num">{eur(d.invoice.vat)}</td></tr>
                  <tr className="tot"><td>Total TTC</td><td /><td className="num">{eur(d.invoice.ttc)}</td></tr>
                </tbody>
              </table>
            ) : <small className="muted">Aucune consommation facturable ce mois-ci.</small>}
            <button type="button" className="btn sm primary" disabled={!d.invoice.lines.length} onClick={() => void download()}>⬇ Facture (Word)</button>
          </div>
          {d.byProject.length > 1 && (
            <div className="aiu-inv">
              <b>Par projet</b>
              {d.byProject.map((p) => <div key={p.id} className="aiu-row"><span>{p.name}</span><b>{p.units}</b></div>)}
            </div>
          )}
          {d.assistants.some((a) => Object.keys(a.sources).length) && (
            <div className="aiu-inv">
              <b>Par usage</b>
              {Object.entries(d.sources).map(([k, label]) => {
                const n = list.reduce((s, a) => s + (a.sources[k] ?? 0), 0);
                return n ? <div key={k} className="aiu-row"><span>{label}</span><b>{n}</b></div> : null;
              })}
            </div>
          )}
        </div>
      </div>

      {d.canConfigure && d.pricing && (
        <details className="aiu-conf" open={edit} onToggle={(e) => setEdit((e.target as HTMLDetailsElement).open)}>
          <summary>⚙ Quotas mensuels et tarifs par assistant (administrateur)</summary>
          <div className="aiu-conf-grid">
            {d.assistants.map((a) => (
              <label key={a.code}>
                <span>{a.avatar} {a.name}</span>
                <input className="inp" type="number" min={0} defaultValue={d.pricing!.assistants[a.code]?.quota} aria-label={`Quota mensuel ${a.name}`} disabled={busy}
                  onBlur={(e) => e.target.value !== String(d.pricing!.assistants[a.code]?.quota) && savePrice(a.code, "quota", e.target.value)} />
                <small>interactions / mois</small>
                <input className="inp" type="number" min={0} step={0.01} defaultValue={d.pricing!.assistants[a.code]?.price} aria-label={`Prix unitaire ${a.name}`} disabled={busy}
                  onBlur={(e) => e.target.value !== String(d.pricing!.assistants[a.code]?.price) && savePrice(a.code, "price", e.target.value)} />
                <small>€ HT / interaction</small>
              </label>
            ))}
          </div>
        </details>
      )}
    </section>
  );
}
