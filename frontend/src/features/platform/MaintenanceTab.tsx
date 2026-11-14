import { useState } from "react";

import { platformApi, supportApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, Loading, OneTimeSecret, Pill, fmtDate, useAction } from "../../components/ui";

export function MaintenanceTab() {
  const tenants = useApi(() => platformApi.tenants());
  const data = useApi(platformApi.maintenance);
  const supportUsers = useApi(platformApi.supportUsers);
  const { run, busy } = useAction();
  const [newAgent, setNewAgent] = useState({ username: "", email: "" });
  const [secret, setSecret] = useState<{ username: string; value: string } | null>(null);
  if (tenants.error) return <ErrorNotice error={tenants.error} onRetry={tenants.reload} />;
  if (data.error) return <ErrorNotice error={data.error} onRetry={data.reload} />;
  if (supportUsers.error) return <ErrorNotice error={supportUsers.error} onRetry={supportUsers.reload} />;
  if (!tenants.data || !data.data || !supportUsers.data) return <Loading />;
  const entitlement = new Map(data.data.entitlements.map((item) => [item.tenant, item]));
  const toggle = (tenant: number, enabled: boolean) => run(() => platformApi.setMaintenance(tenant, { enabled }),
    enabled ? "Maintenance attribuée" : "Maintenance retirée").then(() => data.reload(), () => undefined);
  const move = (id: number, status: "triaged" | "in_progress" | "resolved") => run(() => supportApi.update(id, { status }),
    status === "resolved" ? "Demande résolue" : "Demande prise en charge").then(() => data.reload(), () => undefined);
  const createAgent = () => run(() => platformApi.createSupportUser(newAgent), "Compte support créé")
    .then((result) => { if (result) { setSecret({ username: result.username, value: result.temporaryPassword }); setNewAgent({ username: "", email: "" }); supportUsers.reload(); } }, () => undefined);
  return <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
    {secret && <Card title={`Accès provisoire · ${secret.username}`}><OneTimeSecret label="Mot de passe provisoire. Il devra être changé à la première connexion." value={secret.value} /><button className="btn sm" onClick={() => setSecret(null)}>Masquer</button></Card>}
    <Card title="Équipe support Control Tower" sub="Les agents disposent uniquement de la file de demandes support, pas de la console Pilote ni des espaces clients.">
      <div className="tbl-wrap"><table className="tbl tight"><thead><tr><th>Identifiant</th><th>E-mail</th><th>État</th></tr></thead><tbody>
        {supportUsers.data.map((user) => <tr key={user.id}><td>{user.username}</td><td>{user.email || "—"}</td><td>{user.isActive ? "Actif" : "Désactivé"}</td></tr>)}
      </tbody></table></div>
      <div className="frow" style={{ alignItems: "end", marginTop: 12 }}><Field id="support-user" label="Identifiant"><input className="inp" value={newAgent.username} onChange={(e) => setNewAgent({ ...newAgent, username: e.target.value })} /></Field>
        <Field id="support-email" label="E-mail"><input className="inp" type="email" value={newAgent.email} onChange={(e) => setNewAgent({ ...newAgent, email: e.target.value })} /></Field>
        <button className="btn primary" disabled={busy || !newAgent.username.trim()} onClick={createAgent}>Créer un accès support</button></div>
    </Card>
    <div className="grid g3">
      <Card title="Demandes totales"><b>{data.data.statistics.total}</b></Card>
      <Card title="Nouvelles"><b>{data.data.statistics.byStatus.new ?? 0}</b></Card>
      <Card title="En cours"><b>{(data.data.statistics.byStatus.triaged ?? 0) + (data.data.statistics.byStatus.in_progress ?? 0)}</b></Card>
    </div>
    <Card title="Droits de maintenance par client" sub="La maintenance est un service séparé des licences applicatives.">
      <div className="tbl-wrap"><table className="tbl tight"><thead><tr><th>Client</th><th>Service</th><th>Demandes</th><th>Action</th></tr></thead>
        <tbody>{tenants.data.map((tenant) => { const grant = entitlement.get(tenant.id); return <tr key={tenant.id}>
          <td>{tenant.name}</td><td>{grant?.enabled ? <Pill tone="ok">Activée</Pill> : <Pill tone="">Non attribuée</Pill>}</td>
          <td>{grant?.requestCount ?? 0}</td><td><button className="btn sm" disabled={busy} onClick={() => toggle(tenant.id, !grant?.enabled)}>{grant?.enabled ? "Retirer l’accès" : "Attribuer l’accès"}</button></td>
        </tr>; })}</tbody>
      </table></div>
    </Card>
    <Card title="Demandes d’assistance Control Tower" sub="Les demandes des clients ayant reçu un droit de maintenance arrivent ici pour triage et suivi.">
      <div className="tbl-wrap"><table className="tbl tight"><thead><tr><th>Client</th><th>Demandeur</th><th>Objet</th><th>Catégorie</th><th>Date</th><th>État</th><th>Suivi</th></tr></thead>
        <tbody>{data.data.requests.map((item) => <tr key={item.id}><td>{item.tenantName}</td><td>{item.requester}</td>
          <td><b>{item.title}</b><br /><small className="muted">{item.description}</small></td><td>{item.category}</td><td>{fmtDate(item.createdAt)}</td>
          <td>{item.status}</td><td>{item.status === "new" ? <button className="btn sm" disabled={busy} onClick={() => move(item.id, "triaged")}>Trier</button>
            : item.status !== "resolved" && item.status !== "closed" ? <button className="btn sm" disabled={busy} onClick={() => move(item.id, "resolved")}>Résoudre</button> : "—"}</td>
        </tr>)}{data.data.requests.length === 0 && <tr><td colSpan={7} className="muted">Aucune demande d’assistance.</td></tr>}</tbody>
      </table></div>
    </Card>
  </div>;
}
