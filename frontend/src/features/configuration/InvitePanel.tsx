// Inviter une ou plusieurs personnes à créer leur compte (Pilote : avec ou sans entreprise ; admin : dans son entreprise).
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { platformApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, useAction } from "../../components/ui";

type Inv = { id: number; email: string; tenant: string | null; role: string | null; status: string; statusLabel: string; invitedBy: string; createdAt: string; sentAt: string | null; expiresAt: string; acceptedAt: string | null; acceptedUser: string | null };
type Role = { code: string; label: string };
const TONE: Record<string, string> = { pending: "info", accepted: "ok", expired: "warn", revoked: "" };

export function InvitePanel({ pilot }: { pilot?: boolean }) {
  const list = useApi(() => api.get<{ invitations: Inv[]; roles: Role[] }>("/invitations"));
  const tenants = useApi(() => (pilot ? platformApi.tenants() : Promise.resolve([])), [pilot]);
  const { run, busy } = useAction();
  const [emails, setEmails] = useState("");
  const [message, setMessage] = useState("");
  const [tenant, setTenant] = useState("");
  const [roles, setRoles] = useState<Role[]>([]);
  const [role, setRole] = useState("");
  const [result, setResult] = useState<{ sent: Inv[]; skipped: { email: string; reason: string }[] } | null>(null);

  useEffect(() => {
    if (!pilot && list.data) setRoles(list.data.roles);
  }, [pilot, list.data]);
  useEffect(() => {
    if (!pilot) return;
    setRole("");
    if (!tenant) { setRoles([]); return; }
    api.get<{ roles: Role[] }>(`/invitations/roles?tenant=${tenant}`).then((r) => setRoles(r.roles), () => setRoles([]));
  }, [pilot, tenant]);
  useEffect(() => {
    if (!role && roles.length) setRole((roles.find((r) => r.code !== "admin") ?? roles[0]).code);
  }, [roles, role]);

  const count = emails.split(/[\s,;]+/).filter((x) => x.includes("@")).length;
  const needsRole = !pilot || !!tenant;
  const send = () =>
    void run(() => api.post<{ sent: Inv[]; skipped: { email: string; reason: string }[] }>("/invitations",
      { emails, message, role: needsRole ? role : undefined, tenant: pilot ? tenant || undefined : undefined }), "Invitations envoyées")
      .then((r) => { setResult(r ?? null); setEmails(""); list.reload(); }, () => undefined);

  return (
    <Card title="✉️ Inviter des personnes" sub={pilot
      ? "Invitez une ou plusieurs personnes à découvrir Control Tower (inscription libre avec démo) ou à rejoindre directement une entreprise."
      : "Invitez vos collègues ou consultants : ils reçoivent un e-mail de présentation et leur compte est rattaché à votre entreprise avec le profil choisi."}>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <label><span className="muted" style={{ fontSize: 12 }}>Adresses e-mail (une par ligne, ou séparées par des virgules)</span>
          <textarea className="inp" rows={3} placeholder={"marie.durand@societe.fr\npaul.martin@societe.fr"} value={emails} onChange={(e) => setEmails(e.target.value)} /></label>
        <div className="grid g2" style={{ gap: 10 }}>
          {pilot && (
            <label><span className="muted" style={{ fontSize: 12 }}>Entreprise</span>
              <select className="inp" value={tenant} onChange={(e) => setTenant(e.target.value)}>
                <option value="">Aucune : inscription libre (démo ou code entreprise)</option>
                {(tenants.data ?? []).filter((t) => t.status === "active").map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select></label>
          )}
          {needsRole && (
            <label><span className="muted" style={{ fontSize: 12 }}>Profil attribué</span>
              <select className="inp" value={role} onChange={(e) => setRole(e.target.value)}>
                {roles.map((r) => <option key={r.code} value={r.code}>{r.label}</option>)}
              </select></label>
          )}
        </div>
        <label><span className="muted" style={{ fontSize: 12 }}>Message personnel (facultatif, repris dans l’e-mail)</span>
          <textarea className="inp" rows={2} maxLength={1000} placeholder="Bonjour, je vous invite à rejoindre notre espace de pilotage…" value={message} onChange={(e) => setMessage(e.target.value)} /></label>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <button type="button" className="btn primary" disabled={busy || !count || (needsRole && !role)} onClick={send}>
            {busy ? "Envoi…" : `Envoyer ${count > 1 ? `${count} invitations` : "l’invitation"}`}
          </button>
          <span className="muted" style={{ fontSize: 12 }}>L’e-mail présente la plateforme (modules, données hébergées en Europe, IA, accompagnement offert) avec un lien personnel valable 14 jours.</span>
        </div>
        {result && (
          <div className="callout ok" style={{ display: "block" }}>
            <b>{result.sent.length} invitation(s) envoyée(s).</b>
            {result.skipped.length > 0 && <div>Non envoyées : {result.skipped.map((x) => `${x.email} (${x.reason})`).join(", ")}</div>}
          </div>
        )}
        {list.data && list.data.invitations.length > 0 && (
          <div className="tbl-wrap"><table className="tbl tight">
            <thead><tr><th>Personne</th>{pilot && <th>Entreprise</th>}<th>Profil</th><th>Envoyée</th><th>État</th><th /></tr></thead>
            <tbody>{list.data.invitations.map((i) => (
              <tr key={i.id}>
                <td>{i.email}{i.acceptedUser && <small className="muted" style={{ display: "block" }}>{i.acceptedUser}</small>}</td>
                {pilot && <td>{i.tenant ?? <span className="muted">Inscription libre</span>}</td>}
                <td>{i.role ?? "—"}</td>
                <td>{new Date(i.sentAt ?? i.createdAt).toLocaleDateString("fr-FR")}<small className="muted" style={{ display: "block" }}>par {i.invitedBy}</small></td>
                <td><span className={`pill ${TONE[i.status] ?? ""}`}>{i.statusLabel}</span></td>
                <td><div className="btns">
                  {(i.status === "pending" || i.status === "expired") && <button className="btn ghost sm" disabled={busy} onClick={() => void run(() => api.post(`/invitations/${i.id}`, {}), "Invitation renvoyée").then(() => list.reload(), () => undefined)}>Renvoyer</button>}
                  {i.status === "pending" && <button className="btn ghost sm" disabled={busy} onClick={() => void run(() => api.delete(`/invitations/${i.id}`), "Invitation révoquée").then(() => list.reload(), () => undefined)}>Révoquer</button>}
                </div></td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </div>
    </Card>
  );
}
