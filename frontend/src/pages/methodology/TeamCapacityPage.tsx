import { useState } from "react";

import { calendarApi } from "../../api/collab";
import { methodologyApi } from "../../api/methodology";
import { useApi, type Loadable } from "../../api/useApi";
import { Card, ErrorNotice, Loading, useAction } from "../../components/ui";
import { BarChart, COLORS, fmt, Kpi, Status } from "../../features/methodology/shared";
import type { Allocation } from "../../types/methodology";
import type { PageProps } from "./types";

const iso = (d: Date) => d.toISOString().slice(0, 10);
const mondayOf = (d: Date) => {
  const x = new Date(d);
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7));
  return x;
};

/** Capacité réelle : disponibilités, affectations, charge planifiée et consommée, surcharges. */
export function TeamCapacityPage({ info }: PageProps) {
  const id = info.project.id;
  const [start, setStart] = useState(() => iso(mondayOf(new Date())));
  const [span, setSpan] = useState(5);
  const end = iso(new Date(new Date(`${start}T12:00`).getTime() + (span - 1) * 864e5));
  const c = useApi(() => methodologyApi.capacity(id, start, end), [id, start, end]);
  const allocs = useApi(() => methodologyApi.allocations(id), [id]);
  const av = useApi(() => methodologyApi.availabilities({ project: id, start, end }), [id, start, end]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="disc-filter">
        <label>
          À partir du <input className="inp" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <div className="seg">
          {[
            [5, "Semaine"],
            [12, "2 semaines"],
            [26, "4 semaines"],
          ].map(([n, l]) => (
            <button key={n} className={span === n ? "on" : ""} onClick={() => setSpan(Number(n))}>
              {l}
            </button>
          ))}
        </div>
      </div>
      {c.error && <ErrorNotice error={c.error} onRetry={c.reload} />}
      {!c.data && !c.error && <Loading />}
      {c.data && (
        <>
          <div className="kpis cap-kpis">
            <Kpi label="Capacité théorique" value={`${c.data.totals.theoretical} h`} />
            <Kpi
              label="Capacité disponible"
              value={`${c.data.totals.productive} h`}
              sub={`productivité ${Math.round(c.data.productiveRatio * 100)} %`}
            />
            <Kpi label="Charge planifiée" value={`${c.data.totals.planned} h`} />
            <Kpi label="Charge consommée" value={`${c.data.totals.consumed} h`} />
            <Kpi
              label="Taux d'utilisation"
              value={`${c.data.totals.utilization} %`}
              tone={c.data.totals.utilization > 100 ? "crit" : ""}
            />
            <Kpi
              label="Capacité restante"
              value={`${c.data.totals.remaining} h`}
              tone={c.data.totals.remaining < 0 ? "crit" : "ok"}
            />
            <Kpi
              label="Surchargés"
              value={c.data.overloaded.length}
              tone={c.data.overloaded.length ? "crit" : ""}
              sub={c.data.overloaded.map((u) => u.name).join(", ")}
            />
            <Kpi
              label="Sous-utilisés"
              value={c.data.underUsed.length}
              sub={c.data.underUsed.map((u) => u.name).join(", ")}
            />
          </div>
          {c.data.weeks && c.data.weeks.length > 1 && (
            <Card title="Capacité par semaine">
              <BarChart
                labels={c.data.weeks.map((w) => fmt(w.week))}
                series={[
                  { name: "Disponible", values: c.data.weeks.map((w) => w.productive), color: COLORS.a },
                  { name: "Planifié", values: c.data.weeks.map((w) => w.planned), color: COLORS.b },
                  { name: "Consommé", values: c.data.weeks.map((w) => w.consumed), color: COLORS.d },
                ]}
              />
            </Card>
          )}
          <Card
            title="Capacité par collaborateur"
            sub="Disponible = théorique − absences − congés − indisponibilités − réunions, sans double déduction."
          >
            <div className="tbl-wrap">
              <table className="tbl tight">
                <thead>
                  <tr>
                    <th>Collaborateur</th>
                    <th className="r">Affect.</th>
                    <th className="r">Théorique</th>
                    <th className="r">Indispo.</th>
                    <th className="r">Réunions</th>
                    <th className="r">Disponible</th>
                    <th className="r">Planifié</th>
                    <th className="r">Consommé</th>
                    <th className="r">Autres projets</th>
                    <th>Utilisation</th>
                    <th>Jours</th>
                  </tr>
                </thead>
                <tbody>
                  {c.data.members.map((m) => (
                    <tr key={m.user.id}>
                      <td>
                        <b>{m.user.name}</b>
                        <div className="muted">{[m.role, m.scrumRole.toUpperCase()].filter(Boolean).join(" · ")}</div>
                      </td>
                      <td className="r">{m.allocationPct} %</td>
                      <td className="r">{m.theoretical}</td>
                      <td className="r">{m.unavailable}</td>
                      <td className="r">{m.meetings}</td>
                      <td className="r">
                        <b>{m.productive}</b>
                      </td>
                      <td className="r">{m.planned}</td>
                      <td className="r">{m.consumed}</td>
                      <td className="r muted">{m.otherProjects}</td>
                      <td>
                        <div className="util">
                          <i className={m.state} style={{ width: `${Math.min(m.utilization, 150) / 1.5}%` }} />
                        </div>
                        <Status
                          value={m.state}
                          label={
                            m.state === "over"
                              ? `${m.utilization} % · surcharge`
                              : m.state === "under"
                                ? `${m.utilization} % · sous-utilisé`
                                : `${m.utilization} %`
                          }
                        />
                      </td>
                      <td>
                        <div className="days-strip" aria-label={`Disponibilités de ${m.user.name}`}>
                          {Object.entries(m.perDay).map(([d, h]) => (
                            <span
                              key={d}
                              className={h === 0 ? "off" : ""}
                              title={`${fmt(d)} : ${h} h`}
                              style={{ opacity: 0.35 + Math.min(h / Math.max(m.hoursPerDay, 1), 1) * 0.65 }}
                            />
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {!c.data.members.length && (
                    <tr>
                      <td colSpan={11} className="muted">
                        Aucune affectation : ajoutez l'équipe ci-dessous.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
      <div className="grid g2">
        <Allocations projectId={id} allocs={allocs} canEdit={info.can.capacity} onChange={c.reload} />
        <Availabilities projectId={id} av={av} canEdit={info.can.capacity} onChange={() => (av.reload(), c.reload())} />
      </div>
    </div>
  );
}

function Allocations({
  projectId,
  allocs,
  canEdit,
  onChange,
}: {
  projectId: string;
  allocs: Loadable<Allocation[]>;
  canEdit: boolean;
  onChange: () => void;
}) {
  const people = useApi(() => calendarApi.people(projectId), [projectId]);
  const { run, busy } = useAction();
  const save = (a: Allocation, patch: Partial<Allocation>) =>
    void run(() => methodologyApi.saveAllocation(a.id, patch), "Affectation enregistrée").then(
      () => (allocs.reload(), onChange()),
      () => undefined,
    );
  if (allocs.error) return <ErrorNotice error={allocs.error} />;
  return (
    <Card
      title="Équipe et affectations"
      sub="Taux d'affectation, heures par jour, jours travaillés, réunions récurrentes. Rôles Scrum indépendants des droits PCT."
    >
      <div className="tbl-wrap">
        <table className="tbl tight">
          <thead>
            <tr>
              <th>Collaborateur</th>
              <th>Rôle Scrum</th>
              <th className="r">%</th>
              <th className="r">h/j</th>
              <th className="r">j/sem</th>
              <th className="r">Réunions h/sem</th>
            </tr>
          </thead>
          <tbody>
            {(allocs.data ?? [])
              .filter((a) => a.active)
              .map((a) => (
                <tr key={a.id}>
                  <td>
                    {a.user.name}
                    <div className="muted">{a.projectRole}</div>
                  </td>
                  <td>
                    <select
                      className="inp"
                      aria-label={`Rôle Scrum de ${a.user.name}`}
                      disabled={!canEdit}
                      value={a.scrumRole}
                      onChange={(e) => save(a, { scrumRole: e.target.value })}
                    >
                      <option value="">—</option>
                      <option value="po">Product Owner</option>
                      <option value="sm">Scrum Master</option>
                      <option value="dev">Developer</option>
                    </select>
                  </td>
                  {(["allocationPct", "hoursPerDay", "daysPerWeek", "meetingHoursPerWeek"] as const).map((k) => (
                    <td key={k} className="r">
                      <input
                        className="inp num"
                        type="number"
                        aria-label={`${k} de ${a.user.name}`}
                        disabled={!canEdit}
                        defaultValue={a[k]}
                        onBlur={(e) => Number(e.target.value) !== a[k] && save(a, { [k]: Number(e.target.value) })}
                      />
                    </td>
                  ))}
                </tr>
              ))}
          </tbody>
        </table>
      </div>
      {canEdit && (
        <select
          className="inp"
          aria-label="Ajouter un collaborateur à l'équipe"
          value=""
          disabled={busy}
          onChange={(e) =>
            e.target.value &&
            void run(
              () => methodologyApi.addAllocation(projectId, { user: Number(e.target.value), allocationPct: 100 }),
              "Collaborateur ajouté",
            ).then(
              () => (allocs.reload(), onChange()),
              () => undefined,
            )
          }
        >
          <option value="">+ Ajouter un collaborateur…</option>
          {(people.data ?? [])
            .filter((p) => !(allocs.data ?? []).some((a) => a.user.id === p.id && a.active))
            .map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
        </select>
      )}
    </Card>
  );
}

function Availabilities({
  projectId,
  av,
  canEdit,
  onChange,
}: {
  projectId: string;
  av: Loadable<Awaited<ReturnType<typeof methodologyApi.availabilities>>>;
  canEdit: boolean;
  onChange: () => void;
}) {
  const people = useApi(() => calendarApi.people(projectId), [projectId]);
  const { run, busy } = useAction();
  const [f, setF] = useState({ user: "", kind: "leave", start: "", end: "", hours: "", note: "" });
  return (
    <Card
      title="Congés, absences et indisponibilités"
      sub="Chacun déclare les siennes ; jours fériés : toute l'entreprise."
    >
      <table className="tbl tight">
        <tbody>
          {(av.data?.rows ?? []).map((a) => (
            <tr key={a.id}>
              <td>{a.user?.name ?? <i>Toute l'entreprise</i>}</td>
              <td>{a.kindLabel}</td>
              <td className="mono">
                {fmt(a.start)} → {fmt(a.end)}
              </td>
              <td>{a.hours == null ? "journée" : `${a.hours} h/j`}</td>
              <td className="muted">{a.note}</td>
              <td className="r">
                {(a.mine || canEdit) && (
                  <button
                    className="btn sm ghost"
                    onClick={() =>
                      void run(() => methodologyApi.removeAvailability(a.id), "Supprimé").then(
                        onChange,
                        () => undefined,
                      )
                    }
                  >
                    Retirer
                  </button>
                )}
              </td>
            </tr>
          ))}
          {av.data && !av.data.rows.length && (
            <tr>
              <td className="muted">Aucune indisponibilité sur la période.</td>
            </tr>
          )}
        </tbody>
      </table>
      <div className="avail-form">
        <select
          className="inp"
          aria-label="Pour qui"
          value={f.user}
          onChange={(e) => setF({ ...f, user: e.target.value })}
        >
          <option value="">Moi</option>
          {canEdit &&
            (people.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
        </select>
        <select className="inp" aria-label="Type" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
          {(av.data?.kinds ?? []).map((k) => (
            <option key={k.code} value={k.code}>
              {k.label}
            </option>
          ))}
        </select>
        <input
          className="inp"
          type="date"
          aria-label="Du"
          value={f.start}
          onChange={(e) => setF({ ...f, start: e.target.value, end: f.end || e.target.value })}
        />
        <input
          className="inp"
          type="date"
          aria-label="Au"
          value={f.end}
          onChange={(e) => setF({ ...f, end: e.target.value })}
        />
        <input
          className="inp num"
          type="number"
          placeholder="h/j"
          aria-label="Heures par jour (vide : journée)"
          value={f.hours}
          onChange={(e) => setF({ ...f, hours: e.target.value })}
        />
        <input
          className="inp"
          placeholder="Note"
          aria-label="Note"
          value={f.note}
          onChange={(e) => setF({ ...f, note: e.target.value })}
        />
        <button
          className="btn sm primary"
          disabled={busy || !f.start}
          onClick={() =>
            void run(
              () =>
                methodologyApi.addAvailability({
                  ...f,
                  user: f.user ? Number(f.user) : undefined,
                  hours: f.hours || null,
                }),
              "Indisponibilité enregistrée",
            ).then(
              () => (setF({ ...f, start: "", end: "", hours: "", note: "" }), onChange()),
              () => undefined,
            )
          }
        >
          Ajouter
        </button>
      </div>
    </Card>
  );
}
