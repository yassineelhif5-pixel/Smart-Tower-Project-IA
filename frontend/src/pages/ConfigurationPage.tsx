import { useEffect, useState } from "react";

import { PageHead, Tabs } from "../components/ui";
import { ApiTab } from "../features/configuration/ApiTab";
import { AuditTab } from "../features/configuration/AuditTab";
import { DatabaseTab } from "../features/configuration/DatabaseTab";
import { NotificationsTab } from "../features/configuration/NotificationsTab";
import { RightsTab } from "../features/configuration/RightsTab";
import { UsersTab } from "../features/configuration/UsersTab";
import type { Me } from "../types/api";

type Tab = "users" | "rights" | "database" | "api" | "notifications" | "audit";
const TABS: [Tab, string][] = [
  ["users", "Utilisateurs et accès"],
  ["rights", "Matrice des droits"],
  ["database", "Base de données"],
  ["api", "API"],
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
        eyebrow="La plateforme et les accès sont-ils maîtrisés ?"
        title="Configuration"
        sub="Comptes et droits, connexion à la base, API et notifications. Réservé aux administrateurs."
      />
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <Tabs<Tab> tabs={TABS} value={tab} onChange={setTab} />
        {tab === "users" && <UsersTab me={me} />}
        {tab === "rights" && <RightsTab />}
        {tab === "database" && <DatabaseTab />}
        {tab === "api" && <ApiTab />}
        {tab === "notifications" && <NotificationsTab adminEmail={me.email} />}
        {tab === "audit" && <AuditTab />}
      </div>
    </div>
  );
}
