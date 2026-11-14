import { useState, type FormEvent } from "react";

import { ApiError } from "../api/client";
import { authApi } from "../api/endpoints";
import { Field } from "../components/ui";
import { usePrefs } from "../i18n";

function errorText(err: unknown, fallback: string) {
  if (!(err instanceof ApiError)) return fallback;
  const details = err.details.map((d) => (typeof d === "string" ? d : d.message)).filter(Boolean);
  return details.length ? details.join(" ") : err.message;
}

/** Étape 1 : l'utilisateur demande un lien de réinitialisation. */
export function ForgotPasswordForm({ onBack }: { onBack: () => void }) {
  const { t } = usePrefs();
  const [identifier, setIdentifier] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await authApi.forgotPassword(identifier.trim());
      setSent(true);
    } catch (err) {
      setError(errorText(err, t("forgot.failed")));
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div className="callout ok" role="status">
          <b>{t("forgot.sentTitle")}</b>
          <div>{t("forgot.sent")}</div>
        </div>
        <button className="btn primary" type="button" onClick={onBack} style={{ justifyContent: "center" }}>
          {t("forgot.back")}
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <Field id="forgot-identifier" label={t("forgot.identifier")}>
        <input
          id="forgot-identifier"
          className="inp"
          autoComplete="email"
          placeholder="prenom.nom@entreprise.com"
          value={identifier}
          onChange={(e) => setIdentifier(e.target.value)}
          required
          autoFocus
        />
      </Field>
      {error && (
        <div className="callout warn" role="alert">
          {error}
        </div>
      )}
      <button className="btn primary" type="submit" disabled={busy || !identifier.trim()} style={{ justifyContent: "center" }}>
        {busy ? t("forgot.sending") : t("forgot.submit")}
      </button>
      <button className="btn ghost sm auth-link" type="button" onClick={onBack}>
        ← {t("forgot.back")}
      </button>
    </form>
  );
}

/** Étape 2 : l'utilisateur arrive par le lien reçu et choisit un nouveau mot de passe. */
export function ResetPasswordForm({ uid, token, onDone }: { uid: string; token: string; onDone: (username?: string) => void }) {
  const { t } = usePrefs();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (password !== confirm) {
      setError(t("reset.mismatch"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await authApi.resetPassword(uid, token, password);
      // Confirmation reçue de la base : retour direct à l'écran de connexion, identifiant prérempli.
      onDone(res.username ?? "");
      setDone(true);
    } catch (err) {
      setError(errorText(err, t("reset.failed")));
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div className="callout ok" role="status">
          <b>{t("reset.doneTitle")}</b>
          <div>{t("reset.done")}</div>
        </div>
        <button className="btn primary" type="button" onClick={() => onDone()} style={{ justifyContent: "center" }}>
          {t("login.submit")}
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <Field id="reset-password" label={t("reset.new")}>
        <div className="password-field">
          <input
            id="reset-password"
            className="inp password-input"
            type={show ? "text" : "password"}
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={10}
            required
            autoFocus
          />
          <button
            className="password-toggle"
            type="button"
            aria-label={show ? t("login.hideAria") : t("login.showAria")}
            aria-pressed={show}
            onClick={() => setShow((v) => !v)}
          >
            {show ? t("login.hide") : t("login.show")}
          </button>
        </div>
      </Field>
      <Field id="reset-confirm" label={t("reset.confirm")}>
        <input
          id="reset-confirm"
          className="inp"
          type={show ? "text" : "password"}
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          required
        />
      </Field>
      <div className="auth-hint muted">{t("reset.rules")}</div>
      {error && (
        <div className="callout warn" role="alert">
          {error}
        </div>
      )}
      <button className="btn primary" type="submit" disabled={busy} style={{ justifyContent: "center" }}>
        {busy ? t("reset.saving") : t("reset.submit")}
      </button>
      <button className="btn ghost sm auth-link" type="button" onClick={() => onDone()}>
        ← {t("forgot.back")}
      </button>
    </form>
  );
}
