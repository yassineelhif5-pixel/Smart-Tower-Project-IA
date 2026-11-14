// Sprint Goal, Daily Scrum, Sprint Review et tableau de bord Scrum.
import { useEffect, useState } from "react";

import { calendarApi } from "../../api/collab";
import { methodologyApi } from "../../api/methodology";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, fmtDate, Loading, Modal, useAction } from "../../components/ui";
import {
  AssistPanel,
  BarChart,
  COLORS,
  fmt,
  GOAL_STATUS,
  Kpi,
  LineChart,
  SprintPicker,
  Status,
  useSprint,
} from "../../features/methodology/shared";
import type { SprintMetrics } from "../../types/methodology";
import type { PageProps } from "./types";

export function SprintCharts({ m }: { m: SprintMetrics }) {
  return (
    <div className="grid g2">
      <Card title="Burndown" sub="Points restants (scope réel) et ligne idéale">
        <LineChart
          labels={m.burndown.map((p) => p.date)}
          series={[
            { name: "Restant", values: m.burndown.map((p) => p.remaining), color: COLORS.a },
            { name: "Idéal", values: m.burndown.map((p) => p.ideal), color: COLORS.d, dashed: true },
          ]}
        />
      </Card>
      <Card title="Burnup" sub="Points terminés et périmètre">
        <LineChart
          labels={m.burnup.map((p) => p.date)}
          series={[
            { name: "Terminé", values: m.burnup.map((p) => p.done), color: COLORS.a },
            { name: "Périmètre", values: m.burnup.map((p) => p.scope), color: COLORS.c, dashed: true },
          ]}
        />
      </Card>
      <Card title="Vélocité" sub={`Moyenne des 3 derniers sprints : ${m.velocity.average ?? "—"}`}>
        {m.velocity.sprints.length ? (
          <BarChart
            labels={m.velocity.sprints.map((s) => `S${s.number}`)}
            series={[
              { name: "Engagé", values: m.velocity.sprints.map((s) => s.committed), color: COLORS.d },
              { name: "Réalisé", values: m.velocity.sprints.map((s) => s.completed), color: COLORS.a },
            ]}
          />
        ) : (
          <p className="muted">Pas encore de sprint terminé.</p>
        )}
      </Card>
      <Card title="Répartition du travail">
        <ul className="hbars">
          {m.byMember.map((b) => (
            <li key={b.name}>
              <span className="hb-l">{b.name}</span>
              <span className="hb-t">
                <i style={{ width: `${b.points ? (b.done / b.points) * 100 : 0}%` }} />
              </span>
              <span className="hb-v mono">
                {b.done}/{b.points} pts
              </span>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

function MetricKpis({ m }: { m: SprintMetrics }) {
  return (
    <div className="kpis cap-kpis">
      <Kpi label="Jours écoulés / restants" value={`${m.daysElapsed} / ${m.daysRemaining}`} />
      <Kpi label="Points prévus" value={m.pointsPlanned} />
      <Kpi label="Points terminés" value={m.pointsDone} tone="ok" />
      <Kpi label="Points restants" value={m.pointsRemaining} />
      <Kpi label="Capacité initiale" value={`${m.capacityInitial} h`} />
      <Kpi label="Capacité consommée" value={`${m.capacityConsumed} h`} />
      <Kpi label="Charge restante" value={`${m.remainingHours} h`} />
      <Kpi label="Bloqués" value={m.blocked.length} tone={m.blocked.length ? "crit" : ""} />
    </div>
  );
}

function GoalBanner({ m }: { m: SprintMetrics }) {
  return m.goal ? (
    <div className="goal-banner">
      <span>Sprint Goal</span> {m.goal.objective} <em>{m.goal.statusLabel}</em>
      <small>
        Atteinte appréciée par l'équipe : {m.goal.progress} % · tâches terminées : {m.tasksDoneRate} % (indicateur
        distinct)
      </small>
    </div>
  ) : (
    <div className="callout warn">Aucun Sprint Goal défini pour ce sprint.</div>
  );
}

/** Tableau de bord Scrum. */
export function ScrumDashboardPage({ info }: PageProps) {
  const d = useApi(() => methodologyApi.scrumDashboard(info.project.id), [info.project.id]);
  if (d.error) return <ErrorNotice error={d.error} onRetry={d.reload} />;
  if (!d.data) return <Loading />;
  const x = d.data;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {x.metrics ? (
        <>
          <h2 className="cal-title no-cap">
            {x.metrics.sprint.label} · {fmt(x.metrics.sprint.start)} → {fmt(x.metrics.sprint.end)}{" "}
            <Status value={x.metrics.sprint.status} label={x.metrics.sprint.statusLabel} />
          </h2>
          <GoalBanner m={x.metrics} />
          <MetricKpis m={x.metrics} />
          <SprintCharts m={x.metrics} />
        </>
      ) : (
        <div className="empty">Aucun sprint : commencez par le Sprint Planning.</div>
      )}
      <div className="grid g3">
        <Card title="Product Backlog">
          <p>
            <b>{x.backlog.ready}</b> élément(s) prêts ({x.backlog.readyPoints} pts) · {x.backlog.new} à affiner
          </p>
        </Card>
        <Card title="Cérémonies à venir">
          <ul className="plain">
            {x.ceremonies.map((c) => (
              <li key={c.id}>
                {c.title} <span className="muted">{fmtDate(c.start)}</span>
              </li>
            ))}
            {!x.ceremonies.length && <li className="muted">Aucune.</li>}
          </ul>
        </Card>
        <Card title="Rétrospectives">
          <p>Actions d'amélioration réalisées : {x.improvementRate == null ? "—" : `${x.improvementRate} %`}</p>
          <ul className="plain">
            {x.retros.map((r) => (
              <li key={r.id}>
                {r.title} <Status value={r.status} label={r.statusLabel} />
              </li>
            ))}
          </ul>
        </Card>
      </div>
      <AssistPanel
        projectId={info.project.id}
        topics={[
          ["blockers", "Blocages"],
          ["sprint_summary", "Résumé du sprint"],
          ["capacity", "Capacité"],
        ]}
      />
    </div>
  );
}

/** Espace du Sprint Goal : suivi indépendant du pourcentage de tâches terminées. */
export function SprintGoalPage({ info }: PageProps) {
  const sp = useSprint(info.project.id);
  const s = useApi(() => (sp.id ? methodologyApi.sprint(sp.id) : Promise.resolve(null)), [sp.id]);
  const people = useApi(() => calendarApi.people(info.project.id), [info.project.id]);
  const [f, setF] = useState({
    objective: "",
    value: "",
    expectedResults: "",
    successCriteria: "",
    risks: "",
    owner: "",
    status: "not_started",
    progress: 0,
  });
  const { run, busy } = useAction();
  useEffect(() => {
    const g = s.data?.sprint.goal;
    if (g)
      setF({
        objective: g.objective,
        value: g.value,
        expectedResults: g.expectedResults,
        successCriteria: g.successCriteria,
        risks: g.risks,
        owner: String(g.owner?.id ?? ""),
        status: g.status,
        progress: g.progress,
      });
  }, [s.data]);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {sp.list.data && <SprintPicker sprints={sp.list.data.sprints} value={sp.id} onChange={sp.setId} />}
      {s.error && <ErrorNotice error={s.error} />}
      {s.data && (
        <>
          <GoalBanner m={s.data.metrics} />
          <Card
            title="Sprint Goal"
            sub="Visible dans le Sprint Board, le tableau de bord, le calendrier et le suivi du sprint."
          >
            <div className="ev-form">
              <Field id="g-obj" label="Objectif du sprint">
                <textarea
                  id="g-obj"
                  className="inp"
                  rows={2}
                  value={f.objective}
                  onChange={(e) => setF({ ...f, objective: e.target.value })}
                />
              </Field>
              <div className="grid g2">
                {(["value", "expectedResults", "successCriteria", "risks"] as const).map((k) => (
                  <Field
                    key={k}
                    id={`g-${k}`}
                    label={
                      {
                        value: "Valeur attendue",
                        expectedResults: "Résultats attendus",
                        successCriteria: "Critères de réussite",
                        risks: "Risques",
                      }[k]
                    }
                  >
                    <textarea
                      id={`g-${k}`}
                      className="inp"
                      rows={2}
                      value={f[k]}
                      onChange={(e) => setF({ ...f, [k]: e.target.value })}
                    />
                  </Field>
                ))}
              </div>
              <div className="grid g3">
                <Field id="g-owner" label="Responsable du suivi">
                  <select
                    id="g-owner"
                    className="inp"
                    value={f.owner}
                    onChange={(e) => setF({ ...f, owner: e.target.value })}
                  >
                    <option value="">—</option>
                    {(people.data ?? []).map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field id="g-status" label="Statut">
                  <select
                    id="g-status"
                    className="inp"
                    value={f.status}
                    onChange={(e) => setF({ ...f, status: e.target.value })}
                  >
                    {["not_started", "on_track", "at_risk", "achieved", "partial", "missed"].map((k) => (
                      <option key={k} value={k}>
                        {GOAL_STATUS[k]}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field id="g-prog" label={`Progression vers l'objectif : ${f.progress} %`}>
                  <input
                    id="g-prog"
                    type="range"
                    min={0}
                    max={100}
                    step={5}
                    value={f.progress}
                    onChange={(e) => setF({ ...f, progress: Number(e.target.value) })}
                  />
                </Field>
              </div>
              <p className="muted">
                User Stories associées : {s.data.sprint.goal?.items.map((i) => i.title).join(", ") || "—"}
              </p>
              <button
                className="btn primary"
                disabled={busy || !info.can.plan}
                onClick={() =>
                  void run(
                    () =>
                      methodologyApi.sprintAction(s.data!.sprint.id, "goal", {
                        ...f,
                        owner: f.owner ? Number(f.owner) : null,
                      }),
                    "Sprint Goal enregistré",
                  ).then(s.reload, () => undefined)
                }
              >
                Enregistrer
              </button>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}

/** Daily Scrum : inspection et adaptation du plan ; obstacles et leur résolution. */
export function DailyScrumPage({ info }: PageProps) {
  const sp = useSprint(info.project.id);
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const d = useApi(() => (sp.id ? methodologyApi.daily(sp.id, date) : Promise.resolve(null)), [sp.id, date]);
  const mine = d.data?.entries.find((e) => e.mine);
  const [f, setF] = useState({ progress: "", plan: "", impediment: "" });
  const [notes, setNotes] = useState("");
  const { run, busy } = useAction();
  useEffect(() => {
    setF({ progress: mine?.progress ?? "", plan: mine?.plan ?? "", impediment: mine?.impediment ?? "" });
    setNotes(d.data?.notes ?? "");
  }, [d.data, mine]);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="cal-tools">
        {sp.list.data && <SprintPicker sprints={sp.list.data.sprints} value={sp.id} onChange={sp.setId} />}
        <input
          className="inp"
          type="date"
          aria-label="Date du Daily"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          style={{ width: "auto" }}
        />
      </div>
      <p className="muted">
        Le Daily Scrum sert à inspecter la progression vers le Sprint Goal et à adapter le plan ; la saisie individuelle
        est facultative.
      </p>
      {d.error && <ErrorNotice error={d.error} />}
      {d.data && sp.id && (
        <div className="grid g2">
          <Card title="Ma contribution">
            <div className="ev-form">
              {(["progress", "plan", "impediment"] as const).map((k) => (
                <Field
                  key={k}
                  id={`d-${k}`}
                  label={
                    {
                      progress: "Ce qui a progressé depuis le dernier Daily",
                      plan: "Ce qui est prévu jusqu'au prochain",
                      impediment: "Obstacles rencontrés",
                    }[k]
                  }
                >
                  <textarea
                    id={`d-${k}`}
                    className="inp"
                    rows={2}
                    value={f[k]}
                    onChange={(e) => setF({ ...f, [k]: e.target.value })}
                  />
                </Field>
              ))}
              <button
                className="btn primary"
                disabled={busy}
                onClick={() =>
                  void run(() => methodologyApi.saveDaily(sp.id!, { date, entry: f }), "Enregistré").then(
                    d.reload,
                    () => undefined,
                  )
                }
              >
                Enregistrer
              </button>
            </div>
          </Card>
          <Card title="Adaptation du plan (équipe)">
            <textarea
              className="inp"
              rows={4}
              aria-label="Notes de l'équipe"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
            <button
              className="btn sm"
              style={{ marginTop: 8 }}
              disabled={busy}
              onClick={() =>
                void run(() => methodologyApi.saveDaily(sp.id!, { date, notes }), "Notes enregistrées").then(
                  d.reload,
                  () => undefined,
                )
              }
            >
              Enregistrer les notes
            </button>
            <ul className="plain" style={{ marginTop: 12 }}>
              {d.data.entries.map((e) => (
                <li key={e.id}>
                  <b>{e.user.name}</b> — {e.progress} {e.plan && <span className="muted">· prévu : {e.plan}</span>}
                </li>
              ))}
            </ul>
          </Card>
          <Card title="Obstacles" sub="Actions de résolution, responsable, échéance et statut.">
            <table className="tbl tight">
              <tbody>
                {d.data.impediments.map((e) => (
                  <ImpedimentRow key={e.id} e={e} team={d.data!.team} onSaved={d.reload} />
                ))}
                {!d.data.impediments.length && (
                  <tr>
                    <td className="muted">Aucun obstacle signalé.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </Card>
        </div>
      )}
    </div>
  );
}

function ImpedimentRow({
  e,
  team,
  onSaved,
}: {
  e: NonNullable<Awaited<ReturnType<typeof methodologyApi.daily>>>["impediments"][number];
  team: { id: number; name: string }[];
  onSaved: () => void;
}) {
  const { run } = useAction();
  const save = (body: Record<string, unknown>) =>
    void run(() => methodologyApi.saveImpediment(e.id, body), "Obstacle mis à jour").then(onSaved, () => undefined);
  return (
    <tr>
      <td>
        {e.impediment}
        <div className="muted">
          {e.user.name} · {fmt(e.date)}
        </div>
      </td>
      <td>
        <input
          className="inp"
          placeholder="Action de résolution"
          aria-label="Action de résolution"
          defaultValue={e.resolution}
          onBlur={(ev) => ev.target.value !== e.resolution && save({ resolution: ev.target.value })}
        />
      </td>
      <td>
        <select
          className="inp"
          aria-label="Responsable"
          value={e.resolutionOwner?.id ?? ""}
          onChange={(ev) => save({ resolutionOwner: ev.target.value ? Number(ev.target.value) : null })}
        >
          <option value="">—</option>
          {team.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      </td>
      <td>
        <input
          className="inp"
          type="date"
          aria-label="Résolution prévue"
          defaultValue={e.resolutionDue ?? ""}
          onBlur={(ev) => save({ resolutionDue: ev.target.value || null })}
        />
      </td>
      <td>
        <select
          className="inp"
          aria-label="Statut"
          value={e.impedimentStatus}
          onChange={(ev) => save({ status: ev.target.value })}
        >
          <option value="open">Ouvert</option>
          <option value="in_progress">En cours</option>
          <option value="resolved">Résolu</option>
        </select>
      </td>
    </tr>
  );
}

/** Sprint Review et clôture du sprint. */
export function SprintReviewPage({ info }: PageProps) {
  const sp = useSprint(info.project.id);
  const r = useApi(() => (sp.id ? methodologyApi.review(sp.id) : Promise.resolve(null)), [sp.id]);
  const [f, setF] = useState({ increment: "", demos: "", feedback: "", decisions: "", backlogChanges: "" });
  const [closing, setClosing] = useState(false);
  const { run, busy } = useAction();
  useEffect(() => {
    if (r.data)
      setF({
        increment: r.data.increment,
        demos: r.data.demos,
        feedback: r.data.feedback,
        decisions: r.data.decisions,
        backlogChanges: r.data.backlogChanges,
      });
  }, [r.data]);
  const d = r.data;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {sp.list.data && <SprintPicker sprints={sp.list.data.sprints} value={sp.id} onChange={sp.setId} />}
      {r.error && <ErrorNotice error={r.error} />}
      {d && (
        <div className="grid g2">
          <Card title="Sprint Review" sub={`Objectif initial : ${d.sprint.goal?.objective ?? "—"}`}>
            <div className="ev-form">
              {(["increment", "demos", "feedback", "decisions", "backlogChanges"] as const).map((k) => (
                <Field
                  key={k}
                  id={`r-${k}`}
                  label={
                    {
                      increment: "Incrément réalisé",
                      demos: "Démonstrations",
                      feedback: "Retours des parties prenantes",
                      decisions: "Décisions",
                      backlogChanges: "Évolutions du Product Backlog",
                    }[k]
                  }
                >
                  <textarea
                    id={`r-${k}`}
                    className="inp"
                    rows={2}
                    value={f[k]}
                    onChange={(e) => setF({ ...f, [k]: e.target.value })}
                  />
                </Field>
              ))}
              <div className="btns">
                <button
                  className="btn"
                  disabled={busy}
                  onClick={() =>
                    void run(() => methodologyApi.saveReview(d.sprint.id, f), "Enregistré").then(
                      r.reload,
                      () => undefined,
                    )
                  }
                >
                  Enregistrer
                </button>
                <button
                  className="btn primary"
                  disabled={busy}
                  onClick={() =>
                    void run(
                      () => methodologyApi.saveReview(d.sprint.id, { ...f, held: true }),
                      "Compte rendu généré",
                    ).then(r.reload, () => undefined)
                  }
                >
                  Marquer tenue et générer le compte rendu
                </button>
              </div>
            </div>
          </Card>
          <Card title="Périmètre">
            <h4 className="ev-sec">Terminées ({d.done.length})</h4>
            <ul className="plain">
              {d.done.map((i) => (
                <li key={i.id}>✓ {i.title}</li>
              ))}
            </ul>
            <h4 className="ev-sec">Non terminées ({d.notDone.length})</h4>
            <ul className="plain">
              {d.notDone.map((i) => (
                <li key={i.id}>○ {i.title}</li>
              ))}
            </ul>
            {d.report && <pre className="report">{d.report}</pre>}
            {d.sprint.status === "active" && info.can.approve && (
              <button className="btn primary" onClick={() => setClosing(true)}>
                Clôturer le sprint
              </button>
            )}
          </Card>
        </div>
      )}
      {closing && d && (
        <CloseSprint
          sprintId={d.sprint.id}
          onClose={() => setClosing(false)}
          onDone={() => (r.reload(), sp.list.reload())}
        />
      )}
    </div>
  );
}

function CloseSprint({ sprintId, onClose, onDone }: { sprintId: number; onClose: () => void; onDone: () => void }) {
  const [goalStatus, setGoalStatus] = useState("");
  const [unfinished, setUnfinished] = useState("backlog");
  const { run, busy } = useAction();
  return (
    <Modal
      title="Clôture du sprint"
      onClose={onClose}
      footer={
        <button
          className="btn primary"
          disabled={!goalStatus || busy}
          onClick={() =>
            void run(
              () => methodologyApi.sprintAction(sprintId, "close", { goalStatus, unfinished }),
              "Sprint clôturé — rétrospective programmée",
            ).then(
              () => (onClose(), onDone()),
              () => undefined,
            )
          }
        >
          Clôturer
        </button>
      }
    >
      <div className="ev-form">
        <fieldset className="radios">
          <legend>Le Sprint Goal est-il atteint ? (appréciation de l'équipe, pas le % de tâches)</legend>
          {["achieved", "partial", "missed"].map((k) => (
            <label key={k}>
              <input type="radio" name="gs" checked={goalStatus === k} onChange={() => setGoalStatus(k)} />{" "}
              {GOAL_STATUS[k]}
            </label>
          ))}
        </fieldset>
        <fieldset className="radios">
          <legend>Éléments non terminés</legend>
          <label>
            <input
              type="radio"
              name="uf"
              checked={unfinished === "backlog"}
              onChange={() => setUnfinished("backlog")}
            />{" "}
            Retour au Product Backlog
          </label>
          <label>
            <input type="radio" name="uf" checked={unfinished === "next"} onChange={() => setUnfinished("next")} /> Vers
            le sprint suivant
          </label>
        </fieldset>
        <p className="muted">
          Une rétrospective est proposée automatiquement, avec événement dans le calendrier et rappels.
        </p>
      </div>
    </Modal>
  );
}
