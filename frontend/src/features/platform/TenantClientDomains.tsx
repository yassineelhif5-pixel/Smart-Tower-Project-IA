// Pilote, fiche entreprise : domaines e-mail autorisés pour chaque client (un ou plusieurs par client).
import { useState } from "react";

import { api } from "../../api/client";
import { platformApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Loading, Pill, useAction } from "../../components/ui";

export function TenantClientDomains({ tenantId }: { tenantId: number }) {
  const domains = useApi(platformApi.domains);
  const clients = useApi(() => api.get<{ code: string; name: string; tenant: number }[]>("/platform/clients"));
  const { run, busy } = useAction();
  const [draft, setDraft] = useState<Record<string, string>>({});
  if (domains.error) return <ErrorNotice error={domains.error} onRetry={domains.reload} />;
  if (clients.error) return <ErrorNotice error={clients.error} onRetry={clients.reload} />;
  if (!domains.data || !clients.data) return <Loading />;
  const mine = domains.data.filter((d) => d.tenant === tenantId);
  const list = clients.data.filter((c) => c.tenant === tenantId);
  const add = (client: string) => {
    const domain = (draft[client] ?? "").trim().replace(/^@/, "");
    if (!domain) return;
    void run(() => platformApi.assignDomain({ domain, tenant: tenantId, enabled: true, client }), "Domaine autorisé pour le client")
      .then(() => { setDraft({ ...draft, [client]: "" }); domains.reload(); }, () => undefined);
  };
  const update = (id: number, body: { client?: string | null; enabled?: boolean }, msg: string) =>
    void run(() => platformApi.updateDomain(id, body), msg).then(() => domains.reload(), () => undefined);
  const unassigned = mine.filter((d) => !d.client);
  return (
    <Card title="Domaines autorisés par client" sub="Activez un ou plusieurs domaines e-mail pour chaque client de l’entreprise. Les comptes et demandes d’accès SSO de ces domaines sont rattachés automatiquement au client, qui voit alors tous ses projets.">
      {list.length === 0 ? <p className="muted">Cette entreprise n’a pas encore de client.</p> : (
        <div className="tbl-wrap">
          <table className="tbl tight">
            <thead><tr><th>Client</th><th>Domaines autorisés</th><th>Ajouter un domaine</th></tr></thead>
            <tbody>
              {list.map((c) => {
                const rows = mine.filter((d) => d.client === c.code);
                return (
                  <tr key={c.code}>
                    <td><b>{c.name}</b></td>
                    <td>
                      {rows.length === 0 ? <span className="muted">Aucun</span> : (
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                          {rows.map((d) => (
                            <span key={d.id} className="mono" style={{ display: "inline-flex", gap: 6, alignItems: "center", border: "1px solid var(--line)", borderRadius: 999, padding: "3px 6px 3px 10px", opacity: d.enabled ? 1 : 0.55 }}>
                              @{d.domain}{!d.enabled && <Pill tone="">désactivé</Pill>}
                              <button type="button" className="btn sm ghost" disabled={busy} title={d.enabled ? "Désactiver" : "Réactiver"}
                                onClick={() => update(d.id, { enabled: !d.enabled }, d.enabled ? "Domaine désactivé" : "Domaine réactivé")}>{d.enabled ? "✕" : "↺"}</button>
                            </span>
                          ))}
                        </div>
                      )}
                    </td>
                    <td>
                      <form style={{ display: "flex", gap: 6 }} onSubmit={(e) => { e.preventDefault(); add(c.code); }}>
                        <input className="inp" style={{ maxWidth: 200 }} placeholder="client.fr" aria-label={`Nouveau domaine pour ${c.name}`}
                          value={draft[c.code] ?? ""} onChange={(e) => setDraft({ ...draft, [c.code]: e.target.value })} />
                        <button className="btn sm primary" type="submit" disabled={busy || !(draft[c.code] ?? "").trim()}>+ Activer</button>
                      </form>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {unassigned.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <b>Domaines de l’entreprise sans client</b>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 6 }}>
            {unassigned.map((d) => (
              <span key={d.id} className="mono" style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>@{d.domain}
                <select className="inp" style={{ width: "auto" }} aria-label={`Rattacher ${d.domain} à un client`} value="" disabled={busy}
                  onChange={(e) => e.target.value && update(d.id, { client: e.target.value }, "Domaine rattaché au client")}>
                  <option value="">Rattacher à un client…</option>
                  {list.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
                </select>
              </span>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}
