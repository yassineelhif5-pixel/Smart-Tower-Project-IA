import { useEffect, useState } from "react";

import { methodologyApi } from "../../api/methodology";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, Loading, useAction } from "../../components/ui";
import {
  AssistPanel,
  BarChart,
  COLORS,
  GuardDialog,
  Kpi,
  SprintPicker,
  useGuarded,
  useSprint,
} from "../../features/methodology/shared";
import type { PageProps } from "./types";

const STEPS = [
  "Backlog priorisé",
  "Disponibilités",
  "Capacité",
  "Vélocité",
  "Sélection",
  "Sprint Goal",
  "Dépendances",
  "Charge et points",
  "Validation",
];

/** Assistant de Sprint Planning : rien n'est sélectionné sans le Product Owner et l'équipe. */
export function SprintPlanningPage({ info }: PageProps) {
  const id = info.project.id;
  const sp = useSprint(id);
  const [creating, setCreating] = useState(false);
  const [step, setStep] = useState(0);
  const plan = useApi(() => (sp.id ? methodologyApi.planning(sp.id) : Promise.resolve(null)), [sp.id]);
  const [chosen, setChosen] = useState<number[]>([]);
  const [goal, setGoal] = useState({ objective: "", value: "", successCriteria: "" });
  const guard = useGuarded();
  const { run, busy } = useAction();
  useEffect(() => {
    if (plan.data) {
      setChosen(plan.data.backlog.filter((i) => i.selected).map((i) => i.id));
      const g = plan.data.sprint.goal;
      setGoal({ objective: g?.objective ?? "", value: g?.value ?? "", successCriteria: g?.successCriteria ?? "" });
    }
  }, [plan.data]);

  const refresh = () => (plan.reload(), sp.list.reload());
  const d = plan.data;
  const pts = d ? d.backlog.filter((i) => chosen.includes(i.id)).reduce((s, i) => s + (i.storyPoints ?? 0), 0) : 0;
  const hrs = d ? d.backlog.filter((i) => chosen.includes(i.id)).reduce((s, i) => s + (i.estimateHours ?? 0), 0) : 0;
  const locked = d ? ["active", "done", "cancelled"].includes(d.sprint.status) : true;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="cal-tools">
        {sp.list.data && <SprintPicker sprints={sp.list.data.sprints} value={sp.id} onChange={sp.setId} />}
        {info.can.plan && (
          <button className="btn sm primary" onClick={() => setCreating(true)}>
            + Nouveau sprint
          </button>
        )}
      </div>
      {creating && (
        <NewSprint
          weeks={info.settings.sprintWeeks}
          onCancel={() => setCreating(false)}
          onCreate={(body) =>
            void guard
              .run((confirm) => methodologyApi.addSprint(id, { ...body, confirm }), "Sprint créé")
              .then((s) => {
                if (s) {
                  setCreating(false);
                  sp.list.reload();
                  sp.setId(s.id);
                }
              })
          }
        />
      )}
      {plan.error && <ErrorNotice error={plan.error} onRetry={plan.reload} />}
      {sp.id && !d && !plan.error && <Loading />}
      {!sp.id && sp.list.data && <div className="empty">Aucun sprint : créez le premier.</div>}
      {d && (
        <Card
          title={`Sprint Planning — ${d.sprint.label}`}
          sub={`${d.sprint.start} → ${d.sprint.end} · ${d.sprint.statusLabel}`}
        >
          <ol className="steps">
            {STEPS.map((s, i) => (
              <li key={s} className={i === step ? "on" : i < step ? "done" : ""}>
                <button onClick={() => setStep(i)}>
                  <span>{i + 1}</span> {s}
                </button>
              </li>
            ))}
          </ol>
          {step === 0 && (
            <ol className="backlog">
              {d.backlog.map((i) => (
                <li key={i.id}>
                  <span className="bl-rank">{i.rank}</span>
                  <span className="bl-title">{i.title}</span>
                  <span className="pts">{i.storyPoints ?? "–"}</span>
                  <span className="muted">{i.statusLabel}</span>
                </li>
              ))}
            </ol>
          )}
          {step === 1 && (
            <table className="tbl tight">
              <tbody>
                {d.capacity.members.map((m) => (
                  <tr key={m.user.id}>
                    <td>{m.user.name}</td>
                    <td>{m.scrumRole.toUpperCase() || "—"}</td>
                    <td>{m.offDays.length ? `${m.offDays.length} jour(s) d'absence` : "disponible tout le sprint"}</td>
                    <td className="r">{m.productive} h</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {step === 2 && (
            <div className="kpis">
              <Kpi label="Capacité théorique" value={`${d.capacity.totals.theoretical} h`} />
              <Kpi label="Capacité disponible" value={`${d.capacity.totals.productive} h`} />
              <Kpi label="Développeurs" value={d.capacity.members.length} />
            </div>
          )}
          {step === 3 &&
            (d.velocity.sprints.length ? (
              <BarChart
                labels={d.velocity.sprints.map((s) => `S${s.number}`)}
                series={[
                  { name: "Engagé", values: d.velocity.sprints.map((s) => s.committed), color: COLORS.d },
                  { name: "Réalisé", values: d.velocity.sprints.map((s) => s.completed), color: COLORS.a },
                ]}
              />
            ) : (
              <p className="muted">Pas encore d'historique de vélocité.</p>
            ))}
          {step === 4 && (
            <>
              <p className="muted">
                Vélocité moyenne : {d.velocity.average ?? "—"} points. Les éléments « proposés » tiennent dans la
                vélocité et la capacité ; cochez ceux que l'équipe retient.
              </p>
              <ol className="backlog">
                {d.backlog.map((i) => (
                  <li key={i.id} className={chosen.includes(i.id) ? "picked" : ""}>
                    <input
                      type="checkbox"
                      disabled={locked}
                      aria-label={`Sélectionner ${i.title}`}
                      checked={chosen.includes(i.id)}
                      onChange={(e) =>
                        setChosen(e.target.checked ? [...chosen, i.id] : chosen.filter((x) => x !== i.id))
                      }
                    />
                    <span className="bl-title">{i.title}</span>
                    {i.suggested && <span className="pill info">proposé</span>}
                    <span className="pts">{i.storyPoints ?? "–"}</span>
                    <span className="muted">{i.estimateHours ? `${i.estimateHours} h` : ""}</span>
                  </li>
                ))}
              </ol>
              <button
                className="btn primary"
                disabled={locked || busy}
                onClick={() =>
                  void guard
                    .run(
                      (confirm) => methodologyApi.sprintAction(d.sprint.id, "select", { items: chosen, confirm }),
                      "Sprint Backlog enregistré",
                    )
                    .then(refresh)
                }
              >
                Enregistrer la sélection ({pts} points)
              </button>
            </>
          )}
          {step === 5 && (
            <div className="ev-form">
              <Field
                id="sg-obj"
                label="Sprint Goal"
                hint="Un objectif cohérent, compréhensible et mesurable — pas une liste de tâches."
              >
                <textarea
                  id="sg-obj"
                  className="inp"
                  rows={2}
                  value={goal.objective}
                  onChange={(e) => setGoal({ ...goal, objective: e.target.value })}
                />
              </Field>
              <div className="grid g2">
                <Field id="sg-val" label="Valeur attendue">
                  <input
                    id="sg-val"
                    className="inp"
                    value={goal.value}
                    onChange={(e) => setGoal({ ...goal, value: e.target.value })}
                  />
                </Field>
                <Field id="sg-crit" label="Critères de réussite">
                  <input
                    id="sg-crit"
                    className="inp"
                    value={goal.successCriteria}
                    onChange={(e) => setGoal({ ...goal, successCriteria: e.target.value })}
                  />
                </Field>
              </div>
              <button
                className="btn primary"
                disabled={busy || !goal.objective.trim()}
                onClick={() =>
                  void run(
                    () => methodologyApi.sprintAction(d.sprint.id, "goal", { ...goal, items: chosen }),
                    "Sprint Goal enregistré",
                  ).then(refresh, () => undefined)
                }
              >
                Enregistrer le Sprint Goal
              </button>
              <AssistPanel projectId={id} topics={[["sprint_goal", "Proposer un Sprint Goal"]]} />
            </div>
          )}
          {step === 6 &&
            (d.dependencyIssues.length ? (
              <ul className="conflicts">
                {d.dependencyIssues.map((x, i) => (
                  <li key={i}>
                    <div>
                      « {x.item} » dépend de « {x.dependsOn} » ({x.status})
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">Aucune dépendance bloquante dans la sélection enregistrée.</p>
            ))}
          {step === 7 && (
            <div className="kpis">
              <Kpi
                label="Points sélectionnés"
                value={pts}
                tone={d.velocity.average && pts > d.velocity.average * 1.2 ? "crit" : ""}
                sub={`vélocité ${d.velocity.average ?? "—"}`}
              />
              <Kpi
                label="Heures estimées"
                value={`${hrs} h`}
                tone={hrs > d.capacity.totals.productive ? "crit" : ""}
                sub={`capacité ${d.capacity.totals.productive} h`}
              />
            </div>
          )}
          {step === 8 && (
            <div className="ev-form">
              <div className="validations">
                <div>
                  <b>Product Owner</b> : {d.sprint.poValidated ? `validé par ${d.sprint.poValidated.by}` : "à valider"}
                  {!d.sprint.poValidated && (
                    <button
                      className="btn sm"
                      onClick={() =>
                        void run(
                          () => methodologyApi.sprintAction(d.sprint.id, "validate", { as: "po" }),
                          "Validation du PO enregistrée",
                        ).then(refresh, () => undefined)
                      }
                    >
                      Valider (PO)
                    </button>
                  )}
                </div>
                <div>
                  <b>Équipe</b> : {d.sprint.teamValidated ? `engagée (${d.sprint.teamValidated.by})` : "à valider"}
                  {!d.sprint.teamValidated && (
                    <button
                      className="btn sm"
                      onClick={() =>
                        void run(
                          () => methodologyApi.sprintAction(d.sprint.id, "validate", { as: "team" }),
                          "Engagement de l'équipe enregistré",
                        ).then(refresh, () => undefined)
                      }
                    >
                      Valider (équipe)
                    </button>
                  )}
                </div>
              </div>
              {d.sprint.status !== "active" && info.can.approve && (
                <button
                  className="btn primary"
                  onClick={() =>
                    void run(
                      () => methodologyApi.sprintAction(d.sprint.id, "start"),
                      "Sprint démarré : cérémonies ajoutées au calendrier",
                    ).then(refresh, () => undefined)
                  }
                >
                  Démarrer le sprint
                </button>
              )}
            </div>
          )}
          <div className="btns" style={{ justifyContent: "space-between" }}>
            <button className="btn" disabled={step === 0} onClick={() => setStep(step - 1)}>
              Précédent
            </button>
            <button className="btn primary" disabled={step === STEPS.length - 1} onClick={() => setStep(step + 1)}>
              Suivant
            </button>
          </div>
        </Card>
      )}
      <GuardDialog guard={guard} />
    </div>
  );
}

function NewSprint({
  weeks,
  onCancel,
  onCreate,
}: {
  weeks: number;
  onCancel: () => void;
  onCreate: (b: Record<string, unknown>) => void;
}) {
  const [f, setF] = useState({ name: "", start: "", weeks, goal: "", team: "" });
  return (
    <Card title="Nouveau sprint">
      <div className="grid g3">
        <Field id="ns-name" label="Nom (facultatif)">
          <input id="ns-name" className="inp" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </Field>
        <Field id="ns-start" label="Début" hint="Vide : lundi suivant le dernier sprint">
          <input
            id="ns-start"
            className="inp"
            type="date"
            value={f.start}
            onChange={(e) => setF({ ...f, start: e.target.value })}
          />
        </Field>
        <Field id="ns-weeks" label="Durée">
          <select
            id="ns-weeks"
            className="inp"
            value={f.weeks}
            onChange={(e) => setF({ ...f, weeks: Number(e.target.value) })}
          >
            {[1, 2, 3, 4].map((w) => (
              <option key={w} value={w}>
                {w} semaine{w > 1 ? "s" : ""}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <div className="btns">
        <button className="btn" onClick={onCancel}>
          Annuler
        </button>
        <button className="btn primary" onClick={() => onCreate({ ...f, start: f.start || undefined })}>
          Créer
        </button>
      </div>
    </Card>
  );
}
