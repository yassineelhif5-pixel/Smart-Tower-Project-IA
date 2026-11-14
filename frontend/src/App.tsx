import { ClientSpacePage } from "./features/clientspace/ClientSpacePage";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";

import { ApiError, onSessionProblem } from "./api/client";
import { authApi } from "./api/endpoints";
import { Shell } from "./components/Shell";
import { ErrorNotice, Loading, PageHead } from "./components/ui";
import { LicensesTab } from "./features/licensing/LicensesTab";
import { ChangePasswordPage } from "./pages/ChangePasswordPage";
import { ConfigurationPage } from "./pages/ConfigurationPage";
import { LoginPage } from "./pages/LoginPage";
import { MyAccessPage } from "./pages/MyAccessPage";
import { SSORequestsPanel } from "./features/configuration/SSORequestsPanel";
import { AccessChangeRequestsPanel } from "./features/configuration/AccessChangeRequestsPanel";
import { ProjectsPage } from "./pages/ProjectsPage";
import { ReportingPage } from "./pages/ReportingPage";
import { TimeSheetPage } from "./pages/TimeSheetPage";
import { MaintenanceWorkspace } from "./features/maintenance/MaintenanceWorkspace";
import { PilotPage } from "./pages/PilotPage";
import type { Me } from "./types/api";

// Calendrier (FullCalendar) et collaboration : chargés à la première ouverture, pour alléger la page d'accueil.
const CalendarPage = lazy(() => import("./pages/CalendarPage").then((m) => ({ default: m.CalendarPage })));
const MethodologyPage = lazy(() => import("./pages/MethodologyPage").then((m) => ({ default: m.MethodologyPage })));
const CollaborationPage = lazy(() =>
  import("./pages/CollaborationPage").then((m) => ({ default: m.CollaborationPage })),
);

export type Route = "pilote" | "projets" | "reporting" | "pilotage" | "calendrier" | "collaboration" | "configuration" | "licences" | "acces" | "sso-requests" | "access-requests" | "temps" | "maintenance" | "support" | "espace-client";

const LICENSE_CAPS = ["licenses.view", "sessions.view", "requests.view"];

/** Écrans accessibles selon le profil. Le serveur revérifie chaque droit : ceci n'adapte que l'affichage. */
export function routesFor(me: Me): Route[] {
  // Le Pilote n'a jamais accès aux données métier ni aux discussions des entreprises clientes.
  if (me.isPlatformAdmin) return ["pilote", "acces"];
  if (me.isSupport) return ["support", "acces"];
  const work: Route[] = [];
  if (me.permissions.project?.[0]) work.push("projets", "reporting");
  if (me.permissions.methodology?.[0]) work.push("pilotage");
  if (me.permissions.planning?.[0]) work.push("calendrier");
  if (me.permissions.collaboration?.[0]) work.push("collaboration");
  if (me.permissions.timesheet?.[0]) work.push("temps");
  if (me.clientSpaceEnabled) work.push("espace-client");
  if (me.maintenanceEnabled) work.push("maintenance");
  if (me.capabilities.includes("users.approve_sso")) work.push("sso-requests");
  if (me.capabilities.includes("users.request_access_change")) work.push("access-requests");
  if (me.isAdmin) return [...work, "configuration", "acces"];
  return me.capabilities.some((c) => LICENSE_CAPS.includes(c)) ? [...work, "licences", "acces"] : [...work, "acces"];
}

const routeFromHash = (allowed: Route[]): Route => {
  const r = window.location.hash.replace("#", "").split("/")[0] as Route;
  if (allowed.includes(r)) return r;
  // Écran non autorisé pour ce profil (ex. adresse restée d'une autre session) : on repart d'une adresse propre.
  if (allowed[0]) window.history.replaceState(null, "", `#${allowed[0]}`);
  return allowed[0];
};

type Session =
  | { status: "loading" }
  | { status: "anonymous" }
  | { status: "error"; error: ApiError }
  | { status: "ready"; me: Me };

export function App() {
  const [session, setSession] = useState<Session>({ status: "loading" });
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const on = () => setHash(window.location.hash);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  const refresh = useCallback(() => {
    authApi
      .me()
      .then((me) => setSession({ status: "ready", me }))
      .catch((e: ApiError) =>
        setSession(e.status === 401 || e.status === 403 ? { status: "anonymous" } : { status: "error", error: e }),
      );
  }, []);

  useEffect(() => {
    refresh();
    return onSessionProblem((e) => (e.status === 401 ? setSession({ status: "anonymous" }) : refresh()));
  }, [refresh]);

  const logout = useCallback(() => {
    authApi.logout().finally(() => setSession({ status: "anonymous" }));
  }, []);

  if (session.status === "loading")
    return (
      <main className="auth">
        <Loading />
      </main>
    );
  if (session.status === "error")
    return (
      <main className="auth">
        <ErrorNotice error={session.error} onRetry={refresh} />
      </main>
    );
  if (session.status === "anonymous") return <LoginPage onLogged={(me) => setSession({ status: "ready", me })} />;

  const { me } = session;
  if (me.mustChangePassword)
    return (
      <ChangePasswordPage me={me} onDone={(next) => setSession({ status: "ready", me: next })} onLogout={logout} />
    );

  const allowed = routesFor(me);
  void hash; // relit la route à chaque changement d'ancre
  const route = routeFromHash(allowed);
  return (
    <Shell me={me} onLogout={logout} routes={allowed} route={route}>
      {route === "pilote" && <PilotPage />}
      <Suspense fallback={<Loading />}>
        {route === "pilotage" && <MethodologyPage me={me} />}
        {route === "calendrier" && <CalendarPage me={me} />}
        {route === "collaboration" && <CollaborationPage me={me} />}
      </Suspense>
      {route === "configuration" && <ConfigurationPage me={me} />}
      {route === "sso-requests" && <div className="page"><PageHead eyebrow={me.tenant?.name ?? ""} title="Demandes d’accès" sub="Vérifiez les demandes de connexion SSO et attribuez un profil adapté." /><SSORequestsPanel /></div>}
      {route === "access-requests" && <div className="page"><PageHead eyebrow={me.tenant?.name ?? ""} title="Changements d’accès" sub="Demandez une modification de profil à l’administrateur de votre entreprise." /><AccessChangeRequestsPanel me={me} /></div>}
      {route === "projets" && <ProjectsPage me={me} />}
      {route === "reporting" && <ReportingPage me={me} />}
      {route === "temps" && <TimeSheetPage me={me} />}
      {route === "espace-client" && <ClientSpacePage me={me} />}
      {route === "maintenance" && <MaintenanceWorkspace me={me} />}
      {route === "support" && <MaintenanceWorkspace me={me} />}
      {route === "licences" && (
        <div className="page">
          <PageHead
            eyebrow={me.tenant?.name ?? ""}
            title="Licences"
            sub="Licences, sessions et demandes de votre entreprise, selon vos droits délégués."
          />
          <LicensesTab capabilities={me.capabilities} />
        </div>
      )}
      {route === "acces" && <MyAccessPage />}
    </Shell>
  );
}
