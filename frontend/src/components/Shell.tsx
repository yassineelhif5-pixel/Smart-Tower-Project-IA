import { useEffect, useState, type ReactNode } from "react";

import type { Route } from "../App";
import { Brand } from "../pages/LoginPage";
import type { Me } from "../types/api";
import { Icon } from "./ui";
import { HelpChat } from "./HelpChat";
import { NotificationBell } from "./NotificationBell";
import { TenantSwitcher } from "./TenantSwitch";
import { PrefsSwitcher, usePrefs, type TKey } from "../i18n";

/** Cadre de l'application : même barre latérale et même en-tête que index.html. */
const NAV: Record<Route, string> = {
  pilote: "shield",
  projets: "folder",
  reporting: "file",
  pilotage: "target",
  calendrier: "calendar",
  collaboration: "chat",
  configuration: "gear",
  licences: "key",
  acces: "user",
  "sso-requests": "user",
  "access-requests": "user",
  temps: "clock",
  maintenance: "chat",
  support: "chat",
  "espace-client": "file",
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
  const { t } = usePrefs();
  const [menuOpen, setMenuOpen] = useState(false);
  // Sur petit écran, le menu se referme après chaque navigation.
  useEffect(() => setMenuOpen(false), [route]);
  const initials = me.name
    .split(" ")
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  return (
    <div className="app">
      <aside className={`rail${menuOpen ? " open" : ""}`}>
        <Brand />
        <TenantSwitcher label={me.isPlatformAdmin ? t("shell.platform") : t("shell.organisation")} name={me.tenant?.name ?? t("shell.globalAdmin")}
          tenants={me.tenants ?? []} />
        <nav className="nav" aria-label={t("shell.mainNav")}>
          <h6>{me.isPlatformAdmin ? t("shell.platform") : t("shell.mySpace")}</h6>
          {routes.map((r) => (
            <a
              key={r}
              href={`#${r}`}
              className={route === r ? "on" : ""}
              aria-current={route === r ? "page" : undefined}
            >
              <Icon name={NAV[r]} /> {t(`nav.${r}` as TKey)}
            </a>
          ))}
        </nav>
        <div className="rail-foot">
          <span>{t("shell.secureApi")}</span>
          <span className="api">
            <i />
            {t("shell.backendData")}
          </span>
        </div>
      </aside>
      <div className="work">
        {menuOpen && <div className="rail-scrim" onClick={() => setMenuOpen(false)} aria-hidden="true" />}
        <header className="top">
          <button
            className="burger"
            type="button"
            aria-label={t("shell.menu")}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <path d="M4 7h16M4 12h16M4 17h16" />
            </svg>
          </button>
          <div className="top-tools">
            <PrefsSwitcher />
            {me.tenant && <NotificationBell />}
            <div className="who" aria-label={t("shell.connectedUser")}>
              <span className="av" style={{ background: "var(--av1)" }}>
                {initials}
              </span>
              <span className="who-t">
                <b>{me.name}</b>
                <small>{me.role?.label ?? t("shell.noRole")}</small>
              </span>
            </div>
            <button className="btn sm" onClick={onLogout}>
              {t("shell.logout")}
            </button>
          </div>
        </header>
        <main className="main">{children}</main>
        <HelpChat />
      </div>
    </div>
  );
}
