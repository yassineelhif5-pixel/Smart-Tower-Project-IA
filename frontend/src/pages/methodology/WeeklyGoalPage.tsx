import { useState } from "react";

import { calendarApi } from "../../api/collab";
import { methodologyApi } from "../../api/methodology";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, Loading, useAction } from "../../components/ui";
import { fmt, GOAL_STATUS, PRIORITY, Status } from "../../features/methodology/shared";
import type { WeeklyGoal } from "../../types/methodology";
import type { PageProps } from "./types";
import { mondayIso, shiftWeek } from "./WeeklyPlanningPage";

/** Weekly Goals : plusieurs objectifs par semaine, sur une ou plusieurs phases, avec actions et critères. */
export function WeeklyGoalPage({ info }: PageProps) {
  const id = info.project.id;
  const [week, setWeek] = useState(() => mondayIso());
  const w = useApi(() => methodologyApi.week(id, week), [id, week]);
  const phases = useApi(() => methodologyApi.phases(id), [id]);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="cal-nav">
        <button className="icon-btn" aria-label="Semaine précédente" onClick={() => setWeek(shiftWeek(week, -1))}>
          ‹
        </button>
        <h2 className="cal-title no-cap">Weekly Goals — semaine du {fmt(week)}</h2>
        <button className="icon-btn" aria-label="Semaine suivante" onClick={() => setWeek(shiftWeek(week, 1))}>
          ›
        </button>
      </div>
      {w.error && <ErrorNotice error={w.error} onRetry={w.reload} />}
      {!w.data && !w.error && <Loading />}
      {w.data && (
        <div className="goal-grid">
          {w.data.plan.goals.map((g) => (
            <GoalCard
              key={g.id}
              goal={g}
              projectId={id}
              phases={phases.data?.phases ?? []}
              editable={info.can.plan && w.data!.plan.state !== "closed"}
              onChange={w.reload}
              tracking={w.data!.tracking.goals.find((t) => t.id === g.id)}
            />
          ))}
          {!w.data.plan.goals.length && (
            <div className="empty">Aucun objectif pour cette semaine : préparez-la dans l'onglet « Semaine ».</div>
          )}
        </div>
      )}
      {w.data && w.data.history.length > 0 && (
        <Card title="Semaines précédentes">
          <table className="tbl tight">
            <tbody>
              {w.data.history.map((h) => (
                <tr key={h.weekStart} className="click" onClick={() => setWeek(h.weekStart)}>
                  <td>Semaine du {fmt(h.weekStart)}</td>
                  <td>
                    <Status value={h.status} label={h.statusLabel} />
                  </td>
                  <td className="muted">
                    {{ draft: "En préparation", validated: "Validée", closed: "Clôturée" }[h.state]}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

function GoalCard({
  goal,
  projectId,
  phases,
  editable,
  onChange,
  tracking,
}: {
  goal: WeeklyGoal;
  projectId: string;
  phases: { id: number; name: string }[];
  editable: boolean;
  onChange: () => void;
  tracking?: { done: number; planned: number; rate: number; plannedHours: number; consumedHours: number };
}) {
  const [edit, setEdit] = useState(false);
  const [f, setF] = useState(goal);
  const people = useApi(() => (edit ? calendarApi.people(projectId) : Promise.resolve([])), [edit, projectId]);
  const { run, busy } = useAction();
  return (
    <section className="card goal-card">
      <div className="card-h">
        <div>
          <h2 className="sec">{goal.title}</h2>
          <small>
            {PRIORITY[goal.priority]} · {goal.owner?.name ?? "sans responsable"} ·{" "}
            {goal.phases.map((p) => p.name).join(", ") || "toutes phases"}
          </small>
        </div>
        <Status value={goal.status} />
      </div>
      <div className="card-b">
        {!edit ? (
          <>
            {goal.expectedResults && (
              <p>
                <b>Résultats attendus :</b> {goal.expectedResults}
              </p>
            )}
            {goal.deliverables && (
              <p>
                <b>Livrables :</b> {goal.deliverables}
              </p>
            )}
            {goal.successCriteria && (
              <p>
                <b>Critères de réussite :</b> {goal.successCriteria}
              </p>
            )}
            {goal.risks && (
              <p>
                <b>Risques et dépendances :</b> {goal.risks}
              </p>
            )}
            {tracking && (
              <p className="muted">
                {tracking.done}/{tracking.planned} actions · {tracking.rate} % · {tracking.consumedHours}/
                {tracking.plannedHours} h
              </p>
            )}
            <ul className="plain">
              {goal.actions.map((a) => (
                <li key={a.id}>
                  <Status value={a.status} /> {a.title}{" "}
                  <span className="muted">
                    {a.owner?.name ?? ""} {a.carriedOver ? "· reportée" : ""}
                  </span>
                </li>
              ))}
            </ul>
            {goal.result && (
              <p>
                <b>Résultat constaté :</b> {goal.result}
              </p>
            )}
            {editable && (
              <div className="btns">
                <button className="btn sm" onClick={() => setEdit(true)}>
                  Modifier
                </button>
                <button
                  className="btn sm ghost"
                  onClick={() =>
                    window.confirm("Supprimer cet objectif ?") &&
                    void run(() => methodologyApi.removeGoal(goal.id), "Objectif supprimé").then(
                      onChange,
                      () => undefined,
                    )
                  }
                >
                  Supprimer
                </button>
              </div>
            )}
          </>
        ) : (
          <div className="ev-form">
            <Field id={`g-t-${goal.id}`} label="Objectif">
              <input
                id={`g-t-${goal.id}`}
                className="inp"
                value={f.title}
                onChange={(e) => setF({ ...f, title: e.target.value })}
              />
            </Field>
            {(["expectedResults", "deliverables", "successCriteria", "risks", "result"] as const).map((k) => (
              <Field
                key={k}
                id={`g-${k}-${goal.id}`}
                label={
                  {
                    expectedResults: "Résultats attendus",
                    deliverables: "Livrables attendus",
                    successCriteria: "Critères de réussite",
                    risks: "Risques et dépendances",
                    result: "Résultat constaté",
                  }[k]
                }
              >
                <textarea
                  id={`g-${k}-${goal.id}`}
                  className="inp"
                  rows={2}
                  value={f[k]}
                  onChange={(e) => setF({ ...f, [k]: e.target.value })}
                />
              </Field>
            ))}
            <div className="grid g3">
              <select
                className="inp"
                aria-label="Priorité"
                value={f.priority}
                onChange={(e) => setF({ ...f, priority: e.target.value })}
              >
                {Object.entries(PRIORITY).map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
              </select>
              <select
                className="inp"
                aria-label="Statut"
                value={f.status}
                onChange={(e) => setF({ ...f, status: e.target.value })}
              >
                {["not_started", "in_progress", "achieved", "partial", "missed"].map((k) => (
                  <option key={k} value={k}>
                    {GOAL_STATUS[k]}
                  </option>
                ))}
              </select>
              <select
                className="inp"
                aria-label="Responsable"
                value={f.owner?.id ?? ""}
                onChange={(e) =>
                  setF({ ...f, owner: e.target.value ? { id: Number(e.target.value), name: "" } : null })
                }
              >
                <option value="">Responsable…</option>
                {(people.data ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="chips">
              {phases.map((p) => {
                const on = f.phases.some((x) => x.id === p.id);
                return (
                  <button
                    key={p.id}
                    className={`chip ${on ? "on" : ""}`}
                    aria-pressed={on}
                    onClick={() =>
                      setF({ ...f, phases: on ? f.phases.filter((x) => x.id !== p.id) : [...f.phases, p] })
                    }
                  >
                    {p.name}
                  </button>
                );
              })}
            </div>
            <div className="btns">
              <button className="btn" onClick={() => setEdit(false)}>
                Annuler
              </button>
              <button
                className="btn primary"
                disabled={busy}
                onClick={() =>
                  void run(
                    () =>
                      methodologyApi.saveGoal(goal.id, {
                        title: f.title,
                        expectedResults: f.expectedResults,
                        deliverables: f.deliverables,
                        successCriteria: f.successCriteria,
                        risks: f.risks,
                        result: f.result,
                        priority: f.priority,
                        status: f.status,
                        owner: f.owner?.id ?? null,
                        phases: f.phases.map((p) => p.id),
                      }),
                    "Objectif enregistré",
                  ).then(
                    () => (setEdit(false), onChange()),
                    () => undefined,
                  )
                }
              >
                Enregistrer
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
