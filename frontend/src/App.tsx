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
import { PilotPage } from "./pages/PilotPage";
import type { Me } from "./types/api";

// Calendrier (FullCalendar) et collaboration : chargés à la première ouverture, pour alléger la page d'accueil.
const CalendarPage = lazy(() => import("./pages/CalendarPage").then((m) => ({ default: m.CalendarPage })));
const MethodologyPage = lazy(() => import("./pages/MethodologyPage").then((m) => ({ default: m.MethodologyPage })));
const CollaborationPage = lazy(() =>
  import("./pages/CollaborationPage").then((m) => ({ default: m.CollaborationPage })),
);

export type Route = "pilote" | "pilotage" | "calendrier" | "collaboration" | "configuration" | "licences" | "acces";

const LICENSE_CAPS = ["licenses.view", "sessions.view", "requests.view"];

/** Écrans accessibles selon le profil. Le serveur revérifie chaque droit : ceci n'adapte que l'affichage. */
export function routesFor(me: Me): Route[] {
  // Le Pilote n'a jamais accès aux données métier ni aux discussions des entreprises clientes.
  if (me.isPlatformAdmin) return ["pilote", "acces"];
  const work: Route[] = [];
  if (me.permissions.methodology?.[0]) work.push("pilotage");
  if (me.permissions.planning?.[0]) work.push("calendrier");
  if (me.permissions.collaboration?.[0]) work.push("collaboration");
  if (me.isAdmin) return [...work, "configuration", "acces"];
  return me.capabilities.some((c) => LICENSE_CAPS.includes(c)) ? [...work, "licences", "acces"] : [...work, "acces"];
}

const routeFromHash = (allowed: Route[]): Route => {
  const r = window.location.hash.replace("#", "").split("/")[0] as Route;
  return allowed.includes(r) ? r : allowed[0];
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
