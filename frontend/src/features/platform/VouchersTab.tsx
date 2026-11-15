import { useState } from "react";

import { platformApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, Loading, Modal, useAction } from "../../components/ui";
import type { Offer, VoucherIssueResult } from "../../types/api";
import { fmtDate } from "../../components/ui";
import { MODULE_GROUPS, ModuleChoices } from "./OffersTab";

const availableVersions = (offers: Offer[] | null) =>
  (offers ?? []).flatMap((offer) =>
    offer.isActive ? offer.versions.filter((version) => version.isPublished).map((version) => ({ offer, version })) : [],
  );

export function VouchersTab() {
  const offers = useApi(platformApi.offers);
  const tenants = useApi(() => platformApi.tenants());
  const batches = useApi(platformApi.voucherBatches);
  const { run, busy } = useAction();
  const [open, setOpen] = useState(false);
  const [issued, setIssued] = useState<VoucherIssueResult | null>(null);
  const [form, setForm] = useState({ version: "", tenant: "", clientEmail: "", quantity: "1", expiresAt: "", restrictModules: false, features: "" });
  const versions = availableVersions(offers.data ?? null);
  const chosen = versions.find(({ version }) => version.id === Number(form.version))?.version;
  const allowedCodes = chosen?.features.length ? chosen.features : MODULE_GROUPS.flatMap((group) => group.items.map(([code]) => code));
  const submit = () =>
    run(
      () =>
        platformApi.createVouchers({
          version: Number(form.version),
          targetTenant: Number(form.tenant),
          quantity: Number(form.quantity),
          expiresAt: form.expiresAt ? new Date(form.expiresAt).toISOString() : null,
          ...(form.clientEmail.trim() ? { clientEmail: form.clientEmail.trim() } : {}),
          ...(form.restrictModules ? { features: form.features ? form.features.split(",").map((item) => item.trim()).filter(Boolean) : allowedCodes } : {}),
        }),
      "Vouchers générés",
    ).then(
      (result) => {
        if (result) {
          setIssued(result);
          batches.reload();
        }
      },
      () => undefined,
    );
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Card
        title="Vouchers d’activation"
        sub="Générez des codes à usage unique liés à un client et à une version publiée. Les codes ne sont affichés qu’à leur création."
        extra={<button className="btn primary sm" onClick={() => setOpen(true)}>Générer un lot</button>}
      >
        {versions.length === 0 && <div className="notice warn" role="status" style={{ marginBottom: 12 }}>
          Aucune offre publiée et active n’est actuellement sélectionnable. Publiez une version dans « Offres » et activez son offre ; ses modules pourront ensuite être limités lors de la génération du voucher.
        </div>}
        {batches.error ? <ErrorNotice error={batches.error} onRetry={batches.reload} /> : !batches.data ? <Loading /> :
          batches.data.length === 0 ? <p className="muted">Aucun lot de vouchers créé.</p> : (
            <div className="tbl-wrap">
              <table className="tbl">
                <thead><tr><th>Lot</th><th>Client</th><th>Offre</th><th>Codes</th><th>Créé le</th><th>Expiration</th><th>Créé par</th></tr></thead>
                <tbody>{batches.data.map((batch) => (
                  <tr key={batch.batchId}>
                    <td className="mono">{batch.batchId.slice(0, 8)}</td>
                    <td>{batch.tenant}</td>
                    <td>{batch.offer} v{batch.version}</td>
                    <td>{batch.redeemed}/{batch.total} utilisés · {batch.installed} installés{batch.revoked ? ` · ${batch.revoked} révoqués` : ""}</td>
                    <td className="muted">{fmtDate(batch.createdAt)}</td>
                    <td className="muted">{batch.expiresAt ? fmtDate(batch.expiresAt) : "Sans expiration"}</td>
                    <td className="mono">{batch.createdBy ?? "—"}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
      </Card>
      {open && !issued && (
        <Modal title="Générer des vouchers" onClose={() => setOpen(false)} footer={
          <><button className="btn" onClick={() => setOpen(false)}>Annuler</button>
            <button className="btn primary" disabled={busy || !form.version || !form.tenant || !Number(form.quantity)} onClick={submit}>Générer</button></>
        }>
          <div className="frow">
            <Field id="voucher-version" label="Offre publiée">
              <select id="voucher-version" className="inp" value={form.version} onChange={(e) => setForm({ ...form, version: e.target.value, restrictModules: false, features: "" })}>
                <option value="">Choisir…</option>
                {versions.map(({ offer, version }) => <option key={version.id} value={version.id}>{offer.name} v{version.number} · {version.namedLicenses} nominatives, {version.concurrentLicenses} concurrentes</option>)}
              </select>
            </Field>
            <Field id="voucher-tenant" label="Client destinataire">
              <select id="voucher-tenant" className="inp" value={form.tenant} onChange={(e) => setForm({ ...form, tenant: e.target.value })}>
                <option value="">Choisir…</option>
                {(tenants.data ?? []).filter((tenant) => tenant.status === "active").map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}
              </select>
            </Field>
          <Field id="voucher-client-email" label="E-mail du contact client (facultatif)" hint="Le lot sera aussi envoyé aux administrateurs du client ayant une adresse e-mail.">
            <input id="voucher-client-email" className="inp" type="email" value={form.clientEmail} onChange={(e) => setForm({ ...form, clientEmail: e.target.value })} />
          </Field>
          </div>
          <div style={{ margin: "8px 0 14px" }}>
            <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input type="checkbox" checked={form.restrictModules} onChange={(e) => setForm({ ...form, restrictModules: e.target.checked, features: "" })} />
              Limiter les modules activés par ce voucher
            </label>
            {form.restrictModules && <div style={{ marginTop: 12 }}>
              {!chosen && <p className="muted">Sélectionnez les modules maintenant, puis choisissez une offre publiée et active pour générer les codes.</p>}
              <ModuleChoices value={form.features} onChange={(features) => setForm({ ...form, features })} allowedCodes={allowedCodes} />
            </div>}
          </div>
          <div className="frow">
            <Field id="voucher-quantity" label="Nombre de codes">
              <input id="voucher-quantity" className="inp num" type="number" min={1} max={500} value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} />
            </Field>
            <Field id="voucher-expiry" label="Expiration (facultatif)">
              <input id="voucher-expiry" className="inp" type="datetime-local" value={form.expiresAt} onChange={(e) => setForm({ ...form, expiresAt: e.target.value })} />
            </Field>
          </div>
          {tenants.error && <ErrorNotice error={tenants.error} onRetry={tenants.reload} />}
          {offers.error && <ErrorNotice error={offers.error} onRetry={offers.reload} />}
          <p className="muted">Chaque code active directement cette offre pour le client sélectionné, une seule fois. La limitation de modules ne peut retirer que des modules prévus par l’offre.</p>
        </Modal>
      )}
      {open && issued && (
        <Modal title={`Lot créé · ${issued.tenant}`} onClose={() => { setOpen(false); setIssued(null); }} wide footer={
          <button className="btn primary" onClick={() => { setOpen(false); setIssued(null); }}>J’ai conservé les codes</button>
        }>
          <div className="notice">Copiez et transmettez ces codes au client par un canal sûr. Ils ne pourront plus être relus après fermeture.</div>
          <p><b>{issued.offer} v{issued.version}</b> · {issued.codes.length} code(s) · {issued.expiresAt ? `expire ${fmtDate(issued.expiresAt)}` : "sans expiration"}</p>
          <div className={issued.email.sent ? "notice" : "notice warn"} role="status">{issued.email.message}{issued.email.recipients.length > 0 && <div className="muted" style={{ marginTop: 5 }}>{issued.email.recipients.join(" · ")}</div>}</div>
          <p className="muted">Modules activés : {issued.features.length ? issued.features.map((code) => MODULE_GROUPS.flatMap((g) => g.items).find(([id]) => id === code)?.[1] ?? code).join(", ") : "tous les modules de l’offre"}</p>
          <textarea className="inp mono" rows={Math.min(15, issued.codes.length)} readOnly value={issued.codes.join("\n")} aria-label="Codes voucher à conserver" />
        </Modal>
      )}
    </div>
  );
}
