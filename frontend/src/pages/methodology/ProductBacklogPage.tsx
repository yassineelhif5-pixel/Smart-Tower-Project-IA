import { useState, type DragEvent } from "react";

import { calendarApi } from "../../api/collab";
import { methodologyApi } from "../../api/methodology";
import { useApi } from "../../api/useApi";
import { ErrorNotice, Field, fmtDate, Loading, Modal, useAction } from "../../components/ui";
import { PRIORITY, Status } from "../../features/methodology/shared";
import type { BacklogItem } from "../../types/methodology";
import type { PageProps } from "./types";

export const KIND_LABEL: Record<string, string> = {
  epic: "Epic",
  feature: "Feature",
  story: "User Story",
  task: "Task",
  bug: "Bug",
  spike: "Spike",
};

/** Product Backlog : tri par priorité, filtres, recherche, regroupement par Epic, glisser-déposer (Product Owner). */
export function ProductBacklogPage({ info }: PageProps) {
  const id = info.project.id;
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");
  const [group, setGroup] = useState(false);
  const list = useApi(() => methodologyApi.backlog(id, { q, kind, status }), [id, q, kind, status]);
  const [editing, setEditing] = useState<BacklogItem | null | "new">(null);
  const [drag, setDrag] = useState<number | null>(null);
  const { run } = useAction();
  const canPrio = info.can.prioritize;

  const drop = (target: BacklogItem) => (e: DragEvent) => {
    e.preventDefault();
    if (drag == null || drag === target.id || !list.data) return;
    const ids = list.data.map((i) => i.id).filter((x) => x !== drag);
    ids.splice(ids.indexOf(target.id), 0, drag);
    list.setData(ids.map((x) => list.data!.find((i) => i.id === x)!));
    void run(() => methodologyApi.reorder(id, ids), "Priorités enregistrées").then(list.reload, list.reload);
    setDrag(null);
  };
  const move = (item: BacklogItem, dir: -1 | 1) => {
    if (!list.data) return;
    const ids = list.data.map((i) => i.id);
    const i = ids.indexOf(item.id);
    const j = i + dir;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    void run(() => methodologyApi.reorder(id, ids)).then(list.reload, () => undefined);
  };

  const rows = list.data ?? [];
  const epics = rows.filter((i) => i.kind === "epic");
  const groups: [string, BacklogItem[]][] = group
    ? [
        ...epics.map((e) => [e.title, rows.filter((i) => i.parent?.id === e.id)] as [string, BacklogItem[]]),
        ["Sans Epic", rows.filter((i) => i.kind !== "epic" && !i.parent)],
      ]
    : [["", rows]];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="cal-tools">
        <input
          className="inp cal-search"
          type="search"
          placeholder="Rechercher…"
          aria-label="Rechercher dans le backlog"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <select
          className="inp"
          aria-label="Type"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          style={{ width: "auto" }}
        >
          <option value="">Tous types</option>
          {Object.entries(KIND_LABEL).map(([k, l]) => (
            <option key={k} value={k}>
              {l}
            </option>
          ))}
        </select>
        <select
          className="inp"
          aria-label="Statut"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          style={{ width: "auto" }}
        >
          <option value="">Statuts actifs</option>
          <option value="new">Nouveau</option>
          <option value="ready">Prêt</option>
          <option value="selected">Dans un sprint</option>
          <option value="done">Terminé</option>
          <option value="removed">Retiré</option>
        </select>
        <label className="cal-check">
          <input type="checkbox" checked={group} onChange={(e) => setGroup(e.target.checked)} /> Regrouper par Epic
        </label>
        {info.can.plan && (
          <button className="btn sm primary" onClick={() => setEditing("new")}>
            + Élément
          </button>
        )}
      </div>
      {!canPrio && (
        <small className="muted">Seul le Product Owner (ou un responsable habilité) modifie l'ordre de priorité.</small>
      )}
      {list.error && <ErrorNotice error={list.error} onRetry={list.reload} />}
      {!list.data && !list.error && <Loading />}
      {groups.map(([title, items]) => (
        <div key={title || "all"}>
          {title && <div className="rt-group">{title}</div>}
          <ol className="backlog">
            {items.map((i) => (
              <li
                key={i.id}
                draggable={canPrio}
                onDragStart={() => setDrag(i.id)}
                onDragOver={(e) => canPrio && e.preventDefault()}
                onDrop={drop(i)}
                className={`${drag === i.id ? "drag" : ""} kind-${i.kind}`}
              >
                <span className="bl-rank">{i.rank}</span>
                <span className="bl-kind">{KIND_LABEL[i.kind]}</span>
                <button className="link bl-title" onClick={() => setEditing(i)}>
                  {i.key && <span className="mono muted">{i.key} </span>}
                  {i.title}
                </button>
                <span className="muted">{i.parent?.title}</span>
                <span className="pts" title="Story Points">
                  {i.storyPoints ?? "–"}
                </span>
                <span>{PRIORITY[i.priority]}</span>
                <Status
                  value={
                    i.status === "ready"
                      ? "ok"
                      : i.status === "done"
                        ? "done"
                        : i.status === "selected"
                          ? "planned"
                          : ""
                  }
                  label={i.statusLabel}
                />
                {i.dependencies.length > 0 && (
                  <span className="muted" title={i.dependencies.map((d) => d.title).join(", ")}>
                    ⛓ {i.dependencies.length}
                  </span>
                )}
                {canPrio && (
                  <span className="bl-move">
                    <button className="icon-btn" aria-label={`Monter ${i.title}`} onClick={() => move(i, -1)}>
                      ↑
                    </button>
                    <button className="icon-btn" aria-label={`Descendre ${i.title}`} onClick={() => move(i, 1)}>
                      ↓
                    </button>
                  </span>
                )}
              </li>
            ))}
          </ol>
        </div>
      ))}
      {editing && (
        <ItemModal
          projectId={id}
          item={editing === "new" ? null : editing}
          all={rows}
          onClose={() => setEditing(null)}
          onSaved={list.reload}
          canEdit={info.can.plan}
        />
      )}
    </div>
  );
}

export function ItemModal({
  projectId,
  item,
  all,
  onClose,
  onSaved,
  canEdit,
}: {
  projectId: string;
  item: BacklogItem | null;
  all: BacklogItem[];
  onClose: () => void;
  onSaved: () => void;
  canEdit: boolean;
}) {
  const [f, setF] = useState({
    kind: item?.kind ?? "story",
    title: item?.title ?? "",
    key: item?.key ?? "",
    description: item?.description ?? "",
    userStory: item?.userStory ?? "",
    acceptance: item?.acceptance ?? "",
    priority: item?.priority ?? "normal",
    storyPoints: item?.storyPoints ?? "",
    estimateHours: item?.estimateHours ?? "",
    status: item?.status ?? "new",
    assignee: item?.assignee?.id ?? "",
    parent: item?.parent?.id ?? "",
    dependencies: item?.dependencies.map((d) => d.id) ?? [],
    team: item?.team ?? "",
  });
  const people = useApi(() => calendarApi.people(projectId), [projectId]);
  const history = useApi(() => (item ? methodologyApi.item(item.id) : Promise.resolve(null)), [item?.id]);
  const { run, busy } = useAction();
  const save = () =>
    void run(() => {
      const body = {
        ...f,
        storyPoints: f.storyPoints === "" ? null : Number(f.storyPoints),
        estimateHours: f.estimateHours === "" ? null : Number(f.estimateHours),
        assignee: f.assignee || null,
        parent: f.parent || null,
        ...(item && ["selected"].includes(item.status) ? { status: undefined } : {}),
      };
      return item ? methodologyApi.saveItem(item.id, body) : methodologyApi.addItem(projectId, body);
    }, "Élément enregistré").then(
      () => (onSaved(), onClose()),
      () => undefined,
    );
  return (
    <Modal
      wide
      title={item ? item.title : "Nouvel élément du backlog"}
      onClose={onClose}
      footer={
        canEdit && (
          <button className="btn primary" disabled={busy || !f.title.trim()} onClick={save}>
            Enregistrer
          </button>
        )
      }
    >
      <div className="ev-form">
        <div className="grid g3">
          <Field id="bi-kind" label="Type">
            <select id="bi-kind" className="inp" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
              {Object.entries(KIND_LABEL).map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            </select>
          </Field>
          <Field id="bi-key" label="Référence">
            <input
              id="bi-key"
              className="inp mono"
              value={f.key}
              onChange={(e) => setF({ ...f, key: e.target.value })}
            />
          </Field>
          <Field id="bi-parent" label="Epic / Feature parente">
            <select
              id="bi-parent"
              className="inp"
              value={f.parent}
              onChange={(e) => setF({ ...f, parent: e.target.value ? Number(e.target.value) : "" })}
            >
              <option value="">—</option>
              {all
                .filter((i) => ["epic", "feature"].includes(i.kind) && i.id !== item?.id)
                .map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.title}
                  </option>
                ))}
            </select>
          </Field>
        </div>
        <Field id="bi-title" label="Titre">
          <input
            id="bi-title"
            className="inp"
            value={f.title}
            onChange={(e) => setF({ ...f, title: e.target.value })}
          />
        </Field>
        <Field id="bi-us" label="User Story" hint="En tant que…, je veux…, afin de…">
          <textarea
            id="bi-us"
            className="inp"
            rows={2}
            value={f.userStory}
            onChange={(e) => setF({ ...f, userStory: e.target.value })}
          />
        </Field>
        <div className="grid g2">
          <Field id="bi-desc" label="Description">
            <textarea
              id="bi-desc"
              className="inp"
              rows={3}
              value={f.description}
              onChange={(e) => setF({ ...f, description: e.target.value })}
            />
          </Field>
          <Field id="bi-ac" label="Critères d'acceptation">
            <textarea
              id="bi-ac"
              className="inp"
              rows={3}
              value={f.acceptance}
              onChange={(e) => setF({ ...f, acceptance: e.target.value })}
            />
          </Field>
        </div>
        <div className="grid g3">
          <Field id="bi-prio" label="Priorité">
            <select
              id="bi-prio"
              className="inp"
              value={f.priority}
              onChange={(e) => setF({ ...f, priority: e.target.value })}
            >
              {Object.entries(PRIORITY).map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            </select>
          </Field>
          <Field id="bi-sp" label="Story Points">
            <input
              id="bi-sp"
              className="inp"
              type="number"
              min={0}
              step={0.5}
              value={f.storyPoints}
              onChange={(e) => setF({ ...f, storyPoints: e.target.value })}
            />
          </Field>
          <Field id="bi-h" label="Estimation (h)">
            <input
              id="bi-h"
              className="inp"
              type="number"
              min={0}
              step={0.5}
              value={f.estimateHours}
              onChange={(e) => setF({ ...f, estimateHours: e.target.value })}
            />
          </Field>
          <Field id="bi-who" label="Responsable">
            <select
              id="bi-who"
              className="inp"
              value={f.assignee}
              onChange={(e) => setF({ ...f, assignee: e.target.value ? Number(e.target.value) : "" })}
            >
              <option value="">—</option>
              {(people.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </Field>
          <Field id="bi-team" label="Équipe">
            <input id="bi-team" className="inp" value={f.team} onChange={(e) => setF({ ...f, team: e.target.value })} />
          </Field>
          <Field id="bi-st" label="Statut">
            <select
              id="bi-st"
              className="inp"
              value={f.status}
              disabled={f.status === "selected"}
              onChange={(e) => setF({ ...f, status: e.target.value })}
            >
              <option value="new">Nouveau</option>
              <option value="ready">Prêt</option>
              <option value="selected" disabled>
                Dans un sprint
              </option>
              <option value="done">Terminé</option>
              <option value="removed">Retiré</option>
            </select>
          </Field>
        </div>
        <Field id="bi-deps" label="Dépendances">
          <div className="chips" id="bi-deps">
            {all
              .filter((i) => i.id !== item?.id && i.kind !== "epic")
              .slice(0, 40)
              .map((i) => {
                const on = f.dependencies.includes(i.id);
                return (
                  <button
                    key={i.id}
                    className={`chip ${on ? "on" : ""}`}
                    aria-pressed={on}
                    onClick={() =>
                      setF({
                        ...f,
                        dependencies: on ? f.dependencies.filter((x) => x !== i.id) : [...f.dependencies, i.id],
                      })
                    }
                  >
                    {i.key || i.title.slice(0, 24)}
                  </button>
                );
              })}
          </div>
        </Field>
        {history.data && history.data.history.length > 0 && (
          <details>
            <summary>Historique des modifications ({history.data.history.length})</summary>
            <ul className="plain">
              {history.data.history
                .slice()
                .reverse()
                .map((h, i) => (
                  <li key={i} className="muted">
                    {fmtDate(h.at)} · {h.by} · {h.event}
                  </li>
                ))}
            </ul>
          </details>
        )}
      </div>
    </Modal>
  );
}
