// Pilote › Configuration : client OAuth Google de la plateforme (« Continuer avec Google » pour tous les comptes).
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { useApi } from "../../api/useApi";
import { Card, useAction } from "../../components/ui";

type G = { clientId: string; hasSecret: boolean; secretHint: string; enabled: boolean; source: "pilot" | "env" | ""; redirectUri: string; origin: string; updatedBy: string; updatedAt: string | null };

export function GoogleConfigCard() {
  const r = useApi(() => api.get<G>("/platform/config/google"));
  const { run, busy } = useAction();
  const [f, setF] = useState({ clientId: "", clientSecret: "", enabled: true });
  useEffect(() => {
    if (r.data) setF({ clientId: r.data.clientId, clientSecret: "", enabled: r.data.enabled || !r.data.clientId });
  }, [r.data]);
  if (!r.data) return null;
  const g = r.data;
  const copy = (v: string) => void navigator.clipboard?.writeText(v);
  return (
    <Card title="🔑 Connexion Google (inscription et connexion)" sub="Permet à toute personne de créer son compte ou de se connecter avec Google, sans configuration par entreprise.">
      <p style={{ margin: "0 0 8px" }}>
        État : {g.enabled ? <b className="t-ok">activée</b> : <b className="t-crit">non configurée</b>}
        {g.source === "env" && <span className="muted"> (variables GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)</span>}
      </p>
      <div className="callout info" style={{ marginBottom: 10, display: "block" }}>
        <b>À déclarer dans Google Cloud Console</b> (API et services › Identifiants › ID client OAuth « Application Web ») :
        <div style={{ marginTop: 6, display: "grid", gap: 4 }}>
          <span>Origine JavaScript autorisée : <code>{g.origin}</code> <button type="button" className="btn ghost sm" onClick={() => copy(g.origin)}>Copier</button></span>
          <span>URI de redirection autorisée : <code>{g.redirectUri}</code> <button type="button" className="btn ghost sm" onClick={() => copy(g.redirectUri)}>Copier</button></span>
        </div>
      </div>
      <div className="grid g2" style={{ gap: 8 }}>
        <label><span className="muted" style={{ fontSize: 12 }}>ID client</span>
          <input className="inp" value={f.clientId} placeholder="xxxxxxxx.apps.googleusercontent.com" onChange={(e) => setF({ ...f, clientId: e.target.value })} /></label>
        <label><span className="muted" style={{ fontSize: 12 }}>Code secret du client {g.hasSecret ? `(défini${g.secretHint ? ` ····${g.secretHint}` : ""})` : "(non défini)"}</span>
          <input className="inp" type="password" autoComplete="new-password" placeholder={g.hasSecret ? "laisser vide pour conserver" : "GOCSPX-…"} value={f.clientSecret} onChange={(e) => setF({ ...f, clientSecret: e.target.value })} /></label>
      </div>
      <label style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
        <input type="checkbox" checked={f.enabled} onChange={(e) => setF({ ...f, enabled: e.target.checked })} /> Activer « Continuer avec Google »
      </label>
      <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap", alignItems: "center" }}>
        <button type="button" className="btn primary sm" disabled={busy}
          onClick={() => void run(() => api.put("/platform/config/google", { ...f, clientSecret: f.clientSecret || undefined }), "Connexion Google enregistrée").then(() => r.reload(), () => undefined)}>Enregistrer</button>
        {g.source === "pilot" && <button type="button" className="btn sm" disabled={busy} onClick={() => void run(() => api.put("/platform/config/google", { reset: true }), "Réglage Google effacé").then(() => r.reload(), () => undefined)}>Effacer</button>}
        <span className="muted" style={{ fontSize: 12 }}>Le secret est stocké chiffré et jamais réaffiché.{g.updatedBy && ` Modifié par ${g.updatedBy}.`}</span>
      </div>
    </Card>
  );
}
