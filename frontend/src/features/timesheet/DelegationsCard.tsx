import { useState } from "react";

import { timeApi } from "../../api/endpoints";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, Loading, useAction } from "../../components/ui";
import type { Me } from "../../types/api";

const STATE = { active: "En cours", future: "À venir", past: "Terminée" } as const;

function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
const frDate = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString("fr-FR");

/** Absences : délégation de la validation des temps. `admin` : gestion de toutes les délégations de l'entreprise. */
export function DelegationsCard({ me, admin = false }: { me: Me; admin?: boolean }) {
  const data = useApi(timeApi.delegations);
  const { run, busy } = useAction();
  const [form, setForm] = useState({ delegator: "", delegate: "", startDate: today(), endDate: today(), reason: "" });
  const [open, setOpen] = useState(false);

  if (data.error) return <ErrorNotice error={data.error} onRetry={data.reload} />;
  if (!data.data) return <Loading />;
  const d = data.data;
  if (d.mode === "auto" && !admin) return null;

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((o) => ({ ...o, [k]: e.target.value }));
  const delegatorId = admin && form.delegator ? Number(form.delegator) : me.id;
  const choices = d.people.filter((p) => p.id !== delegatorId);
  const valid = form.delegate && form.startDate && form.endDate && form.endDate >= form.startDate && (!admin || form.delegator);

  const create = () =>
    run(
      () =>
        timeApi.createDelegation({
          delegator: admin ? Number(form.delegator) : undefined,
          delegate: Number(form.delegate),
          startDate: form.startDate,
          endDate: form.endDate,
          reason: form.reason,
        }),
      "Délégation enregistrée",
    ).then(
      () => {
        setForm({ delegator: "", delegate: "", startDate: today(), endDate: today(), reason: "" });
        setOpen(false);
        data.reload();
      },
      () => undefined,
    );
  const remove = (id: number) =>
    run(() => timeApi.deleteDelegation(id), "Délégation retirée").then(() => data.reload(), () => undefined);

  const received = d.rows.filter((r) => r.delegate === me.id && r.state === "active");

  return (
    <Card
      title={admin ? "Délégations en cas d’absence" : "Mes absences"}
      sub={
        admin
          ? "Pendant la période, le délégué valide les temps à la place de l’absent. L’absent garde son droit de valider."
          : "Vous partez ? Confiez la validation de vos temps à un collègue pour la durée de votre absence."
      }
      extra={
        !open && (
          <button className="btn sm" type="button" onClick={() => setOpen(true)}>
            + {admin ? "Nouvelle délégation" : "Déclarer une absence"}
          </button>
        )
      }
    >
      {received.length > 0 && (
        <div className="callout info" style={{ marginBottom: 12 }}>
          Vous remplacez actuellement{" "}
          <b>{received.map((r) => `${r.delegatorName} (jusqu’au ${frDate(r.endDate)})`).join(", ")}</b> : leurs saisies à valider
          apparaissent dans « À valider ».
        </div>
      )}
      {open && (
        <div className="proj-form" style={{ marginBottom: 14 }}>
          <div className="frow">
            {admin && (
              <Field id="dl-delegator" label="Personne absente *">
                <select id="dl-delegator" className="inp" value={form.delegator} onChange={set("delegator")}>
                  <option value="">Choisir…</option>
                  {d.people.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </Field>
            )}
            <Field id="dl-delegate" label="Remplaçant pour la validation *">
              <select id="dl-delegate" className="inp" value={form.delegate} onChange={set("delegate")}>
                <option value="">Choisir…</option>
                {choices.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <div className="frow">
            <Field id="dl-start" label="Du *">
              <input id="dl-start" className="inp" type="date" value={form.startDate} onChange={set("startDate")} />
            </Field>
            <Field id="dl-end" label="Au (inclus) *">
              <input id="dl-end" className="inp" type="date" min={form.startDate} value={form.endDate} onChange={set("endDate")} />
            </Field>
            <Field id="dl-reason" label="Motif">
              <input id="dl-reason" className="inp" maxLength={200} placeholder="Congés, formation…" value={form.reason} onChange={set("reason")} />
            </Field>
          </div>
          <div className="btns" style={{ justifyContent: "flex-end" }}>
            <button className="btn ghost" type="button" onClick={() => setOpen(false)}>
              Annuler
            </button>
            <button className="btn primary" type="button" disabled={busy || !valid} onClick={create}>
              Enregistrer la délégation
            </button>
          </div>
        </div>
      )}
      {d.rows.length === 0 ? (
        !open && <div className="empty">Aucune délégation en cours ou à venir.</div>
      ) : (
        <div className="tbl-wrap">
          <table className="tbl tight">
            <thead>
              <tr>
                <th>Absent</th>
                <th>Remplaçant</th>
                <th>Période</th>
                <th>Motif</th>
                <th>État</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {d.rows.map((r) => (
                <tr key={r.id}>
                  <td>{r.delegatorName}</td>
                  <td>{r.delegateName}</td>
                  <td>
                    {frDate(r.startDate)} → {frDate(r.endDate)}
                  </td>
                  <td className="muted">{r.reason || "—"}</td>
                  <td>
                    <span className={`ts-chip ${r.state === "active" ? "approved" : r.state === "future" ? "pending" : ""}`}>{STATE[r.state]}</span>
                  </td>
                  <td className="r">
                    {(d.canManageAll || r.delegator === me.id) && r.state !== "past" && (
                      <button className="btn ghost sm" type="button" disabled={busy} onClick={() => remove(r.id)}>
                        Retirer
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
