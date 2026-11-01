import { useState } from "react";

import { platformApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, fmtDate, Loading, Modal, Pill, useAction } from "../../components/ui";
import type { LicenseRequest } from "../../types/api";
import { REQUEST_LABEL, REQUEST_TONE } from "../licensing/labels";
import { RequestView } from "../licensing/RequestView";

const FILTERS: [string, string][] = [
  ["", "Toutes"],
  ["SUBMITTED", "Soumises"],
  ["UNDER_REVIEW", "En cours d'examen"],
  ["ADDITIONAL_INFORMATION_REQUIRED", "Informations demandées"],
  ["APPROVED", "Approuvées (à exécuter)"],
  ["PARTIALLY_APPROVED", "Approuvées partiellement (à exécuter)"],
  ["FULFILLED", "Réalisées"],
  ["REJECTED", "Refusées"],
];

function Decide({ id, onClose, onChanged }: { id: number; onClose: () => void; onChanged: () => void }) {
  const req = useApi(() => platformApi.request(id), [id]);
  const { run, busy } = useAction();
  const [form, setForm] = useState({ status: "UNDER_REVIEW", quantity: "", comment: "" });
  const act = (action: "decide" | "fulfil" | "comment", body: object, msg: string) =>
    run(() => platformApi.requestAction(id, action, body), msg).then(
      (r) => {
        if (r) req.setData(r);
        setForm({ ...form, comment: "" });
        onChanged();
      },
      () => undefined,
    );
  const r: LicenseRequest | null = req.data;
  const decidable = r && ["SUBMITTED", "UNDER_REVIEW"].includes(r.status);
  const executable = r && ["APPROVED", "PARTIALLY_APPROVED"].includes(r.status);
  return (
    <Modal title={r ? `Demande n° ${r.id} · ${r.tenant.name}` : "Demande"} onClose={onClose} wide>
      {req.error ? (
        <ErrorNotice error={req.error} />
      ) : !r ? (
        <Loading />
      ) : (
        <RequestView request={r}>
          {decidable && (
            <Card
              title="Décision du Pilote"
              sub="Une demande approuvée n'est réalisée qu'après son exécution (attribution effective)."
            >
              <div className="frow">
                <Field id="d-s" label="Décision">
                  <select
                    id="d-s"
                    className="inp"
                    value={form.status}
                    onChange={(e) => setForm({ ...form, status: e.target.value })}
                  >
                    <option value="UNDER_REVIEW">Prendre en examen</option>
                    <option value="ADDITIONAL_INFORMATION_REQUIRED">Demander des informations</option>
                    <option value="APPROVED">Approuver</option>
                    <option value="PARTIALLY_APPROVED">Approuver partiellement</option>
                    <option value="REJECTED">Refuser</option>
                  </select>
                </Field>
                {form.status === "PARTIALLY_APPROVED" && (
                  <Field id="d-q" label="Quantité accordée">
                    <input
                      id="d-q"
                      className="inp num"
                      type="number"
                      min={1}
                      value={form.quantity}
                      onChange={(e) => setForm({ ...form, quantity: e.target.value })}
                    />
                  </Field>
                )}
              </div>
              <Field id="d-c" label="Commentaire (obligatoire pour un refus ou une demande d'informations)">
                <textarea
                  id="d-c"
                  className="inp"
                  rows={2}
                  value={form.comment}
                  onChange={(e) => setForm({ ...form, comment: e.target.value })}
                />
              </Field>
              <button
                className="btn primary"
                disabled={busy}
                onClick={() =>
                  act(
                    "decide",
                    {
                      status: form.status,
                      quantityGranted: form.quantity ? Number(form.quantity) : null,
                      comment: form.comment,
                    },
                    "Décision enregistrée",
                  )
                }
              >
                Enregistrer la décision
              </button>
            </Card>
          )}
          {executable && (
            <Card
              title="Exécution"
              sub={
                ["named", "concurrent"].includes(r.kind)
                  ? `Ajoute ${r.quantityGranted} licence(s) au stock de l'entreprise.`
                  : "Décrivez l'opération réalisée (nouvel abonnement, nouvelle version d'offre…)."
              }
            >
              <Field id="f-c" label="Commentaire">
                <textarea
                  id="f-c"
                  className="inp"
                  rows={2}
                  value={form.comment}
                  onChange={(e) => setForm({ ...form, comment: e.target.value })}
                />
              </Field>
              <button
                className="btn primary"
                disabled={busy}
                onClick={() => act("fulfil", { comment: form.comment }, "Demande exécutée")}
              >
                Exécuter l'attribution
              </button>
            </Card>
          )}
          {!decidable && !executable && (
            <div className="frow">
              <input
                className="inp"
                aria-label="Commentaire"
                placeholder="Ajouter un commentaire"
                value={form.comment}
                onChange={(e) => setForm({ ...form, comment: e.target.value })}
              />
              <button
                className="btn"
                disabled={busy || !form.comment}
                onClick={() => act("comment", { comment: form.comment }, "Commentaire ajouté")}
              >
                Commenter
              </button>
            </div>
          )}
        </RequestView>
      )}
    </Modal>
  );
}

export function RequestsTab() {
  const [status, setStatus] = useState("");
  const list = useApi(() => platformApi.requests(status), [status]);
  const [open, setOpen] = useState<number | null>(null);
  return (
    <Card
      title="Demandes des entreprises"
      sub="Licences supplémentaires, quotas, évolutions d'offre et options."
      extra={
        <select
          className="inp"
          aria-label="Filtrer les demandes"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          {FILTERS.map(([k, l]) => (
            <option key={k} value={k}>
              {l}
            </option>
          ))}
        </select>
      }
    >
      {list.error ? (
        <ErrorNotice error={list.error} onRetry={list.reload} />
      ) : !list.data ? (
        <Loading />
      ) : list.data.length === 0 ? (
        <p className="muted">Aucune demande.</p>
      ) : (
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>N°</th>
                <th>Entreprise</th>
                <th>Objet</th>
                <th className="num">Quantité</th>
                <th>Statut</th>
                <th>Soumise le</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.data.map((r) => (
                <tr key={r.id}>
                  <td className="mono">{r.id}</td>
                  <td>{r.tenant.name}</td>
                  <td>{r.kindLabel}</td>
                  <td className="num">{r.quantity ?? "—"}</td>
                  <td>
                    <Pill tone={REQUEST_TONE[r.status]}>{REQUEST_LABEL[r.status]}</Pill>
                  </td>
                  <td className="muted">{fmtDate(r.submittedAt)}</td>
                  <td>
                    <button className="btn sm" onClick={() => setOpen(r.id)}>
                      Traiter
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {open !== null && <Decide id={open} onClose={() => setOpen(null)} onChanged={list.reload} />}
    </Card>
  );
}
