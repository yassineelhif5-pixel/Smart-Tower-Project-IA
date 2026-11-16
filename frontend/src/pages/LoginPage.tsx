import { useEffect, useState, type FormEvent } from "react";
import { Copyright } from "../components/Copyright";

import { ApiError } from "../api/client";
import { API_BASE } from "../api/client";
import { authApi, signupApi } from "../api/endpoints";
import { GoogleIcon, SignupForm, type InviteInfo } from "./SignupForm";
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
  const verified = params.get("verified");
  const googleState = params.get("google");
  const [mode, setMode] = useState<"login" | "forgot" | "reset" | "signup">(
    resetUid && resetToken ? "reset" : params.get("signup") ? "signup" : "login",
  );
  const [providers, setProviders] = useState<{ google: boolean; signup: boolean }>({ google: false, signup: true });
  const [unverified, setUnverified] = useState<string | null>(null);
  const [resent, setResent] = useState(false);
  const inviteToken = params.get("invite") || "";
  const [invite, setInvite] = useState<InviteInfo | null>(null);
  const [inviteError, setInviteError] = useState(false);
  useEffect(() => {
    signupApi.providers().then(setProviders, () => undefined);
    if (inviteToken) {
      signupApi.invitation(inviteToken).then((r) => {
        if (r.valid && r.email) {
          setInvite({ token: inviteToken, email: r.email, tenant: r.tenant, invitedBy: r.invitedBy, message: r.message });
          try { sessionStorage.setItem("pct.invite", inviteToken); } catch { /* stockage indisponible */ }
          setMode("signup");
        } else setInviteError(true);
      }, () => setInviteError(true));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const startGoogle = () =>
    window.location.assign(`${API_BASE}/auth/google/start${invite ? `?invite=${encodeURIComponent(invite.token)}` : ""}`);

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
      if (err instanceof ApiError && err.code === "EMAIL_NOT_VERIFIED") {
        const d = err.details.find((x) => typeof x === "object" && x.field === "email");
        setUnverified(d && typeof d === "object" ? d.message : username.trim());
        setResent(false);
      } else setUnverified(null);
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
  if (mode === "signup") {
    return (
      <AuthLayout title={invite ? "Accepter l’invitation" : "Créer un compte"}
        sub={invite ? "Créez votre compte Control Tower en quelques secondes." : "Inscrivez-vous gratuitement : démo de 3 jours ou accès à votre entreprise."}>
        <SignupForm onBack={() => setMode("login")} google={providers.google} onGoogle={startGoogle} invite={invite} />
        {invite && <p className="muted" style={{ fontSize: 12, textAlign: "center", margin: "10px 0 0" }}>Vous avez déjà un compte avec {invite.email} ? Connectez-vous : l’invitation sera acceptée automatiquement.</p>}
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
      {verified === "1" && (
        <div className="callout ok" role="status" style={{ marginBottom: 14 }}>
          <b>✓ Adresse e-mail confirmée</b>
          <div>Votre compte est actif. Connectez-vous avec votre adresse e-mail et votre mot de passe.</div>
        </div>
      )}
      {verified === "0" && (
        <div className="callout warn" role="alert" style={{ marginBottom: 14 }}>
          <b>Lien de confirmation invalide ou expiré.</b>
          <div>Connectez-vous pour recevoir un nouveau lien, ou recréez votre compte.</div>
        </div>
      )}
      {inviteError && (
        <div className="callout warn" role="alert" style={{ marginBottom: 14 }}>
          Ce lien d’invitation n’est plus valide (expiré, déjà utilisé ou révoqué). Demandez une nouvelle invitation ou créez votre compte.
        </div>
      )}
      {googleState && (
        <div className="callout warn" role="alert" style={{ marginBottom: 14 }}>
          {googleState === "unavailable" ? "La connexion Google n’est pas encore activée sur la plateforme." : "Connexion Google impossible. Réessayez."}
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
            {unverified && (
              <div style={{ marginTop: 6 }}>
                <button type="button" className="btn sm" disabled={resent}
                  onClick={() => void signupApi.resend(unverified).then(() => setResent(true), () => setResent(true))}>
                  {resent ? "E-mail de confirmation renvoyé" : "Renvoyer l’e-mail de confirmation"}
                </button>
              </div>
            )}
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
          <button className="btn sso-btn" type="button" onClick={startGoogle}>
            <GoogleIcon />
            <span>{t("login.google")}</span>
          </button>
        </div>
        <button className="btn ghost sm sso-other" type="button" onClick={() => startSso("")}>
          {t("login.otherSso")}
        </button>
      </div>
      {providers.signup && (
        <div className="auth-signup">
          <span className="muted">Pas encore de compte ?</span>{" "}
          <button className="auth-link-inline" type="button" onClick={() => setMode("signup")}>
            <b>Créer un compte</b>
          </button>
        </div>
      )}
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
