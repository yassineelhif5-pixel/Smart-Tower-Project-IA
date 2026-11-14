import { useMemo, useState } from "react";

import { calendarApi } from "../../api/collab";
import { methodologyApi } from "../../api/methodology";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Field, Loading, useAction } from "../../components/ui";
import type { Phase as BasePhase } from "../../types/methodology";

/** Phase avec son état actuel calculé d'après les tâches rattachées (live). */
type Phase = BasePhase & { live?: boolean; tasks?: number; tasksDone?: number; blocked?: number; manualProgress?: number; manualStatus?: string };
import { DetailedPlanning, PlanningAlerts, planningApi } from "../../features/planning/DetailedPlanning";
import type { PageProps } from "./types";

/** Phases types proposées pour démarrer un planning macro en Cycle en V. */
const V_TEMPLATE = [
  "Cadrage",
  "Spécifications",
  "Conception générale",
  "Conception détaillée",
  "Réalisation",
  "Tests d’intégration",
  "Recette (VABF)",
  "Mise en production (VSR)",
];
const STATUSES: [string, string][] = [
  ["todo", "Non démarré"],
  ["doing", "En cours"],
  ["done", "Terminé"],
  ["late", "En retard"],
  ["skipped", "Sans objet"],
];
const DAY = 86400000;
const toDate = (s: string) => new Date(`${s}T00:00:00`);
const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const fr = (s: string | null) => (s ? toDate(s).toLocaleDateString("fr-FR") : "—");
const addDays = (s: string, n: number) => iso(new Date(toDate(s).getTime() + n * DAY));

type Form = {
  name: string; start: string; end: string; forecastEnd: string; owner: string; status: string;
  progress: number; dependsOn: number[]; validationCriteria: string;
};
const EMPTY: Form = { name: "", start: "", end: "", forecastEnd: "", owner: "", status: "todo", progress: 0, dependsOn: [], validationCriteria: "" };

export function MacroPlanningPage({ info }: PageProps) {
  const id = info.project.id;
  const data = useApi(() => methodologyApi.phases(id), [id]);
  const people = useApi(() => calendarApi.people(id), [id]);
  const planning = useApi(() => planningApi(id), [id]);
  const { run, busy } = useAction();
  const [editing, setEditing] = useState<Phase | "new" | null>(null);
  const [form, setForm] = useState<Form>(EMPTY);
  const canEdit = info.can.edit;

  if (data.error) return <ErrorNotice error={data.error} onRetry={data.reload} />;
  if (!data.data) return <Loading />;
  const phases = [...(data.data.phases as Phase[])].sort((a, b) => a.order - b.order || a.id - b.id);
  const milestones = data.data.milestones ?? [];

  const open = (p: Phase | "new") => {
    setEditing(p);
    if (p === "new") {
      const last = phases.reduce<string | null>((m, ph) => (ph.end && (!m || ph.end > m) ? ph.end : m), null);
      const start = last ? addDays(last, 1) : info.project.start ?? iso(new Date());
      setForm({ ...EMPTY, start, end: addDays(start, 27), dependsOn: phases.length ? [phases[phases.length - 1].id] : [] });
    } else {
      setForm({
        name: p.name, start: p.start ?? "", end: p.end ?? "", forecastEnd: p.forecastEnd ?? "", owner: p.owner ? String(p.owner.id) : "",
        status: p.manualStatus ?? p.status, progress: p.manualProgress ?? p.progress, dependsOn: p.dependsOn, validationCriteria: p.validationCriteria,
      });
    }
  };
  const save = () => {
    const body = { ...form, owner: form.owner ? Number(form.owner) : null, forecastEnd: form.forecastEnd || null, start: form.start || null, end: form.end || null };
    return run(
      () => (editing === "new" || !editing ? methodologyApi.addPhase(id, body) : methodologyApi.savePhase(editing.id, body)),
      editing === "new" ? "Phase ajoutée" : "Phase enregistrée",
    ).then(() => (setEditing(null), data.reload(), planning.reload()), () => undefined);
  };
  const createTemplate = async () => {
    let start = info.project.start ?? iso(new Date());
    let prev: number | null = null;
    for (const name of V_TEMPLATE) {
      const end = addDays(start, 27);
      try {
        const created: Phase | undefined = await run(() =>
          methodologyApi.addPhase(id, { name, start, end, dependsOn: prev ? [prev] : [] }),
        );
        prev = created?.id ?? prev;
      } catch {
        break;
      }
      start = addDays(end, 1);
    }
    data.reload();
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="pl-head no-print">
        <a className="btn sm" href={`#projets/${encodeURIComponent(id)}/config`} title="Modifier le projet">
          ⚙ Paramètres du projet
        </a>
      </div>
      {planning.data && <PlanningAlerts alerts={planning.data.alerts} />}
      <Card
        title="Planning macro"
        sub="État actuel du projet : l’avancement et le statut de chaque phase se recalculent à chaque changement de statut des tâches rattachées. Hachures : glissement ; ligne violette : aujourd’hui."
        extra={
          canEdit && (
            <button className="btn primary" type="button" onClick={() => open("new")}>
              + Ajouter une phase
            </button>
          )
        }
      >
        {phases.length === 0 ? (
          <div className="empty">
            <p>Aucune phase pour ce projet.</p>
            {canEdit && (
              <button className="btn" type="button" disabled={busy} onClick={createTemplate}>
                Proposer les phases types du Cycle en V
              </button>
            )}
          </div>
        ) : (
          <Gantt phases={phases} milestones={milestones} projectStart={info.project.start} projectEnd={info.project.end} onPick={canEdit ? open : undefined} />
        )}
      </Card>

      {editing && (
        <Card title={editing === "new" ? "Nouvelle phase" : `Modifier « ${editing.name} »`}>
          <div className="ev-form">
            <div className="grid g2">
              <Field id="ph-name" label="Phase *">
                <input id="ph-name" className="inp" maxLength={120} autoFocus value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </Field>
              <Field id="ph-owner" label="Responsable">
                <select id="ph-owner" className="inp" value={form.owner} onChange={(e) => setForm({ ...form, owner: e.target.value })}>
                  <option value="">Non désigné</option>
                  {(people.data ?? []).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <div className="grid g3">
              <Field id="ph-start" label="Début">
                <input id="ph-start" className="inp" type="date" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} />
              </Field>
              <Field id="ph-end" label="Fin prévue">
                <input id="ph-end" className="inp" type="date" min={form.start || undefined} value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} />
              </Field>
              <Field id="ph-fend" label="Fin réestimée">
                <input id="ph-fend" className="inp" type="date" min={form.start || undefined} value={form.forecastEnd} onChange={(e) => setForm({ ...form, forecastEnd: e.target.value })} />
              </Field>
            </div>
            <div className="grid g2">
              <Field id="ph-status" label="Statut">
                <select id="ph-status" className="inp" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  {STATUSES.map(([k, l]) => (
                    <option key={k} value={k}>
                      {l}
                    </option>
                  ))}
                </select>
              </Field>
              {editing !== "new" && editing.live ? (
                <Field id="ph-prog" label="Avancement">
                  <div className="muted" style={{ fontSize: 12.5, paddingTop: 8 }}>
                    Calculé automatiquement : {editing.progress} % ({editing.tasksDone}/{editing.tasks} tâches terminées). Rattachez les tâches à cette phase dans Mes projets › Tâches.
                  </div>
                </Field>
              ) : (
                <Field id="ph-prog" label={`Avancement : ${form.progress} %`}>
                  <input id="ph-prog" type="range" min={0} max={100} step={5} value={form.progress} onChange={(e) => setForm({ ...form, progress: Number(e.target.value) })} />
                </Field>
              )}
            </div>
            {phases.filter((p) => editing === "new" || p.id !== editing.id).length > 0 && (
              <div className="ng-phases">
                <span className="muted">Dépend de :</span>
                {phases
                  .filter((p) => editing === "new" || p.id !== editing.id)
                  .map((p) => {
                    const on = form.dependsOn.includes(p.id);
                    return (
                      <label key={p.id} className={`chip-toggle${on ? " on" : ""}`}>
                        <input type="checkbox" checked={on}
                          onChange={() => setForm({ ...form, dependsOn: on ? form.dependsOn.filter((x) => x !== p.id) : [...form.dependsOn, p.id] })} />
                        {p.name}
                      </label>
                    );
                  })}
              </div>
            )}
            <Field id="ph-crit" label="Critères de validation de fin de phase">
              <textarea id="ph-crit" className="inp" rows={2} value={form.validationCriteria} onChange={(e) => setForm({ ...form, validationCriteria: e.target.value })} />
            </Field>
            <div className="btns" style={{ justifyContent: "space-between" }}>
              <span>
                {editing !== "new" && (
                  <button className="btn danger" type="button" disabled={busy}
                    onClick={() => run(() => methodologyApi.deletePhase(editing.id), "Phase supprimée").then(() => (setEditing(null), data.reload()), () => undefined)}>
                    Supprimer
                  </button>
                )}
              </span>
              <span className="btns">
                <button className="btn ghost" type="button" onClick={() => setEditing(null)}>
                  Annuler
                </button>
                <button className="btn primary" type="button" disabled={busy || !form.name.trim()} onClick={save}>
                  Enregistrer
                </button>
              </span>
            </div>
          </div>
        </Card>
      )}

      {phases.length > 0 && (
        <Card title="Détail des phases">
          <div className="tbl-wrap">
            <table className="tbl tight">
              <thead>
                <tr>
                  <th>Phase</th>
                  <th>Responsable</th>
                  <th>Début</th>
                  <th>Fin prévue</th>
                  <th>Fin réestimée</th>
                  <th>Statut</th>
                  <th className="r">Avancement</th>
                  <th>Tâches</th>
                  {canEdit && <th />}
                </tr>
              </thead>
              <tbody>
                {phases.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <b>{p.name}</b>
                    </td>
                    <td>{p.owner?.name ?? <span className="faint">—</span>}</td>
                    <td>{fr(p.start)}</td>
                    <td>{fr(p.end)}</td>
                    <td className={p.forecastEnd && p.end && p.forecastEnd > p.end ? "t-crit" : ""}>{fr(p.forecastEnd)}</td>
                    <td>
                      <span className={`gt-st gt-${p.status}`}>{p.statusLabel}</span>
                    </td>
                    <td className="r">{p.progress} %</td>
                    <td>{p.live ? `${p.tasksDone}/${p.tasks}` : <span className="faint">manuel</span>}</td>
                    {canEdit && (
                      <td className="r">
                        <button className="btn sm" type="button" onClick={() => open(p)}>
                          Modifier
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      {planning.error && <ErrorNotice error={planning.error} onRetry={planning.reload} />}
      {planning.data && <DetailedPlanning data={planning.data} />}
    </div>
  );
}

type Milestone = { id: number; title: string; date: string; status: string; phase?: string };

function Gantt({
  phases, milestones, projectStart, projectEnd, onPick,
}: {
  phases: Phase[]; milestones: Milestone[]; projectStart: string | null; projectEnd: string | null; onPick?: (p: Phase) => void;
}) {
  const range = useMemo(() => {
    const dates = [
      ...phases.flatMap((p) => [p.start, p.end, p.forecastEnd]),
      ...milestones.map((m) => String(m.date).slice(0, 10)),
      projectStart, projectEnd,
    ].filter(Boolean) as string[];
    if (!dates.length) return null;
    const min = toDate(dates.reduce((a, b) => (a < b ? a : b)));
    const max = toDate(dates.reduce((a, b) => (a > b ? a : b)));
    const from = new Date(min.getFullYear(), min.getMonth(), 1);
    const to = new Date(max.getFullYear(), max.getMonth() + 1, 0);
    const months: Date[] = [];
    for (let d = new Date(from); d <= to; d = new Date(d.getFullYear(), d.getMonth() + 1, 1)) months.push(d);
    return { from: from.getTime(), span: to.getTime() + DAY - from.getTime(), months };
  }, [phases, milestones, projectStart, projectEnd]);

  if (!range) return <div className="empty">Renseignez les dates des phases pour afficher le Gantt.</div>;
  const pos = (s: string) => ((toDate(s).getTime() - range.from) / range.span) * 100;
  const width = (a: string, b: string) => Math.max(0.8, ((toDate(b).getTime() + DAY - toDate(a).getTime()) / range.span) * 100);
  const today = iso(new Date());
  const todayPos = pos(today);

  return (
    <div className="gt" role="img" aria-label="Diagramme de Gantt du planning macro">
      <div className="gt-head">
        <div className="gt-label" />
        <div className="gt-track">
          {range.months.map((m) => (
            <span key={m.getTime()} style={{ left: `${pos(iso(m))}%`, width: `${width(iso(m), iso(new Date(m.getFullYear(), m.getMonth() + 1, 0)))}%` }}>
              {m.toLocaleDateString("fr-FR", { month: "short", year: range.months.length > 12 ? "2-digit" : undefined })}
            </span>
          ))}
        </div>
      </div>
      {phases.map((p) => {
        const late = p.forecastEnd && p.end && p.forecastEnd > p.end;
        return (
          <div key={p.id} className={`gt-row${onPick ? " click" : ""}`} onClick={() => onPick?.(p)}>
            <div className="gt-label">
              <b>{p.name}</b>
              <small>
                {fr(p.start)} → {fr(p.end)} · {p.progress} %
                {p.live ? ` · ${p.tasksDone}/${p.tasks} tâches` : ""}
                {p.blocked ? ` · ${p.blocked} bloquée(s)` : ""}
              </small>
            </div>
            <div className="gt-track">
              {todayPos >= 0 && todayPos <= 100 && <i className="gt-today" style={{ left: `${todayPos}%` }} />}
              {p.start && p.end ? (
                <>
                  <span className={`gt-bar gt-${p.status}`} style={{ left: `${pos(p.start)}%`, width: `${width(p.start, p.end)}%` }} title={`${p.name} · ${p.statusLabel}`}>
                    <em style={{ width: `${p.progress}%` }} />
                  </span>
                  {late && <span className="gt-slip" style={{ left: `${pos(addDays(p.end!, 1))}%`, width: `${width(addDays(p.end!, 1), p.forecastEnd!)}%` }} title={`Fin réestimée ${fr(p.forecastEnd)}`} />}
                </>
              ) : (
                <span className="gt-nodate">Dates à renseigner</span>
              )}
            </div>
          </div>
        );
      })}
      {milestones.length > 0 && (
        <div className="gt-row">
          <div className="gt-label">
            <b>Jalons</b>
          </div>
          <div className="gt-track">
            {todayPos >= 0 && todayPos <= 100 && <i className="gt-today" style={{ left: `${todayPos}%` }} />}
            {milestones.map((m) => (
              <span key={m.id} className="gt-ms" style={{ left: `${pos(String(m.date).slice(0, 10))}%` }} title={`${m.title} · ${fr(String(m.date).slice(0, 10))}`} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
