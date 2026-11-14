import { useState } from "react";

import { adminApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Loading, useAction } from "../../components/ui";

export function SSORequestsPanel() {
  const queue = useApi(adminApi.ssoRequests);
  const { run, busy } = useAction();
  const [roles, setRoles] = useState<Record<number, string>>({});
  if (queue.error) return <ErrorNotice error={queue.error} onRetry={queue.reload} />;
  if (!queue.data) return <Loading />;
  const act = (id: number, action: "approve" | "reject") => run(
    () => adminApi.decideSsoRequest(id, action, action === "approve" ? roles[id] : undefined),
    action === "approve" ? "Accès accepté" : "Demande refusée",
  ).then(() => queue.reload(), () => undefined);
  return <Card title="Demandes d’accès SSO" sub="Les comptes créés via SSO restent bloqués jusqu’à leur validation et l’attribution d’un profil.">
    <div className="tbl-wrap"><table className="tbl tight">
      <thead><tr><th>Utilisateur</th><th>Date</th><th>État</th><th>Profil à attribuer</th><th>Décision</th></tr></thead>
      <tbody>{queue.data.requests.map((item) => <tr key={item.id}>
        <td><b>{[item.firstName, item.lastName].filter(Boolean).join(" ") || item.email}</b><br /><span className="muted">{item.email}</span>{item.clientName && <><br /><small>🏢 Domaine du client <b>{item.clientName}</b></small></>}</td>
        <td>{new Date(item.requestedAt).toLocaleString()}</td><td>{item.status === "pending" ? "À traiter" : item.status === "approved" ? "Acceptée" : "Refusée"}</td>
        <td>{item.status === "pending" && <select className="inp" aria-label={`Profil pour ${item.email}`} value={roles[item.id] ?? ""}
          onChange={(e) => setRoles((old) => ({ ...old, [item.id]: e.target.value }))}>
          <option value="">Choisir un profil</option>{queue.data!.roles.filter((role) => !role.external || item.client).map((role) => <option key={role.code} value={role.code}>{role.label}</option>)}
        </select>}{item.status !== "pending" && (item.reviewedBy ?? "—")}</td>
        <td>{item.status === "pending" && <div className="btns">
          <button className="btn primary sm" disabled={busy || !roles[item.id]} onClick={() => act(item.id, "approve")}>Accepter</button>
          <button className="btn sm" disabled={busy} onClick={() => act(item.id, "reject")}>Refuser</button>
        </div>}</td>
      </tr>)}{queue.data.requests.length === 0 && <tr><td colSpan={5} className="muted">Aucune demande pour le moment.</td></tr>}</tbody>
    </table></div>
  </Card>;
}
