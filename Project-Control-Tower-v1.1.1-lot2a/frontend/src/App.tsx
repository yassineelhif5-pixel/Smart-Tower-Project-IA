import { useCallback, useEffect, useState } from "react";

import { ApiError, onSessionProblem } from "./api/client";
import { authApi } from "./api/endpoints";
import { Shell } from "./components/Shell";
import { Card, ErrorNotice, Loading, PageHead } from "./components/ui";
import { ChangePasswordPage } from "./pages/ChangePasswordPage";
import { ConfigurationPage } from "./pages/ConfigurationPage";
import { LoginPage } from "./pages/LoginPage";
import type { Me } from "./types/api";

type Session =
  | { status: "loading" }
  | { status: "anonymous" }
  | { status: "error"; error: ApiError }
  | { status: "ready"; me: Me };

export function App() {
  const [session, setSession] = useState<Session>({ status: "loading" });

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

  return (
    <Shell me={me} onLogout={logout}>
      {me.isAdmin ? (
        <ConfigurationPage me={me} />
      ) : (
        <div className="page">
          <PageHead eyebrow="Accès" title="Module réservé" />
          <Card title="Configuration">
            <p style={{ margin: 0 }}>
              Le module Configuration est réservé aux administrateurs. Demandez un accès à un administrateur de la
              plateforme.
            </p>
          </Card>
        </div>
      )}
    </Shell>
  );
}
