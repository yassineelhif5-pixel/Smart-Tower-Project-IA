// Pilote : gestion des utilisateurs de chaque entreprise (comme l'administrateur), rattachement au bon client
// et affectation à tous les projets d'un client.
import { useState } from "react";

import { api } from "../../api/client";
import { platformApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, Loading, Modal, OneTimeSecret, Pill, useAction } from "../../components/ui";

type Role = { code: string; label: string; internal: boolean };
type Client = { code: string; name: string; projects: number };
type U = { id: number; username: string; firstName: string; lastName: string; email: string; role: string; client: string | null; clientName: string | null;
  isActive: boolean; lastLogin: string | null; projects: { id: string; name: string; client: string }[] };
type Data = { tenant: { id: number; name: string }; users: U[]; roles: Role[]; clients: Client[] };

export function PilotUsersTab() {
  const tenants = useApi(() => platformApi.tenants());
  const [tid, setTid] = useState<number | null>(null);
  const tenantId = tid ?? tenants.data?.[0]?.id ?? null;
  if (tenants.error) return <ErrorNotice error={tenants.error} onRetry={tenants.reload} />;
  if (!tenants.data) return <Loading />;
  return (
    <>
      <div className="toolbar" style={{ marginBottom: 12, display: "flex", gap: 8, alignItems: "center" }}>
        <b>Entreprise :</b>
        <select className="inp" style={{ maxWidth: 360 }} aria-label="Entreprise" value={tenantId ?? ""} onChange={(e) => setTid(Number(e.target.value))}>
          {tenants.data.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      </div>
      {tenantId && <TenantUsers key={tenantId} tenantId={tenantId} />}
    </>
  );
}

function TenantUsers({ tenantId }: { tenantId: number }) {
  const url = `/platform/tenants/${tenantId}/users`;
  const r = useApi(() => api.get<Data>(url), [url]);
  const { run, busy } = useAction();
  const [creating, setCreating] = useState(false);
  const [secret, setSecret] = useState<{ user: string; pwd: string } | null>(null);
  const [q, setQ] = useState("");
  const [assign, setAssign] = useState<{ user: U; client: string } | null>(null);
  const [detail, setDetail] = useState<number | null>(null);
  if (r.error) return <ErrorNotice error={r.error} onRetry={r.reload} />;
  if (!r.data) return <Loading />;
  const d = r.data;
  const roleOf = (c: string) => d.roles.find((x) => x.code === c);
  const patch = (u: U, body: Record<string, unknown>, msg: string) => void run(() => api.patch(`${url}/${u.id}`, body), msg).then(() => r.reload(), () => undefined);
  const reset = (u: U) => void run(() => api.post<{ temporaryPassword: string }>(`${url}/${u.id}`, { action: "reset-password" }), "Mot de passe réinitialisé")
    .then((res) => res && setSecret({ user: u.username, pwd: res.temporaryPassword }), () => undefined);
  const doAssign = () => assign && void run(() => api.post<{ assigned: number }>(`${url}/${assign.user.id}`, { action: "assign-client", client: assign.client }), "Utilisateur affecté aux projets du client")
    .then(() => { setAssign(null); r.reload(); }, () => undefined);
  const users = d.users.filter((u) => !q.trim() || `${u.username} ${u.firstName} ${u.lastName} ${u.email} ${u.clientName ?? ""} ${roleOf(u.role)?.label ?? ""}`.toLowerCase().includes(q.trim().toLowerCase()));
  return (
    <Card title={`Utilisateurs — ${d.tenant.name}`} sub="Créez et gérez les comptes comme l’administrateur de l’entreprise. Les comptes externes (client) sont rattachés à leur client ; tout compte peut être affecté d’un clic à tous les projets d’un client."
      extra={<button type="button" className="btn primary sm" onClick={() => setCreating(true)}>+ Nouvel utilisateur</button>}>
      <input className="inp" style={{ maxWidth: 320, marginBottom: 10 }} placeholder="Rechercher…" aria-label="Rechercher un utilisateur" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="tbl-wrap">
        <table className="tbl tight">
          <thead><tr><th>Utilisateur</th><th>Profil</th><th>Client</th><th>Projets</th><th>État</th><th>Actions</th></tr></thead>
          <tbody>
            {users.map((u) => {
              const role = roleOf(u.role);
              return (
                <tr key={u.id}>
                  <td><button type="button" className="linklike" style={{ background: "none", border: 0, padding: 0, cursor: "pointer", color: "var(--accent)", fontWeight: 700, textAlign: "left" }}
                    title="Voir le détail" onClick={() => setDetail(u.id)}>{[u.firstName, u.lastName].filter(Boolean).join(" ") || u.username}</button><small className="muted" style={{ display: "block" }}>{u.username}{u.email ? ` · ${u.email}` : ""}</small></td>
                  <td>
                    <select className="inp" aria-label={`Profil de ${u.username}`} value={u.role} disabled={busy} onChange={(e) => {
                      const nr = roleOf(e.target.value);
                      patch(u, { role: e.target.value, ...(nr && !nr.internal && !u.client && d.clients[0] ? { client: d.clients[0].code } : {}) }, "Profil modifié");
                    }}>
                      {d.roles.map((x) => <option key={x.code} value={x.code}>{x.label}{x.internal ? "" : " (externe)"}</option>)}
                    </select>
                  </td>
                  <td>
                    {role && !role.internal ? (
                      <select className="inp" aria-label={`Client de ${u.username}`} value={u.client ?? ""} disabled={busy} onChange={(e) => patch(u, { client: e.target.value }, "Client rattaché")}>
                        {d.clients.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
                      </select>
                    ) : <span className="muted">Interne</span>}
                  </td>
                  <td>{u.projects.length ? <span title={u.projects.map((p) => p.name).join(", ")}>{u.projects.length} projet(s)</span> : <span className="muted">Aucun</span>}</td>
                  <td>{u.isActive ? <Pill tone="ok">Actif</Pill> : <Pill tone="">Inactif</Pill>}</td>
                  <td>
                    <div className="btns">
                      <button type="button" className="btn sm" onClick={() => setDetail(u.id)}>Détails</button>
                      <button type="button" className="btn sm" disabled={busy} onClick={() => setAssign({ user: u, client: u.client ?? d.clients[0]?.code ?? "" })}>Affecter à un client</button>
                      <button type="button" className="btn sm" disabled={busy} onClick={() => reset(u)}>Mot de passe</button>
                      <button type="button" className="btn sm ghost" disabled={busy} onClick={() => patch(u, { isActive: !u.isActive }, u.isActive ? "Compte désactivé" : "Compte réactivé")}>{u.isActive ? "Désactiver" : "Réactiver"}</button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {detail && <UserDetail url={`${url}/${detail}`} onClose={() => setDetail(null)} />}
      {creating && <CreateUser d={d} url={url} onClose={() => setCreating(false)} onCreated={(u, pwd) => { setCreating(false); setSecret({ user: u, pwd }); r.reload(); }} />}
      {assign && (
        <Modal title={`Affecter ${assign.user.username} aux projets d’un client`} onClose={() => setAssign(null)}
          footer={<><button type="button" className="btn" onClick={() => setAssign(null)}>Annuler</button><button type="button" className="btn primary" disabled={busy || !assign.client} onClick={doAssign}>Affecter</button></>}>
          <Field id="as-client" label="Client">
            <select id="as-client" className="inp" value={assign.client} onChange={(e) => setAssign({ ...assign, client: e.target.value })}>
              {d.clients.map((c) => <option key={c.code} value={c.code}>{c.name} ({c.projects} projet(s))</option>)}
            </select>
          </Field>
          <p className="muted">L’utilisateur reçoit l’accès à tous les projets actuels de ce client (ses autres affectations sont conservées).</p>
        </Modal>
      )}
      {secret && (
        <Modal title={`Mot de passe temporaire — ${secret.user}`} onClose={() => setSecret(null)} footer={<button type="button" className="btn primary" onClick={() => setSecret(null)}>J’ai copié le mot de passe</button>}>
          <div className="callout ok" style={{ marginBottom: 10 }}>✓ Mot de passe enregistré. Identifiant de connexion : <b className="mono">{secret.user}</b></div>
          <OneTimeSecret label="Mot de passe temporaire (à changer à la première connexion)." value={secret.pwd} />
        </Modal>
      )}
    </Card>
  );
}

function CreateUser({ d, url, onClose, onCreated }: { d: Data; url: string; onClose: () => void; onCreated: (username: string, pwd: string) => void }) {
  const { run, busy } = useAction();
  const [f, setF] = useState({ username: "", firstName: "", lastName: "", email: "", role: d.roles.find((r) => r.code === "consultant")?.code ?? d.roles[0]?.code ?? "", client: d.clients[0]?.code ?? "", assign: true });
  const role = d.roles.find((r) => r.code === f.role);
  const external = role ? !role.internal : false;
  const submit = () => void run(() => api.post<{ temporaryPassword: string; username: string }>(url, {
    username: f.username, firstName: f.firstName, lastName: f.lastName, email: f.email, role: f.role,
    client: external ? f.client : null, ...(f.assign && f.client ? { clientProjects: f.client } : {}),
  }), "Utilisateur créé").then((res) => res && onCreated(res.username, res.temporaryPassword), () => undefined);
  return (
    <Modal title="Nouvel utilisateur" onClose={onClose}
      footer={<><button type="button" className="btn" onClick={onClose}>Annuler</button><button type="button" className="btn primary" disabled={busy || !f.username.trim() || !f.role || (external && !f.client)} onClick={submit}>Créer</button></>}>
      <div className="grid g2">
        <Field id="pu-user" label="Identifiant"><input id="pu-user" className="inp" value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} /></Field>
        <Field id="pu-mail" label="E-mail"><input id="pu-mail" className="inp" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
        <Field id="pu-fn" label="Prénom"><input id="pu-fn" className="inp" value={f.firstName} onChange={(e) => setF({ ...f, firstName: e.target.value })} /></Field>
        <Field id="pu-ln" label="Nom"><input id="pu-ln" className="inp" value={f.lastName} onChange={(e) => setF({ ...f, lastName: e.target.value })} /></Field>
        <Field id="pu-role" label="Profil">
          <select id="pu-role" className="inp" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
            {d.roles.map((r) => <option key={r.code} value={r.code}>{r.label}{r.internal ? "" : " (externe)"}</option>)}
          </select>
        </Field>
        <Field id="pu-client" label={external ? "Client (obligatoire)" : "Client"}>
          <select id="pu-client" className="inp" value={f.client} onChange={(e) => setF({ ...f, client: e.target.value })}>
            {!external && <option value="">— Aucun —</option>}
            {d.clients.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
          </select>
        </Field>
      </div>
      <label style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 10 }}>
        <input type="checkbox" checked={f.assign} disabled={!f.client} onChange={(e) => setF({ ...f, assign: e.target.checked })} /> Affecter aussi à tous les projets de ce client
      </label>
    </Modal>
  );
}

type Detail = Omit<U, "projects" | "client"> & { client: string | null; clientName: string | null;
  displayName: string; roleLabel: string; internal: boolean; dateJoined: string; title: string; team: string; authMode: string; mustChangePassword: boolean;
  license: { kind: string; since: string } | null; sso: { email: string; since: string; issuer: string } | null;
  projects: { id: string; name: string; client: string; canEdit: boolean; dailyRate: string | null; since: string; isPm: boolean; openTasks: number; entries: number }[];
  timesheet: { entries: number; lastDate: string | null };
  allProjects: { id: string; code: string; name: string; client: string }[];
  activity: { at: string; event: string; entity: string; by: string; result: string }[];
};
const dt = (v: string | null | undefined, time = false) => (v ? new Date(v).toLocaleString("fr-FR", time ? { dateStyle: "short", timeStyle: "short" } : { dateStyle: "short" }) : "—");
const AUTH: Record<string, string> = { standard: "Identifiant et mot de passe", sso: "SSO uniquement", both: "Mot de passe ou SSO" };

function UserDetail({ url, onClose }: { url: string; onClose: () => void }) {
  const r = useApi(() => api.get<Detail>(url), [url]);
  const [editing, setEditing] = useState(false);
  const u = r.data;
  return (
    <Modal title={u ? `👤 ${u.displayName}` : "Utilisateur"} onClose={onClose} wide>
      {r.error ? <ErrorNotice error={r.error} onRetry={r.reload} /> : !u ? <Loading /> : (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="kpis">
            <div className="kpi"><label>Profil</label><strong style={{ fontSize: 16 }}>{u.roleLabel}</strong><small>{u.internal ? "Interne" : `Externe · ${u.clientName ?? "sans client"}`}</small></div>
            <div className="kpi"><label>État</label><strong style={{ fontSize: 16 }}>{u.isActive ? "Actif" : "Inactif"}</strong><small>{u.mustChangePassword ? "Mot de passe à changer" : "Mot de passe défini"}</small></div>
            <div className="kpi"><label>Dernière connexion</label><strong style={{ fontSize: 16 }}>{dt(u.lastLogin, true)}</strong><small>Créé le {dt(u.dateJoined)}</small></div>
            <div className="kpi"><label>Projets</label><strong>{u.projects.length}</strong><small>{u.timesheet.entries} saisie(s) de temps · dernière {dt(u.timesheet.lastDate)}</small></div>
          </div>
          <Card title="Identité et accès">
            <div className="grid g2" style={{ fontSize: 14 }}>
              <div><span className="muted">Identifiant</span><br /><b className="mono">{u.username}</b></div>
              <div><span className="muted">E-mail</span><br /><b>{u.email || "—"}</b></div>
              <div><span className="muted">Fonction / équipe</span><br /><b>{[u.title, u.team].filter(Boolean).join(" · ") || "—"}</b></div>
              <div><span className="muted">Client rattaché</span><br /><b>{u.clientName ?? "—"}</b></div>
              <div><span className="muted">Mode de connexion</span><br /><b>{AUTH[u.authMode] ?? u.authMode}</b></div>
              <div><span className="muted">SSO</span><br /><b>{u.sso ? `${u.sso.email} (depuis le ${dt(u.sso.since)})` : "Non lié"}</b></div>
              <div><span className="muted">Licence</span><br /><b>{u.license ? `${u.license.kind || "Nominative"} depuis le ${dt(u.license.since)}` : "Aucune licence nominative"}</b></div>
            </div>
          </Card>
          <Card title="Projets affectés" extra={<button type="button" className="btn sm primary" onClick={() => setEditing(!editing)}>{editing ? "Fermer" : "Gérer les projets"}</button>}>
            {editing && <ProjectPicker url={url} u={u} onSaved={(d) => { r.setData(d); setEditing(false); }} />}
            {editing ? null : u.projects.length === 0 ? <p className="muted">Aucun projet affecté.</p> : (
              <div className="tbl-wrap"><table className="tbl tight">
                <thead><tr><th>Projet</th><th>Client</th><th>Rôle</th><th>Droit</th><th className="r">TJM</th><th className="r">Tâches ouvertes</th><th className="r">Saisies</th><th>Depuis</th></tr></thead>
                <tbody>{u.projects.map((p) => (
                  <tr key={p.id}><td><b>{p.name}</b></td><td>{p.client}</td><td>{p.isPm ? <Pill tone="acc">Chef de projet</Pill> : "Membre"}</td>
                    <td>{p.canEdit ? "Modification" : "Lecture"}</td><td className="r">{p.dailyRate ? `${Number(p.dailyRate).toLocaleString("fr-FR")} €` : "—"}</td>
                    <td className="r">{p.openTasks}</td><td className="r">{p.entries}</td><td>{dt(p.since)}</td></tr>
                ))}</tbody>
              </table></div>
            )}
          </Card>
          <Card title="Dernières actions" sub="Journal d’audit : actions faites par ce compte ou sur ce compte (25 dernières).">
            {u.activity.length === 0 ? <p className="muted">Aucune activité enregistrée.</p> : (
              <div className="tbl-wrap"><table className="tbl tight">
                <thead><tr><th>Date</th><th>Action</th><th>Objet</th><th>Par</th></tr></thead>
                <tbody>{u.activity.map((a, i) => (
                  <tr key={i}><td>{dt(a.at, true)}</td><td>{a.event}{a.result !== "success" ? <Pill tone="crit">{a.result}</Pill> : null}</td><td>{a.entity}</td><td>{a.by}</td></tr>
                ))}</tbody>
              </table></div>
            )}
          </Card>
        </div>
      )}
    </Modal>
  );
}

/** Choix des projets affectés : cases par projet (accès) et droit de modification, regroupés par client. */
function ProjectPicker({ url, u, onSaved }: { url: string; u: Detail; onSaved: (d: Detail) => void }) {
  const { run, busy } = useAction();
  const [sel, setSel] = useState<Record<string, boolean>>(() => Object.fromEntries(u.projects.map((p) => [p.id, p.canEdit])));
  const [q, setQ] = useState("");
  const groups = new Map<string, Detail["allProjects"]>();
  for (const p of u.allProjects) {
    if (q.trim() && !`${p.name} ${p.code} ${p.client}`.toLowerCase().includes(q.trim().toLowerCase())) continue;
    groups.set(p.client || "Sans client", [...(groups.get(p.client || "Sans client") ?? []), p]);
  }
  const toggle = (id: string, on: boolean) => setSel((s) => { const n = { ...s }; if (on) n[id] = n[id] ?? !!u.internal; else delete n[id]; return n; });
  const save = () => void run(() => api.put<Detail>(`${url}/projects`, { projects: Object.entries(sel).map(([project, canEdit]) => ({ project, canEdit })) }), "Projets affectés enregistrés")
    .then((d) => d && onSaved(d), () => undefined);
  const count = Object.keys(sel).length;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <input className="inp" style={{ maxWidth: 300 }} placeholder="Filtrer les projets…" aria-label="Filtrer les projets" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="muted">{count} projet(s) sélectionné(s)</span>
        <button type="button" className="btn sm primary" style={{ marginLeft: "auto" }} disabled={busy} onClick={save}>Enregistrer</button>
      </div>
      {[...groups.entries()].map(([client, list]) => {
        const all = list.every((p) => p.id in sel);
        return (
          <div key={client} style={{ border: "1px solid var(--line)", borderRadius: 10, padding: "8px 12px" }}>
            <label style={{ display: "flex", gap: 8, alignItems: "center", fontWeight: 700, marginBottom: 6 }}>
              <input type="checkbox" checked={all} onChange={(e) => list.forEach((p) => toggle(p.id, e.target.checked))} /> {client} <small className="muted">({list.length} projet(s) — tout cocher)</small>
            </label>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(260px,1fr))", gap: 4 }}>
              {list.map((p) => (
                <div key={p.id} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <label style={{ display: "flex", gap: 6, alignItems: "center", flex: 1 }}>
                    <input type="checkbox" checked={p.id in sel} onChange={(e) => toggle(p.id, e.target.checked)} /> {p.name}
                  </label>
                  {p.id in sel && (
                    <label style={{ fontSize: 12, display: "flex", gap: 4, alignItems: "center" }} title="Droit de modification sur le projet">
                      <input type="checkbox" checked={sel[p.id]} onChange={(e) => setSel({ ...sel, [p.id]: e.target.checked })} /> modif.
                    </label>
                  )}
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
