// Paiement en ligne (Stripe Checkout) : choix d'une offre ou d'un nombre de licences, puis redirection vers Stripe.
// Utilisé par l'admin d'entreprise (Licences), l'admin d'une démo terminée (accueil) et le Pilote (demande validée).
import { useEffect, useState } from "react";

import { api, ApiError } from "../../api/client";
import { useApi } from "../../api/useApi";

type Offer = { id: number; offer: string; description: string; number: number; price: string | null; currency: string; interval: string; intervalLabel: string; maxUsers: number | null; named: number; concurrent: number; payable: boolean };
export type PaymentRow = { id: number; tenant: string; kind: string; label: string; amount: string; currency: string; interval: string; status: string; statusLabel: string; createdAt: string; paidAt: string | null; appliedAt: string | null; error: string; requestId: number | null; checkoutUrl: string; by: string };
type Options = {
  configured: boolean; mode: string; currency: string;
  tenant: { id: number; name: string; demo: boolean };
  current: { offer: string; version: number; status: string; endDate: string | null; demo: boolean } | null;
  offers: Offer[];
  licensePrices: { named: string; concurrent: string; interval: string; intervalLabel: string };
  canBuyLicenses: boolean;
  preselect: { mode: "offer"; versionId: number } | { mode: "licenses"; licenseKind: "named" | "concurrent"; quantity: number } | null;
  request: { id: number; status: string; kind: string } | null;
  payments: PaymentRow[];
};

const money = (v: number | string, cur: string) => Number(v).toLocaleString("fr-FR", { style: "currency", currency: cur || "EUR" });

export function PaymentPanel({ tenantId, requestId, pilot, onPaid }: { tenantId?: number; requestId?: number; pilot?: boolean; onPaid?: () => void }) {
  const qs = new URLSearchParams();
  if (tenantId) qs.set("tenant", String(tenantId));
  if (requestId) qs.set("request", String(requestId));
  const r = useApi(() => api.get<Options>(`/payments/options?${qs.toString()}`), [tenantId, requestId]);
  const [mode, setMode] = useState<"offer" | "licenses">("offer");
  const [versionId, setVersionId] = useState<number | null>(null);
  const [kind, setKind] = useState<"named" | "concurrent">("named");
  const [qty, setQty] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [link, setLink] = useState<string | null>(null);

  useEffect(() => {
    const o = r.data;
    if (!o) return;
    const p = o.preselect;
    if (p?.mode === "licenses" && o.canBuyLicenses) {
      setMode("licenses");
      setKind(p.licenseKind);
      setQty(p.quantity);
    } else {
      setMode("offer");
      setVersionId(p?.mode === "offer" ? p.versionId : o.offers.find((x) => x.payable)?.id ?? null);
    }
  }, [r.data]);

  if (r.error) return <div className="callout warn"><b>{r.error.message}</b></div>;
  if (!r.data) return <p className="muted">Chargement des offres…</p>;
  const o = r.data;
  if (!o.configured)
    return <div className="callout info" style={{ display: "block" }}><b>Paiement en ligne indisponible</b> · le Pilote n’a pas encore configuré Stripe{pilot ? " (Pilote › Configuration › Paiement Stripe)" : ""}.</div>;

  const offer = o.offers.find((x) => x.id === versionId) ?? null;
  const unit = mode === "licenses" ? Number(kind === "named" ? o.licensePrices.named : o.licensePrices.concurrent) : Number(offer?.price ?? 0);
  const total = mode === "licenses" ? unit * qty : unit;
  const interval = mode === "licenses" ? o.licensePrices.intervalLabel : offer?.intervalLabel ?? "";
  const canPay = mode === "offer" ? !!offer?.payable : o.canBuyLicenses && unit > 0 && qty >= 1;

  const pay = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<{ url: string; paymentId: number }>("/payments/checkout", {
        mode, versionId: mode === "offer" ? versionId : undefined, licenseKind: mode === "licenses" ? kind : undefined,
        quantity: mode === "licenses" ? qty : 1, tenant: tenantId, request: requestId,
      });
      if (pilot) {
        setLink(res.url);
        onPaid?.();
      } else window.location.assign(res.url);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Paiement impossible.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="pay-panel">
      <div className="muted" style={{ fontSize: 13 }}>
        {o.tenant.name} · abonnement actuel : {o.current ? <b>{o.current.offer} v{o.current.version} ({o.current.status}{o.current.endDate ? `, jusqu’au ${new Date(o.current.endDate).toLocaleDateString("fr-FR")}` : ""})</b> : <b>aucun</b>}
        {o.mode === "test" && <span className="pill warn" style={{ marginLeft: 8 }}>Stripe en mode test</span>}
      </div>
      <div className="pay-modes" role="tablist">
        <button type="button" role="tab" aria-selected={mode === "offer"} className={`pay-mode${mode === "offer" ? " on" : ""}`} onClick={() => setMode("offer")}>
          <b>📦 Choisir une offre</b><small className="muted">Abonnement complet (licences et modules inclus)</small>
        </button>
        <button type="button" role="tab" aria-selected={mode === "licenses"} disabled={!o.canBuyLicenses} className={`pay-mode${mode === "licenses" ? " on" : ""}`} onClick={() => setMode("licenses")}
          title={o.canBuyLicenses ? "" : "Disponible avec un abonnement en cours"}>
          <b>🔢 Acheter des licences</b><small className="muted">{o.canBuyLicenses ? "Le nombre de votre choix, ajouté à l’abonnement" : "Nécessite d’abord une offre"}</small>
        </button>
      </div>

      {mode === "offer" ? (
        o.offers.length ? (
          <div className="onb-offers">
            {o.offers.map((x) => (
              <label key={x.id} className={`onb-offer${versionId === x.id ? " on" : ""}${x.payable ? "" : " disabled"}`}>
                <input type="radio" name={`pay-offer-${tenantId ?? "me"}`} disabled={!x.payable} checked={versionId === x.id} onChange={() => setVersionId(x.id)} />
                <span style={{ flex: 1 }}>
                  <b>{x.offer}</b> <span className="muted">v{x.number}</span>
                  <span style={{ float: "right" }}>{x.payable ? <b>{money(x.price as string, x.currency)}</b> : <span className="muted">sur devis</span>} <small className="muted">{x.payable ? x.intervalLabel : ""}</small></span>
                  <small className="muted" style={{ display: "block" }}>
                    {[x.maxUsers ? `${x.maxUsers} utilisateurs` : "utilisateurs illimités", x.named ? `${x.named} licence(s) nominative(s)` : "", x.concurrent ? `${x.concurrent} concurrente(s)` : ""].filter(Boolean).join(" · ")}
                    {x.description ? ` — ${x.description}` : ""}
                  </small>
                </span>
              </label>
            ))}
          </div>
        ) : <p className="muted">Aucune offre publiée.</p>
      ) : (
        <div className="grid g2" style={{ gap: 10 }}>
          <label><span className="muted" style={{ fontSize: 12 }}>Type de licence</span>
            <select className="inp" value={kind} onChange={(e) => setKind(e.target.value as "named" | "concurrent")}>
              <option value="named">Nominative · {money(o.licensePrices.named, o.currency)} {o.licensePrices.intervalLabel}</option>
              <option value="concurrent">Concurrente · {money(o.licensePrices.concurrent, o.currency)} {o.licensePrices.intervalLabel}</option>
            </select></label>
          <label><span className="muted" style={{ fontSize: 12 }}>Nombre de licences</span>
            <input className="inp num" type="number" min={1} max={1000} value={qty} onChange={(e) => setQty(Math.max(1, Math.min(1000, Number(e.target.value) || 1)))} /></label>
        </div>
      )}

      <div className="pay-total">
        <span>Total : <b>{money(total, o.currency)}</b> <span className="muted">{interval}</span></span>
        <button type="button" className="btn primary" disabled={busy || !canPay} onClick={() => void pay()}>
          {busy ? "Redirection…" : pilot ? "Créer le lien de paiement" : "💳 Payer avec Stripe"}
        </button>
      </div>
      <p className="muted" style={{ fontSize: 12, margin: 0 }}>
        Paiement sécurisé par Stripe (carte, SEPA selon votre compte). L’abonnement ou les licences sont activés automatiquement dès la confirmation du paiement.
      </p>
      {error && <div className="callout warn" role="alert"><b>{error}</b></div>}
      {link && (
        <div className="callout ok" style={{ display: "block" }}>
          <b>Lien de paiement prêt.</b> Ouvrez-le pour payer maintenant ou envoyez-le au client :
          <div style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap" }}>
            <input className="inp" readOnly value={link} style={{ flex: 1, minWidth: 240 }} onFocus={(e) => e.target.select()} />
            <button type="button" className="btn sm" onClick={() => void navigator.clipboard?.writeText(link)}>Copier</button>
            <a className="btn primary sm" href={link} target="_blank" rel="noopener noreferrer">Ouvrir Stripe</a>
          </div>
        </div>
      )}
      {o.payments.length > 0 && <PaymentHistory rows={o.payments} />}
    </div>
  );
}

export function PaymentHistory({ rows, showTenant }: { rows: PaymentRow[]; showTenant?: boolean }) {
  return (
    <div className="tbl-wrap"><table className="tbl tight">
      <thead><tr><th>Date</th>{showTenant && <th>Entreprise</th>}<th>Objet</th><th>Montant</th><th>État</th><th>Par</th></tr></thead>
      <tbody>{rows.map((p) => (
        <tr key={p.id}>
          <td>{new Date(p.createdAt).toLocaleString("fr-FR")}</td>
          {showTenant && <td>{p.tenant}</td>}
          <td>{p.label}{p.requestId ? <small className="muted"> · demande n° {p.requestId}</small> : null}</td>
          <td>{money(p.amount, p.currency)} <small className="muted">{p.interval === "month" ? "/ mois" : p.interval === "year" ? "/ an" : ""}</small></td>
          <td><span className={`pill ${p.status === "applied" ? "ok" : p.status === "pending" ? "info" : p.status === "paid" ? "warn" : ""}`}>{p.statusLabel}</span>
            {p.error && <small className="t-crit" style={{ display: "block" }}>{p.error}</small>}
            {p.checkoutUrl && <a href={p.checkoutUrl} target="_blank" rel="noopener noreferrer" style={{ display: "block", fontSize: 12 }}>Reprendre le paiement</a>}</td>
          <td>{p.by}</td>
        </tr>
      ))}</tbody>
    </table></div>
  );
}

/** Retour de Stripe (?payment=success&session_id=… ou ?payment=cancelled) : confirme et affiche le résultat. */
export function PaymentReturn({ onDone }: { onDone?: () => void }) {
  const params = new URLSearchParams(window.location.search);
  const state = params.get("payment");
  const sid = params.get("session_id");
  const [msg, setMsg] = useState<{ tone: "ok" | "warn" | "info"; text: string } | null>(
    state === "cancelled" ? { tone: "info", text: "Paiement annulé : aucun montant n’a été débité." } : state === "success" ? { tone: "info", text: "Confirmation du paiement en cours…" } : null,
  );
  useEffect(() => {
    if (!state) return;
    const clean = () => window.history.replaceState(null, "", window.location.pathname + window.location.hash);
    if (state !== "success" || !sid) {
      clean();
      return;
    }
    api.post<PaymentRow>("/payments/confirm", { sessionId: sid }).then(
      (p) => {
        setMsg(p.status === "applied"
          ? { tone: "ok", text: `Paiement reçu : ${p.label}. Votre abonnement est à jour.` }
          : p.status === "paid"
            ? { tone: "warn", text: `Paiement reçu (${p.label}) ; l’activation demande une intervention du Pilote${p.error ? ` : ${p.error}` : ""}.` }
            : { tone: "info", text: "Paiement en cours de confirmation par Stripe. Actualisez dans quelques instants." });
        clean();
        onDone?.();
      },
      (e) => {
        setMsg({ tone: "warn", text: e instanceof ApiError ? e.message : "Confirmation du paiement impossible." });
        clean();
      },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  if (!msg) return null;
  return (
    <div className={`callout ${msg.tone}`} role="status" style={{ marginBottom: 12, display: "flex", justifyContent: "space-between", gap: 10 }}>
      <span>{msg.text}</span>
      <button type="button" className="btn ghost sm" onClick={() => setMsg(null)}>×</button>
    </div>
  );
}
