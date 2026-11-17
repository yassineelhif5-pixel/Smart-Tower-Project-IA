import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

/** Préférences d'affichage de l'utilisateur : thème et langue, gardées dans le navigateur. */
export type Theme = "system" | "light" | "dark";
export type Lang = "fr" | "en";

const DICT = {
  fr: {
    "brand.sub": "Pilotage projets",
    "login.title": "Bienvenue",
    "login.sub": "Connectez-vous à votre espace de pilotage Control Tower.",
    "login.username": "Identifiant",
    "login.password": "Mot de passe",
    "login.show": "Afficher",
    "login.hide": "Masquer",
    "login.showAria": "Afficher le mot de passe",
    "login.hideAria": "Masquer le mot de passe",
    "login.submit": "Se connecter",
    "login.busy": "Connexion…",
    "login.failed": "Connexion impossible.",
    "login.or": "ou",
    "login.ssoEmail": "Adresse e-mail professionnelle",
    "login.ssoEmailHint": "Saisissez votre adresse e-mail professionnelle pour continuer.",
    "login.ssoError": "Connexion SSO impossible. Vérifiez l’adresse ou contactez l’administrateur de votre entreprise.",
    "login.microsoft": "Continuer avec Microsoft",
    "login.google": "Continuer avec Google",
    "login.otherSso": "Autre connexion SSO d’entreprise",
    "login.secure": "Connexion sécurisée · Vos accès restent gérés par votre entreprise",
    "login.forgot": "Mot de passe oublié ?",
    "forgot.title": "Mot de passe oublié",
    "forgot.sub": "Indiquez votre e-mail ou votre identifiant : nous vous enverrons un lien pour choisir un nouveau mot de passe.",
    "forgot.identifier": "E-mail ou identifiant",
    "forgot.submit": "Envoyer le lien",
    "forgot.sending": "Envoi…",
    "forgot.failed": "La demande n’a pas pu être envoyée. Réessayez dans un instant.",
    "forgot.sentTitle": "Vérifiez votre boîte de réception",
    "forgot.sent": "Si un compte correspond, un e-mail avec un lien valable 1 heure vient d’être envoyé. Pensez à vérifier les courriers indésirables.",
    "forgot.back": "Retour à la connexion",
    "reset.title": "Nouveau mot de passe",
    "reset.sub": "Choisissez le nouveau mot de passe de votre compte Control Tower.",
    "reset.new": "Nouveau mot de passe",
    "reset.confirm": "Confirmer le mot de passe",
    "reset.rules": "10 caractères minimum, pas uniquement des chiffres, différent de votre identifiant.",
    "reset.mismatch": "Les deux mots de passe ne sont pas identiques.",
    "reset.submit": "Enregistrer le mot de passe",
    "reset.saving": "Enregistrement…",
    "reset.failed": "Le mot de passe n’a pas pu être modifié.",
    "reset.doneTitle": "Mot de passe modifié",
    "reset.done": "Vous pouvez maintenant vous connecter avec votre nouveau mot de passe.",
    "prefs.theme": "Thème",
    "prefs.light": "Clair",
    "prefs.dark": "Sombre",
    "prefs.system": "Système",
    "prefs.lang": "Langue",
    "shell.platform": "Plateforme",
    "shell.organisation": "Organisation",
    "shell.globalAdmin": "Administration globale",
    "shell.mySpace": "Mon espace",
    "shell.mainNav": "Navigation principale",
    "shell.secureApi": "API sécurisée",
    "shell.backendData": "Données servies par le backend",
    "shell.connectedUser": "Utilisateur connecté",
    "shell.noRole": "Sans rôle",
    "shell.logout": "Se déconnecter",
    "shell.menu": "Ouvrir le menu",
    "nav.pilote": "Pilote",
    "nav.projets": "Mes projets",
    "nav.reporting": "Reporting",
    "nav.pilotage": "Pilotage",
    "nav.calendrier": "Calendrier",
    "nav.collaboration": "Collaboration",
    "nav.configuration": "Paramétrage",
    "nav.licences": "Licences",
    "nav.acces": "Mon accès",
    "nav.sso-requests": "Demandes d’accès",
    "nav.access-requests": "Changements d’accès",
    "nav.temps": "Saisie de temps",
    "nav.recette": "Recette",
    "nav.espace-client": "Espace client",
    "nav.maintenance": "Assistance Control Tower",
    "nav.support": "File du support",
  },
  en: {
    "brand.sub": "Project control",
    "login.title": "Welcome",
    "login.sub": "Sign in to your Control Tower workspace.",
    "login.username": "Username",
    "login.password": "Password",
    "login.show": "Show",
    "login.hide": "Hide",
    "login.showAria": "Show password",
    "login.hideAria": "Hide password",
    "login.submit": "Sign in",
    "login.busy": "Signing in…",
    "login.failed": "Unable to sign in.",
    "login.or": "or",
    "login.ssoEmail": "Work email address",
    "login.ssoEmailHint": "Enter your work email address to continue.",
    "login.ssoError": "SSO sign-in failed. Check the address or contact your company administrator.",
    "login.microsoft": "Continue with Microsoft",
    "login.google": "Continue with Google",
    "login.otherSso": "Other company SSO",
    "login.secure": "Secure sign-in · Your access is managed by your company",
    "login.forgot": "Forgot password?",
    "forgot.title": "Forgot password",
    "forgot.sub": "Enter your email or username and we’ll send you a link to choose a new password.",
    "forgot.identifier": "Email or username",
    "forgot.submit": "Send link",
    "forgot.sending": "Sending…",
    "forgot.failed": "The request could not be sent. Please try again shortly.",
    "forgot.sentTitle": "Check your inbox",
    "forgot.sent": "If an account matches, an email with a link valid for 1 hour has just been sent. Check your spam folder too.",
    "forgot.back": "Back to sign in",
    "reset.title": "New password",
    "reset.sub": "Choose a new password for your Control Tower account.",
    "reset.new": "New password",
    "reset.confirm": "Confirm password",
    "reset.rules": "At least 10 characters, not only digits, different from your username.",
    "reset.mismatch": "The two passwords do not match.",
    "reset.submit": "Save password",
    "reset.saving": "Saving…",
    "reset.failed": "The password could not be changed.",
    "reset.doneTitle": "Password changed",
    "reset.done": "You can now sign in with your new password.",
    "prefs.theme": "Theme",
    "prefs.light": "Light",
    "prefs.dark": "Dark",
    "prefs.system": "System",
    "prefs.lang": "Language",
    "shell.platform": "Platform",
    "shell.organisation": "Organisation",
    "shell.globalAdmin": "Global administration",
    "shell.mySpace": "My workspace",
    "shell.mainNav": "Main navigation",
    "shell.secureApi": "Secure API",
    "shell.backendData": "Data served by the backend",
    "shell.connectedUser": "Signed-in user",
    "shell.noRole": "No role",
    "shell.logout": "Sign out",
    "shell.menu": "Open menu",
    "nav.pilote": "Pilot",
    "nav.projets": "My projects",
    "nav.reporting": "Reporting",
    "nav.pilotage": "Steering",
    "nav.calendrier": "Calendar",
    "nav.collaboration": "Collaboration",
    "nav.configuration": "Settings",
    "nav.licences": "Licences",
    "nav.acces": "My access",
    "nav.sso-requests": "Access requests",
    "nav.access-requests": "Access changes",
    "nav.temps": "Timesheet",
    "nav.recette": "Testing",
    "nav.espace-client": "Client space",
    "nav.maintenance": "Control Tower support",
    "nav.support": "Support queue",
  },
} as const;

export type TKey = keyof (typeof DICT)["fr"];

type Prefs = {
  theme: Theme;
  lang: Lang;
  setTheme: (t: Theme) => void;
  setLang: (l: Lang) => void;
  t: (key: TKey) => string;
};

function read<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const v = localStorage.getItem(key) as T | null;
    return v && allowed.includes(v) ? v : fallback;
  } catch {
    return fallback;
  }
}
function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* stockage indisponible : la préférence vaut pour la session */
  }
}

const fallbackPrefs: Prefs = {
  theme: "system",
  lang: "fr",
  setTheme: () => {},
  setLang: () => {},
  t: (key) => DICT.fr[key],
};
const PrefsContext = createContext<Prefs>(fallbackPrefs);

export function PrefsProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => read("pct.theme", ["system", "light", "dark"] as const, "system"));
  const [lang, setLangState] = useState<Lang>(() => read("pct.lang", ["fr", "en"] as const, "fr"));

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") delete root.dataset.theme;
    else root.dataset.theme = theme;
  }, [theme]);
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    write("pct.theme", t);
  }, []);
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    write("pct.lang", l);
  }, []);
  const t = useCallback((key: TKey) => DICT[lang][key] ?? DICT.fr[key], [lang]);

  const value = useMemo(() => ({ theme, lang, setTheme, setLang, t }), [theme, lang, setTheme, setLang, t]);
  return <PrefsContext.Provider value={value}>{children}</PrefsContext.Provider>;
}

export function usePrefs() {
  return useContext(PrefsContext);
}

const SunIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </svg>
);
const MoonIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
  </svg>
);
const MonitorIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="2" y="3" width="20" height="14" rx="2" />
    <path d="M8 21h8M12 17v4" />
  </svg>
);

/** Sélecteurs de thème et de langue, utilisés dans l'en-tête et sur la page de connexion. */
export function PrefsSwitcher({ compact = false }: { compact?: boolean }) {
  const { theme, setTheme, lang, setLang, t } = usePrefs();
  const themes: [Theme, TKey, () => ReactNode][] = [
    ["light", "prefs.light", SunIcon],
    ["dark", "prefs.dark", MoonIcon],
    ["system", "prefs.system", MonitorIcon],
  ];
  return (
    <div className={`prefs${compact ? " compact" : ""}`}>
      <div className="prefs-theme" role="radiogroup" aria-label={t("prefs.theme")}>
        {themes.map(([value, label, Ico]) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={theme === value}
            className={theme === value ? "on" : ""}
            title={t(label)}
            aria-label={t(label)}
            onClick={() => setTheme(value)}
          >
            <Ico />
          </button>
        ))}
      </div>
      <div className="prefs-lang" role="radiogroup" aria-label={t("prefs.lang")}>
        {(["fr", "en"] as const).map((l) => (
          <button
            key={l}
            type="button"
            role="radio"
            aria-checked={lang === l}
            className={lang === l ? "on" : ""}
            onClick={() => setLang(l)}
          >
            {l.toUpperCase()}
          </button>
        ))}
      </div>
    </div>
  );
}
