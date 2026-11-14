import { useState } from "react";

import { adminApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, Loading, useAction } from "../../components/ui";
import type { Me } from "../../types/api";

export function AccessChangeRequestsPanel({ me }: { me: Me }) {
  const queue = useApi(adminApi.accessChangeRequests);
  const { run, busy } = useAction();
  const [user, setUser] = useState("");
  const [roleById, setRoleById] = useState<Record<number, string>>({});
  const [role, setRole] = useState("");
  const [reason, setReason] = useState("");
  if (queue.error) return <ErrorNotice error={queue.error} onRetry={queue.reload} />;
  if (!queue.data) return <Loading />;
  const submit = () => run(() => adminApi.requestAccessChange({ user: Number(user), role, reason: reason.trim() }),
    "Demande transmise à l’administrateur").then(() => { setReason(""); queue.reload(); }, () => undefined);
  const decide = (id: number, action: "approve" | "reject") => run(
    () => adminApi.decideAccessChange(id, action, roleById[id]), action === "approve" ? "Accès modifié" : "Demande refusée",
  ).then(() => queue.reload(), () => undefined);
  return <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
    {!me.isAdmin && <Card title="Demander un changement d’accès" sub="Choisissez la personne, le profil souhaité et expliquez le besoin. L’administrateur appliquera le changement après validation.">
      <div className="frow"><Field id="access-request-user" label="Utilisateur"><select className="inp" value={user} onChange={(e) => setUser(e.target.value)}>
        <option value="">Choisir…</option>{queue.data.users.map((u) => <option key={u.id} value={u.id}>{u.username}{u.email ? ` · ${u.email}` : ""}</option>)}
      </select></Field><Field id="access-request-role" label="Profil souhaité"><select className="inp" value={role} onChange={(e) => setRole(e.target.value)}>
        <option value="">Choisir…</option>{queue.data.roles.map((r) => <option key={r.code} value={r.code}>{r.label}</option>)}
      </select></Field></div>
      <Field id="access-request-reason" label="Motif"><textarea className="inp" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      <button className="btn primary" disabled={busy || !user || !role || !reason.trim()} onClick={submit}>Envoyer la demande</button>
    </Card>}
    <Card title={me.isAdmin ? "Demandes à valider" : "Mes demandes d’accès"} sub="Toute décision d’accès est journalisée.">
      <div className="tbl-wrap"><table className="tbl tight"><thead><tr><th>Utilisateur</th><th>Demandeur</th><th>Profil souhaité</th><th>Motif</th><th>État</th><th>Décision</th></tr></thead>
        <tbody>{queue.data.requests.map((r) => <tr key={r.id}><td>{r.username}<br /><small className="muted">{r.email}</small></td><td>{r.requestedBy}</td>
          <td>{me.isAdmin && r.status === "pending" ? <select className="inp" value={roleById[r.id] ?? r.requestedRole} onChange={(e) => setRoleById((old) => ({ ...old, [r.id]: e.target.value }))}>
            {queue.data!.roles.map((x) => <option key={x.code} value={x.code}>{x.label}</option>)}</select> : r.requestedRole}</td>
          <td>{r.reason}</td><td>{r.status === "pending" ? "À traiter" : r.status === "approved" ? "Acceptée" : "Refusée"}</td>
          <td>{me.isAdmin && r.status === "pending" && <div className="btns"><button className="btn primary sm" disabled={busy} onClick={() => decide(r.id, "approve")}>Valider</button>
            <button className="btn sm" disabled={busy} onClick={() => decide(r.id, "reject")}>Refuser</button></div>}</td>
        </tr>)}{queue.data.requests.length === 0 && <tr><td colSpan={6} className="muted">Aucune demande.</td></tr>}</tbody>
      </table></div>
    </Card>
  </div>;
}
