import { useState, type FormEvent } from "react";

import { ApiError } from "../api/client";
import { authApi } from "../api/endpoints";
import { Field } from "../components/ui";
import type { Me } from "../types/api";

export function Brand() {
  return (
    <div className="brand">
      <svg width="34" height="34" viewBox="0 0 34 34" aria-hidden="true">
        <rect width="34" height="34" rx="9" fill="#35B6AD" />
        <path d="M13 27l2-12h4l2 12z" fill="#06221F" />
        <rect x="11" y="10" width="12" height="5" rx="1.5" fill="#06221F" />
        <path
          d="M8 9a12 12 0 0 1 18 0M10.5 6.5a8.5 8.5 0 0 1 13 0"
          stroke="#06221F"
          strokeWidth="1.8"
          fill="none"
          strokeLinecap="round"
        />
      </svg>
      <div>
        <b>Control Tower</b>
        <small>Pilotage projets</small>
      </div>
    </div>
  );
}

export function AuthLayout({ title, sub, children }: { title: string; sub: string; children: React.ReactNode }) {
  return (
    <main className="auth">
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
        </div>
      </div>
    </main>
  );
}

export function LoginPage({ onLogged }: { onLogged: (me: Me) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onLogged(await authApi.login(username.trim(), password));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Connexion impossible.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout title="Connexion" sub="Accédez à votre espace avec votre identifiant.">
      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <Field id="username" label="Identifiant">
          <input
            id="username"
            className="inp"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </Field>
        <Field id="password" label="Mot de passe">
          <input
            id="password"
            className="inp"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </Field>
        {error && (
          <div className="callout warn" role="alert">
            <b>{error}</b>
          </div>
        )}
        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? "Connexion…" : "Se connecter"}
        </button>
      </form>
    </AuthLayout>
  );
}
