// Consommation de licences : par ressource du client et reporting global (stock, utilisation, tendance, commandes).
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { useApi } from "../../api/useApi";

type Row = { user: number; name: string; role: string; internal: boolean; company: string; licence: string; licenceKind: string; licenceNumber: string;
  since: string | null; sessions: number; hours: number; activeDays: number; lastLogin: string | null; inactive: boolean };
type Stock = { total: number; used: number; available: number; rate: number | null };
type Data = { clientName: string; rows: Row[]; monthly: { month: string; label: string; activeUsers: number; sessions: number; hours: number; named: number }[];
  global: { resources: number; namedHolders: number; activeResources: number; inactiveHolders: number; sessions: number; hours: number; peakUsers: number;
    peakDay: string | null; tenantNamed: Stock; tenantConcurrent: Stock; ordered: Record<string, string>;
    orders: { id: string; item: string; quantity: string; status: string; at: string; projects: string[] }[] } };
const ST: Record<string, string> = { pending: "En attente", accepted: "Acceptée", rejected: "Refusée", delivered: "Livrée" };
const KIND_COLOR: Record<string, string> = { named: "#2563eb", concurrent: "#7c3aed", session: "#0891b2", none: "#94a3b8" };
const d = (s: string | null) => (s ? new Date(s).toLocaleDateString("fr-FR") : "—");

export function LicenceReport({ clients }: { clients: { code: string; name: string }[] }) {
  const [client, setClient] = useState(clients[0]?.code ?? "");
  useEffect(() => { if (!client && clients[0]) setClient(clients[0].code); }, [clients, client]);
  const [months, setMonths] = useState(3);
  const [view, setView] = useState<"global" | "resources">("global");
  const r = useApi(() => (client ? api.get<Data>(`/client-portal/licences?client=${encodeURIComponent(client)}&months=${months}`) : Promise.resolve(null)), [client, months]);
  const x = r.data;
  const kpi = (label: string, value: string | number, sub?: string, warn = false) => (
    <div style={{ border: "1px solid var(--line, #e2e8f0)", borderRadius: 10, padding: "8px 10px" }}>
      <div className="muted" style={{ fontSize: 12 }}>{label}</div><b style={{ fontSize: 18, color: warn ? "#b45309" : undefined }}>{value}</b>
      {sub && <div className="muted" style={{ fontSize: 12 }}>{sub}</div>}
    </div>
  );
  const stock = (label: string, s: Stock) => (
    <div style={{ border: "1px solid var(--line, #e2e8f0)", borderRadius: 10, padding: "8px 10px" }}>
      <div className="muted" style={{ fontSize: 12 }}>{label}</div>
      <b style={{ fontSize: 18 }}>{s.used} / {s.total}</b> <span className="muted" style={{ fontSize: 12 }}>utilisées · {s.available} disponible(s)</span>
      <div style={{ height: 6, borderRadius: 3, background: "#e2e8f0", marginTop: 6, overflow: "hidden" }}>
        <div style={{ width: `${Math.min(100, s.rate ?? 0)}%`, height: "100%", background: (s.rate ?? 0) >= 90 ? "#b91c1c" : "#2563eb" }} />
      </div>
    </div>
  );
  const maxUsers = Math.max(1, ...(x?.monthly ?? []).map((m) => Math.max(m.activeUsers, m.named)));
  return (
    <section className="cs-card">
      <div className="vb-bar">
        <b>Consommation de licences</b>
        <select className="inp" style={{ width: "auto" }} aria-label="Client" value={client} onChange={(e) => setClient(e.target.value)}>
          {clients.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
        </select>
        <select className="inp" style={{ width: "auto" }} aria-label="Période" value={months} onChange={(e) => setMonths(Number(e.target.value))}>
          {[1, 3, 6, 12].map((m) => <option key={m} value={m}>{m === 1 ? "Mois en cours" : `${m} derniers mois`}</option>)}
        </select>
        <div className="vb-seg">
          <button type="button" className={view === "global" ? "on" : ""} onClick={() => setView("global")}>Reporting global</button>
          <button type="button" className={view === "resources" ? "on" : ""} onClick={() => setView("resources")}>Par ressource</button>
        </div>
      </div>
      {!x ? <p className="muted">Chargement…</p> : view === "global" ? (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 8, margin: "10px 0" }}>
            {kpi("Ressources du client", x.global.resources, `${x.global.activeResources} active(s) sur la période`)}
            {kpi("Licences nominatives détenues", x.global.namedHolders, x.global.inactiveHolders ? `${x.global.inactiveHolders} sans activité` : "toutes utilisées", x.global.inactiveHolders > 0)}
            {kpi("Sessions", x.global.sessions, `${x.global.hours.toLocaleString("fr-FR")} h d'utilisation`)}
            {kpi("Pic d'utilisateurs / jour", x.global.peakUsers, x.global.peakDay ? `le ${d(x.global.peakDay)}` : "")}
            {stock("Stock nominatif (entreprise)", x.global.tenantNamed)}
            {stock("Stock concurrent (entreprise)", x.global.tenantConcurrent)}
          </div>
          <b>Tendance mensuelle</b>
          <div className="tbl-wrap">
            <table className="tbl tight">
              <thead><tr><th>Mois</th><th className="r">Licences nominatives</th><th className="r">Utilisateurs actifs</th><th className="r">Sessions</th><th className="r">Heures</th><th style={{ width: "35%" }} /></tr></thead>
              <tbody>{x.monthly.map((m) => (
                <tr key={m.month}><td style={{ textTransform: "capitalize" }}>{m.label}</td><td className="r">{m.named}</td><td className="r">{m.activeUsers}</td><td className="r">{m.sessions}</td><td className="r">{m.hours.toLocaleString("fr-FR")}</td>
                  <td><div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                    <div title="Licences nominatives" style={{ height: 6, width: `${(m.named / maxUsers) * 100}%`, background: "#2563eb", borderRadius: 3 }} />
                    <div title="Utilisateurs actifs" style={{ height: 6, width: `${(m.activeUsers / maxUsers) * 100}%`, background: "#16a34a", borderRadius: 3 }} />
                  </div></td></tr>
              ))}</tbody>
            </table>
          </div>
          <b>Licences commandées par le client</b>
          {x.global.orders.length === 0 ? <p className="muted">Aucune commande de licence.</p> : (
            <div className="tbl-wrap"><table className="tbl tight">
              <thead><tr><th>Date</th><th>Article</th><th className="r">Quantité</th><th>Projets</th><th>Statut</th></tr></thead>
              <tbody>{x.global.orders.map((o) => <tr key={o.id}><td>{d(o.at)}</td><td>{o.item}</td><td className="r">{o.quantity}</td><td>{o.projects.join(", ")}</td><td>{ST[o.status] ?? o.status}</td></tr>)}</tbody>
            </table></div>
          )}
        </>
      ) : (
        <div className="tbl-wrap" style={{ marginTop: 10 }}>
          <table className="tbl tight">
            <thead><tr><th>Ressource</th><th>Licence</th><th>Depuis</th><th className="r">Sessions</th><th className="r">Heures</th><th className="r">Jours actifs</th><th>Dernière connexion</th></tr></thead>
            <tbody>{x.rows.map((p) => (
              <tr key={p.user}>
                <td><b>{p.name}</b><div className="muted" style={{ fontSize: 12 }}>{p.role}{p.company ? ` · ${p.company}` : ""}{p.internal ? "" : " · compte client"}</div></td>
                <td><span style={{ padding: "1px 8px", borderRadius: 999, fontSize: 12, background: `${KIND_COLOR[p.licenceKind]}1a`, color: KIND_COLOR[p.licenceKind] }}>{p.licence}</span>
                  {p.licenceNumber && <div className="muted" style={{ fontSize: 11 }}>{p.licenceNumber}</div>}
                  {p.licenceKind === "named" && p.inactive && <div style={{ fontSize: 11, color: "#b45309" }}>⚠ licence non utilisée</div>}</td>
                <td>{d(p.since)}</td><td className="r">{p.sessions}</td><td className="r">{p.hours.toLocaleString("fr-FR")}</td><td className="r">{p.activeDays}</td><td>{d(p.lastLogin)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </section>
  );
}
