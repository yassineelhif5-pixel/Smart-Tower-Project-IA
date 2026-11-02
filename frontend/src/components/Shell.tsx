import type { ReactNode } from "react";

import type { Route } from "../App";
import { Brand } from "../pages/LoginPage";
import type { Me } from "../types/api";
import { Icon } from "./ui";

/** Cadre de l'application : même barre latérale et même en-tête que index.html. */
const NAV: Record<Route, [string, string]> = {
  pilote: ["shield", "Pilote"],
  pilotage: ["target", "Pilotage"],
  calendrier: ["calendar", "Calendrier"],
  collaboration: ["chat", "Collaboration"],
  configuration: ["gear", "Configuration"],
  licences: ["key", "Licences"],
  acces: ["user", "Mon accès"],
};

export function Shell({
  me,
  onLogout,
  routes,
  route,
  children,
}: {
  me: Me;
  onLogout: () => void;
  routes: Route[];
  route: Route;
  children: ReactNode;
}) {
  const initials = me.name
    .split(" ")
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  return (
    <div className="app">
      <aside className="rail">
        <Brand />
        <div className="tenant">
          <span className="dot" />
          <div>
            <small>{me.isPlatformAdmin ? "Plateforme" : "Organisation"}</small>
            {me.tenant?.name ?? "Administration globale"}
          </div>
        </div>
        <nav className="nav" aria-label="Navigation principale">
          <h6>{me.isPlatformAdmin ? "Plateforme" : "Mon espace"}</h6>
          {routes.map((r) => (
            <a
              key={r}
              href={`#${r}`}
              className={route === r ? "on" : ""}
              aria-current={route === r ? "page" : undefined}
            >
              <Icon name={NAV[r][0]} /> {NAV[r][1]}
            </a>
          ))}
        </nav>
        <div className="rail-foot">
          <span>API sécurisée</span>
          <span className="api">
            <i />
            Données servies par le backend
          </span>
        </div>
      </aside>
      <div className="work">
        <header className="top">
          <div />
          <div className="top-tools">
            <div className="who" aria-label="Utilisateur connecté">
              <span className="av" style={{ background: "var(--av1)" }}>
                {initials}
              </span>
              <span className="who-t">
                <b>{me.name}</b>
                <small>{me.role?.label ?? "Sans rôle"}</small>
              </span>
            </div>
            <button className="btn sm" onClick={onLogout}>
              Se déconnecter
            </button>
          </div>
        </header>
        <main className="main">{children}</main>
      </div>
    </div>
  );
}
