import { useState } from "react";

import { platformApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, Loading, Modal, Pill, Switch, useAction } from "../../components/ui";
import type { Offer, OfferVersion } from "../../types/api";
import { fmtPrice } from "../licensing/labels";

type Draft = {
  price: string;
  currency: string;
  billingPeriod: string;
  durationDays: string;
  trialDays: string;
  licenseModel: string;
  maxUsers: string;
  namedLicenses: string;
  concurrentLicenses: string;
  maxSessionsPerUser: string;
  features: string;
  conditions: string;
  publish: boolean;
};

const toDraft = (v: OfferVersion | null): Draft => ({
  price: v?.price ?? "",
  currency: v?.currency ?? "EUR",
  billingPeriod: v?.billingPeriod ?? "month",
  durationDays: v?.durationDays?.toString() ?? "",
  trialDays: v?.trialDays.toString() ?? "0",
  licenseModel: v?.licenseModel ?? "mixed",
  maxUsers: v?.maxUsers?.toString() ?? "",
  namedLicenses: v?.namedLicenses.toString() ?? "0",
  concurrentLicenses: v?.concurrentLicenses.toString() ?? "0",
  maxSessionsPerUser: v?.maxSessionsPerUser?.toString() ?? "",
  features: (v?.features ?? []).join(", "),
  conditions: v?.conditions ?? "",
  publish: v?.isPublished ?? false,
});

const num = (s: string) => (s.trim() === "" ? null : Number(s));

const toBody = (d: Draft) => ({
  price: d.price.trim() === "" ? null : d.price,
  currency: d.currency,
  billingPeriod: d.billingPeriod as OfferVersion["billingPeriod"],
  durationDays: num(d.durationDays),
  trialDays: Number(d.trialDays || 0),
  licenseModel: d.licenseModel as OfferVersion["licenseModel"],
  maxUsers: num(d.maxUsers),
  namedLicenses: Number(d.namedLicenses || 0),
  concurrentLicenses: Number(d.concurrentLicenses || 0),
  maxSessionsPerUser: num(d.maxSessionsPerUser),
  features: d.features
    .split(",")
    .map((f) => f.trim())
    .filter(Boolean),
  conditions: d.conditions,
  publish: d.publish,
});

/** Édite une version en brouillon, ou crée une nouvelle version à partir de la dernière (prix, quotas…). */
function VersionEditor({
  offer,
  base,
  mode,
  onClose,
  onSaved,
}: {
  offer: Offer;
  base: OfferVersion | null;
  mode: "edit" | "new";
  onClose: () => void;
  onSaved: () => void;
}) {
  const { run, busy } = useAction();
  const [d, setD] = useState<Draft>(toDraft(base));
  const f = (k: keyof Draft) => (e: { target: { value: string } }) => setD({ ...d, [k]: e.target.value });
  const save = () =>
    run(
      () =>
        mode === "edit" && base
          ? platformApi.updateVersion(base.id, toBody(d))
          : platformApi.createVersion(offer.id, toBody(d)),
      mode === "edit" ? "Version enregistrée" : "Nouvelle version créée",
    ).then(
      () => {
        onSaved();
        onClose();
      },
      () => undefined,
    );
  return (
    <Modal
      title={mode === "edit" ? `${offer.name} · version ${base?.number}` : `${offer.name} · nouvelle version`}
      onClose={onClose}
      wide
      footer={
        <>
          <button className="btn" onClick={onClose}>
            Annuler
          </button>
          <button className="btn primary" disabled={busy} onClick={save}>
            Enregistrer
          </button>
        </>
      }
    >
      <div className="notice" style={{ marginBottom: 12 }}>
        Une version publiée ou déjà souscrite n'est plus modifiable : les abonnements en cours gardent leurs conditions.
        Pour changer un prix, créez une nouvelle version.
      </div>
      <div className="frow">
        <Field id="v-price" label="Prix (HT)" hint="Vide : prix à définir.">
          <input id="v-price" className="inp num" value={d.price} onChange={f("price")} />
        </Field>
        <Field id="v-cur" label="Devise">
          <input id="v-cur" className="inp mono" maxLength={3} value={d.currency} onChange={f("currency")} />
        </Field>
        <Field id="v-per" label="Période">
          <select id="v-per" className="inp" value={d.billingPeriod} onChange={f("billingPeriod")}>
            <option value="month">Mensuelle</option>
            <option value="year">Annuelle</option>
            <option value="once">Unique</option>
          </select>
        </Field>
      </div>
      <div className="frow">
        <Field id="v-dur" label="Durée d'abonnement (jours)" hint="Vide : sans terme.">
          <input id="v-dur" className="inp num" value={d.durationDays} onChange={f("durationDays")} />
        </Field>
        <Field id="v-trial" label="Période d'essai (jours)">
          <input id="v-trial" className="inp num" value={d.trialDays} onChange={f("trialDays")} />
        </Field>
        <Field id="v-model" label="Modèle de licences">
          <select id="v-model" className="inp" value={d.licenseModel} onChange={f("licenseModel")}>
            <option value="named">Nominatives</option>
            <option value="concurrent">Concurrentes</option>
            <option value="mixed">Nominatives et concurrentes</option>
          </select>
        </Field>
      </div>
      <div className="frow">
        <Field id="v-users" label="Utilisateurs actifs max" hint="Vide : illimité.">
          <input id="v-users" className="inp num" value={d.maxUsers} onChange={f("maxUsers")} />
        </Field>
        <Field id="v-named" label="Licences nominatives incluses">
          <input id="v-named" className="inp num" value={d.namedLicenses} onChange={f("namedLicenses")} />
        </Field>
        <Field id="v-conc" label="Licences concurrentes incluses">
          <input id="v-conc" className="inp num" value={d.concurrentLicenses} onChange={f("concurrentLicenses")} />
        </Field>
        <Field id="v-sess" label="Connexions simultanées par utilisateur" hint="Vide : illimité.">
          <input id="v-sess" className="inp num" value={d.maxSessionsPerUser} onChange={f("maxSessionsPerUser")} />
        </Field>
      </div>
      <Field
        id="v-feat"
        label="Fonctionnalités incluses"
        hint="Codes séparés par des virgules (project, planning, action, budget, resource, document, test, risk, report, delegation…). Vide : toutes."
      >
        <input id="v-feat" className="inp mono" value={d.features} onChange={f("features")} />
      </Field>
      <Field id="v-cond" label="Conditions">
        <textarea id="v-cond" className="inp" rows={3} value={d.conditions} onChange={f("conditions")} />
      </Field>
      <label style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
        <Switch
          checked={d.publish}
          onChange={(v) => setD({ ...d, publish: v })}
          label="Publier"
          disabled={mode === "edit" && base?.isPublished}
        />
        Publier (souscriptible par les entreprises)
      </label>
    </Modal>
  );
}

export function OffersTab() {
  const offers = useApi(platformApi.offers);
  const { run, busy } = useAction();
  const [editing, setEditing] = useState<{ offer: Offer; base: OfferVersion | null; mode: "edit" | "new" } | null>(
    null,
  );
  const [creating, setCreating] = useState({ open: false, code: "", name: "", description: "" });
  if (offers.error) return <ErrorNotice error={offers.error} onRetry={offers.reload} />;
  if (!offers.data) return <Loading />;
  return (
    <Card
      title="Offres commerciales"
      sub="Prix, durées, quotas et fonctionnalités sont des données modifiables, jamais écrites dans le code."
      extra={
        <button className="btn primary sm" onClick={() => setCreating({ ...creating, open: true })}>
          Nouvelle offre
        </button>
      }
    >
      <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th>Offre</th>
              <th>Version publiée</th>
              <th>Prix</th>
              <th className="num">Utilisateurs</th>
              <th className="num">Nominatives</th>
              <th className="num">Concurrentes</th>
              <th>Active</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {offers.data.map((o) => {
              const v = o.currentVersion;
              const draft = o.versions.find((x) => !x.isPublished && !x.inUse);
              return (
                <tr key={o.id}>
                  <td>
                    <b>{o.name}</b>
                    <div className="muted" style={{ fontSize: 12 }}>
                      {o.description}
                    </div>
                  </td>
                  <td>{v ? `v${v.number}` : <Pill tone="warn">Aucune</Pill>}</td>
                  <td>{v ? fmtPrice(v.price, v.currency, v.billingPeriod) : "—"}</td>
                  <td className="num">{v ? (v.maxUsers ?? "illimité") : "—"}</td>
                  <td className="num">{v?.namedLicenses ?? "—"}</td>
                  <td className="num">{v?.concurrentLicenses ?? "—"}</td>
                  <td>
                    <Switch
                      checked={o.isActive}
                      label={`Offre ${o.name} active`}
                      disabled={busy}
                      onChange={(value) =>
                        run(
                          () => platformApi.updateOffer(o.id, { isActive: value }),
                          value ? "Offre activée" : "Offre désactivée",
                        ).then(offers.reload, () => undefined)
                      }
                    />
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    {draft && (
                      <button className="btn sm" onClick={() => setEditing({ offer: o, base: draft, mode: "edit" })}>
                        Brouillon v{draft.number}
                      </button>
                    )}{" "}
                    <button
                      className="btn sm"
                      onClick={() => setEditing({ offer: o, base: o.versions[0] ?? null, mode: "new" })}
                    >
                      Nouvelle version
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {editing && <VersionEditor {...editing} onClose={() => setEditing(null)} onSaved={offers.reload} />}
      {creating.open && (
        <Modal
          title="Nouvelle offre"
          onClose={() => setCreating({ ...creating, open: false })}
          footer={
            <button
              className="btn primary"
              disabled={busy || !creating.code || !creating.name}
              onClick={() =>
                run(
                  () =>
                    platformApi.createOffer({
                      code: creating.code,
                      name: creating.name,
                      description: creating.description,
                    }),
                  "Offre créée",
                ).then(
                  () => {
                    setCreating({ open: false, code: "", name: "", description: "" });
                    offers.reload();
                  },
                  () => undefined,
                )
              }
            >
              Créer
            </button>
          }
        >
          <div className="frow">
            <Field id="o-code" label="Code">
              <input
                id="o-code"
                className="inp mono"
                value={creating.code}
                onChange={(e) => setCreating({ ...creating, code: e.target.value })}
              />
            </Field>
            <Field id="o-name" label="Nom">
              <input
                id="o-name"
                className="inp"
                value={creating.name}
                onChange={(e) => setCreating({ ...creating, name: e.target.value })}
              />
            </Field>
          </div>
          <Field id="o-desc" label="Description">
            <input
              id="o-desc"
              className="inp"
              value={creating.description}
              onChange={(e) => setCreating({ ...creating, description: e.target.value })}
            />
          </Field>
          <p className="muted">Ajoutez ensuite une version : prix, quotas, fonctionnalités, puis publiez-la.</p>
        </Modal>
      )}
    </Card>
  );
}
