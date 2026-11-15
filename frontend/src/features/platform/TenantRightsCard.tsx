import { useEffect, useState } from "react";

import { platformApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Loading, useAction } from "../../components/ui";

export function TenantRightsCard({ tenantId }: { tenantId: number }) {
  const data = useApi(() => platformApi.tenantRights(tenantId), [tenantId]);
  const { run, busy } = useAction();
  const [draft, setDraft] = useState<Record<string, { projectCreate: boolean; capabilities: string[] }>>({});
  useEffect(() => {
    if (data.data) setDraft(Object.fromEntries(data.data.roles.filter((r) => !r.locked)
      .map((r) => [r.code, { projectCreate: r.projectCreate, capabilities: r.capabilities }])));
  }, [data.data]);
  if (data.error) return <ErrorNotice error={data.error} onRetry={data.reload} />;
  if (!data.data) return <Loading />;
  const toggle = (role: string, code: string) => setDraft((old) => {
    const current = old[role]?.capabilities ?? [];
    return { ...old, [role]: { ...old[role], capabilities: current.includes(code) ? current.filter((c) => c !== code) : [...current, code] } };
  });
  return <Card title="Droits attribués par le Pilote" sub="Définissez, par profil, qui peut créer des projets et gérer les utilisateurs, licences, sessions et demandes. Le profil Administrateur du client reste complet.">
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {data.data.roles.map((role) => <div key={role.code} style={{ border: "1px solid var(--line)", borderRadius: 10, padding: 12 }}>
        <b>{role.label}</b>
        <label style={{ display: "flex", alignItems: "center", gap: 8, margin: "10px 0" }}>
          <input type="checkbox" checked={role.locked ? true : (draft[role.code]?.projectCreate ?? role.projectCreate)} disabled={role.locked}
            onChange={() => setDraft((old) => ({ ...old, [role.code]: { ...old[role.code], projectCreate: !(old[role.code]?.projectCreate ?? role.projectCreate) } }))} />
          Peut créer des projets
        </label>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 6 }}>
          {data.data!.catalog.filter((c) => c.delegable).map((item) => <label key={item.code} style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input type="checkbox" checked={role.locked || (draft[role.code]?.capabilities ?? role.capabilities).includes(item.code)} disabled={role.locked}
              onChange={() => toggle(role.code, item.code)} />
            {item.domain} · {item.action}
          </label>)}
        </div>
      </div>)}
      <button className="btn primary" disabled={busy} onClick={() => run(() => platformApi.setTenantRights(tenantId, draft), "Droits par profil enregistrés").then((result) => { if (result) data.setData(result); }, () => undefined)}>Enregistrer les droits</button>
    </div>
  </Card>;
}
