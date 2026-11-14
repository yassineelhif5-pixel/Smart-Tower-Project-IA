import { adminApi, platformApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Loading } from "../../components/ui";

export function SaaSReportPanel({ scope }: { scope: "tenant" | "platform" }) {
  const report = useApi(scope === "platform" ? platformApi.saasReport : adminApi.saasReport, [scope]);
  if (report.error) return <ErrorNotice error={report.error} onRetry={report.reload} />;
  if (!report.data) return <Loading />;
  const r = report.data;
  return <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
    <Card title={scope === "platform" ? "État SaaS global" : `État SaaS · ${r.tenant ?? "mon entreprise"}`} sub="Indicateurs calculés sur les dernières 24 heures à partir des requêtes journalisées.">
      {scope === "platform" && <div className="kpis">
        <div className="kpi"><label>Entreprises actives</label><strong>{r.tenants?.active ?? 0}</strong><small>{r.tenants?.total ?? 0} au total · {r.tenants?.suspended ?? 0} suspendue(s)</small></div>
        <div className="kpi"><label>Base de données</label><strong>{r.database?.connected ? "Connectée" : "Indisponible"}</strong><small>{r.database?.serverVersion ?? r.database?.error ?? "État inconnu"} · {r.database?.latencyMs ?? "—"} ms</small></div>
        <div className="kpi"><label>Migrations</label><strong>{r.database?.migrations?.applied ?? "—"}</strong><small>{r.database?.migrations?.pending?.length ?? 0} en attente</small></div>
      </div>}
      <div className="kpis" style={{ marginTop: 12 }}>
        <div className="kpi"><label>Requêtes API</label><strong>{r.api24h.requests}</strong><small>24 dernières heures</small></div>
        <div className={`kpi ${r.api24h.serverErrors ? "warn" : "ok"}`}><label>Erreurs serveur</label><strong>{r.api24h.serverErrors}</strong><small>{r.api24h.clientErrors} erreur(s) côté client</small></div>
        <div className="kpi"><label>Temps moyen</label><strong>{r.api24h.avgMs} ms</strong></div>
      </div>
    </Card>
    <Card title="Redémarrage des services" sub={r.deployment === "serverless" ? "Les instances sont gérées par la plateforme d’hébergement." : "Le processus applicatif est géré par l’environnement d’exploitation."}>
      <div className="notice">{r.restartMessage}</div>
    </Card>
  </div>;
}
