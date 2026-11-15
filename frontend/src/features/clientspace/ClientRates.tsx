// TJM et durée de contrat (jours) par consultant pour un client, avec consommation (jours envoyés / validés) et reste.
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { useApi } from "../../api/useApi";
import { useAction } from "../../components/ui";

type Num = string | number | null;
type Row = { user: number; name: string; role: string; company: string; rate: Num; days: Num; start: string; end: string; profileRate: Num; billable: boolean; external: boolean;
  usedDays: Num; validatedDays: Num; remainingDays: Num; pct: number | null; amount: Num; budget: Num; updatedBy: string; updatedAt: string };
type Data = { client: string; clientName: string; canEdit: boolean; rows: Row[]; showAmounts: boolean; canToggleAmounts: boolean; amountsHidden: boolean };
type Edit = { user: number; rate: string; days: string; start: string; end: string; billable: boolean };

const n = (v: Num) => Number(v ?? 0);
const fr = (v: Num) => (v === null || v === "" || v === undefined ? "—" : n(v).toLocaleString("fr-FR", { maximumFractionDigits: 2 }));
const eur = (v: Num) => (v === null || v === "" || v === undefined ? "—" : n(v).toLocaleString("fr-FR", { style: "currency", currency: "EUR" }));
const dfr = (s: string) => (s ? new Date(`${s}T00:00:00`).toLocaleDateString("fr-FR") : "");

export function ClientRates({ clients }: { clients: { code: string; name: string }[] }) {
  const [client, setClient] = useState(clients[0]?.code ?? "");
  useEffect(() => { if (!client && clients[0]) setClient(clients[0].code); }, [clients, client]);
  const r = useApi(() => (client ? api.get<Data>(`/client-space/rates?client=${encodeURIComponent(client)}`) : Promise.resolve(null)), [client]);
  const { run, busy } = useAction();
  const [edit, setEdit] = useState<Edit | null>(null);
  if (!clients.length) return <section className="cs-card"><p className="muted">Aucun client accessible.</p></section>;
  const d = r.data;
  const save = () => edit && void run(() => api.put("/client-space/rates", { client, ...edit }), "TJM et contrat enregistrés").then(() => { setEdit(null); r.reload(); }, () => undefined);
  const tot = (d?.rows ?? []).reduce((a, x) => ({ days: a.days + n(x.days), used: a.used + n(x.usedDays), budget: a.budget + n(x.budget), amount: a.amount + n(x.amount) }), { days: 0, used: 0, budget: 0, amount: 0 });
  const bar = (pct: number | null) => {
    if (pct === null) return null;
    const color = pct >= 100 ? "#b91c1c" : pct >= 80 ? "#d97706" : "#16a34a";
    return (
      <div title={`${pct.toFixed(0)} % consommé`} style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <div style={{ flex: 1, minWidth: 60, height: 6, borderRadius: 3, background: "#e2e8f0", overflow: "hidden" }}>
          <div style={{ width: `${Math.min(100, pct)}%`, height: "100%", background: color }} />
        </div>
        <span style={{ fontSize: 12, color }}>{pct.toFixed(0)} %</span>
      </div>
    );
  };
  return (
    <section className="cs-card">
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <b>TJM &amp; durée de contrat par consultant</b>
        <select className="inp" style={{ width: "auto" }} aria-label="Client" value={client} onChange={(e) => { setClient(e.target.value); setEdit(null); }}>
          {clients.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
        </select>
      </div>
      {d && d.canToggleAmounts && (
        <label className="vb-check" style={{ margin: "8px 0", padding: "8px 10px", border: "1px solid var(--line, #e2e8f0)", borderRadius: 8, display: "flex" }}>
          <input type="checkbox" checked={d.showAmounts} disabled={busy}
            onChange={(e) => void run(() => api.put("/client-space/rates/visibility", { client, show: e.target.checked }),
              e.target.checked ? "TJM et montants affichés pour ce client" : "TJM et montants masqués pour ce client").then(() => r.reload(), () => undefined)} />
          <span><b>Afficher le TJM et les montants</b> à ce client et sur ses CRA <span className="muted">(désactivé par défaut ; décoché : jours uniquement, ni TJM ni sommes)</span></span>
        </label>
      )}
      {d?.amountsHidden && <p className="notice">Les TJM et montants ne sont pas affichés pour ce client.</p>}
      <p className="muted">
        Le TJM saisi ici est celui de la facture générée avec le CRA pour ce client (sauf TJM spécifique à un projet). La consommation compte les jours
        envoyés en validation (hors brouillons et refus) sur la période du contrat ; une alerte apparaît à 80 % puis à 100 %.
        Une ressource interne sans TJM (ou marquée non facturable) a son CRA généré sans facture ; un intervenant externe sans TJM bloque la génération.
      </p>
      {!d ? <p className="muted">Chargement…</p> : d.rows.length === 0 ? <p className="muted">Aucun consultant sur les projets de ce client.</p> : (
        <div className="tbl-wrap">
          <table className="tbl tight">
            <thead><tr><th>Consultant</th><th className="r">TJM HT</th><th className="r">Jours contractés</th><th>Période</th><th className="r">Consommés</th><th className="r">Restants</th><th>Consommation</th><th className="r">Budget</th><th /></tr></thead>
            <tbody>
              {d.rows.map((x) => edit?.user === x.user ? (
                <tr key={x.user}>
                  <td><b>{x.name}</b><div className="muted" style={{ fontSize: 12 }}>{x.role}</div></td>
                  <td><input className="inp" style={{ width: 90 }} type="number" min={0} step="0.01" aria-label="TJM" placeholder={x.profileRate ? `profil ${fr(x.profileRate)}` : "€"} value={edit.rate} onChange={(e) => setEdit({ ...edit, rate: e.target.value })} /></td>
                  <td><input className="inp" style={{ width: 80 }} type="number" min={0} step="0.5" aria-label="Jours contractés" value={edit.days} onChange={(e) => setEdit({ ...edit, days: e.target.value })} /></td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <input className="inp" style={{ width: 140 }} type="date" aria-label="Début" value={edit.start} onChange={(e) => setEdit({ ...edit, start: e.target.value })} />{" "}
                    <input className="inp" style={{ width: 140 }} type="date" aria-label="Fin" value={edit.end} onChange={(e) => setEdit({ ...edit, end: e.target.value })} />
                  </td>
                  <td className="r">{fr(x.usedDays)}</td>
                  <td colSpan={3}><label className="vb-check" title="Le CRA sera généré sans facture"><input type="checkbox" checked={!edit.billable} onChange={(e) => setEdit({ ...edit, billable: !e.target.checked })} /> Non facturable (ressource interne)</label></td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button type="button" className="btn sm primary" disabled={busy} onClick={save}>Enregistrer</button>{" "}
                    <button type="button" className="btn sm" onClick={() => setEdit(null)}>Annuler</button>
                  </td>
                </tr>
              ) : (
                <tr key={x.user}>
                  <td><b>{x.name}</b><div className="muted" style={{ fontSize: 12 }}>{x.role}{x.company ? ` · ${x.company}` : ""}{x.external ? " · externe" : ""}</div>
                    {!x.billable && <div style={{ fontSize: 11, color: "#7c3aed" }}>Non facturable — CRA sans facture</div>}</td>
                  <td className="r">{x.rate ? eur(x.rate) : <span className="muted" title="TJM du profil utilisé à défaut">{x.profileRate ? `${eur(x.profileRate)} (profil)` : "—"}</span>}</td>
                  <td className="r">{fr(x.days)}</td>
                  <td style={{ fontSize: 12 }}>{x.start || x.end ? `${dfr(x.start) || "…"} → ${dfr(x.end) || "…"}` : <span className="muted">—</span>}</td>
                  <td className="r" title={`dont ${fr(x.validatedDays)} j validés`}>{fr(x.usedDays)}<div className="muted" style={{ fontSize: 11 }}>{fr(x.validatedDays)} validés</div></td>
                  <td className="r" style={{ color: x.remainingDays !== null && n(x.remainingDays) < 0 ? "#b91c1c" : undefined }}>{fr(x.remainingDays)}</td>
                  <td style={{ minWidth: 120 }}>{bar(x.pct)}{x.pct !== null && x.pct >= 100 && <div style={{ fontSize: 11, color: "#b91c1c" }}>⚠ contrat dépassé</div>}</td>
                  <td className="r">{eur(x.budget)}<div className="muted" style={{ fontSize: 11 }}>{x.amount ? `${eur(x.amount)} consommés` : ""}</div></td>
                  <td>{d.canEdit && <button type="button" className="btn sm" onClick={() => setEdit({ user: x.user, rate: x.rate ? String(x.rate) : "", days: x.days ? String(x.days) : "", start: x.start, end: x.end, billable: x.billable })}>✏️ Modifier</button>}</td>
                </tr>
              ))}
              <tr className="vb-total"><td><b>Total</b></td><td /><td className="r"><b>{fr(tot.days)}</b></td><td /><td className="r"><b>{fr(tot.used)}</b></td><td className="r"><b>{fr(tot.days - tot.used)}</b></td><td /><td className="r"><b>{eur(tot.budget)}</b><div className="muted" style={{ fontSize: 11 }}>{eur(tot.amount)} consommés</div></td><td /></tr>
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
