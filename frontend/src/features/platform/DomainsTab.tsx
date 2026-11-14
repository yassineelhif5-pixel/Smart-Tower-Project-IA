import { useState } from "react";

import { api } from "../../api/client";
import { platformApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, Loading, useAction } from "../../components/ui";

export function DomainsTab() {
  const domains = useApi(platformApi.domains);
  const tenants = useApi(() => platformApi.tenants());
  const clients = useApi(() => api.get<{ code: string; name: string; tenant: number }[]>("/platform/clients"));
  const [client, setClient] = useState("");
  const clientsOf = (t: number) => (clients.data ?? []).filter((c) => c.tenant === t);
  const { run, busy } = useAction();
  const [domain, setDomain] = useState("");
  const [tenant, setTenant] = useState("");
  if (domains.error) return <ErrorNotice error={domains.error} onRetry={domains.reload} />;
  if (tenants.error) return <ErrorNotice error={tenants.error} onRetry={tenants.reload} />;
  if (!domains.data || !tenants.data) return <Loading />;
  const assign = () => run(() => platformApi.assignDomain({ domain: domain.trim(), tenant: Number(tenant), enabled: true, client: client || null }),
    client ? "Domaine autorisé pour le client" : "Domaine affecté à l’entreprise").then(() => { setDomain(""); domains.reload(); }, () => undefined);
  const setRowClient = (id: number, c: string) => run(() => platformApi.updateDomain(id, { client: c || null }),
    c ? "Domaine rattaché au client" : "Domaine rattaché à l’entreprise").then(() => domains.reload(), () => undefined);
  const toggle = (id: number, enabled: boolean) => run(() => platformApi.updateDomain(id, { enabled }),
    enabled ? "Domaine activé" : "Domaine désactivé").then(() => domains.reload(), () => undefined);
  const reassign = (id: number, newTenant: number) => run(() => platformApi.updateDomain(id, { tenant: newTenant }),
    "Entreprise mise à jour").then(() => domains.reload(), () => undefined);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Card title="Domaines des entreprises et de leurs clients" sub="Le Pilote attribue les domaines à une entreprise et, si besoin, à un de ses clients (un client peut avoir plusieurs domaines). Les comptes d’un domaine client sont rattachés automatiquement à ce client.">
        <div className="frow" style={{ alignItems: "end" }}>
          <Field id="sso-domain" label="Domaine e-mail (ex. entreprise.fr)">
            <input id="sso-domain" className="inp" value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="entreprise.fr" />
          </Field>
          <Field id="sso-tenant" label="Entreprise cliente">
            <select id="sso-tenant" className="inp" value={tenant} onChange={(e) => { setTenant(e.target.value); setClient(""); }}>
              <option value="">Choisir une entreprise</option>
              {tenants.data.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </Field>
          <Field id="sso-client" label="Client (facultatif)">
            <select id="sso-client" className="inp" value={client} disabled={!tenant} onChange={(e) => setClient(e.target.value)}>
              <option value="">— Toute l’entreprise —</option>
              {tenant && clientsOf(Number(tenant)).map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
            </select>
          </Field>
          <button className="btn primary" disabled={busy || !domain.trim() || !tenant} onClick={assign}>Affecter le domaine</button>
        </div>
        <div className="tbl-wrap">
          <table className="tbl tight"><thead><tr><th>Domaine</th><th>Entreprise</th><th>Client</th><th>État</th><th>Changer l’entreprise</th><th>Action</th></tr></thead>
            <tbody>{domains.data.map((row) => <tr key={row.id}>
              <td className="mono">{row.domain}</td><td>{row.tenantName}</td>
              <td><select className="inp" aria-label={`Client de ${row.domain}`} value={row.client ?? ""} disabled={busy} onChange={(e) => setRowClient(row.id, e.target.value)}>
                <option value="">— Toute l’entreprise —</option>
                {clientsOf(row.tenant).map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
              </select></td>
              <td>{row.enabled ? "Actif" : "Désactivé"}</td>
              <td><select className="inp" aria-label={`Entreprise de ${row.domain}`} value={row.tenant}
                onChange={(e) => reassign(row.id, Number(e.target.value))}>
                {(tenants.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select></td>
              <td><button className="btn sm" disabled={busy} onClick={() => toggle(row.id, !row.enabled)}>{row.enabled ? "Désactiver" : "Activer"}</button></td>
            </tr>)}
              {domains.data.length === 0 && <tr><td colSpan={6} className="muted">Aucun domaine attribué.</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
