import { useEffect, useState } from "react";

import { PILOT_TENANT_KEY, api } from "../api/client";
import { useApi } from "../api/useApi";

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
  if (me.isPlatformAdmin) return <PilotConfiguration me={me} />;
  return <TenantConfiguration me={me} />;
}

const readPilotTenant = () => { try { return sessionStorage.getItem(PILOT_TENANT_KEY) ?? ""; } catch { return ""; } };

/** Le Pilote choisit l'entreprise puis administre sa configuration avec les mêmes écrans que l'administrateur. */
function PilotConfiguration({ me }: { me: Me }) {
  const tenants = useApi(() => api.get<{ id: number; name: string; slug: string; status: string }[]>("/platform/tenants"));
  const [tid, setTid] = useState(readPilotTenant);
  const admin = useApi(() => (tid ? api.get<Me & { pilotMode?: boolean }>("/admin/whoami") : Promise.resolve(null)), [tid]);
  const choose = (v: string) => {
    try { if (v) sessionStorage.setItem(PILOT_TENANT_KEY, v); else sessionStorage.removeItem(PILOT_TENANT_KEY); } catch { /* stockage indisponible */ }
    setTid(v);
  };
  const list = tenants.data ?? [];
  return (
    <div className="page">
      <div className="callout" style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
        <b>🛡️ Mode Pilote</b>
        <span>Entreprise administrée :</span>
        <select className="inp" style={{ width: "auto", minWidth: 220 }} aria-label="Entreprise administrée" value={tid} onChange={(e) => choose(e.target.value)}>
          <option value="">— Choisir une entreprise —</option>
          {list.map((t) => <option key={t.id} value={String(t.id)}>{t.name}{t.status !== "active" ? ` (${t.status})` : ""}</option>)}
        </select>
        <span className="muted" style={{ fontSize: 12 }}>Vos modifications s'appliquent à cette entreprise et sont tracées à votre nom dans son journal d'audit.</span>
      </div>
      {!tid ? <p className="muted">Choisissez une entreprise pour afficher et modifier sa configuration.</p>
        : admin.error ? <p className="muted">Configuration indisponible pour cette entreprise (entreprise inactive ou licence expirée).</p>
        : !admin.data ? <p className="muted">Chargement…</p>
        : <TenantConfiguration key={tid} me={{ ...admin.data, email: me.email }} pilot />}
    </div>
  );
}

function TenantConfiguration({ me, pilot = false }: { me: Me; pilot?: boolean }) {
  const [tab, setTab] = useState<Tab>(fromHash);
  useEffect(() => {
    window.history.replaceState(null, "", `#configuration/${tab}`);
  }, [tab]);
  return (
    <div className={pilot ? "" : "page"}>
      <PageHead
        eyebrow={`${pilot ? "Pilote · " : ""}Administration de ${me.tenant?.name ?? "votre entreprise"}`}
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
