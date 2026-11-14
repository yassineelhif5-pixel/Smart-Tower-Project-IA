import { useEffect, useState } from "react";

import { adminApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, Loading, Pill, useAction } from "../../components/ui";
import type { SSOSettings } from "../../types/api";
import { SSORequestsPanel } from "./SSORequestsPanel";
import { ClientDomainsCard } from "./ClientDomainsCard";

export function SSOTab() {
  const data = useApi(adminApi.sso);
  const { run, busy } = useAction();
  const [form, setForm] = useState({ issuer: "", clientId: "", clientSecret: "", defaultRole: "", enabled: false });
  const [message, setMessage] = useState("");
  useEffect(() => {
    if (data.data) setForm((current) => ({ ...current, issuer: data.data!.issuer, clientId: data.data!.clientId,
      defaultRole: data.data!.defaultRole, enabled: data.data!.enabled }));
  }, [data.data]);
  if (data.error) return <ErrorNotice error={data.error} onRetry={data.reload} />;
  if (!data.data) return <Loading />;
  const current: SSOSettings = data.data;
  const set = (patch: Partial<typeof form>) => setForm((old) => ({ ...old, ...patch }));
  const redirectUri = `${window.location.origin}/api/v1/auth/sso/callback`;
  async function save() {
    setMessage("");
    await run(() => adminApi.saveSso({ issuer: form.issuer.trim(), clientId: form.clientId.trim(),
      ...(form.clientSecret ? { clientSecret: form.clientSecret } : {}), defaultRole: form.defaultRole,
      enabled: form.enabled }), "Connexion SSO enregistrée").then((result) => {
      if (result) { data.setData(result); set({ clientSecret: "" }); }
    }, () => undefined);
  }
  return <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
    <Card title="Connexion SSO de l’entreprise"
      sub="Connectez votre fournisseur OpenID Connect. Le Pilote reste responsable de l’affectation des domaines aux entreprises."
      extra={<Pill tone={current.enabled ? "ok" : ""}>{current.enabled ? "Activée" : "Désactivée"}</Pill>}>
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div className="notice">
          Domaines autorisés par le Pilote : <b>{current.domains.length ? current.domains.join(", ") : "aucun domaine attribué"}</b>
          {!current.domains.length && <div style={{ marginTop: 5 }}>Demandez au Pilote d’attribuer le domaine avant d’activer SSO.</div>}
        </div>
        <div className="grid g2">
          <Field id="sso-issuer" label="Émetteur OpenID Connect" hint="URL HTTPS de l’émetteur, par exemple l’URL de votre annuaire Microsoft Entra.">
            <input id="sso-issuer" className="inp mono" type="url" placeholder="https://login.microsoftonline.com/…/v2.0"
              value={form.issuer} onChange={(e) => set({ issuer: e.target.value })} />
          </Field>
          <Field id="sso-client-id" label="Identifiant client de l’application SSO">
            <input id="sso-client-id" className="inp mono" value={form.clientId}
              onChange={(e) => set({ clientId: e.target.value })} />
          </Field>
          <Field id="sso-client-secret" label="Secret client"
            hint={current.secretSet ? `Secret chiffré enregistré (…${current.secretHint}). Laissez vide pour le garder.` : "Saisissez le secret client du fournisseur."}>
            <input id="sso-client-secret" className="inp mono" type="password" autoComplete="new-password"
              value={form.clientSecret} onChange={(e) => set({ clientSecret: e.target.value })} />
          </Field>
          <Field id="sso-default-role" label="Profil appliqué aux nouveaux comptes">
            <select id="sso-default-role" className="inp" value={form.defaultRole} onChange={(e) => set({ defaultRole: e.target.value })}>
              <option value="">Choisir un profil…</option>
              {current.roles.map((role) => <option key={role.code} value={role.code}>{role.label}</option>)}
            </select>
          </Field>
        </div>
        <div className="notice">
          <b>URL de retour à enregistrer chez votre fournisseur</b><br />
          <code className="mono">{redirectUri}</code><br />
          Les utilisateurs inconnus pourront demander un accès. Ils resteront bloqués jusqu’à ce qu’un responsable valide la demande et choisisse leur profil. Les comptes déjà créés et actifs dans cette entreprise seront reliés à leur identité SSO.
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: 9 }}>
          <input type="checkbox" checked={form.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
          Activer la connexion SSO pour les domaines attribués
        </label>
        {message && <div className="notice" role="status">{message}</div>}
        <div className="btns"><button className="btn primary" disabled={busy || !form.issuer || !form.clientId || !form.defaultRole || (form.enabled && !current.domains.length)} onClick={save}>
          {busy ? "Enregistrement…" : "Enregistrer la connexion"}
        </button></div>
      </div>
    </Card>
    <ClientDomainsCard />
    <SSORequestsPanel />
  </div>;
}
