import { useEffect, useState } from "react";

import { calendarApi } from "../../api/collab";
import { useApi } from "../../api/useApi";
import { Field, fmtDate, Icon, Modal, Pill, useAction } from "../../components/ui";
import type {
  AssignmentRole,
  CalendarEvent,
  EventInput,
  EventKind,
  EventStatus,
  Person,
  Priority,
  ProjectRef,
} from "../../types/collab";
import { DiscussionPanel } from "../collaboration/DiscussionPanel";
import { iso, isoLocal, KIND_LABEL, PRIORITY_LABEL, STATUS_LABEL } from "./calendarUtils";

type Draft = {
  project: string;
  kind: EventKind;
  title: string;
  description: string;
  phase: string;
  allDay: boolean;
  start: string;
  end: string;
  timezone: string;
  status: EventStatus;
  priority: Priority;
  progress: number;
  assignments: { user: number; role: AssignmentRole; estimatedWorkload: string }[];
  dependencies: { predecessor: number; type: string }[];
};

const ZONES = [
  "Europe/Paris",
  "Europe/London",
  "Europe/Brussels",
  "Africa/Casablanca",
  "Africa/Tunis",
  "America/New_York",
  "America/Montreal",
  "Asia/Dubai",
  "UTC",
];

function draftOf(e: CalendarEvent | null, preset: Partial<Draft>): Draft {
  if (!e) {
    const today = iso(new Date());
    return {
      project: "",
      kind: "task",
      title: "",
      description: "",
      phase: "",
      allDay: true,
      start: today,
      end: today,
      timezone: "Europe/Paris",
      status: "planned",
      priority: "normal",
      progress: 0,
      assignments: [],
      dependencies: [],
      ...preset,
    };
  }
  return {
    project: e.project?.id ?? "",
    kind: e.kind,
    title: e.title,
    description: e.description,
    phase: e.phase,
    allDay: e.allDay,
    start: e.allDay ? e.startDate : isoLocal(new Date(e.start)),
    end: e.allDay ? e.endDate : isoLocal(new Date(e.end)),
    timezone: e.timezone,
    status: e.status,
    priority: e.priority,
    progress: e.progress,
    assignments: e.assignments.map((a) => ({
      user: a.user.id,
      role: a.role,
      estimatedWorkload: a.estimatedWorkload == null ? "" : String(a.estimatedWorkload),
    })),
    dependencies: e.dependencies.map((d) => ({ predecessor: d.predecessor, type: d.type })),
  };
}

/** Création et modification d'un événement : dates, affectations multiples, charge, dépendances, rappels. */
export function CalendarEventModal({
  event,
  preset,
  projects,
  others,
  onSave,
  onDelete,
  onClose,
}: {
  event: CalendarEvent | null;
  preset?: Partial<Draft>;
  projects: ProjectRef[];
  others: CalendarEvent[];
  onSave: (input: EventInput) => Promise<boolean>;
  onDelete: () => Promise<void>;
  onClose: () => void;
}) {
  const [d, setD] = useState<Draft>(() => draftOf(event, preset ?? {}));
  const [tab, setTab] = useState<"detail" | "discussion" | "reminders">("detail");
  const [actual, setActual] = useState("");
  const [saving, setSaving] = useState(false);
  const full = !event || event.canEdit;
  const quick = !!event && !event.canEdit && event.canUpdateProgress;
  const people = useApi(() => calendarApi.people(d.project || undefined), [d.project]);
  const set = (patch: Partial<Draft>) => setD((x) => ({ ...x, ...patch }));

  useEffect(() => {
    // Passage journée entière <-> horaire : on garde la date, on ajoute ou retire l'heure.
    setD((x) =>
      x.allDay
        ? { ...x, start: x.start.slice(0, 10), end: x.end.slice(0, 10) }
        : {
            ...x,
            start: x.start.length === 10 ? `${x.start}T09:00` : x.start,
            end: x.end.length === 10 ? `${x.end}T10:00` : x.end,
          },
    );
  }, [d.allDay]);

  const submit = async () => {
    setSaving(true);
    const input: EventInput = quick
      ? { status: d.status, progress: Number(d.progress), ...(actual ? { actualWorkload: Number(actual) } : {}) }
      : {
          ...(event ? {} : { project: d.project || null, kind: d.kind }),
          kind: d.kind,
          title: d.title,
          description: d.description,
          phase: d.phase,
          allDay: d.allDay,
          // Heures saisies dans le fuseau du navigateur : envoyées comme instant UTC explicite.
          start: d.allDay ? d.start : new Date(d.start).toISOString(),
          end: d.allDay ? d.end : new Date(d.end).toISOString(),
          timezone: d.timezone,
          status: d.status,
          priority: d.priority,
          progress: Number(d.progress),
          assignments: d.assignments.map((a) => ({
            user: a.user,
            role: a.role,
            estimatedWorkload: a.estimatedWorkload === "" ? null : Number(a.estimatedWorkload),
          })),
          dependencies: d.dependencies,
        };
    const ok = await onSave(input).finally(() => setSaving(false));
    if (ok) onClose();
  };

  const addPerson = (p: Person) => {
    if (d.assignments.some((a) => a.user === p.id)) return;
    set({
      assignments: [
        ...d.assignments,
        {
          user: p.id,
          role: d.assignments.some((a) => a.role === "owner") ? "contributor" : "owner",
          estimatedWorkload: "",
        },
      ],
    });
  };
  const personName = (id: number) =>
    people.data?.find((p) => p.id === id)?.name ??
    event?.assignments.find((a) => a.user.id === id)?.user.name ??
    `#${id}`;

  return (
    <Modal
      wide
      title={event ? event.title : "Nouvel événement"}
      onClose={onClose}
      footer={
        tab === "detail" && (
          <>
            {event?.canDelete && (
              <button className="btn danger" style={{ marginRight: "auto" }} onClick={() => void onDelete()}>
                <Icon name="trash" size={15} /> Supprimer
              </button>
            )}
            <button className="btn" onClick={onClose}>
              Fermer
            </button>
            {(full || quick) && (
              <button
                className="btn primary"
                onClick={() => void submit()}
                disabled={saving || (full && !d.title.trim())}
              >
                {saving ? "Enregistrement…" : "Enregistrer"}
              </button>
            )}
          </>
        )
      }
    >
      {event && (
        <div className="tabs" role="tablist" style={{ marginBottom: 14 }}>
          {(
            [
              ["detail", "Détail"],
              ["discussion", "Discussion"],
              ["reminders", "Rappels"],
            ] as const
          ).map(([k, l]) => (
            <button
              key={k}
              role="tab"
              aria-selected={tab === k}
              className={tab === k ? "on" : ""}
              onClick={() => setTab(k)}
            >
              {l}
            </button>
          ))}
        </div>
      )}
      {tab === "discussion" && event?.project && (
        <DiscussionPanel project={event.project.id} action={event.action?.id ?? null} compact />
      )}
      {tab === "discussion" && event && !event.project && (
        <p className="muted">Discussion disponible pour les événements d'un projet.</p>
      )}
      {tab === "reminders" && event && <Reminders event={event} />}
      {tab === "detail" && (
        <div className="ev-form">
          {event?.late && (
            <div className="callout warn">
              <b>En retard</b> — l'échéance est dépassée et l'élément n'est pas terminé.
            </div>
          )}
          {quick && (
            <div className="notice">
              Vous êtes affecté à cet élément : vous pouvez mettre à jour son statut, son avancement et votre temps
              passé.
            </div>
          )}
          <div className="grid g2">
            <Field id="ev-title" label="Titre">
              <input
                id="ev-title"
                className="inp"
                value={d.title}
                disabled={!full}
                onChange={(e) => set({ title: e.target.value })}
              />
            </Field>
            <Field id="ev-project" label="Projet">
              <select
                id="ev-project"
                className="inp"
                value={d.project}
                disabled={!!event}
                onChange={(e) => set({ project: e.target.value, assignments: [] })}
              >
                <option value="">Hors projet (personnel)</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.code} — {p.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field id="ev-kind" label="Type">
              <select
                id="ev-kind"
                className="inp"
                value={d.kind}
                disabled={!full || d.kind === "action"}
                onChange={(e) => set({ kind: e.target.value as EventKind })}
              >
                {Object.entries(KIND_LABEL)
                  .filter(([k]) => k !== "action" || d.kind === "action")
                  .map(([k, l]) => (
                    <option key={k} value={k}>
                      {l}
                    </option>
                  ))}
              </select>
            </Field>
            <Field id="ev-phase" label="Phase">
              <input
                id="ev-phase"
                className="inp"
                value={d.phase}
                disabled={!full}
                onChange={(e) => set({ phase: e.target.value })}
              />
            </Field>
          </div>
          <div className="ev-dates">
            <label className="cal-check">
              <input
                type="checkbox"
                checked={d.allDay}
                disabled={!full}
                onChange={(e) => set({ allDay: e.target.checked })}
              />{" "}
              Journée entière
            </label>
            <Field id="ev-start" label="Début">
              <input
                id="ev-start"
                className="inp"
                type={d.allDay ? "date" : "datetime-local"}
                value={d.start}
                disabled={!full}
                onChange={(e) => set({ start: e.target.value, end: e.target.value > d.end ? e.target.value : d.end })}
              />
            </Field>
            <Field id="ev-end" label={d.allDay ? "Fin (incluse)" : "Fin"}>
              <input
                id="ev-end"
                className="inp"
                type={d.allDay ? "date" : "datetime-local"}
                value={d.end}
                min={d.start}
                disabled={!full}
                onChange={(e) => set({ end: e.target.value })}
              />
            </Field>
            <Field id="ev-tz" label="Fuseau horaire">
              <select
                id="ev-tz"
                className="inp"
                value={d.timezone}
                disabled={!full}
                onChange={(e) => set({ timezone: e.target.value })}
              >
                {[...new Set([d.timezone, ...ZONES])].map((z) => (
                  <option key={z}>{z}</option>
                ))}
              </select>
            </Field>
          </div>
          <div className="grid g3">
            <Field id="ev-status" label="Statut">
              <select
                id="ev-status"
                className="inp"
                value={d.status}
                disabled={!full && !quick}
                onChange={(e) => set({ status: e.target.value as EventStatus })}
              >
                {Object.entries(STATUS_LABEL).map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
              </select>
            </Field>
            <Field id="ev-prio" label="Priorité">
              <select
                id="ev-prio"
                className="inp"
                value={d.priority}
                disabled={!full}
                onChange={(e) => set({ priority: e.target.value as Priority })}
              >
                {Object.entries(PRIORITY_LABEL).map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
              </select>
            </Field>
            <Field id="ev-progress" label={`Avancement : ${d.progress} %`}>
              <input
                id="ev-progress"
                type="range"
                min={0}
                max={100}
                step={5}
                value={d.progress}
                disabled={!full && !quick}
                onChange={(e) => set({ progress: Number(e.target.value) })}
              />
            </Field>
          </div>
          {quick && (
            <Field id="ev-actual" label="Mon temps passé (heures)">
              <input
                id="ev-actual"
                className="inp"
                type="number"
                min={0}
                step={0.5}
                value={actual}
                onChange={(e) => setActual(e.target.value)}
              />
            </Field>
          )}
          <Field id="ev-desc" label="Description">
            <textarea
              id="ev-desc"
              className="inp"
              rows={3}
              value={d.description}
              disabled={!full}
              onChange={(e) => set({ description: e.target.value })}
            />
          </Field>

          <h4 className="ev-sec">Affectations</h4>
          <table className="tbl tight">
            <thead>
              <tr>
                <th>Collaborateur</th>
                <th>Rôle</th>
                <th className="r">Charge estimée (h)</th>
                <th className="r">Réalisé (h)</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {d.assignments.map((a, i) => {
                const known = event?.assignments.find((x) => x.user.id === a.user);
                return (
                  <tr key={a.user}>
                    <td>{personName(a.user)}</td>
                    <td>
                      <select
                        className="inp"
                        value={a.role}
                        disabled={!full}
                        aria-label={`Rôle de ${personName(a.user)}`}
                        onChange={(e) => {
                          const role = e.target.value as AssignmentRole;
                          set({
                            assignments: d.assignments.map((x, j) =>
                              j === i
                                ? { ...x, role }
                                : role === "owner" && x.role === "owner"
                                  ? { ...x, role: "contributor" }
                                  : x,
                            ),
                          });
                        }}
                      >
                        <option value="owner">Responsable</option>
                        <option value="contributor">Contributeur</option>
                        <option value="reviewer">Relecteur</option>
                      </select>
                    </td>
                    <td className="r">
                      <input
                        className="inp"
                        type="number"
                        min={0}
                        step={0.5}
                        style={{ width: 90 }}
                        value={a.estimatedWorkload}
                        disabled={!full}
                        aria-label={`Charge estimée de ${personName(a.user)}`}
                        onChange={(e) =>
                          set({
                            assignments: d.assignments.map((x, j) =>
                              j === i ? { ...x, estimatedWorkload: e.target.value } : x,
                            ),
                          })
                        }
                      />
                    </td>
                    <td className="r mono">{known?.actualWorkload ?? "—"}</td>
                    <td className="r">
                      {full && (
                        <button
                          className="icon-btn"
                          aria-label={`Retirer ${personName(a.user)}`}
                          onClick={() => set({ assignments: d.assignments.filter((_, j) => j !== i) })}
                        >
                          <Icon name="x" size={14} />
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
              {!d.assignments.length && (
                <tr>
                  <td colSpan={5} className="muted">
                    Aucun collaborateur affecté.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          {full && (
            <select
              className="inp"
              aria-label="Ajouter un collaborateur"
              value=""
              onChange={(e) => {
                const p = people.data?.find((x) => x.id === Number(e.target.value));
                if (p) addPerson(p);
              }}
            >
              <option value="">+ Ajouter un collaborateur…</option>
              {(people.data ?? [])
                .filter((p) => !d.assignments.some((a) => a.user === p.id))
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                    {p.team ? ` — ${p.team}` : ""}
                  </option>
                ))}
            </select>
          )}

          <h4 className="ev-sec">Dépendances (doit suivre…)</h4>
          {d.dependencies.map((dep, i) => {
            const pred = others.find((o) => o.id === dep.predecessor);
            return (
              <div key={dep.predecessor} className="dep-row">
                <span>{pred ? `${pred.title} (${pred.endDate})` : `Élément #${dep.predecessor}`}</span>
                <select
                  className="inp"
                  value={dep.type}
                  disabled={!full}
                  aria-label="Type de dépendance"
                  onChange={(e) =>
                    set({ dependencies: d.dependencies.map((x, j) => (j === i ? { ...x, type: e.target.value } : x)) })
                  }
                >
                  <option value="FS">Fin → Début</option>
                  <option value="SS">Début → Début</option>
                  <option value="FF">Fin → Fin</option>
                  <option value="SF">Début → Fin</option>
                </select>
                {full && (
                  <button
                    className="icon-btn"
                    aria-label="Retirer la dépendance"
                    onClick={() => set({ dependencies: d.dependencies.filter((_, j) => j !== i) })}
                  >
                    <Icon name="x" size={14} />
                  </button>
                )}
              </div>
            );
          })}
          {full && (
            <select
              className="inp"
              aria-label="Ajouter une dépendance"
              value=""
              onChange={(e) =>
                e.target.value &&
                set({ dependencies: [...d.dependencies, { predecessor: Number(e.target.value), type: "FS" }] })
              }
            >
              <option value="">+ Ajouter un prédécesseur…</option>
              {others
                .filter(
                  (o) =>
                    o.id !== event?.id &&
                    !d.dependencies.some((x) => x.predecessor === o.id) &&
                    (!d.project || o.project?.id === d.project),
                )
                .map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.title} — {o.startDate} → {o.endDate}
                  </option>
                ))}
            </select>
          )}
          {event && (
            <p className="muted" style={{ fontSize: 12 }}>
              {event.action
                ? "Planning de l'action " + event.action.id + " : dates, statut et responsable y sont recopiés. "
                : ""}
              Créé par {event.createdBy ?? "—"}
              {event.completedAt ? ` · terminé le ${fmtDate(event.completedAt)}` : ""}
            </p>
          )}
        </div>
      )}
    </Modal>
  );
}

function Reminders({ event }: { event: CalendarEvent }) {
  const r = useApi(() => calendarApi.reminders(event.id), [event.id]);
  const { run, busy } = useAction();
  const [at, setAt] = useState(() => {
    const d = new Date(event.start);
    d.setDate(d.getDate() - 1);
    d.setHours(9, 0, 0, 0);
    return isoLocal(d < new Date() ? new Date(Date.now() + 36e5) : d);
  });
  const [channel, setChannel] = useState("inapp");
  return (
    <div className="ev-form">
      <p className="muted" style={{ marginTop: 0 }}>
        Rappels personnels pour cet élément. Le canal doit être activé par votre entreprise et dans vos préférences.
      </p>
      <table className="tbl tight">
        <tbody>
          {(r.data ?? []).map((x) => (
            <tr key={x.id}>
              <td>{fmtDate(x.remindAt)}</td>
              <td>{{ inapp: "Dans PCT", email: "E-mail", teams: "Teams" }[x.channel]}</td>
              <td>
                <Pill
                  tone={
                    x.status === "sent" ? "ok" : x.status === "failed" ? "crit" : x.status === "cancelled" ? "" : "info"
                  }
                >
                  {{ pending: "Prévu", sent: "Envoyé", failed: "Échec", cancelled: "Annulé" }[x.status] ?? x.status}
                </Pill>
                {x.error && <div className="muted">{x.error}</div>}
              </td>
              <td className="r">
                {x.status === "pending" && (
                  <button
                    className="btn sm ghost"
                    disabled={busy}
                    onClick={() =>
                      void run(() => calendarApi.cancelReminder(x.id), "Rappel annulé").then(r.reload, () => undefined)
                    }
                  >
                    Annuler
                  </button>
                )}
              </td>
            </tr>
          ))}
          {r.data && !r.data.length && (
            <tr>
              <td className="muted">Aucun rappel personnel.</td>
            </tr>
          )}
        </tbody>
      </table>
      <div className="dep-row">
        <input
          className="inp"
          type="datetime-local"
          aria-label="Date du rappel"
          value={at}
          onChange={(e) => setAt(e.target.value)}
        />
        <select
          className="inp"
          aria-label="Canal du rappel"
          value={channel}
          onChange={(e) => setChannel(e.target.value)}
        >
          <option value="inapp">Dans PCT</option>
          <option value="email">E-mail</option>
          <option value="teams">Teams</option>
        </select>
        <button
          className="btn sm"
          disabled={busy}
          onClick={() =>
            void run(
              () => calendarApi.addReminder(event.id, new Date(at).toISOString(), channel),
              "Rappel programmé",
            ).then(r.reload, () => undefined)
          }
        >
          Programmer
        </button>
      </div>
    </div>
  );
}
