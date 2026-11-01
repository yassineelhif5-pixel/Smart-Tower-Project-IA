import { platformApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, fmtDate, Loading, Pill } from "../../components/ui";

function Kpi({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: number;
  sub?: string;
  tone?: "ok" | "warn" | "crit";
}) {
  return (
    <div className={`kpi ${tone ?? ""}`}>
      <label>{label}</label>
      <strong>{value}</strong>
      {sub && <small>{sub}</small>}
    </div>
  );
}

export function DashboardTab({ onOpenRequests }: { onOpenRequests: () => void }) {
  const d = useApi(platformApi.dashboard);
  if (d.error) return <ErrorNotice error={d.error} onRetry={d.reload} />;
  if (!d.data) return <Loading />;
  const { tenants, licenses, subscriptions, byOffer, recentOperations, pendingRequests } = d.data;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="kpis" aria-label="Entreprises">
        <Kpi label="Entreprises" value={tenants.total} sub={`${tenants.withoutSubscription} sans abonnement`} />
        <Kpi label="Actives" value={tenants.active} tone="ok" />
        <Kpi label="Suspendues" value={tenants.suspended} tone={tenants.suspended ? "warn" : undefined} />
        <Kpi label="En essai" value={tenants.trial} />
        <Kpi label="Demandes en attente" value={pendingRequests} tone={pendingRequests ? "warn" : undefined} />
      </div>
      <div className="kpis" aria-label="Licences">
        <Kpi label="Licences commercialisées" value={licenses.sold} sub="total des attributions" />
        <Kpi label="Attribuées aux entreprises" value={licenses.allocated} />
        <Kpi label="Disponibles" value={licenses.available} tone="ok" />
        <Kpi
          label="Utilisées"
          value={licenses.used}
          sub={`${licenses.byKind.named.used} nominatives · ${licenses.byKind.concurrent.used} concurrentes`}
        />
        <Kpi
          label="Expirées"
          value={licenses.expired}
          tone={licenses.expired ? "crit" : undefined}
          sub="abonnement échu"
        />
      </div>
      <div className="grid g2">
        <Card title="Abonnements" sub="État des souscriptions en cours et passées.">
          <div className="kpis">
            <Kpi label="Actifs" value={subscriptions.active} tone="ok" />
            <Kpi label="Essai" value={subscriptions.trial} />
            <Kpi label="Suspendus" value={subscriptions.suspended} />
            <Kpi label="Expirés" value={subscriptions.expired} tone={subscriptions.expired ? "crit" : undefined} />
          </div>
        </Card>
        <Card
          title="Clients par offre"
          sub="Abonnements en cours."
          extra={
            pendingRequests > 0 && (
              <button className="btn sm" onClick={onOpenRequests}>
                Traiter les demandes
              </button>
            )
          }
        >
          {byOffer.length === 0 ? (
            <p className="muted">Aucun abonnement en cours.</p>
          ) : (
            <table className="tbl tight">
              <tbody>
                {byOffer.map((o) => (
                  <tr key={o.offer}>
                    <td>{o.offer}</td>
                    <td className="num">{o.tenants}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
      <Card title="Dernières opérations administratives" sub="Entreprises, abonnements, stock et demandes.">
        <div className="tbl-wrap">
          <table className="tbl tight">
            <thead>
              <tr>
                <th>Date</th>
                <th>Auteur</th>
                <th>Entreprise</th>
                <th>Objet</th>
                <th>Événement</th>
                <th>Résultat</th>
              </tr>
            </thead>
            <tbody>
              {recentOperations.map((o, i) => (
                <tr key={i}>
                  <td className="muted" style={{ whiteSpace: "nowrap" }}>
                    {fmtDate(o.at)}
                  </td>
                  <td className="mono">{o.actor ?? "système"}</td>
                  <td>{o.tenant ?? "Plateforme"}</td>
                  <td>{o.entity}</td>
                  <td>
                    <b>{o.event}</b>
                  </td>
                  <td>
                    <Pill tone={o.result === "success" ? "ok" : "crit"}>
                      {o.result === "success" ? "Réussi" : "Refusé"}
                    </Pill>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
