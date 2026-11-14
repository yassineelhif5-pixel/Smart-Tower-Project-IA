import { useEffect, useState } from "react";

import { PageHead, Tabs } from "../components/ui";
import { ApiTab } from "../features/configuration/ApiTab";
import { AuditTab } from "../features/configuration/AuditTab";
import { DelegationTab } from "../features/configuration/DelegationTab";
import { NotificationsTab } from "../features/configuration/NotificationsTab";
import { RightsTab } from "../features/configuration/RightsTab";
import { SSOTab } from "../features/configuration/SSOTab";
import { UsersTab } from "../features/configuration/UsersTab";
import { TeamsIntegrationSettings } from "../features/collaboration/TeamsIntegrationSettings";
import { LicensesTab } from "../features/licensing/LicensesTab";
import { AccessChangeRequestsPanel } from "../features/configuration/AccessChangeRequestsPanel";
import { TimeSettingsTab } from "../features/configuration/TimeSettingsTab";
import { AssistantAdminTab } from "../features/assistant/AssistantSettings";
import { ProjectsAdminTab } from "../features/configuration/ProjectsAdminTab";
import { SaaSReportPanel } from "../features/configuration/SaaSReportPanel";
import { CompanyProfileTab } from "../features/configuration/CompanyProfileTab";
import type { Me } from "../types/api";
import { GuestsTab } from "../components/TenantSwitch";

// L'onglet « Base de données » est un paramètre global de la plateforme : il est passé dans l'espace Pilote.
type Tab = "users" | "company" | "projects" | "licenses" | "rights" | "delegation" | "sso" | "time" | "api" | "connectors" | "notifications" | "audit" | "saas" | "assistant" | "guests";
const TABS: [Tab, string][] = [
  ["users", "Utilisateurs et accès"],
  ["guests", "Invités multi-entreprises"],
  ["company", "Entreprise"],
  ["projects", "Projets"],
  ["licenses", "Licences et demandes"],
  ["rights", "Matrice des droits"],
  ["delegation", "Délégations"],
  ["sso", "Connexion SSO"],
  ["time", "Saisie de temps"],
  ["assistant", "Assistants IA"],
  ["api", "API"],
  ["connectors", "Connecteurs"],
  ["notifications", "Notifications"],
  ["audit", "Journal d'audit"],
  ["saas", "État SaaS"],
];

const fromHash = (): Tab => {
  const t = window.location.hash.replace("#configuration/", "") as Tab;
  return TABS.some(([k]) => k === t) ? t : "users";
};

export function ConfigurationPage({ me }: { me: Me }) {
  const [tab, setTab] = useState<Tab>(fromHash);
  useEffect(() => {
    window.history.replaceState(null, "", `#configuration/${tab}`);
  }, [tab]);
  return (
    <div className="page">
      <PageHead
        eyebrow={`Administration de ${me.tenant?.name ?? "votre entreprise"}`}
        title="Paramétrage"
        sub="Comptes, licences, droits et délégations, API, connecteurs (Microsoft Teams) et notifications de votre entreprise. Réservé aux administrateurs."
      />
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <Tabs<Tab> tabs={TABS} value={tab} onChange={setTab} />
        {tab === "users" && <><UsersTab me={me} /><AccessChangeRequestsPanel me={me} /></>}
        {tab === "guests" && <GuestsTab />}
        {tab === "company" && <CompanyProfileTab />}
        {tab === "projects" && <ProjectsAdminTab me={me} />}
        {tab === "rights" && <RightsTab />}
        {tab === "licenses" && <LicensesTab capabilities={me.capabilities} />}
        {tab === "delegation" && <DelegationTab />}
        {tab === "sso" && <SSOTab />}
        {tab === "time" && <TimeSettingsTab me={me} />}
        {tab === "assistant" && <AssistantAdminTab />}
        {tab === "api" && <ApiTab />}
        {tab === "connectors" && <TeamsIntegrationSettings />}
        {tab === "notifications" && <NotificationsTab adminEmail={me.email} />}
        {tab === "audit" && <AuditTab />}
        {tab === "saas" && <SaaSReportPanel scope="tenant" />}
      </div>
    </div>
  );
}
