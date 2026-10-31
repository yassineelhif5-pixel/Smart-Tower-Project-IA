import type { ReactNode } from "react";

import { Brand } from "../pages/LoginPage";
import type { Me } from "../types/api";
import { Icon } from "./ui";

/** Cadre de l'application : même barre latérale et même en-tête que index.html. */
export function Shell({ me, onLogout, children }: { me: Me; onLogout: () => void; children: ReactNode }) {
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
            <small>Organisation</small>Demo ESN
          </div>
        </div>
        <nav className="nav" aria-label="Navigation principale">
          <h6>Administration</h6>
          {me.isAdmin && (
            <a href="#configuration" className="on">
              <Icon name="gear" /> Configuration
            </a>
          )}
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
