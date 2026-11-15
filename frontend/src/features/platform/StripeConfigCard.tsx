// Pilote › Configuration : compte Stripe (clés, webhook), prix unitaires des licences et journal des paiements.
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { useApi } from "../../api/useApi";
import { Card, useAction } from "../../components/ui";
import { PaymentHistory, type PaymentRow } from "../licensing/PaymentPanel";

type S = { enabled: boolean; source: string; mode: string; hasSecretKey: boolean; secretHint: string; hasWebhookSecret: boolean; publishableKey: string; currency: string;
  namedPrice: string; concurrentPrice: string; licenseInterval: string; updatedBy: string; webhookUrl: string; events: string[] };

export function StripeConfigCard() {
  const r = useApi(() => api.get<S>("/platform/config/stripe"));
  const pays = useApi(() => api.get<{ payments: PaymentRow[] }>("/payments"));
  const { run, busy } = useAction();
  const [f, setF] = useState({ secretKey: "", webhookSecret: "", publishableKey: "", currency: "EUR", namedPrice: "0", concurrentPrice: "0", licenseInterval: "month", enabled: true });
  useEffect(() => {
    if (r.data) setF((x) => ({ ...x, secretKey: "", webhookSecret: "", publishableKey: r.data!.publishableKey, currency: r.data!.currency, namedPrice: r.data!.namedPrice,
      concurrentPrice: r.data!.concurrentPrice, licenseInterval: r.data!.licenseInterval, enabled: r.data!.enabled || !r.data!.hasSecretKey }));
  }, [r.data]);
  if (!r.data) return null;
  const s = r.data;
  const lab = (t: string) => <span className="muted" style={{ fontSize: 12 }}>{t}</span>;
  return (
    <Card title="💳 Paiement en ligne (Stripe)" sub="Les clients et le Pilote paient les offres et les licences via Stripe Checkout ; l’activation est automatique après paiement.">
      <p style={{ margin: "0 0 8px" }}>
        État : {s.enabled ? <b className="t-ok">activé</b> : <b className="t-crit">non configuré</b>}
        {s.mode && <span className={`pill ${s.mode === "live" ? "ok" : "warn"}`} style={{ marginLeft: 8 }}>{s.mode === "live" ? "mode réel" : "mode test"}</span>}
        {s.source === "env" && <span className="muted"> (variables STRIPE_SECRET_KEY / STRIPE_WEBHOOK_SECRET)</span>}
      </p>
      <div className="callout info" style={{ display: "block", marginBottom: 10 }}>
        <b>Webhook à créer dans Stripe</b> (Développeurs › Webhooks › Ajouter un endpoint) :
        <div style={{ marginTop: 4 }}><code>{s.webhookUrl}</code> <button type="button" className="btn ghost sm" onClick={() => void navigator.clipboard?.writeText(s.webhookUrl)}>Copier</button></div>
        <small className="muted">Événements : {s.events.join(", ")}. Copiez ensuite le « secret de signature » (whsec_…) ci-dessous. Sans webhook, le paiement est quand même confirmé au retour du client sur le site.</small>
      </div>
      <div className="grid g2" style={{ gap: 8 }}>
        <label>{lab(`Clé secrète ${s.hasSecretKey ? `(définie ····${s.secretHint})` : "(non définie)"}`)}
          <input className="inp" type="password" autoComplete="new-password" placeholder={s.hasSecretKey ? "laisser vide pour conserver" : "sk_test_… ou sk_live_…"} value={f.secretKey} onChange={(e) => setF({ ...f, secretKey: e.target.value })} /></label>
        <label>{lab(`Secret du webhook ${s.hasWebhookSecret ? "(défini)" : "(non défini)"}`)}
          <input className="inp" type="password" autoComplete="new-password" placeholder={s.hasWebhookSecret ? "laisser vide pour conserver" : "whsec_…"} value={f.webhookSecret} onChange={(e) => setF({ ...f, webhookSecret: e.target.value })} /></label>
        <label>{lab("Clé publiable (facultatif)")}<input className="inp" placeholder="pk_test_…" value={f.publishableKey} onChange={(e) => setF({ ...f, publishableKey: e.target.value })} /></label>
        <label>{lab("Devise")}<input className="inp" maxLength={3} value={f.currency} onChange={(e) => setF({ ...f, currency: e.target.value.toUpperCase() })} /></label>
        <label>{lab("Prix d’une licence nominative (HT)")}<input className="inp num" type="number" min={0} step="0.01" value={f.namedPrice} onChange={(e) => setF({ ...f, namedPrice: e.target.value })} /></label>
        <label>{lab("Prix d’une licence concurrente (HT)")}<input className="inp num" type="number" min={0} step="0.01" value={f.concurrentPrice} onChange={(e) => setF({ ...f, concurrentPrice: e.target.value })} /></label>
        <label>{lab("Facturation des licences")}
          <select className="inp" value={f.licenseInterval} onChange={(e) => setF({ ...f, licenseInterval: e.target.value })}>
            <option value="month">Abonnement mensuel</option><option value="year">Abonnement annuel</option><option value="once">Paiement unique</option>
          </select></label>
      </div>
      <label style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
        <input type="checkbox" checked={f.enabled} onChange={(e) => setF({ ...f, enabled: e.target.checked })} /> Activer le paiement en ligne
      </label>
      <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap", alignItems: "center" }}>
        <button type="button" className="btn primary sm" disabled={busy}
          onClick={() => void run(() => api.put("/platform/config/stripe", { ...f, secretKey: f.secretKey || undefined, webhookSecret: f.webhookSecret || undefined }), "Paiement Stripe enregistré").then(() => r.reload(), () => undefined)}>Enregistrer</button>
        <span className="muted" style={{ fontSize: 12 }}>Les prix des offres se règlent dans l’onglet Offres (prix et période de chaque version). Les clés sont chiffrées et jamais réaffichées.{s.updatedBy && ` Modifié par ${s.updatedBy}.`}</span>
      </div>
      <h4 style={{ margin: "16px 0 6px" }}>Paiements</h4>
      {pays.data?.payments.length ? <PaymentHistory rows={pays.data.payments} showTenant /> : <p className="muted" style={{ margin: 0 }}>Aucun paiement pour l’instant.</p>}
    </Card>
  );
}
