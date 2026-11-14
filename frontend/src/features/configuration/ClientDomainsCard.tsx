// Administrateur : domaines e-mail autorisés pour chaque client (un ou plusieurs par client).
import { useState } from "react";

import { api } from "../../api/client";
import { useApi } from "../../api/useApi";
import { Card, Field, Pill, useAction } from "../../components/ui";

type Row = { id: number; domain: string; client: string | null; clientName: string | null; enabled: boolean; createdBy: string | null };
type Data = { domains: Row[]; clients: { code: string; name: string }[] };

export function ClientDomainsCard() {
  const r = useApi(() => api.get<Data>("/admin/client-domains"));
  const { run, busy } = useAction();
  const [domain, setDomain] = useState("");
  const [client, setClient] = useState("");
  if (!r.data) return null;
  const d = r.data;
  const target = client || d.clients[0]?.code || "";
  const add = () => void run(() => api.post<Data>("/admin/client-domains", { domain: domain.trim(), client: target }), "Domaine autorisé pour le client")
    .then((res) => { if (res) { r.setData(res); setDomain(""); } }, () => undefined);
  const patch = (row: Row, body: Record<string, unknown>, msg: string) => void run(() => api.patch(`/admin/client-domains/${row.id}`, body), msg).then(() => r.reload(), () => undefined);
  const byClient = d.clients.map((c) => ({ ...c, rows: d.domains.filter((x) => x.client === c.code) }));
  const company = d.domains.filter((x) => !x.client);
  return (
    <Card title="Domaines autorisés par client" sub="Autorisez un ou plusieurs domaines e-mail par client (ex. client.fr, client-group.com). Les comptes et demandes d’accès SSO de ces domaines sont rattachés automatiquement au bon client. Le Pilote voit et gère aussi ces domaines.">
      <form className="frow" style={{ alignItems: "end" }} onSubmit={(e) => { e.preventDefault(); add(); }}>
        <Field id="cd-domain" label="Domaine e-mail"><input id="cd-domain" className="inp" placeholder="client.fr" value={domain} onChange={(e) => setDomain(e.target.value)} /></Field>
        <Field id="cd-client" label="Client">
          <select id="cd-client" className="inp" value={target} onChange={(e) => setClient(e.target.value)}>
            {d.clients.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
          </select>
        </Field>
        <button className="btn primary" type="submit" disabled={busy || !domain.trim() || !target}>+ Autoriser</button>
      </form>
      <div className="tbl-wrap" style={{ marginTop: 12 }}>
        <table className="tbl tight">
          <thead><tr><th>Client</th><th>Domaines autorisés</th></tr></thead>
          <tbody>
            {byClient.map((c) => (
              <tr key={c.code}>
                <td><b>{c.name}</b></td>
                <td>
                  {c.rows.length === 0 ? <span className="muted">Aucun domaine</span> : (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                      {c.rows.map((x) => (
                        <span key={x.id} className="mono" style={{ display: "inline-flex", gap: 6, alignItems: "center", border: "1px solid var(--line)", borderRadius: 999, padding: "3px 6px 3px 10px", opacity: x.enabled ? 1 : 0.55 }}>
                          @{x.domain}
                          {!x.enabled && <Pill tone="">désactivé</Pill>}
                          <button type="button" className="btn sm ghost" disabled={busy} title={x.enabled ? "Désactiver" : "Réactiver"}
                            onClick={() => patch(x, { enabled: !x.enabled }, x.enabled ? "Domaine désactivé" : "Domaine réactivé")}>{x.enabled ? "✕" : "↺"}</button>
                        </span>
                      ))}
                    </div>
                  )}
                </td>
              </tr>
            ))}
            {company.length > 0 && (
              <tr>
                <td><span className="muted">Entreprise (sans client)</span></td>
                <td>
                  {company.map((x) => (
                    <span key={x.id} className="mono" style={{ marginRight: 10 }}>@{x.domain}
                      <select className="inp" style={{ display: "inline-block", width: "auto", marginLeft: 6 }} aria-label={`Rattacher ${x.domain} à un client`} value="" disabled={busy}
                        onChange={(e) => e.target.value && patch(x, { client: e.target.value }, "Domaine rattaché au client")}>
                        <option value="">Rattacher à un client…</option>
                        {d.clients.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
                      </select>
                    </span>
                  ))}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
