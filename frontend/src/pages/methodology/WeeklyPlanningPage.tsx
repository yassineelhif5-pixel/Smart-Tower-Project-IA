import { useState } from "react";

import { calendarApi } from "../../api/collab";
import { methodologyApi } from "../../api/methodology";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, Loading, Modal, useAction } from "../../components/ui";
import {
  AssistPanel,
  fmt,
  GOAL_STATUS,
  GuardDialog,
  Kpi,
  PRIORITY,
  Status,
  useGuarded,
} from "../../features/methodology/shared";
import type { WeekData } from "../../types/methodology";
import type { PageProps } from "./types";

export const mondayIso = (d = new Date()) => {
  const x = new Date(d);
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7));
  return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`;
};
export const shiftWeek = (w: string, n: number) =>
  mondayIso(new Date(new Date(`${w}T12:00`).getTime() + n * 7 * 864e5));

const STEPS = [
  "Reliquat de la semaine précédente",
  "Actions reportées",
  "Disponibilités",
  "Capacité collective",
  "Actions proposées",
  "Affectations",
  "Charge par collaborateur",
  "Conflits",
  "Weekly Goals",
  "Validation",
];

/** Pilotage hebdomadaire Cycle en V : assistant de préparation, suivi, réunion et bilan de fin de semaine. */
export function WeeklyPlanningPage({ info }: PageProps) {
  const id = info.project.id;
  const [week, setWeek] = useState(() => mondayIso());
  const [step, setStep] = useState(0);
  const w = useApi(() => methodologyApi.week(id, week), [id, week]);
  const phases = useApi(() => methodologyApi.phases(id), [id]);
  const [closing, setClosing] = useState(false);
  const [meeting, setMeeting] = useState(false);
  const guard = useGuarded();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="cal-nav">
        <button className="icon-btn" aria-label="Semaine précédente" onClick={() => setWeek(shiftWeek(week, -1))}>
          ‹
        </button>
        <h2 className="cal-title no-cap">Semaine du {fmt(week)}</h2>
        <button className="icon-btn" aria-label="Semaine suivante" onClick={() => setWeek(shiftWeek(week, 1))}>
          ›
        </button>
        <button className="btn sm" onClick={() => setWeek(mondayIso())}>
          Cette semaine
        </button>
        {w.data && (
          <Status
            value={w.data.plan.state}
            label={{ draft: "En préparation", validated: "Validée", closed: "Clôturée" }[w.data.plan.state]}
          />
        )}
        {w.data && w.data.plan.state !== "draft" && (
          <Status value={w.data.plan.status} label={w.data.plan.statusLabel} />
        )}
      </div>
      {w.error && <ErrorNotice error={w.error} onRetry={w.reload} />}
      {!w.data && !w.error && <Loading />}
      {w.data && (
        <>
          <Tracking data={w.data} />
          {w.data.plan.state === "draft" && (
            <Card
              title="Préparation de la semaine"
              sub="Assistant en 10 étapes. Les propositions ne sont jamais appliquées sans vous."
            >
              <ol className="steps" aria-label="Étapes">
                {STEPS.map((s, i) => (
                  <li key={s} className={i === step ? "on" : i < step ? "done" : ""}>
                    <button onClick={() => setStep(i)}>
                      <span>{i + 1}</span> {s}
                    </button>
                  </li>
                ))}
              </ol>
              <StepBody
                step={step}
                data={w.data}
                projectId={id}
                canPlan={info.can.plan}
                canApprove={info.can.approve}
                reload={w.reload}
                guard={guard}
              />
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
          <div className="btns">
            <button className="btn" onClick={() => setMeeting(true)}>
              Réunion hebdomadaire
            </button>
            {w.data.plan.state === "validated" && info.can.approve && (
              <button className="btn primary" onClick={() => setClosing(true)}>
                Clôturer la semaine et générer le bilan
              </button>
            )}
          </div>
          {w.data.plan.state === "closed" && w.data.plan.review.summary && (
            <Card title="Bilan de la semaine" sub="Généré automatiquement à la clôture.">
              <p>{w.data.plan.review.summary}</p>
              {(w.data.plan.review.gaps ?? []).length > 0 && (
                <table className="tbl tight">
                  <thead>
                    <tr>
                      <th>Objectif</th>
                      <th>Action non terminée</th>
                      <th>Statut</th>
                      <th>Cause</th>
                    </tr>
                  </thead>
                  <tbody>
                    {w.data.plan.review.gaps!.map((g, i) => (
                      <tr key={i}>
                        <td>{g.goal}</td>
                        <td>{g.action}</td>
                        <td>
                          <Status value={g.status} />
                        </td>
                        <td>{g.cause || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <p>
                <b>Causes :</b> {w.data.plan.review.causes || "—"} · <b>Risques :</b> {w.data.plan.review.risks || "—"}{" "}
                · <b>Actions correctives :</b> {w.data.plan.review.correctiveActions || "—"}
              </p>
            </Card>
          )}
          <VCycleOverview phases={phases.data} />
          <AssistPanel
            projectId={id}
            topics={[
              ["weekly_goals", "Weekly Goals"],
              ["priorities", "Priorisation"],
              ["delays", "Retards"],
              ["capacity", "Capacité"],
              ["risks", "Risques"],
            ]}
          />
          {closing && (
            <CloseWeek projectId={id} week={week} data={w.data} onClose={() => setClosing(false)} onDone={w.reload} />
          )}
          {meeting && (
            <Meeting projectId={id} week={week} data={w.data} onClose={() => setMeeting(false)} onDone={w.reload} />
          )}
        </>
      )}
      <GuardDialog guard={guard} />
    </div>
  );
}

function Tracking({ data }: { data: WeekData }) {
  const t = data.tracking;
  return (
    <div className="kpis cap-kpis">
      <Kpi label="Objectifs" value={data.plan.goals.length} />
      <Kpi label="Actions prévues" value={t.totals.planned ?? 0} />
      <Kpi label="Terminées" value={t.totals.done ?? 0} tone="ok" />
      <Kpi label="En cours" value={t.totals.doing ?? 0} />
      <Kpi label="Bloquées" value={t.totals.blocked ?? 0} tone={t.totals.blocked ? "crit" : ""} />
      <Kpi label="Reportées" value={t.totals.reported ?? 0} />
      <Kpi label="Charge prévue / consommée" value={`${t.plannedHours} / ${t.consumedHours} h`} />
      <Kpi label="Réalisation" value={`${t.rate} %`} sub={`${t.deliverablesDone} livrable(s) réalisé(s)`} />
    </div>
  );
}

function StepBody({
  step,
  data,
  projectId,
  canPlan,
  canApprove,
  reload,
  guard,
}: {
  step: number;
  data: WeekData;
  projectId: string;
  canPlan: boolean;
  canApprove: boolean;
  reload: () => void;
  guard: ReturnType<typeof useGuarded>;
}) {
  const people = useApi(() => calendarApi.people(projectId), [projectId]);
  const [assign, setAssign] = useState<Record<string, { user: string; hours: string }>>({});
  const [goal, setGoal] = useState({
    title: "",
    expectedResults: "",
    priority: "normal",
    successCriteria: "",
    owner: "",
  });
  const [picked, setPicked] = useState<string[]>([]);
  const { run, busy } = useAction();
  const list = (rows: WeekData["unfinished"], empty: string) =>
    rows.length ? (
      <table className="tbl tight">
        <tbody>
          {rows.map((a) => (
            <tr key={a.id}>
              <td>{a.title}</td>
              <td>
                <Status value={a.status} />
              </td>
              <td className="mono">{fmt(a.due)}</td>
              <td>{a.owner?.name ?? "—"}</td>
              <td className="muted">{a.block}</td>
            </tr>
          ))}
        </tbody>
      </table>
    ) : (
      <p className="muted">{empty}</p>
    );
  const c = data.capacity;
  switch (step) {
    case 0:
      return list(data.unfinished, "Toutes les actions de la semaine précédente sont terminées.");
    case 1:
      return list(data.carriedOver, "Aucune action reportée.");
    case 2:
      return (
        <table className="tbl tight">
          <tbody>
            {c.members.map((m) => (
              <tr key={m.user.id}>
                <td>{m.user.name}</td>
                <td>{m.offDays.length ? `absent : ${m.offDays.map(fmt).join(", ")}` : "présent toute la semaine"}</td>
                <td className="r">{m.productive} h disponibles</td>
              </tr>
            ))}
          </tbody>
        </table>
      );
    case 3:
      return (
        <div className="kpis">
          <Kpi label="Théorique" value={`${c.totals.theoretical} h`} />
          <Kpi label="Disponible" value={`${c.totals.productive} h`} />
          <Kpi label="Déjà planifié" value={`${c.totals.planned} h`} />
          <Kpi label="Restant" value={`${c.totals.remaining} h`} tone={c.totals.remaining < 0 ? "crit" : "ok"} />
        </div>
      );
    case 4:
      return (
        <>
          <p className="muted">
            Proposition : {data.proposals.filter((p) => p.suggested).length} action(s), {data.proposedHours} h, dans la
            limite de la capacité. Cochez celles à retenir pour vos objectifs.
          </p>
          <table className="tbl tight">
            <tbody>
              {data.proposals.map((a) => (
                <tr key={a.id}>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`Retenir ${a.title}`}
                      checked={picked.includes(a.id)}
                      onChange={(e) =>
                        setPicked(e.target.checked ? [...picked, a.id] : picked.filter((x) => x !== a.id))
                      }
                    />
                  </td>
                  <td>
                    {a.title} {a.suggested && <Status value="planned" label="proposée" />}{" "}
                    {a.planned && <Status value="ok" label="planifiée" />}
                  </td>
                  <td>{a.priority}</td>
                  <td className="mono">{fmt(a.due)}</td>
                  <td className="r">{a.hours} h</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      );
    case 5:
      return (
        <>
          <table className="tbl tight">
            <tbody>
              {data.proposals
                .filter((a) => picked.includes(a.id) || a.planned)
                .map((a) => (
                  <tr key={a.id}>
                    <td>{a.title}</td>
                    <td>
                      <select
                        className="inp"
                        aria-label={`Responsable de ${a.title}`}
                        value={assign[a.id]?.user ?? String(a.owner?.id ?? "")}
                        onChange={(e) =>
                          setAssign({
                            ...assign,
                            [a.id]: { hours: assign[a.id]?.hours ?? String(a.hours ?? ""), user: e.target.value },
                          })
                        }
                      >
                        <option value="">—</option>
                        {(people.data ?? []).map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <input
                        className="inp num"
                        type="number"
                        aria-label="Heures"
                        value={assign[a.id]?.hours ?? String(a.hours ?? "")}
                        onChange={(e) =>
                          setAssign({
                            ...assign,
                            [a.id]: { user: assign[a.id]?.user ?? String(a.owner?.id ?? ""), hours: e.target.value },
                          })
                        }
                      />
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
          <button
            className="btn primary"
            disabled={!canPlan || busy}
            onClick={() => {
              const items = data.proposals
                .filter((a) => picked.includes(a.id) || a.planned)
                .map((a) => ({
                  action: a.id,
                  user: Number(assign[a.id]?.user ?? a.owner?.id),
                  hours: Number(assign[a.id]?.hours ?? a.hours),
                }))
                .filter((i) => i.user);
              void guard
                .run(
                  (confirm) => methodologyApi.weekAction(projectId, data.weekStart, "assign", { items, confirm }),
                  "Affectations enregistrées dans le calendrier",
                )
                .then(reload);
            }}
          >
            Enregistrer les affectations
          </button>
        </>
      );
    case 6:
      return (
        <table className="tbl tight">
          <tbody>
            {c.members.map((m) => (
              <tr key={m.user.id}>
                <td>{m.user.name}</td>
                <td className="r">
                  {m.planned} / {m.productive} h
                </td>
                <td>
                  <Status
                    value={m.state}
                    label={m.state === "over" ? "Surcharge" : m.state === "under" ? "Sous-utilisé" : "OK"}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      );
    case 7:
      return data.conflicts.length ? (
        <ul className="conflicts">
          {data.conflicts.map((x, i) => (
            <li key={i}>
              <div>
                <b>{x.title}</b>
                <p>{x.explanation}</p>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">Aucun conflit de planning sur la semaine.</p>
      );
    case 8:
      return (
        <>
          <ul className="plain">
            {data.plan.goals.map((g) => (
              <li key={g.id}>
                <b>{g.title}</b> <Status value={g.status} /> <span className="muted">{g.actions.length} action(s)</span>
              </li>
            ))}
          </ul>
          {canPlan && (
            <div className="ev-form">
              <Field id="wg-title" label="Objectif de la semaine">
                <input
                  id="wg-title"
                  className="inp"
                  value={goal.title}
                  onChange={(e) => setGoal({ ...goal, title: e.target.value })}
                />
              </Field>
              <div className="grid g3">
                <Field id="wg-res" label="Résultats attendus">
                  <input
                    id="wg-res"
                    className="inp"
                    value={goal.expectedResults}
                    onChange={(e) => setGoal({ ...goal, expectedResults: e.target.value })}
                  />
                </Field>
                <Field id="wg-crit" label="Critères de réussite">
                  <input
                    id="wg-crit"
                    className="inp"
                    value={goal.successCriteria}
                    onChange={(e) => setGoal({ ...goal, successCriteria: e.target.value })}
                  />
                </Field>
                <Field id="wg-prio" label="Priorité">
                  <select
                    id="wg-prio"
                    className="inp"
                    value={goal.priority}
                    onChange={(e) => setGoal({ ...goal, priority: e.target.value })}
                  >
                    {Object.entries(PRIORITY).map(([k, l]) => (
                      <option key={k} value={k}>
                        {l}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
              <button
                className="btn primary"
                disabled={!goal.title.trim() || busy}
                onClick={() =>
                  void run(
                    () =>
                      methodologyApi.weekAction(projectId, data.weekStart, "goals", {
                        ...goal,
                        owner: goal.owner ? Number(goal.owner) : null,
                        actions: picked.map((a) => ({
                          action: a,
                          hours: data.proposals.find((p) => p.id === a)?.hours,
                        })),
                      }),
                    "Objectif ajouté",
                  ).then(
                    () => (
                      setGoal({ title: "", expectedResults: "", priority: "normal", successCriteria: "", owner: "" }),
                      reload()
                    ),
                    () => undefined,
                  )
                }
              >
                Ajouter l'objectif (avec les {picked.length} action(s) retenue(s))
              </button>
            </div>
          )}
        </>
      );
    default:
      return (
        <div className="ev-form">
          <p>
            {data.plan.goals.length} objectif(s), {c.totals.planned} h planifiées pour {c.totals.productive} h
            disponibles
            {c.overloaded.length ? ` — surcharge : ${c.overloaded.map((u) => u.name).join(", ")}` : ""}.
          </p>
          <button
            className="btn primary"
            disabled={!canApprove}
            onClick={() =>
              void guard
                .run(
                  (confirm) => methodologyApi.weekAction(projectId, data.weekStart, "validate", { confirm }),
                  "Semaine validée",
                )
                .then(reload)
            }
          >
            Valider le planning de la semaine
          </button>
          {!canApprove && (
            <small className="muted">Validation réservée au chef de projet ou à un utilisateur habilité.</small>
          )}
        </div>
      );
  }
}

function VCycleOverview({ phases }: { phases: Awaited<ReturnType<typeof methodologyApi.phases>> | null }) {
  if (!phases) return null;
  const late = phases.phases.filter((p) => p.status === "late");
  return (
    <div className="grid g2">
      <Card
        title="Phases du Cycle en V"
        sub={late.length ? `${late.length} phase(s) en retard` : "Aucune phase en retard"}
      >
        <ul className="phase-list">
          {phases.phases.map((p) => (
            <li key={p.id}>
              <span className="ph-name">{p.name}</span>
              <span className="bar-mini">
                <i style={{ width: `${p.progress}%` }} />
              </span>
              <span className="mono muted">
                {fmt(p.start)} → {fmt(p.forecastEnd ?? p.end)}
              </span>
              <Status value={p.status} label={p.statusLabel} />
              <span className="muted">
                {p.deliverables.filter((d) => d.done).length}/{p.deliverables.length} livrables
              </span>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Jalons">
        {phases.milestones.length ? (
          <ul className="plain">
            {phases.milestones.map((m) => (
              <li key={m.id}>
                ◆ {m.title} <span className="mono muted">{fmt(m.date)}</span> <Status value={m.status} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">Aucun jalon planifié (ajoutez-les dans le calendrier).</p>
        )}
      </Card>
    </div>
  );
}

function CloseWeek({
  projectId,
  week,
  data,
  onClose,
  onDone,
}: {
  projectId: string;
  week: string;
  data: WeekData;
  onClose: () => void;
  onDone: () => void;
}) {
  const [statuses, setStatuses] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      data.tracking.goals.map((g) => [
        String(g.id),
        g.suggestedStatus === "in_progress" ? "partial" : g.suggestedStatus,
      ]),
    ),
  );
  const [f, setF] = useState({ causes: "", risks: "", correctiveActions: "" });
  const { run, busy } = useAction();
  return (
    <Modal
      title="Clôture de la semaine"
      onClose={onClose}
      footer={
        <button
          className="btn primary"
          disabled={busy}
          onClick={() =>
            void run(
              () => methodologyApi.weekAction(projectId, week, "close", { goalStatuses: statuses, ...f }),
              "Bilan généré",
            ).then(
              () => (onClose(), onDone()),
              () => undefined,
            )
          }
        >
          Clôturer et générer le bilan
        </button>
      }
    >
      <div className="ev-form">
        {data.tracking.goals.map((g) => (
          <div key={g.id} className="dep-row">
            <span>
              {g.title}{" "}
              <span className="muted">
                ({g.done}/{g.planned} actions)
              </span>
            </span>
            <select
              className="inp"
              aria-label={`Résultat de ${g.title}`}
              value={statuses[String(g.id)]}
              onChange={(e) => setStatuses({ ...statuses, [g.id]: e.target.value })}
            >
              {["achieved", "partial", "missed"].map((k) => (
                <option key={k} value={k}>
                  {GOAL_STATUS[k]}
                </option>
              ))}
            </select>
          </div>
        ))}
        {(["causes", "risks", "correctiveActions"] as const).map((k) => (
          <Field
            key={k}
            id={`cw-${k}`}
            label={{ causes: "Causes des écarts", risks: "Risques", correctiveActions: "Actions correctives" }[k]}
          >
            <textarea
              id={`cw-${k}`}
              className="inp"
              rows={2}
              value={f[k]}
              onChange={(e) => setF({ ...f, [k]: e.target.value })}
            />
          </Field>
        ))}
      </div>
    </Modal>
  );
}

function Meeting({
  projectId,
  week,
  data,
  onClose,
  onDone,
}: {
  projectId: string;
  week: string;
  data: WeekData;
  onClose: () => void;
  onDone: () => void;
}) {
  const m = data.plan.meeting;
  const people = useApi(() => calendarApi.people(projectId), [projectId]);
  const [f, setF] = useState({
    agenda: m.agenda ?? "",
    objectives: m.objectives ?? "",
    progress: m.progress ?? "",
    problems: m.problems ?? "",
    decisions: m.decisions ?? "",
  });
  const [participants, setParticipants] = useState<number[]>(m.participants ?? []);
  const [acts, setActs] = useState<{ title: string; owner: string; due: string }[]>([]);
  const { run, busy } = useAction();
  return (
    <Modal
      wide
      title="Réunion hebdomadaire"
      onClose={onClose}
      footer={
        <>
          <button
            className="btn"
            disabled={busy || !!data.plan.meetingEvent}
            onClick={() =>
              void run(
                () => methodologyApi.weekAction(projectId, week, "meeting", { ...f, participants, schedule: true }),
                "Réunion programmée dans le calendrier",
              ).then(onDone, () => undefined)
            }
          >
            {data.plan.meetingEvent ? "Programmée" : "Programmer dans le calendrier"}
          </button>
          <button
            className="btn primary"
            disabled={busy}
            onClick={() =>
              void run(
                () =>
                  methodologyApi.weekAction(projectId, week, "meeting", {
                    ...f,
                    participants,
                    actions: acts.map((a) => ({ ...a, owner: a.owner ? Number(a.owner) : null })),
                  }),
                "Compte rendu enregistré",
              ).then(
                () => (setActs([]), onDone()),
                () => undefined,
              )
            }
          >
            Enregistrer
          </button>
        </>
      }
    >
      <div className="ev-form">
        <div className="chips">
          {(people.data ?? []).map((p) => (
            <button
              key={p.id}
              className={`chip ${participants.includes(p.id) ? "on" : ""}`}
              aria-pressed={participants.includes(p.id)}
              onClick={() =>
                setParticipants(
                  participants.includes(p.id) ? participants.filter((x) => x !== p.id) : [...participants, p.id],
                )
              }
            >
              {p.name}
            </button>
          ))}
        </div>
        <div className="grid g2">
          {(["agenda", "objectives", "progress", "problems", "decisions"] as const).map((k) => (
            <Field
              key={k}
              id={`mt-${k}`}
              label={
                {
                  agenda: "Ordre du jour",
                  objectives: "Objectifs",
                  progress: "Points d'avancement",
                  problems: "Problèmes rencontrés",
                  decisions: "Décisions",
                }[k]
              }
            >
              <textarea
                id={`mt-${k}`}
                className="inp"
                rows={2}
                value={f[k]}
                onChange={(e) => setF({ ...f, [k]: e.target.value })}
              />
            </Field>
          ))}
        </div>
        <h4 className="ev-sec">Actions à réaliser (deviennent des actions PCT)</h4>
        {acts.map((a, i) => (
          <div key={i} className="dep-row">
            <input
              className="inp"
              aria-label="Action"
              value={a.title}
              onChange={(e) => setActs(acts.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))}
            />
            <select
              className="inp"
              aria-label="Responsable"
              value={a.owner}
              onChange={(e) => setActs(acts.map((x, j) => (j === i ? { ...x, owner: e.target.value } : x)))}
            >
              <option value="">Responsable…</option>
              {(people.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <input
              className="inp"
              type="date"
              aria-label="Échéance"
              value={a.due}
              onChange={(e) => setActs(acts.map((x, j) => (j === i ? { ...x, due: e.target.value } : x)))}
            />
          </div>
        ))}
        <button className="btn sm ghost" onClick={() => setActs([...acts, { title: "", owner: "", due: "" }])}>
          + Action
        </button>
        {m.report && (
          <>
            <h4 className="ev-sec">Compte rendu</h4>
            <pre className="report">{m.report}</pre>
          </>
        )}
      </div>
    </Modal>
  );
}
