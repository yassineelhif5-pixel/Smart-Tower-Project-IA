// Inscription libre : compte interne (e-mail + mot de passe, confirmation par e-mail) ou Google.
import { useState, type FormEvent } from "react";

import { ApiError } from "../api/client";
import { signupApi } from "../api/endpoints";
import { Field } from "../components/ui";

export function GoogleIcon() {
  return (
    <svg aria-hidden="true" width="20" height="20" viewBox="0 0 48 48"><path fill="#4285F4" d="M43.6 24.5c0-1.4-.1-2.8-.4-4.1H24v7.8h11a9.5 9.5 0 0 1-4.1 6.2v5h6.7c3.9-3.6 6-8.8 6-14.9z"/><path fill="#34A853" d="M24 44c5.5 0 10.1-1.8 13.5-4.8l-6.7-5c-1.8 1.2-4.1 2-6.8 2-5.2 0-9.6-3.5-11.2-8.2H5.9v5.1A20 20 0 0 0 24 44z"/><path fill="#FBBC05" d="M12.8 28c-.4-1.2-.7-2.6-.7-4s.2-2.8.7-4v-5.1H5.9A20 20 0 0 0 3.8 24c0 3.2.8 6.3 2.1 9l6.9-5z"/><path fill="#EA4335" d="M24 11.8c3 0 5.7 1 7.8 3.1l5.8-5.8C34.1 5.8 29.5 4 24 4A20 20 0 0 0 5.9 14.9l6.9 5c1.6-4.7 6-8.1 11.2-8.1z"/></svg>
  );
}

export type InviteInfo = { token: string; email: string; tenant?: string | null; invitedBy?: string; message?: string };

export function SignupForm({ onBack, google, onGoogle, invite }: { onBack: () => void; google: boolean; onGoogle: () => void; invite?: InviteInfo | null }) {
  const [f, setF] = useState({ firstName: "", lastName: "", email: invite?.email ?? "", password: "", confirm: "", accept: false });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<string | null>(null);
  const [resent, setResent] = useState(false);
  const [show, setShow] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (f.password !== f.confirm) {
      setErrors({ confirm: "Les deux mots de passe ne correspondent pas." });
      return;
    }
    setBusy(true);
    setErrors({});
    try {
      const r = await signupApi.signup({ firstName: f.firstName.trim(), lastName: f.lastName.trim(), email: f.email.trim(), password: f.password, acceptTerms: f.accept, invite: invite?.token });
      if (r.loggedIn) {
        try { sessionStorage.removeItem("pct.invite"); } catch { /* stockage indisponible */ }
        window.location.assign("/");
        return;
      }
      setSent(r.email);
    } catch (err) {
      if (err instanceof ApiError) {
        const fe = err.fieldErrors();
        setErrors({ ...fe, ...(Object.keys(fe).length ? {} : { form: err.message }) });
      } else setErrors({ form: "Inscription impossible. Réessayez." });
    } finally {
      setBusy(false);
    }
  }

  if (sent)
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div className="callout ok" role="status">
          <b>✉️ Vérifiez votre boîte de réception</b>
          <div>Si l’adresse <b>{sent}</b> est valide, un e-mail de confirmation vient d’être envoyé. Cliquez sur le lien qu’il contient pour activer votre compte (pensez à regarder dans les courriers indésirables).</div>
        </div>
        <button type="button" className="btn" disabled={resent} onClick={() => void signupApi.resend(sent).then(() => setResent(true), () => setResent(true))}>
          {resent ? "E-mail renvoyé" : "Renvoyer l’e-mail"}
        </button>
        <button type="button" className="auth-link-inline" onClick={onBack}>← Retour à la connexion</button>
      </div>
    );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {invite && (
        <div className="callout ok" style={{ display: "block" }}>
          <b>🎉 {invite.invitedBy} vous invite{invite.tenant ? ` à rejoindre ${invite.tenant}` : ""}.</b>
          {invite.message && <div style={{ fontStyle: "italic", marginTop: 4 }}>« {invite.message} »</div>}
          <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>Créez votre compte avec {invite.email} : il sera activé immédiatement.</div>
        </div>
      )}
      {google && (
        <>
          <button className="btn sso-btn" type="button" onClick={onGoogle}>
            <GoogleIcon />
            <span>S’inscrire avec Google</span>
          </button>
          <div className="auth-sep"><span>ou avec votre e-mail</span></div>
        </>
      )}
      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 12 }} noValidate>
        <div className="grid g2" style={{ gap: 10 }}>
          <Field id="su-first" label="Prénom" error={errors.firstName}>
            <input id="su-first" className="inp" autoComplete="given-name" value={f.firstName} onChange={(e) => setF({ ...f, firstName: e.target.value })} required />
          </Field>
          <Field id="su-last" label="Nom" error={errors.lastName}>
            <input id="su-last" className="inp" autoComplete="family-name" value={f.lastName} onChange={(e) => setF({ ...f, lastName: e.target.value })} required />
          </Field>
        </div>
        <Field id="su-email" label="Adresse e-mail" error={errors.email} hint="Elle servira d’identifiant de connexion.">
          <input id="su-email" className="inp" type="email" autoComplete="email" value={f.email} readOnly={!!invite} onChange={(e) => setF({ ...f, email: e.target.value })} required />
        </Field>
        <Field id="su-pass" label="Mot de passe" error={errors.password} hint="10 caractères minimum, pas uniquement des chiffres.">
          <div className="password-field">
            <input id="su-pass" className="inp password-input" type={show ? "text" : "password"} autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} required />
            <button className="password-toggle" type="button" aria-pressed={show} onClick={() => setShow((v) => !v)}>{show ? "Masquer" : "Afficher"}</button>
          </div>
        </Field>
        <Field id="su-confirm" label="Confirmer le mot de passe" error={errors.confirm}>
          <input id="su-confirm" className="inp" type={show ? "text" : "password"} autoComplete="new-password" value={f.confirm} onChange={(e) => setF({ ...f, confirm: e.target.value })} required />
        </Field>
        <label style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13 }}>
          <input type="checkbox" checked={f.accept} onChange={(e) => setF({ ...f, accept: e.target.checked })} style={{ marginTop: 3 }} />
          <span>J’accepte les conditions d’utilisation de Control Tower et le traitement de mes données pour la gestion de mon compte.</span>
        </label>
        {errors.form && <div className="callout warn" role="alert"><b>{errors.form}</b></div>}
        <button className="btn primary" type="submit" disabled={busy || !f.accept}>{busy ? "Création…" : "Créer mon compte"}</button>
      </form>
      <button type="button" className="auth-link-inline" onClick={onBack}>Déjà un compte ? Se connecter</button>
    </div>
  );
}
