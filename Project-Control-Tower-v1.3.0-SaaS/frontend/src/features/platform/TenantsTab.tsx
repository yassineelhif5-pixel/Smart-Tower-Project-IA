import { useState } from "react";

import { ApiError } from "../../api/client";
import { platformApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, fmtDate, Loading, Modal, OneTimeSecret, Pill, useAction } from "../../components/ui";
import type { CreatedTenant, Offer, TenantRow } from "../../types/api";
import { fmtDay, KIND_LABEL, REQUEST_LABEL, REQUEST_TONE, SUB_TONE, TENANT_TONE } from "../licensing/labels";

const STATUSES: [string, string][] = [
  ["", "Tous les statuts"],
  ["active", "Actif"],
  ["suspended", "Suspendu"],
  ["disabled", "Désactivé"],
  ["archived", "Archivé"],
];

function publishedVersions(offers: Offer[] | null) {
  return (offers ?? [])
    .filter((o) => o.isActive && o.currentVersion)
    .map((o) => ({ offer: o, version: o.currentVersion! }));
}

function CreateTenant({
  offers,
  onClose,
  onCreated,
}: {
  offers: Offer[] | null;
  onClose: () => void;
  onCreated: () => void;
}) {
  const { run, busy } = useAction();
  const [form, setForm] = useState({
    name: "",
    adminUsername: "",
    adminEmail: "",
    offerVersion: "",
    contractReference: "",
    endDate: "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [created, setCreated] = useState<CreatedTenant | null>(null);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const submit = () =>
    run(
      () =>
        platformApi.createTenant({
          name: form.name,
          adminUsername: form.adminUsername,
          adminEmail: form.adminEmail,
          offerVersion: form.offerVersion ? Number(form.offerVersion) : null,
          contractReference: form.contractReference,
          endDate: form.endDate || null,
        }),
      "Entreprise créée",
    ).then(
      (t) => {
        if (t) {
          setCreated(t);
          onCreated();
        }
      },
      (e: unknown) => e instanceof ApiError && setErrors(e.fieldErrors()),
    );
  if (created)
    return (
      <Modal
        title={`Entreprise ${created.name} créée`}
        onClose={onClose}
        footer={
          <button className="btn primary" onClick={onClose}>
            Fermer
          </button>
        }
      >
        <p>
          Premier administrateur : <b className="mono">{created.admin.username}</b>. Transmettez-lui ce mot de passe
          provisoire par un canal sûr ; il devra le changer à la première connexion.
        </p>
        <OneTimeSecret label="Mot de passe provisoire." value={created.temporaryPassword} />
      </Modal>
    );
  return (
    <Modal
      title="Nouvelle entreprise"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>
            Annuler
          </button>
          <button className="btn primary" disabled={busy || !form.name || !form.adminUsername} onClick={submit}>
            Créer l'entreprise
          </button>
        </>
      }
    >
      <div className="frow">
        <Field id="t-name" label="Nom de l'entreprise" error={errors.name}>
          <input id="t-name" className="inp" value={form.name} onChange={set("name")} />
        </Field>
        <Field id="t-offer" label="Offre" hint="Sans offre : l'entreprise n'est pas soumise aux licences.">
          <select id="t-offer" className="inp" value={form.offerVersion} onChange={set("offerVersion")}>
            <option value="">Aucune pour l'instant</option>
            {publishedVersions(offers).map(({ offer, version }) => (
              <option key={version.id} value={version.id}>
                {offer.name} v{version.number} · {version.namedLicenses} nominatives, {version.concurrentLicenses}{" "}
                concurrentes
              </option>
            ))}
          </select>
        </Field>
      </div>
      <div className="frow">
        <Field id="t-admin" label="Identifiant du premier administrateur" error={errors.adminUsername}>
          <input id="t-admin" className="inp mono" value={form.adminUsername} onChange={set("adminUsername")} />
        </Field>
        <Field id="t-mail" label="E-mail de l'administrateur" error={errors.adminEmail}>
          <input id="t-mail" className="inp" type="email" value={form.adminEmail} onChange={set("adminEmail")} />
        </Field>
      </div>
      {form.offerVersion && (
        <div className="frow">
          <Field id="t-ref" label="Référence du contrat (facultatif)">
            <input id="t-ref" className="inp mono" value={form.contractReference} onChange={set("contractReference")} />
          </Field>
          <Field id="t-end" label="Fin d'abonnement" hint="Vide : durée par défaut de l'offre.">
            <input id="t-end" className="inp" type="date" value={form.endDate} onChange={set("endDate")} />
          </Field>
        </div>
      )}
    </Modal>
  );
}

function TenantDetail({
  id,
  offers,
  onClose,
  onChanged,
}: {
  id: number;
  offers: Offer[] | null;
  onClose: () => void;
  onChanged: () => void;
}) {
  const tenant = useApi(() => platformApi.tenant(id), [id]);
  const sub = useApi(() => platformApi.subscription(id), [id]);
  const requests = useApi(() => platformApi.requests(), [id]);
  const audit = useApi(() => platformApi.audit(id), [id]);
  const { run, busy } = useAction();
  const [status, setStatus] = useState({ value: "", reason: "" });
  const [newSub, setNewSub] = useState({ version: "", endDate: "", contractReference: "" });
  const [subChange, setSubChange] = useState({ status: "", endDate: "", reason: "" });
  const [stock, setStock] = useState({ kind: "named", delta: "", reason: "" });
  const refresh = () => {
    tenant.reload();
    sub.reload();
    audit.reload();
    onChanged();
  };
  if (tenant.error)
    return (
      <Modal title="Entreprise" onClose={onClose}>
        <ErrorNotice error={tenant.error} />
      </Modal>
    );
  const t = tenant.data;
  const s = sub.data;
  return (
    <Modal title={t ? `${t.name} · ${t.slug}` : "Entreprise"} onClose={onClose} wide>
      {!t || !s ? (
        <Loading />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="kpis">
            <div className="kpi">
              <label>Statut</label>
              <strong>
                <Pill tone={TENANT_TONE[t.status]}>{t.statusLabel}</Pill>
              </strong>
              {t.statusReason && <small>{t.statusReason}</small>}
            </div>
            <div className="kpi">
              <label>Utilisateurs actifs</label>
              <strong>{s.users.active}</strong>
              <small>{s.users.max ? `sur ${s.users.max} autorisés` : "sans limite"}</small>
            </div>
            <div className="kpi">
              <label>Nominatives</label>
              <strong>
                {s.stock.named.used}/{s.stock.named.total}
              </strong>
              <small>{s.stock.named.available} disponible(s)</small>
            </div>
            <div className="kpi">
              <label>Concurrentes</label>
              <strong>
                {s.stock.concurrent.used}/{s.stock.concurrent.total}
              </strong>
              <small>{s.activeSessions} session(s) active(s)</small>
            </div>
          </div>

          <Card
            title="Accès de l'entreprise"
            sub="Suspendre bloque immédiatement tous ses utilisateurs ; aucune donnée n'est supprimée."
          >
            <div className="frow">
              <Field id="st" label="Nouveau statut">
                <select
                  id="st"
                  className="inp"
                  value={status.value}
                  onChange={(e) => setStatus({ ...status, value: e.target.value })}
                >
                  <option value="">—</option>
                  {STATUSES.slice(1).map(([k, l]) => (
                    <option key={k} value={k}>
                      {l}
                    </option>
                  ))}
                </select>
              </Field>
              <Field id="st-r" label="Motif (obligatoire sauf réactivation)">
                <input
                  id="st-r"
                  className="inp"
                  value={status.reason}
                  onChange={(e) => setStatus({ ...status, reason: e.target.value })}
                />
              </Field>
            </div>
            <button
              className="btn"
              disabled={busy || !status.value}
              onClick={() =>
                run(
                  () => platformApi.updateTenant(id, { status: status.value, reason: status.reason }),
                  "Statut modifié",
                ).then(refresh, () => undefined)
              }
            >
              Appliquer
            </button>
          </Card>

          <Card
            title="Abonnement"
            sub={
              s.enforced
                ? "Contrat, offre et période."
                : "Aucun abonnement : l'entreprise n'est pas soumise aux licences."
            }
          >
            {s.subscription ? (
              <>
                <p>
                  <b>
                    {s.subscription.offer.name} v{s.subscription.version.number}
                  </b>{" "}
                  <Pill tone={SUB_TONE[s.subscription.status]}>{s.subscription.statusLabel}</Pill> · du{" "}
                  {fmtDay(s.subscription.startDate)} au{" "}
                  {s.subscription.endDate ? fmtDay(s.subscription.endDate) : "sans terme"}
                  {s.subscription.trialEnd && ` · essai jusqu'au ${fmtDay(s.subscription.trialEnd)}`}
                  {s.subscription.contract && ` · contrat ${s.subscription.contract.reference}`}
                </p>
                <div className="frow">
                  <Field id="sc-s" label="Statut">
                    <select
                      id="sc-s"
                      className="inp"
                      value={subChange.status}
                      onChange={(e) => setSubChange({ ...subChange, status: e.target.value })}
                    >
                      <option value="">Inchangé</option>
                      <option value="active">Actif</option>
                      <option value="suspended">Suspendu</option>
                      <option value="cancelled">Résilié</option>
                    </select>
                  </Field>
                  <Field id="sc-e" label="Nouvelle échéance">
                    <input
                      id="sc-e"
                      className="inp"
                      type="date"
                      value={subChange.endDate}
                      onChange={(e) => setSubChange({ ...subChange, endDate: e.target.value })}
                    />
                  </Field>
                  <Field id="sc-r" label="Motif">
                    <input
                      id="sc-r"
                      className="inp"
                      value={subChange.reason}
                      onChange={(e) => setSubChange({ ...subChange, reason: e.target.value })}
                    />
                  </Field>
                </div>
                <button
                  className="btn"
                  disabled={busy || (!subChange.status && !subChange.endDate)}
                  onClick={() =>
                    run(
                      () =>
                        platformApi.changeSubscription(id, {
                          ...(subChange.status ? { status: subChange.status } : {}),
                          ...(subChange.endDate ? { endDate: subChange.endDate } : {}),
                          reason: subChange.reason,
                        }),
                      "Abonnement modifié",
                    ).then(refresh, () => undefined)
                  }
                >
                  Modifier l'abonnement
                </button>
              </>
            ) : (
              <>
                <div className="frow">
                  <Field id="ns-v" label="Offre">
                    <select
                      id="ns-v"
                      className="inp"
                      value={newSub.version}
                      onChange={(e) => setNewSub({ ...newSub, version: e.target.value })}
                    >
                      <option value="">Choisir…</option>
                      {publishedVersions(offers).map(({ offer, version }) => (
                        <option key={version.id} value={version.id}>
                          {offer.name} v{version.number}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field id="ns-e" label="Fin" hint="Vide : durée par défaut de l'offre.">
                    <input
                      id="ns-e"
                      className="inp"
                      type="date"
                      value={newSub.endDate}
                      onChange={(e) => setNewSub({ ...newSub, endDate: e.target.value })}
                    />
                  </Field>
                  <Field id="ns-c" label="Référence du contrat">
                    <input
                      id="ns-c"
                      className="inp mono"
                      value={newSub.contractReference}
                      onChange={(e) => setNewSub({ ...newSub, contractReference: e.target.value })}
                    />
                  </Field>
                </div>
                <button
                  className="btn primary"
                  disabled={busy || !newSub.version}
                  onClick={() =>
                    run(
                      () =>
                        platformApi.subscribe(id, {
                          version: Number(newSub.version),
                          endDate: newSub.endDate || null,
                          contractReference: newSub.contractReference,
                        }),
                      "Abonnement créé",
                    ).then(refresh, () => undefined)
                  }
                >
                  Souscrire
                </button>
              </>
            )}
          </Card>

          <Card
            title="Stock de licences"
            sub="Ajouter (+) ou retirer (−). Seules des licences libres peuvent être retirées."
          >
            <div className="frow">
              <Field id="sk-k" label="Type">
                <select
                  id="sk-k"
                  className="inp"
                  value={stock.kind}
                  onChange={(e) => setStock({ ...stock, kind: e.target.value })}
                >
                  <option value="named">Nominatives</option>
                  <option value="concurrent">Concurrentes</option>
                </select>
              </Field>
              <Field id="sk-d" label="Quantité (+ ou −)">
                <input
                  id="sk-d"
                  className="inp num"
                  type="number"
                  value={stock.delta}
                  onChange={(e) => setStock({ ...stock, delta: e.target.value })}
                />
              </Field>
              <Field id="sk-r" label="Motif">
                <input
                  id="sk-r"
                  className="inp"
                  value={stock.reason}
                  onChange={(e) => setStock({ ...stock, reason: e.target.value })}
                />
              </Field>
            </div>
            <button
              className="btn"
              disabled={busy || !Number(stock.delta) || !stock.reason}
              onClick={() =>
                run(
                  () =>
                    platformApi.allocate(id, { kind: stock.kind, delta: Number(stock.delta), reason: stock.reason }),
                  "Stock ajusté",
                ).then(
                  () => {
                    setStock({ ...stock, delta: "", reason: "" });
                    refresh();
                  },
                  () => undefined,
                )
              }
            >
              Appliquer le mouvement
            </button>
            <div className="tbl-wrap" style={{ marginTop: 12 }}>
              <table className="tbl tight">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Type</th>
                    <th className="num">Mouvement</th>
                    <th>Motif</th>
                    <th>Par</th>
                  </tr>
                </thead>
                <tbody>
                  {s.allocations.map((a, i) => (
                    <tr key={i}>
                      <td className="muted">{fmtDate(a.at)}</td>
                      <td>{KIND_LABEL[a.kind]}</td>
                      <td className="num">{a.delta > 0 ? `+${a.delta}` : a.delta}</td>
                      <td>{a.reason}</td>
                      <td className="mono">{a.by ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <div className="grid g2">
            <Card
              title="Utilisateurs"
              sub="Identité et rôle seulement : le Pilote ne voit pas les données privées de l'entreprise."
            >
              <table className="tbl tight">
                <tbody>
                  {t.userList.map((u) => (
                    <tr key={u.id}>
                      <td className="mono">{u.username}</td>
                      <td>{u.role}</td>
                      <td>{u.isActive ? <Pill tone="ok">Actif</Pill> : <Pill tone="">Désactivé</Pill>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
            <Card title="Demandes">
              {(requests.data ?? []).filter((r) => r.tenant.id === id).length === 0 ? (
                <p className="muted">Aucune demande.</p>
              ) : (
                <table className="tbl tight">
                  <tbody>
                    {(requests.data ?? [])
                      .filter((r) => r.tenant.id === id)
                      .map((r) => (
                        <tr key={r.id}>
                          <td className="mono">n° {r.id}</td>
                          <td>{r.kindLabel}</td>
                          <td>
                            <Pill tone={REQUEST_TONE[r.status]}>{REQUEST_LABEL[r.status]}</Pill>
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              )}
            </Card>
          </div>

          <Card title="Historique administratif">
            <div className="tbl-wrap">
              <table className="tbl tight">
                <tbody>
                  {(audit.data ?? []).slice(0, 30).map((r) => (
                    <tr key={r.trace + r.at}>
                      <td className="muted" style={{ whiteSpace: "nowrap" }}>
                        {fmtDate(r.at)}
                      </td>
                      <td className="mono">{r.actor ?? "—"}</td>
                      <td>{r.entity}</td>
                      <td>
                        <b>{r.event}</b>
                      </td>
                      <td className="muted">{[r.old, r.new].filter(Boolean).join(" → ") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}
    </Modal>
  );
}

export function TenantsTab() {
  const [filter, setFilter] = useState({ q: "", status: "" });
  const tenants = useApi(() => platformApi.tenants(filter.q, filter.status), [filter.q, filter.status]);
  const offers = useApi(platformApi.offers);
  const [creating, setCreating] = useState(false);
  const [open, setOpen] = useState<TenantRow | null>(null);
  return (
    <Card
      title="Entreprises clientes"
      sub="Un tenant par entreprise : données, comptes et réglages totalement isolés."
      extra={
        <button className="btn primary sm" onClick={() => setCreating(true)}>
          Nouvelle entreprise
        </button>
      }
    >
      <div className="frow" style={{ marginBottom: 12 }}>
        <input
          className="inp"
          placeholder="Rechercher (nom ou identifiant)"
          aria-label="Rechercher une entreprise"
          value={filter.q}
          onChange={(e) => setFilter({ ...filter, q: e.target.value })}
        />
        <select
          className="inp"
          aria-label="Filtrer par statut"
          value={filter.status}
          onChange={(e) => setFilter({ ...filter, status: e.target.value })}
        >
          {STATUSES.map(([k, l]) => (
            <option key={k} value={k}>
              {l}
            </option>
          ))}
        </select>
      </div>
      {tenants.error ? (
        <ErrorNotice error={tenants.error} onRetry={tenants.reload} />
      ) : !tenants.data ? (
        <Loading />
      ) : (
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>Entreprise</th>
                <th>Statut</th>
                <th className="num">Utilisateurs actifs</th>
                <th>Créée le</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {tenants.data.map((t) => (
                <tr key={t.id}>
                  <td>
                    <b>{t.name}</b>
                    <div className="muted mono" style={{ fontSize: 11 }}>
                      {t.slug}
                    </div>
                  </td>
                  <td>
                    <Pill tone={TENANT_TONE[t.status]}>{t.statusLabel}</Pill>
                  </td>
                  <td className="num">{t.activeUsers}</td>
                  <td className="muted">{fmtDay(t.createdAt)}</td>
                  <td>
                    <button className="btn sm" onClick={() => setOpen(t)}>
                      Gérer
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {creating && <CreateTenant offers={offers.data} onClose={() => setCreating(false)} onCreated={tenants.reload} />}
      {open && (
        <TenantDetail id={open.id} offers={offers.data} onClose={() => setOpen(null)} onChanged={tenants.reload} />
      )}
    </Card>
  );
}
