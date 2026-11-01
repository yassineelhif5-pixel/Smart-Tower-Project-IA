import { meApi } from "../api/endpoints";
import { useApi } from "../api/useApi";
import { Card, ErrorNotice, fmtDate, Loading, PageHead, Pill } from "../components/ui";
import { fmtDay } from "../features/licensing/labels";

const VERBS = ["Consulter", "Créer", "Modifier", "Supprimer", "Valider"];
const MODULE_LABEL: Record<string, string> = {
  project: "Projets",
  client: "Clients",
  planning: "Planning",
  action: "Actions",
  budget: "Budget",
  resource: "Ressources",
  document: "Documents",
  test: "Tests",
  risk: "Risques",
  report: "Reporting",
  user: "Utilisateurs",
  settings: "Paramétrage",
};

/** Profil personnel : entreprise, licence, validité de l'accès, rôle, droits et session. */
export function MyAccessPage() {
  const a = useApi(meApi.access);
  if (a.error) return <ErrorNotice error={a.error} onRetry={a.reload} />;
  if (!a.data) return <Loading />;
  const d = a.data;
  const rights = Object.entries(d.permissions).filter(([, flags]) => flags.some(Boolean));
  return (
    <div className="page">
      <PageHead
        eyebrow="Mon accès"
        title={d.user.name}
        sub={[d.user.title, d.user.email].filter(Boolean).join(" · ")}
      />
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div className="kpis">
          <div className="kpi">
            <label>Entreprise</label>
            <strong style={{ fontSize: 20 }}>{d.company?.name ?? "Plateforme"}</strong>
            <small>{d.role.label}</small>
          </div>
          <div className="kpi">
            <label>Licence</label>
            <strong style={{ fontSize: 20 }}>{d.license.mode}</strong>
            <small className="mono">{d.license.number ?? "—"}</small>
          </div>
          <div className="kpi">
            <label>Accès</label>
            <strong style={{ fontSize: 20 }}>
              <Pill tone={d.access.status === "actif" ? "ok" : "warn"}>{d.access.status}</Pill>
            </strong>
            <small>{d.access.validUntil ? `valable jusqu'au ${fmtDay(d.access.validUntil)}` : "sans échéance"}</small>
          </div>
          <div className="kpi">
            <label>Session</label>
            <strong style={{ fontSize: 20 }}>{d.session ? "ouverte" : "—"}</strong>
            <small>
              {d.session ? `depuis ${fmtDate(d.session.startedAt)} · expire ${fmtDate(d.session.expiresAt)}` : ""}
            </small>
          </div>
        </div>
        <div className="grid g2">
          <Card title="Mes droits" sub="Définis par votre rôle et l'offre de votre entreprise.">
            {rights.length === 0 ? (
              <p className="muted">Aucun droit sur les modules métier.</p>
            ) : (
              <table className="tbl tight">
                <tbody>
                  {rights.map(([module, flags]) => (
                    <tr key={module}>
                      <td>
                        <b>{MODULE_LABEL[module] ?? module}</b>
                      </td>
                      <td>{VERBS.filter((_, i) => flags[i]).join(", ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
          <Card title="Droits d'administration délégués">
            {d.capabilities.length === 0 ? (
              <p className="muted">Aucun.</p>
            ) : (
              <p className="mono">{d.capabilities.join(" · ")}</p>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
