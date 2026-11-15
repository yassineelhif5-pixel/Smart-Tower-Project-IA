import { useState, type FormEvent } from "react";
import { Copyright } from "../components/Copyright";

import { ApiError } from "../api/client";
import { API_BASE } from "../api/client";
import { authApi } from "../api/endpoints";
import { Field } from "../components/ui";
import { PrefsSwitcher, usePrefs } from "../i18n";
import { ForgotPasswordForm, ResetPasswordForm } from "./ForgotPassword";
import type { Me } from "../types/api";

export function Brand() {
  const { t } = usePrefs();
  return (
    <div className="brand">
      <svg width="34" height="34" viewBox="0 0 34 34" aria-hidden="true">
        <defs>
          <linearGradient id="pct-logo" x1="0" y1="0" x2="34" y2="34" gradientUnits="userSpaceOnUse">
            <stop stopColor="#6366F1" />
            <stop offset="1" stopColor="#A855F7" />
          </linearGradient>
        </defs>
        <rect width="34" height="34" rx="10" fill="url(#pct-logo)" />
        <path d="M13 27l2-12h4l2 12z" fill="#FFFFFF" />
        <rect x="11" y="10" width="12" height="5" rx="1.5" fill="#FFFFFF" />
        <path
          d="M8 9a12 12 0 0 1 18 0M10.5 6.5a8.5 8.5 0 0 1 13 0"
          stroke="#FFFFFF"
          strokeWidth="1.8"
          fill="none"
          strokeLinecap="round"
        />
      </svg>
      <div>
        <b>Control Tower</b>
        <small>{t("brand.sub")}</small>
      </div>
    </div>
  );
}

export function AuthLayout({ title, sub, children }: { title: string; sub: string; children: React.ReactNode }) {
  return (
    <main className="auth">
      <div className="auth-prefs">
        <PrefsSwitcher compact />
      </div>
      <div className="auth-card card">
        <div className="card-b" style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <div className="auth-brand">
            <Brand />
          </div>
          <div>
            <h1 style={{ margin: 0, fontSize: 22 }}>{title}</h1>
            <p className="muted" style={{ margin: "6px 0 0" }}>
              {sub}
            </p>
          </div>
          {children}
          <div style={{ textAlign: "center", borderTop: "1px solid var(--line, #e2e8f0)", paddingTop: 10 }}><Copyright /></div>
        </div>
      </div>
    </main>
  );
}

export function LoginPage({ onLogged }: { onLogged: (me: Me) => void }) {
  const { t } = usePrefs();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ssoEmail, setSsoEmail] = useState("");
  const [ssoHint, setSsoHint] = useState(false);
  const params = new URLSearchParams(window.location.search);
  const ssoError = params.get("sso");
  const resetUid = params.get("reset");
  const resetToken = params.get("token");
  const [mode, setMode] = useState<"login" | "forgot" | "reset">(resetUid && resetToken ? "reset" : "login");

  const [passwordOk, setPasswordOk] = useState<string | null>(null);
  const backToLogin = () => {
    if (resetUid) window.history.replaceState(null, "", window.location.pathname);
    setMode("login");
  };
  const afterReset = (login?: string) => {
    if (login) setUsername(login);
    setPassword("");
    setPasswordOk(login ?? "");
    backToLogin();
    setTimeout(() => document.getElementById(login ? "password" : "username")?.focus(), 50);
  };

  const startSso = (provider: "microsoft" | "google" | "") => {
    if (!ssoEmail.trim()) {
      setSsoHint(true);
      document.getElementById("sso-email")?.focus();
      return;
    }
    const providerQuery = provider ? `&provider=${provider}` : "";
    window.location.assign(`${API_BASE}/auth/sso/start?email=${encodeURIComponent(ssoEmail.trim())}${providerQuery}`);
  };

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onLogged(await authApi.login(username.trim(), password));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("login.failed"));
    } finally {
      setBusy(false);
    }
  }

  if (mode === "forgot") {
    return (
      <AuthLayout title={t("forgot.title")} sub={t("forgot.sub")}>
        <ForgotPasswordForm onBack={backToLogin} />
      </AuthLayout>
    );
  }
  if (mode === "reset" && resetUid && resetToken) {
    return (
      <AuthLayout title={t("reset.title")} sub={t("reset.sub")}>
        <ResetPasswordForm uid={resetUid} token={resetToken} onDone={afterReset} />
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title={t("login.title")} sub={t("login.sub")}>
      {passwordOk !== null && (
        <div className="callout ok" role="status" style={{ marginBottom: 14 }}>
          <b>✓ Mot de passe validé</b>
          <div>Votre nouveau mot de passe est enregistré. Connectez-vous{passwordOk ? <> avec l’identifiant <b className="mono">{passwordOk}</b></> : ""}.</div>
        </div>
      )}
      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <Field id="username" label={t("login.username")}>
          <input
            id="username"
            className="inp"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </Field>
        <Field id="password" label={t("login.password")}>
          <div className="password-field">
            <input
              id="password"
              className="inp password-input"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <button
              className="password-toggle"
              type="button"
              aria-label={showPassword ? t("login.hideAria") : t("login.showAria")}
              aria-pressed={showPassword}
              onClick={() => setShowPassword((visible) => !visible)}
            >
              {showPassword ? t("login.hide") : t("login.show")}
            </button>
          </div>
        </Field>
        <div className="auth-forgot">
          <button className="auth-link-inline" type="button" onClick={() => setMode("forgot")}>
            {t("login.forgot")}
          </button>
        </div>
        {error && (
          <div className="callout warn" role="alert">
            <b>{error}</b>
          </div>
        )}
        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? t("login.busy") : t("login.submit")}
        </button>
      </form>
      <div className="auth-sep">
        <span>{t("login.or")}</span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <Field id="sso-email" label={t("login.ssoEmail")}>
          <input
            id="sso-email"
            className="inp"
            type="email"
            autoComplete="email"
            placeholder="prenom.nom@entreprise.com"
            value={ssoEmail}
            onChange={(e) => {
              setSsoEmail(e.target.value);
              setSsoHint(false);
            }}
          />
        </Field>
        {ssoHint && <div className="auth-hint">{t("login.ssoEmailHint")}</div>}
        {ssoError && (
          <div className="callout warn" role="alert">
            {t("login.ssoError")}
          </div>
        )}
        <div className="sso-btns">
          <button className="btn sso-btn" type="button" onClick={() => startSso("microsoft")}>
            <svg aria-hidden="true" width="20" height="20" viewBox="0 0 18 18"><path fill="#f25022" d="M1 1h7.4v7.4H1z"/><path fill="#7fba00" d="M9.6 1H17v7.4H9.6z"/><path fill="#00a4ef" d="M1 9.6h7.4V17H1z"/><path fill="#ffb900" d="M9.6 9.6H17V17H9.6z"/></svg>
            <span>{t("login.microsoft")}</span>
          </button>
          <button className="btn sso-btn" type="button" onClick={() => startSso("google")}>
            <svg aria-hidden="true" width="20" height="20" viewBox="0 0 48 48"><path fill="#4285F4" d="M43.6 24.5c0-1.4-.1-2.8-.4-4.1H24v7.8h11a9.5 9.5 0 0 1-4.1 6.2v5h6.7c3.9-3.6 6-8.8 6-14.9z"/><path fill="#34A853" d="M24 44c5.5 0 10.1-1.8 13.5-4.8l-6.7-5c-1.8 1.2-4.1 2-6.8 2-5.2 0-9.6-3.5-11.2-8.2H5.9v5.1A20 20 0 0 0 24 44z"/><path fill="#FBBC05" d="M12.8 28c-.4-1.2-.7-2.6-.7-4s.2-2.8.7-4v-5.1H5.9A20 20 0 0 0 3.8 24c0 3.2.8 6.3 2.1 9l6.9-5z"/><path fill="#EA4335" d="M24 11.8c3 0 5.7 1 7.8 3.1l5.8-5.8C34.1 5.8 29.5 4 24 4A20 20 0 0 0 5.9 14.9l6.9 5c1.6-4.7 6-8.1 11.2-8.1z"/></svg>
            <span>{t("login.google")}</span>
          </button>
        </div>
        <button className="btn ghost sm sso-other" type="button" onClick={() => startSso("")}>
          {t("login.otherSso")}
        </button>
      </div>
      <div className="auth-secure-note">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <rect x="4" y="11" width="16" height="10" rx="2" />
          <path d="M8 11V7a4 4 0 0 1 8 0v4" />
        </svg>
        {t("login.secure")}
      </div>
    </AuthLayout>
  );
}
