import { adminApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, fmtDate, Loading } from "../../components/ui";

export function AuditTab() {
  const audit = useApi(adminApi.audit);
  if (audit.error) return <ErrorNotice error={audit.error} onRetry={audit.reload} />;
  if (!audit.data) return <Loading />;
  return (
    <Card
      title="Journal d'audit"
      sub="Connexions, comptes, droits, accès, jetons, secrets et notifications. Aucun secret n'y est écrit."
      extra={
        <div className="btns">
          <a className="btn sm" href="/api/v1/licensing/audit?export=csv" download>
            Exporter (CSV)
          </a>
          <button className="btn sm" onClick={audit.reload}>
            Actualiser
          </button>
        </div>
      }
    >
      <div className="tbl-wrap">
        <table className="tbl tight">
          <thead>
            <tr>
              <th>Date</th>
              <th>Auteur</th>
              <th>Objet</th>
              <th>Événement</th>
              <th>Avant</th>
              <th>Après</th>
              <th>Trace</th>
            </tr>
          </thead>
          <tbody>
            {audit.data.map((r) => (
              <tr key={r.trace + r.at}>
                <td className="muted" style={{ whiteSpace: "nowrap" }}>
                  {fmtDate(r.at)}
                </td>
                <td className="mono">{r.actor ?? "—"}</td>
                <td>{r.entity}</td>
                <td>
                  <b>{r.event}</b>
                </td>
                <td className="muted">{r.old || "—"}</td>
                <td>{r.new || "—"}</td>
                <td className="mono muted">{r.trace}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
