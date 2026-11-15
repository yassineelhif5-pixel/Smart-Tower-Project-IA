// Actions du collaborateur : s'affecter une action, changer le statut de ses actions (date de réalisation),
// demander un délai, et tableau glisser-déposer (par statut, regroupé par US, zone « Ma todo »).
import { useState } from "react";

import { api } from "../../api/client";
import { useAction, useToast } from "../../components/ui";

export type BoardTask = {
  id: string; title: string; status: string; statusLabel: string; owner: { id: number; name: string } | null; due: string | null;
  phase: string; doneAt?: string | null; est?: string | null; spent?: string | null; us?: { id: string; title: string; sprint: number | null } | null;
  extension?: { due: string; reason: string; by: string; from: string | null } | null;
};
type Ctx<W> = { id: string; statuses: { code: string; label: string }[]; tasks: BoardTask[] } & W;

export function useMyTask<W>(projectId: string, onChange: (w?: W) => void) {
  const { run, busy } = useAction();
  const call = (taskId: string, body: Record<string, unknown>, msg: string) =>
    run(() => api.post<W>(`/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}/me`, body), msg).then(onChange, () => undefined);
  return {
    busy,
    claim: (t: BoardTask) => call(t.id, { op: "claim" }, "Action affectée à vous"),
    status: (t: BoardTask, status: string, doneAt?: string, spent?: number) => call(t.id, { op: "status", status, ...(doneAt ? { doneAt } : {}), ...(spent != null ? { spent } : {}) }, status === "done" ? "Action terminée" : "Statut mis à jour"),
    extend: (t: BoardTask, due: string, reason: string) => call(t.id, { op: "extend", due, reason }, "Demande de délai envoyée au chef de projet"),
    decide: (t: BoardTask, decision: "approved" | "rejected", comment = "") => call(t.id, { op: "extension_decision", decision, comment }, decision === "approved" ? "Délai accordé" : "Délai refusé"),
  };
}

/** Petite fenêtre : date de réalisation (statut Terminé) ou demande de délai. */
export function MyTaskDialog({ task, mode, onClose, onDone, onExtend }: {
  task: BoardTask; mode: "done" | "extend"; onClose: () => void; onDone: (date: string, spent: number) => void; onExtend: (due: string, reason: string) => void;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const [date, setDate] = useState(mode === "done" ? today : task.due ?? today);
  const [reason, setReason] = useState("");
  const [spent, setSpent] = useState(task.spent && Number(task.spent) ? String(Number(task.spent)) : "");
  return (
    <div className="scrim" onClick={onClose}>
      <div className="modal" role="dialog" aria-label={mode === "done" ? "Date de réalisation" : "Demande de délai"} onClick={(e) => e.stopPropagation()} style={{ maxWidth: 460 }}>
        <div className="modal-h"><h3>{mode === "done" ? "✅ Action terminée" : "⏳ Demander un délai"}</h3><button className="icon-btn" type="button" aria-label="Fermer" onClick={onClose}>✕</button></div>
        <div className="modal-b" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <b>{task.title}</b>
          {mode === "done" ? (
            <><small className="muted">Pour terminer l’action, indiquez le temps réellement passé et la date de réalisation.</small>
            <label>Temps réellement passé (h){task.est && Number(task.est) ? <small className="muted"> — estimé : {Number(task.est)} h</small> : null}
              <input className="inp" type="number" min={0.25} step={0.25} autoFocus value={spent} onChange={(e) => setSpent(e.target.value)} placeholder="ex. 6,5" /></label>
            <label>Date de réalisation<input className="inp" type="date" max={today} value={date} onChange={(e) => setDate(e.target.value)} /></label></>
          ) : (<>
            <small className="muted">Échéance actuelle : {task.due ? new Date(`${task.due}T00:00:00`).toLocaleDateString("fr-FR") : "aucune"}. Le chef de projet accepte ou refuse.</small>
            <label>Nouvelle échéance souhaitée<input className="inp" type="date" min={task.due ?? today} value={date} onChange={(e) => setDate(e.target.value)} /></label>
            <label>Motif<textarea className="inp" rows={3} placeholder="Pourquoi ce délai est nécessaire…" value={reason} onChange={(e) => setReason(e.target.value)} /></label>
          </>)}
        </div>
        <div className="modal-f" style={{ display: "flex", gap: 8, justifyContent: "flex-end", padding: "12px 16px" }}>
          <button className="btn" type="button" onClick={onClose}>Annuler</button>
          {mode === "done"
            ? <button className="btn primary" type="button" disabled={!date || !(Number(spent.replace(",", ".")) > 0)} onClick={() => onDone(date, Number(spent.replace(",", ".")))}>Terminer l’action</button>
            : <button className="btn primary" type="button" disabled={!date || !reason.trim()} onClick={() => onExtend(date, reason)}>Envoyer la demande</button>}
        </div>
      </div>
    </div>
  );
}

/** Tableau glisser-déposer : colonnes = statuts, lignes = US (option), zone « Ma todo ». */
export function TaskBoard<W>({ p, meId, canManage, onChange, onOpen, patch }: {
  p: Ctx<W>; meId: number; canManage: boolean; onChange: (w?: W) => void; onOpen: (id: string) => void;
  patch: (t: BoardTask, body: Record<string, unknown>) => void;
}) {
  const my = useMyTask<W>(p.id, onChange);
  const toast = useToast();
  const [byUs, setByUs] = useState(() => { try { return localStorage.getItem("pct-board-us") === "1"; } catch { return false; } });
  const [mine, setMine] = useState(false);
  const [drag, setDrag] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const [doneFor, setDoneFor] = useState<BoardTask | null>(null);
  const tasks = p.tasks.filter((t) => !mine || t.owner?.id === meId);
  const lanes = byUs
    ? [...new Map(tasks.map((t) => [t.us?.id ?? "__none", t.us ? `${t.us.id} · ${t.us.title}` : "Sans US"])).entries()].sort((a, b) => (a[0] === "__none" ? 1 : b[0] === "__none" ? -1 : a[0].localeCompare(b[0], undefined, { numeric: true })))
    : [["__all", ""] as [string, string]];
  const find = (id: string | null) => p.tasks.find((t) => t.id === id) ?? null;
  const takeOver = (t: BoardTask) =>
    !t.owner || t.owner.id === meId || window.confirm(`Cette action est affectée à ${t.owner.name}. Vous l’affecter ?`);
  const toStatus = (t: BoardTask, status: string) => {
    if (t.status === status) return;
    if (canManage) return status === "done" ? setDoneFor(t) : patch(t, { status });
    if (t.owner?.id !== meId) {
      if (!takeOver(t)) return;
      void (async () => {
        await my.claim(t);
        if (status === "done") setDoneFor({ ...t, owner: { id: meId, name: "" } });
        else await my.status(t, status);
      })();
      return;
    }
    if (status === "done") return setDoneFor(t);
    void my.status(t, status);
  };
  const toTodo = (t: BoardTask) => {
    if (t.owner?.id === meId && t.status === "todo") { toast("Cette action est déjà dans votre todo."); return; }
    if (!takeOver(t)) return;
    void (async () => { if (t.owner?.id !== meId) await my.claim(t); if (t.status !== "todo") await my.status(t, "todo"); })();
  };
  const drop = (status: string | "__todo") => {
    const t = find(drag);
    setDrag(null); setOver(null);
    if (!t) return;
    if (status === "__todo") toTodo(t); else toStatus(t, status);
  };
  const zone = (key: string) => ({
    onDragOver: (e: React.DragEvent) => { e.preventDefault(); setOver(key); },
    onDragLeave: () => setOver((o) => (o === key ? null : o)),
  });
  const card = (t: BoardTask) => (
    <div key={t.id} draggable onDragStart={(e) => { setDrag(t.id); e.dataTransfer.setData("text/plain", t.id); }} onDragEnd={() => { setDrag(null); setOver(null); }}
      onClick={() => onOpen(t.id)} className={`tb-card${drag === t.id ? " dragging" : ""}`} title="Glissez pour changer le statut, ou déposez dans « Ma todo »">
      <b>{t.title}</b>
      <div className="tb-meta">
        <span className="mono">{t.id}</span>
        {t.due && <span className={t.status !== "done" && t.due < new Date().toISOString().slice(0, 10) ? "late" : ""}>📅 {new Date(`${t.due}T00:00:00`).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" })}</span>}
        {t.extension && <span className="warn">⏳ délai demandé</span>}
      </div>
      <div className="tb-owner">{t.owner ? <><i>{t.owner.name.split(/\s+/).map((x) => x[0]).join("").slice(0, 2).toUpperCase()}</i>{t.owner.name}</> : <span className="muted">Non affectée</span>}</div>
    </div>
  );
  return (
    <div className="tb">
      <div className="tb-bar">
        <label><input type="checkbox" checked={byUs} onChange={(e) => { setByUs(e.target.checked); try { localStorage.setItem("pct-board-us", e.target.checked ? "1" : "0"); } catch { /* */ } }} /> Afficher par US</label>
        <label><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Mes actions seulement</label>
        <div {...zone("__todo")} onDrop={(e) => { e.preventDefault(); drop("__todo"); }} className={`tb-todo${over === "__todo" ? " over" : ""}`}>
          🙋 Ma todo — déposez une action ici pour la prendre ({p.tasks.filter((t) => t.owner?.id === meId && t.status === "todo").length})
        </div>
      </div>
      {lanes.map(([lane, label]) => (
        <div key={lane} className="tb-lane">
          {byUs && <div className="tb-lane-h">📘 {label}</div>}
          <div className="tb-cols" style={{ gridTemplateColumns: `repeat(${p.statuses.length}, minmax(180px, 1fr))` }}>
            {p.statuses.map((s) => {
              const key = `${lane}|${s.code}`;
              const items = tasks.filter((t) => t.status === s.code && (lane === "__all" || (t.us?.id ?? "__none") === lane));
              return (
                <div key={s.code} {...zone(key)} onDrop={(e) => { e.preventDefault(); drop(s.code); }} className={`tb-col st-${s.code}${over === key ? " over" : ""}`}>
                  <div className="tb-col-h"><i className={`ta-dot st-${s.code}`} />{s.label}<em>{items.length}</em></div>
                  {items.map(card)}
                </div>
              );
            })}
          </div>
        </div>
      ))}
      {doneFor && <MyTaskDialog task={doneFor} mode="done" onClose={() => setDoneFor(null)} onExtend={() => undefined}
        onDone={(d, sp) => { if (canManage) patch(doneFor, { status: "done", doneAt: d, spent: sp }); else void my.status(doneFor, "done", d, sp); setDoneFor(null); }} />}
    </div>
  );
}
