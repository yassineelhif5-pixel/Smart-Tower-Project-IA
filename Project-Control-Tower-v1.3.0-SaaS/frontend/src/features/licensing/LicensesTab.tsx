import { useState } from "react";

import { licensingApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, fmtDate, Loading, Modal, Pill, useAction } from "../../components/ui";
import type { LicenseRow } from "../../types/api";
import { fmtDay, REQUEST_KINDS, REQUEST_LABEL, REQUEST_TONE, SUB_TONE } from "./labels";
import { RequestView } from "./RequestView";

const can = (caps: string[], code: string) => caps.includes(code);

function Overview() {
  const o = useApi(licensingApi.overview);
  if (o.error) return <ErrorNotice error={o.error} onRetry={o.reload} />;
  if (!o.data) return <Loading />;
  const { subscription: s, stock, users, activeSessions } = o.data;
  if (!o.data.enforced)
    return (
      <div className="callout">
        <div>
          <b>Votre entreprise n'a pas encore d'abonnement.</b>
          <div className="muted">
            Les licences ne s'appliquent pas tant que le Pilote n'a pas souscrit une offre pour vous.
          </div>
        </div>
      </div>
    );
  return (
    <div className="kpis">
      <div className="kpi">
        <label>Offre</label>
        <strong style={{ fontSize: 20 }}>{s ? `${s.offer.name} v${s.version.number}` : "Expirée"}</strong>
        <small>
          {s ? (
            <>
              <Pill tone={SUB_TONE[s.status]}>{s.statusLabel}</Pill> jusqu'au{" "}
              {s.trialEnd ? fmtDay(s.trialEnd) : s.endDate ? fmtDay(s.endDate) : "—"}
            </>
          ) : (
            "Contactez le Pilote"
          )}
        </small>
      </div>
      <div className="kpi">
        <label>Utilisateurs actifs</label>
        <strong>{users.active}</strong>
        <small>{users.max ? `sur ${users.max} autorisés` : "sans limite"}</small>
      </div>
      <div className="kpi">
        <label>Licences nominatives</label>
        <strong>{stock.named.available}</strong>
        <small>
          disponibles sur {stock.named.total} · {stock.named.used} affectée(s)
        </small>
      </div>
      <div className="kpi">
        <label>Licences concurrentes</label>
        <strong>{stock.concurrent.available}</strong>
        <small>
          libres sur {stock.concurrent.total} · {activeSessions} session(s)
        </small>
      </div>
    </div>
  );
}

function Licenses({ caps }: { caps: string[] }) {
  const list = useApi(licensingApi.licenses);
  const { run, busy } = useAction();
  const [target, setTarget] = useState<{ lic: LicenseRow; action: "assign" | "reassign" } | null>(null);
  const [user, setUser] = useState("");
  if (list.error) return <ErrorNotice error={list.error} onRetry={list.reload} />;
  if (!list.data) return <Loading />;
  const named = list.data.licenses.filter((l) => l.kind === "named");
  const concurrent = list.data.licenses.filter((l) => l.kind === "concurrent");
  const act = (
    lic: LicenseRow,
    action: "assign" | "release" | "reassign",
    body: { user?: number; reason?: string },
    msg: string,
  ) =>
    run(() => licensingApi.act(lic.id, action, body), msg).then(
      () => {
        setTarget(null);
        setUser("");
        list.reload();
      },
      () => undefined,
    );
  return (
    <>
      <Card
        title="Licences nominatives"
        sub="Une licence par utilisateur. Une licence libérée retourne dans votre stock ; chaque opération est historisée."
      >
        {named.length === 0 ? (
          <p className="muted">Aucune licence nominative dans votre stock.</p>
        ) : (
          <div className="tbl-wrap">
            <table className="tbl tight">
              <thead>
                <tr>
                  <th>Licence</th>
                  <th>Statut</th>
                  <th>Titulaire</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {named.map((l) => (
                  <tr key={l.id}>
                    <td className="mono">{l.number}</td>
                    <td>
                      <Pill tone={l.holder ? "acc" : "ok"}>{l.statusLabel}</Pill>
                    </td>
                    <td>
                      {l.holder ? (
                        <>
                          <b className="mono">{l.holder.username}</b>{" "}
                          <span className="muted">depuis le {fmtDay(l.holder.since)}</span>
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {!l.holder && can(caps, "licenses.assign") && (
                        <button className="btn sm" onClick={() => setTarget({ lic: l, action: "assign" })}>
                          Affecter
                        </button>
                      )}
                      {l.holder && can(caps, "licenses.release") && (
                        <>
                          <button
                            className="btn sm"
                            disabled={busy}
                            onClick={() => act(l, "release", { reason: "" }, "Licence libérée")}
                          >
                            Libérer
                          </button>{" "}
                          <button className="btn sm" onClick={() => setTarget({ lic: l, action: "reassign" })}>
                            Réaffecter
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card
        title="Licences concurrentes"
        sub="Nombre de connexions simultanées : une licence est occupée le temps d'une session, puis libérée."
      >
        {concurrent.length === 0 ? (
          <p className="muted">Aucune licence concurrente dans votre stock.</p>
        ) : (
          <div className="tbl-wrap">
            <table className="tbl tight">
              <tbody>
                {concurrent.map((l) => (
                  <tr key={l.id}>
                    <td className="mono">{l.number}</td>
                    <td>
                      <Pill tone={l.session ? "acc" : "ok"}>{l.statusLabel}</Pill>
                    </td>
                    <td>
                      {l.session ? (
                        <>
                          <b className="mono">{l.session.user}</b>{" "}
                          <span className="muted">depuis {fmtDate(l.session.since)}</span>
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {target && (
        <Modal
          title={`${target.action === "assign" ? "Affecter" : "Réaffecter"} la licence ${target.lic.number}`}
          onClose={() => setTarget(null)}
          footer={
            <button
              className="btn primary"
              disabled={busy || !user}
              onClick={() =>
                act(
                  target.lic,
                  target.action,
                  { user: Number(user) },
                  target.action === "assign" ? "Licence affectée" : "Licence réaffectée",
                )
              }
            >
              Confirmer
            </button>
          }
        >
          <Field id="lic-u" label="Utilisateur sans licence nominative">
            <select id="lic-u" className="inp" value={user} onChange={(e) => setUser(e.target.value)}>
              <option value="">Choisir…</option>
              {list.data.unlicensedUsers.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name} ({u.username})
                </option>
              ))}
            </select>
          </Field>
        </Modal>
      )}
    </>
  );
}

function Sessions({ caps }: { caps: string[] }) {
  const list = useApi(licensingApi.sessions);
  const { run, busy } = useAction();
  if (!can(caps, "sessions.view")) return null;
  return (
    <Card
      title="Sessions actives"
      sub="Une session inactive se ferme seule et rend sa licence concurrente."
      extra={
        <button className="btn sm" onClick={list.reload}>
          Actualiser
        </button>
      }
    >
      {list.error ? (
        <ErrorNotice error={list.error} onRetry={list.reload} />
      ) : !list.data ? (
        <Loading />
      ) : list.data.length === 0 ? (
        <p className="muted">Aucune session ouverte.</p>
      ) : (
        <div className="tbl-wrap">
          <table className="tbl tight">
            <thead>
              <tr>
                <th>Utilisateur</th>
                <th>Licence</th>
                <th>Ouverte</th>
                <th>Dernière activité</th>
                <th>Expire</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.data.map((s) => (
                <tr key={s.id}>
                  <td className="mono">{s.user.username}</td>
                  <td>
                    {s.mode} {s.license && <span className="mono muted">{s.license}</span>}
                  </td>
                  <td className="muted">{fmtDate(s.startedAt)}</td>
                  <td className="muted">{fmtDate(s.lastSeenAt)}</td>
                  <td className="muted">{fmtDate(s.expiresAt)}</td>
                  <td>
                    {can(caps, "sessions.revoke") && (
                      <button
                        className="btn sm"
                        disabled={busy}
                        onClick={() =>
                          run(() => licensingApi.revokeSession(s.id), "Session révoquée").then(
                            list.reload,
                            () => undefined,
                          )
                        }
                      >
                        Révoquer
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function Requests({ caps }: { caps: string[] }) {
  const list = useApi(licensingApi.requests);
  const offers = useApi(() => (can(caps, "requests.create") ? licensingApi.offers() : Promise.resolve([])));
  const { run, busy } = useAction();
  const [form, setForm] = useState<{
    open: boolean;
    kind: string;
    quantity: string;
    targetOffer: string;
    justification: string;
  }>({
    open: false,
    kind: "named",
    quantity: "",
    targetOffer: "",
    justification: "",
  });
  const [openId, setOpenId] = useState<number | null>(null);
  const detail = useApi(() => (openId ? licensingApi.request(openId) : Promise.resolve(null)), [openId]);
  const [comment, setComment] = useState("");
  if (!can(caps, "requests.view")) return null;
  const withQuantity = ["named", "concurrent", "quota"].includes(form.kind);
  const act = (action: "submit" | "cancel" | "comment", msg: string) =>
    run(() => licensingApi.requestAction(openId!, action, comment), msg).then(
      (r) => {
        if (r) detail.setData(r);
        setComment("");
        list.reload();
      },
      () => undefined,
    );
  return (
    <Card
      title="Demandes au Pilote"
      sub="Licences supplémentaires, quotas, évolution d'offre. Le stock n'augmente qu'après approbation et exécution par le Pilote."
      extra={
        can(caps, "requests.create") && (
          <button className="btn primary sm" onClick={() => setForm({ ...form, open: true })}>
            Nouvelle demande
          </button>
        )
      }
    >
      {list.error ? (
        <ErrorNotice error={list.error} onRetry={list.reload} />
      ) : !list.data ? (
        <Loading />
      ) : list.data.length === 0 ? (
        <p className="muted">Aucune demande.</p>
      ) : (
        <table className="tbl tight">
          <tbody>
            {list.data.map((r) => (
              <tr key={r.id}>
                <td className="mono">n° {r.id}</td>
                <td>{r.kindLabel}</td>
                <td className="num">{r.quantity ?? ""}</td>
                <td>
                  <Pill tone={REQUEST_TONE[r.status]}>{REQUEST_LABEL[r.status]}</Pill>
                </td>
                <td className="muted">{fmtDate(r.createdAt)}</td>
                <td>
                  <button className="btn sm" onClick={() => setOpenId(r.id)}>
                    Ouvrir
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {form.open && (
        <Modal
          title="Nouvelle demande"
          onClose={() => setForm({ ...form, open: false })}
          footer={
            <button
              className="btn primary"
              disabled={
                busy ||
                !form.justification ||
                (withQuantity && !form.quantity) ||
                (form.kind === "offer" && !form.targetOffer)
              }
              onClick={() =>
                run(
                  () =>
                    licensingApi.createRequest({
                      kind: form.kind,
                      quantity: withQuantity ? Number(form.quantity) : null,
                      targetOffer: form.kind === "offer" ? Number(form.targetOffer) : null,
                      justification: form.justification,
                    }),
                  "Demande envoyée au Pilote",
                ).then(
                  () => {
                    setForm({ open: false, kind: "named", quantity: "", targetOffer: "", justification: "" });
                    list.reload();
                  },
                  () => undefined,
                )
              }
            >
              Envoyer
            </button>
          }
        >
          <div className="frow">
            <Field id="rq-k" label="Objet">
              <select
                id="rq-k"
                className="inp"
                value={form.kind}
                onChange={(e) => setForm({ ...form, kind: e.target.value })}
              >
                {REQUEST_KINDS.map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
              </select>
            </Field>
            {withQuantity && (
              <Field id="rq-q" label="Quantité">
                <input
                  id="rq-q"
                  className="inp num"
                  type="number"
                  min={1}
                  value={form.quantity}
                  onChange={(e) => setForm({ ...form, quantity: e.target.value })}
                />
              </Field>
            )}
            {form.kind === "offer" && (
              <Field id="rq-o" label="Offre souhaitée">
                <select
                  id="rq-o"
                  className="inp"
                  value={form.targetOffer}
                  onChange={(e) => setForm({ ...form, targetOffer: e.target.value })}
                >
                  <option value="">Choisir…</option>
                  {(offers.data ?? []).map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.name}
                    </option>
                  ))}
                </select>
              </Field>
            )}
          </div>
          <Field id="rq-j" label="Justification">
            <textarea
              id="rq-j"
              className="inp"
              rows={3}
              value={form.justification}
              onChange={(e) => setForm({ ...form, justification: e.target.value })}
            />
          </Field>
        </Modal>
      )}
      {openId !== null && (
        <Modal title={`Demande n° ${openId}`} onClose={() => setOpenId(null)} wide>
          {!detail.data ? (
            <Loading />
          ) : (
            <RequestView request={detail.data}>
              <Field id="rq-c" label="Commentaire ou réponse au Pilote">
                <textarea
                  id="rq-c"
                  className="inp"
                  rows={2}
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                />
              </Field>
              <div className="btns">
                {["DRAFT", "ADDITIONAL_INFORMATION_REQUIRED"].includes(detail.data.status) && (
                  <button
                    className="btn primary"
                    disabled={busy}
                    onClick={() => act("submit", "Demande renvoyée au Pilote")}
                  >
                    {detail.data.status === "DRAFT" ? "Soumettre" : "Répondre et resoumettre"}
                  </button>
                )}
                <button
                  className="btn"
                  disabled={busy || !comment}
                  onClick={() => act("comment", "Commentaire ajouté")}
                >
                  Commenter
                </button>
                {can(caps, "requests.cancel") &&
                  ["DRAFT", "SUBMITTED", "UNDER_REVIEW", "ADDITIONAL_INFORMATION_REQUIRED"].includes(
                    detail.data.status,
                  ) && (
                    <button className="btn" disabled={busy} onClick={() => act("cancel", "Demande annulée")}>
                      Annuler la demande
                    </button>
                  )}
              </div>
            </RequestView>
          )}
        </Modal>
      )}
    </Card>
  );
}

/** Espace licences de l'entreprise : chaque bloc n'apparaît qu'avec le droit correspondant (vérifié aussi par le serveur). */
export function LicensesTab({ capabilities }: { capabilities: string[] }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {can(capabilities, "licenses.view") && (
        <>
          <Overview />
          <Licenses caps={capabilities} />
        </>
      )}
      <Sessions caps={capabilities} />
      <Requests caps={capabilities} />
    </div>
  );
}
