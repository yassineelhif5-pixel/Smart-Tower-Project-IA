import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { api } from "../../api/client";
import { Card, ErrorNotice, Field, Loading, useAction } from "../../components/ui";

type Inst = {
  id: number; name: string; code: string; description: string; isPilot: boolean; sourceTool: string; targetTool: string;
  owner: { id: number; name: string } | null; status: string; statusLabel: string; startDate: string | null; endDate: string | null;
  cutoverDate: string | null; objectsTotal: number; objectsMigrated: number; objectsFailed: number; objectsPct: number | null;
  notes: string; order: number; actions: { total: number; done: number; open: number; late: number }; progress: number; late: boolean;
};
type Mig = {
  enabled: boolean; source: string; target: string; status: string; statusLabel: string; statusAuto: boolean;
  statuses: { code: string; label: string }[]; instances: Inst[]; pilot: Inst | null; canEdit: boolean; team: { id: number; name: string }[];
  stats: {
    instances: number; done: number; inProgress: number; notStarted: number; blocked: number; objectsTotal: number; objectsMigrated: number;
    objectsFailed: number; objectsPct: number | null; globalActions: { total: number; done: number }; late: number;
  };
};
type TaskLite = { id: string; title: string; status: string; statusLabel: string; due: string | null; owner: { name: string } | null; instance?: { id: number } | null };

const ST_COLOR: Record<string, string> = {
  not_started: "#94a3b8", preparing: "#0ea5e9", extracting: "#6366f1", migrating: "#4f46e5", testing: "#d97706",
  cutover: "#db2777", done: "#16a34a", blocked: "#dc2626", cancelled: "#64748b",
};
const fr = (d: string | null) => (d ? new Date(`${d}T00:00:00`).toLocaleDateString("fr-FR") : "—");
const num = (n: number) => n.toLocaleString("fr-FR");

/** Onglet « Migration » : outils source / cible, instances (pilote, planning, statut, objets migrés), actions par instance. */
export function MigrationTab({ projectId, tasks, onTasksChanged }: { projectId: string; tasks: TaskLite[]; onTasksChanged?: () => void }) {
  const url = `/projects/${encodeURIComponent(projectId)}/migration`;
  const [m, setM] = useState<Mig | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [editing, setEditing] = useState<Inst | "new" | null>(null);
  const [openActs, setOpenActs] = useState<number | null>(null);
  const { run, busy } = useAction();
  const [head, setHead] = useState({ source: "", target: "", status: "" });
  const load = useCallback(() => {
    api.get<Mig>(url).then((d) => { setM(d); setHead({ source: d.source, target: d.target, status: d.statusAuto ? "" : d.status }); }, setError);
  }, [url]);
  useEffect(load, [load]);
  if (error) return <ErrorNotice error={error as never} onRetry={load} />;
  if (!m) return <Loading />;
  const s = m.stats;
  const dirty = head.source !== m.source || head.target !== m.target || head.status !== (m.statusAuto ? "" : m.status);

  // Mini-planning des instances
  const dates = m.instances.flatMap((i) => [i.startDate, i.endDate, i.cutoverDate]).filter(Boolean).map((d) => new Date(`${d}T00:00:00`).getTime());
  const min = dates.length ? Math.min(...dates) : 0;
  const max = dates.length ? Math.max(...dates) : 0;
  const pos = (d: string | null) => (d && max > min ? ((new Date(`${d}T00:00:00`).getTime() - min) / (max - min)) * 100 : 0);
  const today = Date.now();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Card title="🔁 Migration" sub="Outils, statut global et avancement consolidé de toutes les instances.">
        <div className="mg-head">
          <div className="mg-tools">
            <label>
              <small>Outil / système source</small>
              <input className="inp" value={head.source} disabled={!m.canEdit} placeholder="Ex. SAP ECC 6.0" onChange={(e) => setHead({ ...head, source: e.target.value })} />
            </label>
            <span className="mg-arrow">➜</span>
            <label>
              <small>Outil / système cible</small>
              <input className="inp" value={head.target} disabled={!m.canEdit} placeholder="Ex. SAP S/4HANA" onChange={(e) => setHead({ ...head, target: e.target.value })} />
            </label>
            <label>
              <small>Statut global</small>
              <select className="inp" value={head.status} disabled={!m.canEdit} onChange={(e) => setHead({ ...head, status: e.target.value })}>
                <option value="">Automatique (d’après les instances) — {m.statusAuto ? m.statusLabel : "…"}</option>
                {m.statuses.map((x) => <option key={x.code} value={x.code}>{x.label}</option>)}
              </select>
            </label>
            {m.canEdit && dirty && (
              <button className="btn primary" type="button" disabled={busy}
                onClick={() => run(() => api.patch<Mig>(url, head), "Migration mise à jour").then((d) => d && (setM(d), setHead({ source: d.source, target: d.target, status: d.statusAuto ? "" : d.status })), () => undefined)}>
                Enregistrer
              </button>
            )}
          </div>
          <div className="mg-kpis">
            <div><b>{s.instances}</b><small>instance(s)</small></div>
            <div className="ok"><b>{s.done}</b><small>terminée(s)</small></div>
            <div className="run"><b>{s.inProgress}</b><small>en cours</small></div>
            <div><b>{s.notStarted}</b><small>non démarrée(s)</small></div>
            <div className={s.blocked ? "crit" : ""}><b>{s.blocked}</b><small>bloquée(s)</small></div>
            <div className="wide">
              <b>{num(s.objectsMigrated)} / {num(s.objectsTotal)}</b>
              <small>objets migrés{s.objectsPct != null ? ` (${s.objectsPct} %)` : ""}{s.objectsFailed ? ` · ${num(s.objectsFailed)} en échec` : ""}</small>
              <div className="mg-bar"><i style={{ width: `${s.objectsPct ?? 0}%` }} /></div>
            </div>
            <div><b>{s.globalActions.done}/{s.globalActions.total}</b><small>actions globales</small></div>
          </div>
          <p className="faint" style={{ margin: 0, fontSize: 12.5 }}>
            Statut global : <b style={{ color: ST_COLOR[m.status] }}>{m.statusLabel}</b>
            {m.pilot ? <> · Instance pilote : <b>{m.pilot.name}</b> ({m.pilot.statusLabel})</> : " · Aucune instance pilote désignée"}
            {s.late ? <> · <span style={{ color: "#dc2626" }}>{s.late} instance(s) en retard</span></> : null}
          </p>
        </div>
      </Card>

      {m.instances.length > 0 && max > min && (
        <Card title="🗓️ Planning des instances" sub="Démarrage → fin prévue, ◆ date de bascule, ligne rouge = aujourd’hui.">
          <div className="mg-gantt">
            {today >= min && today <= max && <div className="mg-today" style={{ left: `calc(180px + (100% - 180px) * ${(today - min) / (max - min)})` }} />}
            {m.instances.map((i) => (
              <div key={i.id} className="mg-grow">
                <span className="mg-gname">{i.isPilot ? "⭐ " : ""}{i.name}</span>
                <div className="mg-gtrack">
                  {i.startDate && i.endDate && (
                    <div className="mg-gbar" style={{ left: `${pos(i.startDate)}%`, width: `${Math.max(1, pos(i.endDate) - pos(i.startDate))}%`, background: `${ST_COLOR[i.status]}33`, borderColor: ST_COLOR[i.status] }}>
                      <i style={{ width: `${i.progress}%`, background: ST_COLOR[i.status] }} />
                    </div>
                  )}
                  {i.cutoverDate && <span className="mg-cut" style={{ left: `${pos(i.cutoverDate)}%` }} title={`Bascule le ${fr(i.cutoverDate)}`}>◆</span>}
                </div>
              </div>
            ))}
            <div className="mg-gaxis"><span>{fr(new Date(min).toISOString().slice(0, 10))}</span><span>{fr(new Date(max).toISOString().slice(0, 10))}</span></div>
          </div>
        </Card>
      )}

      <Card
        title={`🧩 Instances (${m.instances.length})`}
        sub="Une présentation par instance : outils, planning, statut, objets migrés et actions propres."
        extra={m.canEdit ? <button className="btn primary sm" type="button" onClick={() => setEditing("new")}>+ Nouvelle instance</button> : undefined}
      >
        {m.instances.length === 0 ? (
          <div className="empty">Aucune instance. Ajoutez les instances à migrer (sites, filiales, environnements…) et désignez l’instance pilote.</div>
        ) : (
          <div className="mg-insts">
            {m.instances.map((i) => {
              const acts = tasks.filter((t) => t.instance?.id === i.id);
              return (
                <div key={i.id} className={`mg-inst${i.isPilot ? " pilot" : ""}`} style={{ borderTopColor: ST_COLOR[i.status] }}>
                  <div className="mg-ih">
                    <div>
                      <b>{i.name}</b> {i.code && <span className="mono faint">{i.code}</span>}
                      {i.isPilot && <span className="mg-pilot">⭐ Pilote</span>}
                    </div>
                    <span className="pill nodot" style={{ background: `${ST_COLOR[i.status]}22`, color: ST_COLOR[i.status] }}>{i.statusLabel}</span>
                  </div>
                  <div className="mg-it">{i.sourceTool || "—"} <span>➜</span> {i.targetTool || "—"}</div>
                  {i.description && <p className="mg-desc">{i.description}</p>}
                  <dl className="mg-dl">
                    <dt>Démarrage</dt><dd>{fr(i.startDate)}</dd>
                    <dt>Fin prévue</dt><dd className={i.late ? "crit" : ""}>{fr(i.endDate)}{i.late ? " (en retard)" : ""}</dd>
                    <dt>Bascule</dt><dd>{fr(i.cutoverDate)}</dd>
                    <dt>Responsable</dt><dd>{i.owner?.name ?? "—"}</dd>
                  </dl>
                  <div className="mg-obj">
                    <div><b>{num(i.objectsMigrated)}</b> / {num(i.objectsTotal)} objets{i.objectsFailed ? <span className="crit"> · {num(i.objectsFailed)} en échec</span> : ""}</div>
                    <div className="mg-bar"><i style={{ width: `${i.objectsPct ?? 0}%`, background: ST_COLOR[i.status] }} /></div>
                  </div>
                  <div className="mg-acts">
                    <span>📌 {i.actions.open} action(s) ouverte(s) · {i.actions.done} terminée(s){i.actions.late ? <span className="crit"> · {i.actions.late} en retard</span> : ""}</span>
                    {acts.length > 0 && <button className="btn ghost sm" type="button" onClick={() => setOpenActs(openActs === i.id ? null : i.id)}>{openActs === i.id ? "Masquer" : "Voir les actions"}</button>}
                  </div>
                  {openActs === i.id && (
                    <ul className="mg-actlist">
                      {acts.map((t) => <li key={t.id}><b>{t.title}</b><small>{t.statusLabel} · {t.owner?.name ?? "Non affectée"} · {fr(t.due)}</small></li>)}
                    </ul>
                  )}
                  {i.notes && <p className="mg-desc">📝 {i.notes}</p>}
                  {m.canEdit && (
                    <div className="mg-ia">
                      <button className="btn sm" type="button" onClick={() => setEditing(i)}>✏️ Modifier</button>
                      <button className="btn ghost sm pj-del" type="button" disabled={busy}
                        onClick={() => window.confirm(`Supprimer l’instance « ${i.name} » ? Ses actions deviendront des actions globales du projet.`) &&
                          run(() => api.delete<Mig>(`${url}/instances/${i.id}`), "Instance supprimée").then((d) => { if (d) { setM(d); onTasksChanged?.(); } }, () => undefined)}>
                        🗑
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Card>
      {editing && (
        <InstanceDialog m={m} inst={editing === "new" ? null : editing} busy={busy} onClose={() => setEditing(null)}
          onSave={(body) => run(() => (editing === "new" ? api.post<Mig>(`${url}/instances`, body) : api.patch<Mig>(`${url}/instances/${(editing as Inst).id}`, body)),
            editing === "new" ? "Instance créée" : "Instance mise à jour").then((d) => { if (d) { setM(d); setEditing(null); } }, () => undefined)} />
      )}
    </div>
  );
}

function InstanceDialog({ m, inst, busy, onClose, onSave }: { m: Mig; inst: Inst | null; busy: boolean; onClose: () => void; onSave: (b: Record<string, unknown>) => void }) {
  const [f, setF] = useState({
    name: inst?.name ?? "", code: inst?.code ?? "", description: inst?.description ?? "", isPilot: inst?.isPilot ?? m.instances.length === 0,
    sourceTool: inst?.sourceTool ?? m.source, targetTool: inst?.targetTool ?? m.target, owner: inst?.owner ? String(inst.owner.id) : "",
    status: inst?.status ?? "not_started", startDate: inst?.startDate ?? "", endDate: inst?.endDate ?? "", cutoverDate: inst?.cutoverDate ?? "",
    objectsTotal: String(inst?.objectsTotal ?? 0), objectsMigrated: String(inst?.objectsMigrated ?? 0), objectsFailed: String(inst?.objectsFailed ?? 0),
    notes: inst?.notes ?? "",
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return createPortal(
    <div className="scrim" onClick={onClose}>
      <div className="modal mg-modal" role="dialog" aria-label="Instance de migration" onClick={(e) => e.stopPropagation()}>
        <div className="modal-h">
          <h3>{inst ? `✏️ ${inst.name}` : "➕ Nouvelle instance"}</h3>
          <button className="icon-btn" type="button" aria-label="Fermer" onClick={onClose}>✕</button>
        </div>
        <div className="modal-b" style={{ display: "flex", flexDirection: "column", gap: 10, maxHeight: "70vh", overflow: "auto" }}>
          <div className="frow">
            <Field id="mi-name" label="Nom de l’instance"><input id="mi-name" className="inp" value={f.name} onChange={set("name")} placeholder="Ex. Filiale France, PROD Europe…" /></Field>
            <Field id="mi-code" label="Code"><input id="mi-code" className="inp" value={f.code} onChange={set("code")} placeholder="Ex. FR01" /></Field>
          </div>
          <label className="pj-check"><input type="checkbox" checked={f.isPilot} onChange={(e) => setF({ ...f, isPilot: e.target.checked })} /> ⭐ Instance pilote (migrée en premier pour valider la démarche)</label>
          <div className="frow">
            <Field id="mi-src" label="Outil source"><input id="mi-src" className="inp" value={f.sourceTool} onChange={set("sourceTool")} /></Field>
            <Field id="mi-tgt" label="Outil cible"><input id="mi-tgt" className="inp" value={f.targetTool} onChange={set("targetTool")} /></Field>
          </div>
          <div className="frow">
            <Field id="mi-st" label="Statut de migration">
              <select id="mi-st" className="inp" value={f.status} onChange={set("status")}>{m.statuses.map((x) => <option key={x.code} value={x.code}>{x.label}</option>)}</select>
            </Field>
            <Field id="mi-own" label="Responsable">
              <select id="mi-own" className="inp" value={f.owner} onChange={set("owner")}>
                <option value="">—</option>
                {m.team.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
              </select>
            </Field>
          </div>
          <div className="frow">
            <Field id="mi-sd" label="Date de démarrage"><input id="mi-sd" className="inp" type="date" value={f.startDate} onChange={set("startDate")} /></Field>
            <Field id="mi-ed" label="Fin prévue"><input id="mi-ed" className="inp" type="date" value={f.endDate} onChange={set("endDate")} /></Field>
            <Field id="mi-cd" label="Date de bascule"><input id="mi-cd" className="inp" type="date" value={f.cutoverDate} onChange={set("cutoverDate")} /></Field>
          </div>
          <div className="frow">
            <Field id="mi-ot" label="Objets à migrer"><input id="mi-ot" className="inp num" type="number" min={0} value={f.objectsTotal} onChange={set("objectsTotal")} /></Field>
            <Field id="mi-om" label="Objets migrés"><input id="mi-om" className="inp num" type="number" min={0} value={f.objectsMigrated} onChange={set("objectsMigrated")} /></Field>
            <Field id="mi-of" label="Objets en échec"><input id="mi-of" className="inp num" type="number" min={0} value={f.objectsFailed} onChange={set("objectsFailed")} /></Field>
          </div>
          <Field id="mi-desc" label="Présentation de l’instance"><textarea id="mi-desc" className="inp" rows={3} value={f.description} onChange={set("description")} placeholder="Périmètre, utilisateurs, particularités, volumétrie…" /></Field>
          <Field id="mi-notes" label="Notes de suivi"><textarea id="mi-notes" className="inp" rows={2} value={f.notes} onChange={set("notes")} /></Field>
        </div>
        <div className="modal-f">
          <button className="btn ghost" type="button" onClick={onClose}>Annuler</button>
          <button className="btn primary" type="button" disabled={busy || !f.name.trim()}
            onClick={() => onSave({ ...f, owner: f.owner ? Number(f.owner) : null, objectsTotal: Number(f.objectsTotal || 0), objectsMigrated: Number(f.objectsMigrated || 0), objectsFailed: Number(f.objectsFailed || 0) })}>
            Enregistrer
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
