import { useEffect, useState } from "react";

import { platformApi } from "../api/endpoints";
import { useApi } from "../api/useApi";
import { Card, ErrorNotice, fmtDate, Loading, PageHead, Tabs } from "../components/ui";
import { DatabaseTab } from "../features/configuration/DatabaseTab";
import { DashboardTab } from "../features/platform/DashboardTab";
import { OffersTab } from "../features/platform/OffersTab";
import { RequestsTab } from "../features/platform/RequestsTab";
import { TenantsTab } from "../features/platform/TenantsTab";
import { VouchersTab } from "../features/platform/VouchersTab";
import { DomainsTab } from "../features/platform/DomainsTab";
import { ConnectorAssignmentsTab } from "../features/platform/ConnectorAssignmentsTab";
import { PilotUsersTab } from "../features/platform/PilotUsersTab";
import { ContractsTab } from "../features/platform/ContractsTab";
import { MaintenanceTab } from "../features/platform/MaintenanceTab";
import { PlatformConfigTab } from "../features/platform/PlatformConfigTab";
import { PilotJoinRequests } from "../features/platform/PilotJoinRequests";
import { SaaSReportPanel } from "../features/configuration/SaaSReportPanel";
import { AssistantPilotTab } from "../features/assistant/AssistantSettings";

type Tab = "dashboard" | "tenants" | "contracts" | "users" | "offers" | "requests" | "vouchers" | "domains" | "connectors" | "maintenance" | "audit" | "database" | "saas" | "assistants" | "config" | "joins";
const TABS: [Tab, string][] = [
  ["dashboard", "Tableau de bord"],
  ["saas", "État SaaS"],
  ["tenants", "Entreprises"],
  ["contracts", "Contrats & échéances"],
  ["users", "Utilisateurs"],
  ["offers", "Offres"],
  ["requests", "Demandes"],
  ["joins", "Adhésions"],
  ["vouchers", "Vouchers"],
  ["domains", "Domaines SSO"],
  ["connectors", "Connecteurs (client / projet)"],
  ["assistants", "Assistants IA"],
  ["maintenance", "Maintenance & support"],
  ["audit", "Journal de la plateforme"],
  ["database", "Base de données"],
  ["config", "Configuration"],
];

const fromHash = (): Tab => {
  const t = window.location.hash.replace("#pilote/", "") as Tab;
  return TABS.some(([k]) => k === t) ? t : "dashboard";
};

function PlatformAudit() {
  const rows = useApi(() => platformApi.audit());
  if (rows.error) return <ErrorNotice error={rows.error} onRetry={rows.reload} />;
  if (!rows.data) return <Loading />;
  return (
    <Card
      title="Journal de la plateforme"
      sub="Opérations du Pilote : entreprises, offres, statuts. Ce journal ne peut pas être modifié."
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
            </tr>
          </thead>
          <tbody>
            {rows.data.map((r) => (
              <tr key={r.trace + r.at}>
                <td className="muted" style={{ whiteSpace: "nowrap" }}>
                  {fmtDate(r.at)}
                </td>
                <td className="mono">{r.actor ?? "système"}</td>
                <td>{r.entity}</td>
                <td>
                  <b>{r.event}</b>
                </td>
                <td className="muted">{r.old || "—"}</td>
                <td>{r.new || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/** Interface du Pilote (Super Admin Global) : indépendante des espaces des entreprises clientes. */
export function PilotPage() {
  const [tab, setTab] = useState<Tab>(fromHash);
  useEffect(() => {
    window.history.replaceState(null, "", `#pilote/${tab}`);
  }, [tab]);
  return (
    <div className="page">
      <PageHead
        eyebrow="La plateforme, ses entreprises et leurs licences sont-elles maîtrisées ?"
        title="Pilote"
        sub="Entreprises, offres, abonnements, licences et demandes. Le Pilote n'a pas accès aux données privées des entreprises."
      />
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <Tabs<Tab> tabs={TABS} value={tab} onChange={setTab} />
        {tab === "dashboard" && <DashboardTab onOpenRequests={() => setTab("requests")} />}
        {tab === "saas" && <SaaSReportPanel scope="platform" />}
        {tab === "tenants" && <TenantsTab />}
        {tab === "config" && <PlatformConfigTab />}
        {tab === "contracts" && <ContractsTab />}
        {tab === "users" && <PilotUsersTab />}
        {tab === "offers" && <OffersTab />}
        {tab === "requests" && <RequestsTab />}
        {tab === "joins" && <PilotJoinRequests />}
        {tab === "vouchers" && <VouchersTab />}
        {tab === "domains" && <DomainsTab />}
        {tab === "connectors" && <ConnectorAssignmentsTab />}
        {tab === "assistants" && <AssistantPilotTab />}
        {tab === "maintenance" && <MaintenanceTab />}
        {tab === "audit" && <PlatformAudit />}
        {tab === "database" && <DatabaseTab />}
      </div>
    </div>
  );
}
