import { useState, type FormEvent } from "react";

import { ApiError } from "../api/client";
import { authApi } from "../api/endpoints";
import { Field } from "../components/ui";
import type { Me } from "../types/api";
import { AuthLayout } from "./LoginPage";

export function ChangePasswordPage({
  me,
  onDone,
  onLogout,
}: {
  me: Me;
  onDone: (me: Me) => void;
  onLogout: () => void;
}) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (next !== confirm) {
      setErrors({ confirm: "Les deux mots de passe ne correspondent pas." });
      return;
    }
    setBusy(true);
    setErrors({});
    try {
      onDone(await authApi.changePassword(current, next));
    } catch (err) {
      if (err instanceof ApiError)
        setErrors({
          ...err.fieldErrors(),
          ...(err.fieldErrors().new_password || err.fieldErrors().current_password ? {} : { form: err.message }),
        });
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout
      title="Choisissez un nouveau mot de passe"
      sub={`Bonjour ${me.name}. Votre mot de passe est provisoire : changez-le pour accéder à l'application.`}
    >
      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <Field id="current" label="Mot de passe actuel" error={errors.current_password}>
          <input
            id="current"
            className="inp"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            required
          />
        </Field>
        <Field
          id="next"
          label="Nouveau mot de passe"
          error={errors.new_password}
          hint="10 caractères minimum, ni trop courant, ni uniquement des chiffres, ni proche de l'identifiant."
        >
          <input
            id="next"
            className="inp"
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            required
          />
        </Field>
        <Field id="confirm" label="Confirmer le nouveau mot de passe" error={errors.confirm}>
          <input
            id="confirm"
            className="inp"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
          />
        </Field>
        {errors.form && (
          <div className="callout warn" role="alert">
            <b>{errors.form}</b>
          </div>
        )}
        <div style={{ display: "flex", gap: 8, justifyContent: "space-between" }}>
          <button type="button" className="btn ghost" onClick={onLogout}>
            Se déconnecter
          </button>
          <button className="btn primary" type="submit" disabled={busy}>
            {busy ? "Enregistrement…" : "Changer le mot de passe"}
          </button>
        </div>
      </form>
    </AuthLayout>
  );
}
