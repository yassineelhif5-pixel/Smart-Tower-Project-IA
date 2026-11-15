// Demandes d'adhésion (comptes inscrits avec le code entreprise) : validation par l'admin du tenant ou le Pilote.
import { useState } from "react";

import { api } from "../../api/client";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Loading, useAction } from "../../components/ui";
import type { JoinRequestRow } from "../../types/api";

const LABEL: Record<string, string> = { pending: "À traiter", approved: "Acceptée", rejected: "Refusée", cancelled: "Annulée" };
type Data = { code: string | null; isDemo: boolean; requests: JoinRequestRow[]; roles: { code: string; label: string }[] };

export function JoinRequestTable({ rows, rolesFor, onDecide, busy, showTenant }: {
  rows: JoinRequestRow[]; rolesFor: (r: JoinRequestRow) => { code: string; label: string }[];
  onDecide: (id: number, action: "approve" | "reject", role: string, comment: string) => void; busy: boolean; showTenant?: boolean;
}) {
  const [roles, setRoles] = useState<Record<number, string>>({});
  const [comments, setComments] = useState<Record<number, string>>({});
  if (!rows.length) return <p className="muted" style={{ margin: 0 }}>Aucune demande.</p>;
  return (
    <div className="tbl-wrap"><table className="tbl tight">
      <thead><tr><th>Demandeur</th>{showTenant && <th>Entreprise</th>}<th>Message</th><th>Date</th><th>État</th><th>Profil</th><th>Décision</th></tr></thead>
      <tbody>{rows.map((r) => (
        <tr key={r.id}>
          <td><b>{r.user}</b><br /><span className="muted">{r.email}</span>
            {(r.company || r.jobTitle) && <><br /><small>{[r.jobTitle, r.kind === "individual" ? "Indépendant" : r.company].filter(Boolean).join(" · ")}</small></>}</td>
          {showTenant && <td>{r.tenant}</td>}
          <td style={{ maxWidth: 260 }}>{r.message || <span className="muted">—</span>}</td>
          <td>{new Date(r.createdAt).toLocaleString("fr-FR")}</td>
          <td>{LABEL[r.status] ?? r.status}{r.decidedBy && <><br /><small className="muted">par {r.decidedBy}</small></>}</td>
          <td>{r.status === "pending"
            ? <select className="inp" aria-label={`Profil pour ${r.email}`} value={roles[r.id] ?? ""} onChange={(e) => setRoles({ ...roles, [r.id]: e.target.value })}>
                <option value="">Choisir un profil</option>
                {rolesFor(r).map((x) => <option key={x.code} value={x.code}>{x.label}</option>)}
              </select>
            : r.role ?? "—"}</td>
          <td>{r.status === "pending" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <input className="inp" placeholder="Commentaire (facultatif)" value={comments[r.id] ?? ""} onChange={(e) => setComments({ ...comments, [r.id]: e.target.value })} />
              <div className="btns">
                <button className="btn primary sm" disabled={busy || !roles[r.id]} onClick={() => onDecide(r.id, "approve", roles[r.id], comments[r.id] ?? "")}>Accepter</button>
                <button className="btn sm" disabled={busy} onClick={() => onDecide(r.id, "reject", "", comments[r.id] ?? "")}>Refuser</button>
              </div>
            </div>
          )}{r.status !== "pending" && r.comment && <small className="muted">{r.comment}</small>}</td>
        </tr>
      ))}</tbody>
    </table></div>
  );
}

export function JoinRequestsPanel() {
  const q = useApi(() => api.get<Data>("/admin/join-requests"));
  const { run, busy } = useAction();
  const [show, setShow] = useState(false);
  if (q.error) return q.error.status === 403 ? null : <ErrorNotice error={q.error} onRetry={q.reload} />;
  if (!q.data) return <Loading />;
  const d = q.data;
  const decide = (id: number, action: "approve" | "reject", role: string, comment: string) =>
    void run(() => api.post(`/admin/join-requests/${id}`, { action, role, comment }), action === "approve" ? "Adhésion acceptée" : "Demande refusée")
      .then(() => q.reload(), () => undefined);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, marginBottom: 14 }}>
      <Card title="🔐 Code entreprise" sub="Communiquez ce code aux personnes qui doivent rejoindre votre entreprise : après inscription, elles le saisissent et vous validez leur demande ci-dessous.">
        {d.isDemo ? <p className="muted" style={{ margin: 0 }}>Une démo ne peut pas être rejointe par code.</p> : (
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <code className="join-code">{show ? d.code : "••••-••••"}</code>
            <button type="button" className="btn sm" onClick={() => setShow((v) => !v)}>{show ? "Masquer" : "Afficher"}</button>
            <button type="button" className="btn sm" onClick={() => d.code && void navigator.clipboard?.writeText(d.code)}>Copier</button>
            <button type="button" className="btn ghost sm" disabled={busy}
              onClick={() => { if (window.confirm("Régénérer le code ? L’ancien code ne fonctionnera plus.")) void run(() => api.post("/admin/join-requests/code", {}), "Nouveau code généré").then(() => { setShow(true); q.reload(); }, () => undefined); }}>
              Régénérer
            </button>
          </div>
        )}
      </Card>
      <Card title="Demandes d’adhésion" sub="Comptes inscrits qui demandent à rejoindre votre entreprise avec le code. Choisissez leur profil avant d’accepter.">
        <JoinRequestTable rows={d.requests} rolesFor={() => d.roles} onDecide={decide} busy={busy} />
      </Card>
    </div>
  );
}
