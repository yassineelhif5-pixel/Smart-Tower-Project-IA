import { useState, type DragEvent } from "react";

import { methodologyApi } from "../../api/methodology";
import { useApi } from "../../api/useApi";
import { ErrorNotice, fmtDate, Loading, Modal, useAction } from "../../components/ui";
import { PRIORITY, SprintPicker, useSprint } from "../../features/methodology/shared";
import type { SprintEntry } from "../../types/methodology";
import type { PageProps } from "./types";

/** Sprint Board : colonnes configurables, glisser-déposer, affectation, blocages, historique. */
export function SprintBoardPage({ info }: PageProps) {
  const sp = useSprint(info.project.id);
  const s = useApi(() => (sp.id ? methodologyApi.sprint(sp.id) : Promise.resolve(null)), [sp.id]);
  const [drag, setDrag] = useState<number | null>(null);
  const [who, setWho] = useState("");
  const [detail, setDetail] = useState<SprintEntry | null>(null);
  const { run } = useAction();
  const move = (e: SprintEntry, body: Record<string, unknown>, ok?: string) =>
    void run(() => methodologyApi.moveEntry(e.id, body), ok).then(s.reload, s.reload);
  const drop = (column: string) => (ev: DragEvent) => {
    ev.preventDefault();
    const e = s.data?.items.find((x) => x.id === drag);
    if (e && e.column !== column) move(e, { column });
    setDrag(null);
  };
  const d = s.data;
  const editable = d ? ["planned", "active"].includes(d.sprint.status) : false;
  const people = d
    ? [...new Map(d.items.filter((e) => e.assignee).map((e) => [e.assignee!.id, e.assignee!])).values()]
    : [];
  const items = (d?.items ?? []).filter((e) => !who || String(e.assignee?.id ?? "") === who);
  const known = new Set(d?.columns.map((c) => c.key));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="cal-tools">
        {sp.list.data && <SprintPicker sprints={sp.list.data.sprints} value={sp.id} onChange={sp.setId} />}
        <select
          className="inp"
          aria-label="Filtrer par personne"
          value={who}
          onChange={(e) => setWho(e.target.value)}
          style={{ width: "auto" }}
        >
          <option value="">Tout le monde</option>
          {people.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </div>
      {d?.sprint.goal && (
        <div className="goal-banner">
          <span>Sprint Goal</span> {d.sprint.goal.objective} <em>{d.sprint.goal.statusLabel}</em>
        </div>
      )}
      {s.error && <ErrorNotice error={s.error} onRetry={s.reload} />}
      {sp.id && !d && !s.error && <Loading />}
      {d && (
        <div
          className="board"
          style={{ ["--cols" as string]: d.columns.length + (items.some((e) => !known.has(e.column)) ? 1 : 0) }}
        >
          {[
            ...d.columns,
            ...(items.some((e) => !known.has(e.column))
              ? [{ key: "__other", label: "Autres (colonne retirée)", done: false }]
              : []),
          ].map((c) => {
            const cards = items
              .filter((e) => (c.key === "__other" ? !known.has(e.column) : e.column === c.key))
              .sort((a, b) => a.order - b.order);
            return (
              <section
                key={c.key}
                className={`board-col ${c.done ? "done" : ""}`}
                onDragOver={(e) => editable && e.preventDefault()}
                onDrop={drop(c.key)}
                aria-label={c.label}
              >
                <header>
                  {c.label}{" "}
                  <span className="muted">
                    {cards.length} · {cards.reduce((s, e) => s + (e.points ?? 0), 0)} pts
                  </span>
                </header>
                {cards.map((e) => (
                  <article
                    key={e.id}
                    className={`board-card ${e.blocked ? "blocked" : ""}`}
                    draggable={editable}
                    onDragStart={() => setDrag(e.id)}
                  >
                    <button className="link" onClick={() => setDetail(e)}>
                      {e.item.key && <span className="mono muted">{e.item.key} </span>}
                      {e.item.title}
                    </button>
                    <div className="board-meta">
                      <span className="pts">{e.points ?? "–"}</span>
                      <span>{PRIORITY[e.item.priority]}</span>
                      <span className="muted">{e.assignee?.name ?? "non affecté"}</span>
                    </div>
                    {e.blocked && <div className="t-crit">⛔ {e.blockReason || "Bloqué"}</div>}
                    {editable && (
                      <select
                        className="inp board-move"
                        aria-label={`Déplacer ${e.item.title}`}
                        value={e.column}
                        onChange={(ev) => move(e, { column: ev.target.value })}
                      >
                        {d.columns.map((x) => (
                          <option key={x.key} value={x.key}>
                            {x.label}
                          </option>
                        ))}
                      </select>
                    )}
                  </article>
                ))}
              </section>
            );
          })}
        </div>
      )}
      {detail && d && (
        <Modal title={detail.item.title} onClose={() => setDetail(null)}>
          <div className="ev-form">
            <p>{detail.item.userStory || detail.item.description}</p>
            {detail.item.acceptance && (
              <p>
                <b>Critères d'acceptation :</b> {detail.item.acceptance}
              </p>
            )}
            {editable && (
              <div className="dep-row">
                <label className="cal-check">
                  <input
                    type="checkbox"
                    checked={detail.blocked}
                    onChange={(ev) => (
                      move(
                        detail,
                        { blocked: ev.target.checked, blockReason: detail.blockReason },
                        "Blocage mis à jour",
                      ),
                      setDetail({ ...detail, blocked: ev.target.checked })
                    )}
                  />{" "}
                  Bloqué
                </label>
                <input
                  className="inp"
                  placeholder="Cause du blocage"
                  aria-label="Cause du blocage"
                  defaultValue={detail.blockReason}
                  onBlur={(ev) => detail.blocked && move(detail, { blocked: true, blockReason: ev.target.value })}
                />
                <input
                  className="inp num"
                  type="number"
                  placeholder="Reste (h)"
                  aria-label="Reste à faire (heures)"
                  defaultValue={detail.remainingHours ?? ""}
                  onBlur={(ev) => move(detail, { remainingHours: ev.target.value })}
                />
              </div>
            )}
            <h4 className="ev-sec">Historique</h4>
            <ul className="plain">
              {detail.history
                .slice()
                .reverse()
                .map((h, i) => (
                  <li key={i} className="muted">
                    {fmtDate(h.at)} · {h.by} · {h.event} {h.from ? `${h.from} → ${h.to}` : (h.to ?? "")}
                  </li>
                ))}
              {!detail.history.length && <li className="muted">Aucun mouvement.</li>}
            </ul>
          </div>
        </Modal>
      )}
    </div>
  );
}
