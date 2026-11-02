import { useEffect, useState } from "react";

import { PageHead, Tabs } from "../components/ui";
import { ApiTab } from "../features/configuration/ApiTab";
import { AuditTab } from "../features/configuration/AuditTab";
import { DelegationTab } from "../features/configuration/DelegationTab";
import { NotificationsTab } from "../features/configuration/NotificationsTab";
import { RightsTab } from "../features/configuration/RightsTab";
import { UsersTab } from "../features/configuration/UsersTab";
import { TeamsIntegrationSettings } from "../features/collaboration/TeamsIntegrationSettings";
import { LicensesTab } from "../features/licensing/LicensesTab";
import type { Me } from "../types/api";

// L'onglet « Base de données » est un paramètre global de la plateforme : il est passé dans l'espace Pilote.
type Tab = "users" | "licenses" | "rights" | "delegation" | "api" | "connectors" | "notifications" | "audit";
const TABS: [Tab, string][] = [
  ["users", "Utilisateurs et accès"],
  ["licenses", "Licences et demandes"],
  ["rights", "Matrice des droits"],
  ["delegation", "Délégations"],
  ["api", "API"],
  ["connectors", "Connecteurs"],
  ["notifications", "Notifications"],
  ["audit", "Journal d'audit"],
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
        title="Configuration"
        sub="Comptes, licences, droits et délégations, API, connecteurs (Microsoft Teams) et notifications de votre entreprise. Réservé aux administrateurs."
      />
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <Tabs<Tab> tabs={TABS} value={tab} onChange={setTab} />
        {tab === "users" && <UsersTab me={me} />}
        {tab === "rights" && <RightsTab />}
        {tab === "licenses" && <LicensesTab capabilities={me.capabilities} />}
        {tab === "delegation" && <DelegationTab />}
        {tab === "api" && <ApiTab />}
        {tab === "connectors" && <TeamsIntegrationSettings />}
        {tab === "notifications" && <NotificationsTab adminEmail={me.email} />}
        {tab === "audit" && <AuditTab />}
      </div>
    </div>
  );
}
