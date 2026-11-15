import { useState } from "react";

import { supportApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, Loading, PageHead, useAction } from "../../components/ui";
import type { Me } from "../../types/api";
import { SaaSReportPanel } from "../configuration/SaaSReportPanel";
import { TenantRightsCard } from "../platform/TenantRightsCard";

const STATUS: Record<string, string> = { new: "Nouvelle", triaged: "À traiter", in_progress: "En cours", resolved: "Résolue", closed: "Clôturée" };

export function MaintenanceWorkspace({ me }: { me: Me }) {
  return me.isSupport ? <SupportWorkspace /> : <ClientWorkspace me={me} />;
}

function ClientWorkspace({ me }: { me: Me }) {
  const data = useApi(supportApi.clientRequests);
  const { run, busy } = useAction();
  const [form, setForm] = useState({ title: "", description: "", category: "assistance" });
  if (data.error) return <ErrorNotice error={data.error} onRetry={data.reload} />;
  if (!data.data) return <Loading />;
  const submit = () => run(() => supportApi.createRequest(form), "Demande envoyée au support Control Tower")
    .then(() => { setForm({ title: "", description: "", category: "assistance" }); data.reload(); }, () => undefined);
  return <div className="page">
    <PageHead eyebrow={me.tenant?.name ?? ""} title="Assistance Control Tower" sub={`Service ${data.data.plan}${data.data.endsAt ? ` · jusqu’au ${data.data.endsAt}` : ""}. Votre demande sera suivie par le support et le Pilote.`} />
    <Card title="Nouvelle demande" sub="Décrivez le besoin ou l’incident. La demande sera suivie dans le système.">
      <div className="frow"><Field id="support-category" label="Type"><select className="inp" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
        <option value="assistance">Accompagnement / assistance</option><option value="maintenance">Maintenance</option><option value="incident">Incident</option><option value="question">Question</option>
      </select></Field><Field id="support-title" label="Objet"><input className="inp" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field></div>
      <Field id="support-description" label="Description"><textarea className="inp" rows={4} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
      <button className="btn primary" disabled={busy || !form.title.trim() || !form.description.trim()} onClick={submit}>Envoyer la demande</button>
    </Card>
    <Card title="Mes demandes" sub="Les équipes de support Control Tower et du Pilote assurent le triage et le traitement.">
      <div className="tbl-wrap"><table className="tbl tight"><thead><tr><th>Objet</th><th>Type</th><th>Créée</th><th>État</th></tr></thead><tbody>
        {data.data.requests.map((row) => <tr key={row.id}><td><b>{row.title}</b><br /><small className="muted">{row.description}</small>{row.aiReply && <div style={{ marginTop: 8, padding: 10, borderRadius: 10, background: "#f1f5ff" }}><b>⚡ THOR · Réponse préliminaire</b><p>{row.aiReply}</p><small className="muted">{row.aiAnalysis}</small></div>}</td><td>{row.category}</td><td>{new Date(row.createdAt).toLocaleString()}</td><td>{STATUS[row.status]}</td></tr>)}
        {!data.data.requests.length && <tr><td colSpan={4} className="muted">Aucune demande.</td></tr>}
      </tbody></table></div>
    </Card>
  </div>;
}

function SupportWorkspace() {
  const data = useApi(supportApi.queue);
  const { run, busy } = useAction();
  if (data.error) return <ErrorNotice error={data.error} onRetry={data.reload} />;
  if (!data.data) return <Loading />;
  const update = (id: number, body: { status?: string; assignedTo?: number | null }) => run(() => supportApi.update(id, body), "Demande mise à jour").then(() => data.reload(), () => undefined);
  return <div className="page"><PageHead eyebrow="Control Tower" title="File du support" sub="Demandes de maintenance et d’accompagnement des clients autorisés." />
    <SaaSReportPanel scope="platform" />
    <SupportTenantConfiguration />
    <Card title={`${data.data.requests.length} demandes à suivre`}>
      <div className="tbl-wrap"><table className="tbl tight"><thead><tr><th>Client</th><th>Demandeur</th><th>Objet / détail</th><th>Type</th><th>Assignée à</th><th>État</th></tr></thead><tbody>
        {data.data.requests.map((row) => <tr key={row.id}><td>{row.tenantName}</td><td>{row.requester}<br /><small className="muted">{row.email}</small></td>
          <td><b>{row.title}</b><br /><small>{row.description}</small>{row.aiReply && <div style={{ marginTop: 8, padding: 10, borderRadius: 10, background: "#f1f5ff" }}><b>⚡ THOR · Première analyse</b><p>{row.aiAnalysis}</p><small>{row.aiReply}</small></div>}</td><td>{row.category}</td>
          <td><select className="inp" aria-label={`Agent assigné à ${row.title}`} value={data.data!.staff.find((s) => s.username === row.assignedTo)?.id ?? ""}
            onChange={(e) => update(row.id, { assignedTo: e.target.value ? Number(e.target.value) : null })}>
            <option value="">Non assignée</option>{data.data!.staff.map((staff) => <option key={staff.id} value={staff.id}>{staff.username}</option>)}
          </select></td><td><select className="inp" aria-label={`État de ${row.title}`} value={row.status} disabled={busy}
            onChange={(e) => update(row.id, { status: e.target.value })}>{Object.entries(STATUS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></td>
        </tr>)}{data.data.requests.length === 0 && <tr><td colSpan={6} className="muted">Aucune demande à traiter.</td></tr>}
      </tbody></table></div>
    </Card>
  </div>;
}

function SupportTenantConfiguration() {
  const tenants = useApi(supportApi.tenants);
  const [tenantId, setTenantId] = useState("");
  if (tenants.error) return <ErrorNotice error={tenants.error} onRetry={tenants.reload} />;
  if (!tenants.data) return <Loading />;
  return <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
    <Card title="Paramétrage des accès clients" sub="Le support peut consulter et modifier, avec le Pilote, les droits d’accès par profil de chaque entreprise.">
      <Field id="support-tenant" label="Entreprise">
        <select id="support-tenant" className="inp" value={tenantId} onChange={(e) => setTenantId(e.target.value)}>
          <option value="">Choisir une entreprise…</option>{tenants.data.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name} · {tenant.status}</option>)}
        </select>
      </Field>
    </Card>
    {tenantId && <TenantRightsCard tenantId={Number(tenantId)} />}
  </div>;
}
