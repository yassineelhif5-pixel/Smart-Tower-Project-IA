// Journal des envois de notifications (e-mail) : utilisé par l'administrateur et le Pilote.
import { useState } from "react";

export type Delivery = { at: string; event: string; eventLabel: string; channel: string; recipient: string; subject: string; status: "sent" | "failed" | "skipped"; error: string; source: string };
export type DeliveryData = { stats7d: { sent: number; failed: number; skipped: number }; rows: Delivery[] };
const ST: Record<string, [string, string]> = { sent: ["Envoyé", "#15803d"], failed: ["Échec", "#b91c1c"], skipped: ["Non envoyé", "#b45309"] };

export function DeliveryLog({ data, title = "Journal des envois" }: { data: DeliveryData; title?: string }) {
  const [f, setF] = useState("");
  const [q, setQ] = useState("");
  const rows = data.rows.filter((r) => (!f || r.status === f) && (!q || `${r.recipient} ${r.subject} ${r.eventLabel}`.toLowerCase().includes(q.toLowerCase())));
  return (
    <div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 8 }}>
        <b>{title}</b>
        <span className="muted" style={{ fontSize: 12 }}>7 derniers jours :</span>
        {(["sent", "failed", "skipped"] as const).map((k) => (
          <button key={k} type="button" className={`btn sm ${f === k ? "primary" : ""}`} onClick={() => setF(f === k ? "" : k)}>
            <span style={{ color: f === k ? undefined : ST[k][1] }}>●</span> {ST[k][0]} : {data.stats7d[k]}
          </button>
        ))}
        <input className="inp" style={{ flex: 1, minWidth: 180 }} placeholder="Rechercher (destinataire, objet…)" aria-label="Rechercher" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {rows.length === 0 ? <p className="muted">Aucun envoi enregistré.</p> : (
        <div className="tbl-wrap" style={{ maxHeight: 360, overflow: "auto" }}>
          <table className="tbl tight">
            <thead><tr><th>Date</th><th>Événement</th><th>Destinataire</th><th>Objet</th><th>Statut</th></tr></thead>
            <tbody>{rows.map((r, i) => (
              <tr key={i}>
                <td style={{ whiteSpace: "nowrap", fontSize: 12 }}>{new Date(r.at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</td>
                <td style={{ fontSize: 12 }}>{r.eventLabel}</td>
                <td style={{ fontSize: 12 }}>{r.recipient}</td>
                <td style={{ fontSize: 12 }}>{r.subject}</td>
                <td><span style={{ color: ST[r.status]?.[1], fontSize: 12, fontWeight: 600 }}>{ST[r.status]?.[0] ?? r.status}</span>
                  {r.error && <div className="muted" style={{ fontSize: 11, maxWidth: 260 }}>{r.error}</div>}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}
