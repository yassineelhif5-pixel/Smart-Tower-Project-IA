import { useState } from "react";

import { platformApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Loading, useAction } from "../../components/ui";

export function ConnectorAssignmentsTab() {
  const data = useApi(platformApi.connectorAssignments);
  const { run, busy } = useAction();
  const [q, setQ] = useState("");
  if (data.error) return <ErrorNotice error={data.error} onRetry={data.reload} />;
  if (!data.data) return <Loading />;
  const d = data.data;
  const match = (...t: string[]) => !q.trim() || t.join(" ").toLowerCase().includes(q.trim().toLowerCase());
  const setProject = (project: string, connector: string, enabled: boolean) => run(
    () => platformApi.setProjectConnector(project, connector, enabled),
    enabled ? "Connecteur autorisé sur le projet" : "Connecteur retiré du projet",
  ).then(() => data.reload(), () => undefined);
  const setClient = (tenant: number, client: string, name: string, connector: string, enabled: boolean) => run(
    () => platformApi.setClientConnector(tenant, client, connector, enabled),
    enabled ? `Connecteur accordé au client ${name} : tous ses projets en bénéficient` : `Connecteur retiré au client ${name} et à ses projets`,
  ).then(() => data.reload(), () => undefined);
  const clients = (d.clients ?? []).filter((c) => match(c.tenantName, c.name));
  const projects = d.projects.filter((p) => match(p.tenantName, p.name, p.client));
  return <>
    <div className="toolbar" style={{ marginBottom: 12 }}>
      <input className="inp" style={{ maxWidth: 360 }} placeholder="Filtrer par entreprise, client ou projet…" aria-label="Filtrer" value={q} onChange={(e) => setQ(e.target.value)} />
    </div>
    <Card title="Connecteurs accordés par client" sub="Accordez un connecteur à un client : tous ses projets, actuels et futurs, en bénéficient. Le retrait le désactive sur tous ses projets (vous pouvez ensuite réactiver un projet précis ci-dessous).">
      {clients.length === 0 ? <p className="muted">Aucun client.</p> : <div className="tbl-wrap">
        <table className="tbl tight"><thead><tr><th>Entreprise</th><th>Client</th><th className="r">Projets</th>{d.connectors.map((c) => <th key={c.code}>{c.label}</th>)}</tr></thead>
          <tbody>{clients.map((c) => <tr key={`${c.tenant}-${c.code}`}><td>{c.tenantName}</td><td><b>{c.name}</b></td><td className="r">{c.projectCount}</td>
            {d.connectors.map((connector) => <td key={connector.code} style={{ textAlign: "center" }}>
              <input type="checkbox" aria-label={`${connector.label} pour le client ${c.name}`} checked={!!c.connectors[connector.code]} disabled={busy}
                onChange={(e) => setClient(c.tenant, c.code, c.name, connector.code, e.target.checked)} />
            </td>)}
          </tr>)}</tbody>
        </table>
      </div>}
    </Card>
    <Card title="Connecteurs autorisés par projet" sub="Réglage fin projet par projet. « via client » : connecteur hérité de l’autorisation donnée au client. L’administrateur de l’entreprise ne voit que les connecteurs activés sur au moins un de ses projets.">
      {projects.length === 0 ? <p className="muted">Aucun projet disponible.</p> : <div className="tbl-wrap">
        <table className="tbl tight"><thead><tr><th>Entreprise</th><th>Projet</th><th>Client</th>{d.connectors.map((c) => <th key={c.code}>{c.label}</th>)}</tr></thead>
          <tbody>{projects.map((project) => <tr key={`${project.tenant}-${project.id}`}><td>{project.tenantName}</td><td><b>{project.name}</b></td><td>{project.client}</td>
            {d.connectors.map((connector) => <td key={connector.code} style={{ textAlign: "center" }}>
              <input type="checkbox" aria-label={`${connector.label} pour ${project.name}`} checked={!!project.connectors[connector.code]} disabled={busy}
                onChange={(e) => setProject(project.id, connector.code, e.target.checked)} />
              {project.viaClient?.[connector.code] && <small className="muted" style={{ display: "block", fontSize: 10 }}>via client</small>}
            </td>)}
          </tr>)}</tbody>
        </table>
      </div>}
    </Card>
  </>;
}
