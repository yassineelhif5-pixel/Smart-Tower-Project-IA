// Rétrospectives (préparation collaborative, compte rendu, clôture), actions d'amélioration et rapports.
import { useState } from "react";

import { calendarApi } from "../../api/collab";
import { methodologyApi } from "../../api/methodology";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, fmtDate, Loading, useAction } from "../../components/ui";
import {
  AssistPanel,
  BarChart,
  COLORS,
  fmt,
  GuardDialog,
  Kpi,
  PRIORITY,
  Status,
  useGuarded,
} from "../../features/methodology/shared";
import type { Improvement } from "../../types/methodology";
import type { PageProps } from "./types";

const CATEGORY: Record<string, string> = {
  start: "Commencer",
  stop: "Arrêter",
  continue: "Continuer",
  mad: "Mad",
  sad: "Sad",
  glad: "Glad",
  well: "Ce qui a bien fonctionné",
  improve: "Ce qui peut s'améliorer",
  liked: "Liked",
  learned: "Learned",
  lacked: "Lacked",
  longed: "Longed for",
  less_well: "Ce qui a moins bien fonctionné",
  difficulties: "Difficultés",
  blockers: "Causes de blocage",
  proposals: "Propositions d'amélioration",
};
const FORMATS: [string, string][] = [
  ["ssc", "Start / Stop / Continue"],
  ["msg", "Mad / Sad / Glad"],
  ["wwi", "What went well / What could improve"],
  ["4ls", "4Ls"],
  ["free", "Format libre"],
];
const IMP_STATUS: Record<string, string> = {
  todo: "À faire",
  doing: "En cours",
  done: "Réalisée",
  dropped: "Abandonnée",
};

export function RetrospectivePage({ info }: PageProps) {
  const id = info.project.id;
  const list = useApi(() => methodologyApi.retros(id), [id]);
  const [sel, setSel] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const current = sel ?? list.data?.retros[0]?.id ?? null;
  return (
    <div className="disc">
      <aside className="disc-list" aria-label="Rétrospectives">
        {info.can.plan && (
          <button className="btn sm primary" onClick={() => setCreating(true)}>
            + Programmer une rétrospective
          </button>
        )}
        {list.data?.retros.map((r) => (
          <button
            key={r.id}
            className={`disc-item ${r.id === current ? "on" : ""}`}
            onClick={() => (setSel(r.id), setCreating(false))}
          >
            <b>{r.title}</b>
            <small>
              {fmtDate(r.scheduledAt)} · {r.triggerLabel} · {r.feedbackCount} retour(s)
            </small>
            <Status value={r.status} label={r.statusLabel} />
          </button>
        ))}
        {list.data && !list.data.retros.length && <p className="muted">Aucune rétrospective.</p>}
      </aside>
      {creating ? (
        <NewRetro projectId={id} onDone={(rid) => (setCreating(false), list.reload(), setSel(rid))} />
      ) : current ? (
        <RetroDetailView
          key={current}
          rid={current}
          canEdit={info.can.plan}
          canApprove={info.can.approve}
          projectId={id}
          onChange={list.reload}
        />
      ) : (
        <div className="empty">Sélectionnez une rétrospective.</div>
      )}
    </div>
  );
}

function NewRetro({ projectId, onDone }: { projectId: string; onDone: (id: number) => void }) {
  const [f, setF] = useState({
    title: "Rétrospective",
    format: "ssc",
    scheduledAt: "",
    anonymous: false,
    trigger: "adhoc",
    periodLabel: "",
  });
  const { run, busy } = useAction();
  return (
    <section className="disc-thread">
      <h3>Programmer une rétrospective</h3>
      <div className="ev-form">
        <Field id="nr-t" label="Titre">
          <input id="nr-t" className="inp" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
        </Field>
        <div className="grid g2">
          <Field id="nr-d" label="Date et heure">
            <input
              id="nr-d"
              className="inp"
              type="datetime-local"
              value={f.scheduledAt}
              onChange={(e) => setF({ ...f, scheduledAt: e.target.value })}
            />
          </Field>
          <Field id="nr-f" label="Format">
            <select id="nr-f" className="inp" value={f.format} onChange={(e) => setF({ ...f, format: e.target.value })}>
              {FORMATS.map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            </select>
          </Field>
          <Field id="nr-tr" label="Occasion">
            <select
              id="nr-tr"
              className="inp"
              value={f.trigger}
              onChange={(e) => setF({ ...f, trigger: e.target.value })}
            >
              {[
                ["adhoc", "Ponctuelle"],
                ["weekly", "Hebdomadaire"],
                ["monthly", "Mensuelle"],
                ["phase", "Fin de phase"],
                ["milestone", "Fin de jalon"],
                ["project", "Fin de projet"],
              ].map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            </select>
          </Field>
          <Field id="nr-p" label="Période concernée">
            <input
              id="nr-p"
              className="inp"
              value={f.periodLabel}
              onChange={(e) => setF({ ...f, periodLabel: e.target.value })}
            />
          </Field>
        </div>
        <label className="cal-check">
          <input type="checkbox" checked={f.anonymous} onChange={(e) => setF({ ...f, anonymous: e.target.checked })} />{" "}
          Autoriser les retours anonymes (si la politique de l'entreprise le permet)
        </label>
        <button
          className="btn primary"
          disabled={busy || !f.scheduledAt}
          onClick={() =>
            void run(
              () => methodologyApi.addRetro(projectId, { ...f, scheduledAt: new Date(f.scheduledAt).toISOString() }),
              "Rétrospective programmée : invitations et rappels envoyés",
            ).then(
              (r) => r && onDone(r.id),
              () => undefined,
            )
          }
        >
          Programmer
        </button>
      </div>
    </section>
  );
}

function RetroDetailView({
  rid,
  canEdit,
  canApprove,
  projectId,
  onChange,
}: {
  rid: number;
  canEdit: boolean;
  canApprove: boolean;
  projectId: string;
  onChange: () => void;
}) {
  const r = useApi(() => methodologyApi.retro(rid), [rid]);
  const people = useApi(() => calendarApi.people(projectId), [projectId]);
  const [text, setText] = useState<Record<string, string>>({});
  const [anon, setAnon] = useState(false);
  const [report, setReport] = useState<string | null>(null);
  const [imp, setImp] = useState({ title: "", owner: "", due: "", priority: "normal", resultIndicator: "" });
  const { run, busy } = useAction();
  const guard = useGuarded();
  if (r.error) return <ErrorNotice error={r.error} onRetry={r.reload} />;
  if (!r.data) return <Loading />;
  const d = r.data;
  const closed = d.status === "closed";
  const refresh = (x: typeof d | undefined) => {
    if (x) r.setData(x);
    onChange();
  };
  return (
    <section className="disc-thread">
      <header className="disc-h">
        <div>
          <h3>{d.title}</h3>
          <small className="muted">
            {fmtDate(d.scheduledAt)} · {d.formatLabel} · animée par {d.facilitator?.name ?? "—"} ·{" "}
            {d.participants.filter((p) => p.contributed).length}/{d.participants.length} contributions
          </small>
        </div>
        <Status value={d.status} label={d.statusLabel + (d.forcedClose ? " (forcée)" : "")} />
      </header>
      {d.previousOpen.length > 0 && (
        <div className="callout warn">
          <div>
            <b>Actions d'amélioration précédentes non terminées</b>
            <ul className="plain">
              {d.previousOpen.map((i) => (
                <li key={i.id}>
                  {i.title} — {i.owner?.name ?? "sans responsable"} {i.due ? `· ${fmt(i.due)}` : ""}{" "}
                  {i.late && <span className="t-crit">en retard</span>}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
      <div className="retro-board" style={{ ["--cols" as string]: d.categories.length }}>
        {d.categories.map((c) => (
          <div key={c} className="retro-col">
            <h4>{CATEGORY[c] ?? c}</h4>
            {d.feedback
              .filter((f) => f.category === c)
              .map((f) => (
                <div key={f.id} className="retro-note">
                  <p>{f.text}</p>
                  <small className="muted">
                    {f.anonymous ? "anonyme" : f.author?.name}
                    {d.isParticipant && !closed && (
                      <button className="link" onClick={() => void methodologyApi.vote(f.id).then(r.reload)}>
                        ▲ {f.votes}
                      </button>
                    )}
                    {!d.isParticipant && ` · ${f.votes} vote(s)`}
                  </small>
                </div>
              ))}
            {!closed && (
              <div className="retro-add">
                <textarea
                  className="inp"
                  rows={2}
                  aria-label={`Ajouter dans ${CATEGORY[c] ?? c}`}
                  value={text[c] ?? ""}
                  onChange={(e) => setText({ ...text, [c]: e.target.value })}
                />
                <button
                  className="btn sm"
                  disabled={!text[c]?.trim()}
                  onClick={() =>
                    void run(() =>
                      methodologyApi.retroAction(rid, "feedback", { category: c, text: text[c], anonymous: anon }),
                    ).then(
                      (x) => (setText({ ...text, [c]: "" }), refresh(x)),
                      () => undefined,
                    )
                  }
                >
                  Ajouter
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
      {!closed && d.allowAnonymous && (
        <label className="cal-check">
          <input type="checkbox" checked={anon} onChange={(e) => setAnon(e.target.checked)} /> Contribuer anonymement
          (votre nom n'est pas enregistré)
        </label>
      )}
      <h4 className="ev-sec">Décisions et actions d'amélioration</h4>
      <table className="tbl tight">
        <tbody>
          {d.improvements.map((i) => (
            <ImprovementRow key={i.id} i={i} people={people.data ?? []} editable={canEdit} onSaved={r.reload} />
          ))}
        </tbody>
      </table>
      {!closed && canEdit && (
        <div className="avail-form">
          <input
            className="inp"
            placeholder="Action d'amélioration"
            aria-label="Action d'amélioration"
            value={imp.title}
            onChange={(e) => setImp({ ...imp, title: e.target.value })}
          />
          <select
            className="inp"
            aria-label="Responsable"
            value={imp.owner}
            onChange={(e) => setImp({ ...imp, owner: e.target.value })}
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
            value={imp.due}
            onChange={(e) => setImp({ ...imp, due: e.target.value })}
          />
          <input
            className="inp"
            placeholder="Indicateur de résultat"
            aria-label="Indicateur de résultat"
            value={imp.resultIndicator}
            onChange={(e) => setImp({ ...imp, resultIndicator: e.target.value })}
          />
          <button
            className="btn sm primary"
            disabled={busy || !imp.title.trim()}
            onClick={() =>
              void run(
                () =>
                  methodologyApi.retroAction(rid, "improvements", {
                    ...imp,
                    owner: imp.owner ? Number(imp.owner) : null,
                    due: imp.due || null,
                  }),
                "Action créée dans PCT",
              ).then(
                (x) => (setImp({ title: "", owner: "", due: "", priority: "normal", resultIndicator: "" }), refresh(x)),
                () => undefined,
              )
            }
          >
            Ajouter
          </button>
        </div>
      )}
      <h4 className="ev-sec">Compte rendu</h4>
      <textarea
        className="inp"
        rows={5}
        aria-label="Compte rendu"
        disabled={closed}
        value={report ?? d.report}
        onChange={(e) => setReport(e.target.value)}
      />
      {!closed && canEdit && (
        <div className="btns">
          <button
            className="btn"
            onClick={() =>
              void run(
                () => methodologyApi.saveRetro(rid, { report: report ?? d.report, status: "held" }),
                "Compte rendu enregistré",
              ).then(refresh, () => undefined)
            }
          >
            Enregistrer (rétrospective tenue)
          </button>
          <button
            className="btn primary"
            onClick={() =>
              void guard.run((confirm) => {
                if (confirm && !canApprove) throw new Error("not allowed");
                return methodologyApi
                  .retroAction(rid, "close", { report: report ?? d.report, force: confirm })
                  .then(refresh);
              }, "Rétrospective clôturée")
            }
          >
            Clôturer
          </button>
        </div>
      )}
      <AssistPanel
        projectId={projectId}
        topics={[
          ["retro_synthesis", "Synthèse des retours"],
          ["recurring_improvements", "Améliorations récurrentes"],
        ]}
      />
      <GuardDialog
        guard={guard}
        confirmLabel={canApprove ? "Clôturer quand même (autorisation)" : "Réservé au droit Valider"}
      />
    </section>
  );
}

function ImprovementRow({
  i,
  people,
  editable,
  onSaved,
}: {
  i: Improvement;
  people: { id: number; name: string }[];
  editable: boolean;
  onSaved: () => void;
}) {
  const { run } = useAction();
  const save = (body: Record<string, unknown>) =>
    void run(() => methodologyApi.saveImprovement(i.id, body), "Action mise à jour").then(onSaved, () => undefined);
  return (
    <tr>
      <td>
        {i.title}
        {i.resultIndicator && <div className="muted">Indicateur : {i.resultIndicator}</div>}
      </td>
      <td>
        <select
          className="inp"
          aria-label="Responsable"
          disabled={!editable}
          value={i.owner?.id ?? ""}
          onChange={(e) => save({ owner: e.target.value ? Number(e.target.value) : null })}
        >
          <option value="">—</option>
          {people.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </td>
      <td>
        <input
          className="inp"
          type="date"
          aria-label="Échéance"
          disabled={!editable}
          defaultValue={i.due ?? ""}
          onBlur={(e) => e.target.value !== (i.due ?? "") && save({ due: e.target.value || null })}
        />
      </td>
      <td>{PRIORITY[i.priority]}</td>
      <td>
        <select
          className="inp"
          aria-label="Statut"
          disabled={!editable}
          value={i.status}
          onChange={(e) => save({ status: e.target.value })}
        >
          {Object.entries(IMP_STATUS).map(([k, l]) => (
            <option key={k} value={k}>
              {l}
            </option>
          ))}
        </select>
        {i.late && <span className="t-crit"> en retard</span>}
      </td>
    </tr>
  );
}

/** Toutes les actions d'amélioration du projet et leur taux de réalisation. */
export function RetrospectiveActionsPage({ info }: PageProps) {
  const list = useApi(() => methodologyApi.retros(info.project.id), [info.project.id]);
  const people = useApi(() => calendarApi.people(info.project.id), [info.project.id]);
  const [open, setOpen] = useState(true);
  if (list.error) return <ErrorNotice error={list.error} onRetry={list.reload} />;
  if (!list.data) return <Loading />;
  const rows = list.data.improvements.filter((i) => !open || !["done", "dropped"].includes(i.status));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="kpis">
        <Kpi label="Actions d'amélioration" value={list.data.improvements.length} />
        <Kpi label="Réalisées" value={`${list.data.rate ?? 0} %`} tone="ok" />
        <Kpi
          label="En retard"
          value={list.data.improvements.filter((i) => i.late).length}
          tone={list.data.improvements.some((i) => i.late) ? "crit" : ""}
        />
      </div>
      <label className="cal-check">
        <input type="checkbox" checked={open} onChange={(e) => setOpen(e.target.checked)} /> Seulement les actions
        ouvertes
      </label>
      <Card
        title="Suivi des actions d'amélioration"
        sub="Chaque décision est aussi une action PCT : la terminer dans PCT la marque réalisée."
      >
        <table className="tbl tight">
          <thead>
            <tr>
              <th>Action</th>
              <th>Responsable</th>
              <th>Échéance</th>
              <th>Priorité</th>
              <th>Statut</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((i) => (
              <ImprovementRow
                key={i.id}
                i={i}
                people={people.data ?? []}
                editable={info.can.plan}
                onSaved={list.reload}
              />
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={5} className="muted">
                  Aucune action.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

type Reports = {
  weeks?: { weekStart: string; statusLabel: string; rate: number; plannedHours: number; consumedHours: number }[];
  phases?: { id: number; name: string; progress: number; statusLabel: string; status: string }[];
  velocity?: { sprints: { number: number; committed: number; completed: number }[]; average: number | null };
  sprints?: {
    id: number;
    label: string;
    committedPoints: number | null;
    completedPoints: number | null;
    goalStatus: string | null;
    statusLabel: string;
  }[];
  retros: { count: number; closed: number; improvements: number; improvementsDone: number; late: number };
  capacity: { start: string; available: number; planned: number }[];
};

/** Rapports : semaines, phases, vélocité, objectifs de sprint, rétrospectives, capacité historisée. */
export function MethodologyReportsPage({ info }: PageProps) {
  const r = useApi(
    () => methodologyApi.reports(info.project.id) as Promise<unknown> as Promise<Reports>,
    [info.project.id],
  );
  if (r.error) return <ErrorNotice error={r.error} onRetry={r.reload} />;
  if (!r.data) return <Loading />;
  const d = r.data;
  return (
    <div className="grid g2">
      {d.weeks && (
        <Card title="Réalisation hebdomadaire">
          {d.weeks.length ? (
            <BarChart
              labels={d.weeks.map((w) => fmt(w.weekStart))}
              series={[{ name: "Réalisation %", values: d.weeks.map((w) => w.rate), color: COLORS.a }]}
            />
          ) : (
            <p className="muted">Aucune semaine planifiée.</p>
          )}
        </Card>
      )}
      {d.phases && (
        <Card title="Avancement des phases">
          <ul className="phase-list">
            {d.phases.map((p) => (
              <li key={p.id}>
                <span className="ph-name">{p.name}</span>
                <span className="bar-mini">
                  <i style={{ width: `${p.progress}%` }} />
                </span>
                <Status value={p.status} label={p.statusLabel} />
              </li>
            ))}
          </ul>
        </Card>
      )}
      {d.velocity && (
        <Card title="Vélocité" sub={`Moyenne : ${d.velocity.average ?? "—"}`}>
          <BarChart
            labels={d.velocity.sprints.map((s) => `S${s.number}`)}
            series={[
              { name: "Engagé", values: d.velocity.sprints.map((s) => s.committed), color: COLORS.d },
              { name: "Réalisé", values: d.velocity.sprints.map((s) => s.completed), color: COLORS.a },
            ]}
          />
        </Card>
      )}
      {d.sprints && (
        <Card title="Objectifs de sprint">
          <table className="tbl tight">
            <tbody>
              {d.sprints.map((s) => (
                <tr key={s.id}>
                  <td>{s.label}</td>
                  <td>{s.statusLabel}</td>
                  <td className="r">
                    {s.completedPoints ?? "—"} / {s.committedPoints ?? "—"} pts
                  </td>
                  <td>{s.goalStatus ? <Status value={s.goalStatus} /> : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      <Card title="Rétrospectives et amélioration continue">
        <p>
          {d.retros.closed}/{d.retros.count} rétrospective(s) clôturée(s) · {d.retros.improvementsDone}/
          {d.retros.improvements} action(s) réalisée(s) · {d.retros.late} en retard
        </p>
      </Card>
      <Card
        title="Capacité historisée"
        sub="Instantanés enregistrés à la validation des semaines et au démarrage des sprints."
      >
        {d.capacity.length ? (
          <BarChart
            labels={d.capacity.map((c) => fmt(c.start))}
            series={[
              { name: "Disponible", values: d.capacity.map((c) => c.available), color: COLORS.a },
              { name: "Planifié", values: d.capacity.map((c) => c.planned), color: COLORS.b },
            ]}
          />
        ) : (
          <p className="muted">Aucun instantané pour l'instant.</p>
        )}
      </Card>
    </div>
  );
}
