import { createPortal } from "react-dom";
import { useCallback, useEffect, useState } from "react";

import { api } from "../../api/client";
import { Field, useAction, useToast } from "../../components/ui";

export type UserAlert = {
  id: string; title: string; message: string; level: "info" | "warning" | "critical"; levelLabel: string;
  action: string | null; actionTitle: string | null; by: string; at: string; clientVisible: boolean;
  closed: boolean; closedBy?: string; notified: number; mailed: number; canClose?: boolean;
};
type ActionRef = { id: string; title: string };

const ICON = { info: "🔔", warning: "⚠️", critical: "🚨" } as const;
const changed = "pct-alerts-changed";

/** Recharge les listes d'alertes ouvertes ailleurs dans la page. */
const emitChange = () => window.dispatchEvent(new Event(changed));

/** Fenêtre « Lancer une alerte » : sur le projet ou sur une action ; tous les membres sont notifiés (cloche + e-mail). */
export function AlertDialog({ projectId, actions, action, onClose }: {
  projectId: string; actions?: ActionRef[]; action?: ActionRef | null; onClose: () => void;
}) {
  const [internal, setInternal] = useState(false);
  useEffect(() => {
    api.get<{ internal: boolean }>(`/projects/${encodeURIComponent(projectId)}/alerts`).then((d) => setInternal(d.internal), () => undefined);
  }, [projectId]);
  const { run, busy } = useAction();
  const toast = useToast();
  const [form, setForm] = useState({
    title: action ? `Action « ${action.title} »`.slice(0, 150) : "", message: "", level: "warning",
    action: action?.id ?? "", clientVisible: true, email: true,
  });
  const send = () =>
    run(() => api.post<UserAlert>(`/projects/${encodeURIComponent(projectId)}/alerts`, { ...form, action: form.action || null }))
      .then((a) => {
        if (!a) return;
        emitChange();
        toast(`Alerte envoyée à ${a.notified} membre(s)${a.mailed ? `, ${a.mailed} e-mail(s)` : ""}`);
        onClose();
      }, () => undefined);
  return createPortal(
    <div className="scrim" onClick={onClose}>
      <div className="modal" role="dialog" aria-label="Lancer une alerte" onClick={(e) => e.stopPropagation()}>
        <div className="modal-h">
          <h3>🚨 Lancer une alerte</h3>
          <button className="icon-btn" type="button" aria-label="Fermer" onClick={onClose}>✕</button>
        </div>
        <div className="modal-b" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <p className="muted" style={{ margin: 0, fontSize: 13 }}>
            Tous les membres du projet la reçoivent dans leurs notifications et par e-mail.
          </p>
          <div className="al-levels" role="radiogroup" aria-label="Niveau">
            {(["info", "warning", "critical"] as const).map((l) => (
              <label key={l} className={`al-level al-${l}${form.level === l ? " on" : ""}`}>
                <input type="radio" name="al-level" checked={form.level === l} onChange={() => setForm({ ...form, level: l })} />
                {ICON[l]} {l === "info" ? "Information" : l === "warning" ? "Attention" : "Critique"}
              </label>
            ))}
          </div>
          <Field id="al-action" label="Concerne">
            <select id="al-action" className="inp" value={form.action} onChange={(e) => setForm({ ...form, action: e.target.value })} disabled={!!action}>
              <option value="">Le projet en général</option>
              {(action ? [action] : actions ?? []).map((a) => (
                <option key={a.id} value={a.id}>Action {a.id} · {a.title}</option>
              ))}
            </select>
          </Field>
          <Field id="al-title" label="Titre">
            <input id="al-title" className="inp" maxLength={150} value={form.title} placeholder="Ex. Livraison bloquée par l’environnement de test"
              onChange={(e) => setForm({ ...form, title: e.target.value })} autoFocus />
          </Field>
          <Field id="al-msg" label="Message">
            <textarea id="al-msg" className="inp" rows={4} maxLength={2000} value={form.message} placeholder="Contexte, impact, aide attendue…"
              onChange={(e) => setForm({ ...form, message: e.target.value })} />
          </Field>
          <label className="pj-check">
            <input type="checkbox" checked={form.email} onChange={(e) => setForm({ ...form, email: e.target.checked })} /> Envoyer aussi par e-mail
          </label>
          {internal && (
            <label className="pj-check">
              <input type="checkbox" checked={form.clientVisible} onChange={(e) => setForm({ ...form, clientVisible: e.target.checked })} />
              Prévenir aussi le client (sinon équipe interne uniquement)
            </label>
          )}
        </div>
        <div className="modal-f">
          <button className="btn ghost" type="button" onClick={onClose}>Annuler</button>
          <button className="btn primary" type="button" disabled={busy || !form.title.trim()} onClick={send}>
            {busy ? "Envoi…" : "Envoyer l’alerte"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

/** Bouton « Alerte » (en-tête du projet). */
export function AlertButton({ projectId, actions }: { projectId: string; actions?: ActionRef[] }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className="al-btn" type="button" title="Lancer une alerte aux membres du projet" onClick={() => setOpen(true)}>
        🚨 Lancer une alerte
      </button>
      {open && <AlertDialog projectId={projectId} actions={actions} onClose={() => setOpen(false)} />}
    </>
  );
}

/** Alertes ouvertes lancées par les membres (bandeau en haut du projet). */
export function UserAlertsStrip({ projectId }: { projectId: string }) {
  const [alerts, setAlerts] = useState<UserAlert[] | null>(null);
  const [all, setAll] = useState(false);
  const { run, busy } = useAction();
  const load = useCallback(() => {
    api.get<{ alerts: UserAlert[] }>(`/projects/${encodeURIComponent(projectId)}/alerts`).then((d) => setAlerts(d.alerts), () => setAlerts([]));
  }, [projectId]);
  useEffect(() => {
    load();
    window.addEventListener(changed, load);
    return () => window.removeEventListener(changed, load);
  }, [load]);
  if (!alerts) return null;
  const open = alerts.filter((a) => !a.closed);
  const shown = all ? alerts : open;
  if (!alerts.length) return null;
  return (
    <div className="al-strip">
      <div className="al-strip-h">
        <b>🚨 Alertes du projet</b> <span className="faint">{open.length} ouverte(s)</span>
        <button className="btn ghost sm" type="button" onClick={() => setAll(!all)}>{all ? "Masquer les clôturées" : "Voir l’historique"}</button>
      </div>
      {shown.length === 0 && <div className="faint" style={{ fontSize: 13 }}>Aucune alerte ouverte.</div>}
      {shown.map((a) => (
        <div key={a.id} className={`al-item al-${a.level}${a.closed ? " closed" : ""}`}>
          <span aria-hidden="true">{ICON[a.level]}</span>
          <div>
            <b>{a.title}</b>
            {a.actionTitle && <span className="pill nodot" style={{ marginLeft: 6 }}>Action {a.action} · {a.actionTitle}</span>}
            {a.message && <p>{a.message}</p>}
            <small className="faint">
              {a.levelLabel} · par {a.by} · {new Date(a.at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })} · {a.notified} membre(s) notifié(s)
              {a.closed && ` · clôturée${a.closedBy ? ` par ${a.closedBy}` : ""}`}
            </small>
          </div>
          {a.canClose && (
            <button className="btn ghost sm" type="button" disabled={busy}
              onClick={() => run(() => api.patch(`/projects/${encodeURIComponent(projectId)}/alerts`, { id: a.id, closed: !a.closed })).then(load, () => undefined)}>
              {a.closed ? "Rouvrir" : "Clôturer"}
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
