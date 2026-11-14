import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { api, ApiError } from "../../api/client";
import { useToast } from "../../components/ui";

type Person = { id: number; name: string };
type DepRef = { id: string; title: string; status: string; statusLabel: string; due: string | null; project: string; projectName: string | null };
export type DrawerTask = {
  id: string; title: string; status: string; statusLabel: string; owner: Person | null; due: string | null; startDate: string | null;
  prio: string; phase: string; est: string | null; dependsOn?: DepRef[]; successors?: DepRef[]; blockedBy?: number; depConflict?: boolean;
  instance?: { id: number; name: string } | null;
};
type Ctx = {
  id: string; team: Person[]; statuses: { code: string; label: string }[]; phases: string[];
  instances?: { id: number; name: string; isPilot: boolean }[]; tasks: DrawerTask[];
};
type Comment = { id: number; author: string; authorId: number | null; at: string; body: string; internal: boolean };

const fr = (d: string | null) => (d ? new Date(`${d}T00:00:00`).toLocaleDateString("fr-FR") : "—");

/** Panneau latéral d'une action : modification directe (enregistrement automatique), dépendances, commentaires avec @mentions, discussion. */
export function ActionDrawer<W extends Ctx>({ p, taskId, canEdit, onChanged, onClose, onDiscuss, onAlert, onDelete }: {
  p: W; taskId: string; canEdit: boolean; onChanged: (w: W) => void; onClose: () => void;
  onDiscuss: (t: DrawerTask) => void; onAlert: (t: DrawerTask) => void; onDelete: (t: DrawerTask) => void;
}) {
  const toast = useToast();
  const t = p.tasks.find((x) => x.id === taskId);
  const [title, setTitle] = useState(t?.title ?? "");
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState<"comments" | "history">("comments");
  const [comments, setComments] = useState<Comment[] | null>(null);
  const [history, setHistory] = useState<{ at: string; text: string }[]>([]);
  const [body, setBody] = useState("");
  const [mentions, setMentions] = useState<Person[]>([]);
  const [internal, setInternal] = useState(false);
  const [mq, setMq] = useState<string | null>(null);
  const [dq, setDq] = useState("");
  const [found, setFound] = useState<DepRef[]>([]);
  const ta = useRef<HTMLTextAreaElement>(null);
  const url = `/projects/${encodeURIComponent(p.id)}/tasks/${encodeURIComponent(taskId)}`;

  useEffect(() => setTitle(t?.title ?? ""), [t?.title]);
  useEffect(() => {
    api.get<{ comments: Comment[]; history: { at: string; text: string }[] }>(`${url}/comments`).then((d) => { setComments(d.comments); setHistory(d.history); }, () => setComments([]));
  }, [url]);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  useEffect(() => {
    if (dq.trim().length < 2) return setFound([]);
    const h = window.setTimeout(() => {
      api.get<DepRef[]>(`/actions-search?q=${encodeURIComponent(dq.trim())}`).then((r) => setFound(r.filter((x) => x.id !== taskId)), () => setFound([]));
    }, 300);
    return () => window.clearTimeout(h);
  }, [dq, taskId]);

  const save = async (patch: Record<string, unknown>, msg?: string) => {
    setSaving(true);
    try {
      const w = await api.patch<W>(url, patch);
      onChanged(w);
      if (msg) toast(msg);
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Modification impossible.", true);
    } finally {
      setSaving(false);
    }
  };
  const mentionList = useMemo(() => (mq === null ? [] : p.team.filter((m) => m.name.toLowerCase().includes(mq.toLowerCase())).slice(0, 6)), [mq, p.team]);
  const onBody = (v: string) => {
    setBody(v);
    const caret = ta.current?.selectionStart ?? v.length;
    const m = v.slice(0, caret).match(/@([\p{L}\w.-]*)$/u);
    setMq(m ? m[1] : null);
  };
  const pickMention = (m: Person) => {
    const caret = ta.current?.selectionStart ?? body.length;
    const before = body.slice(0, caret).replace(/@([\p{L}\w.-]*)$/u, `@${m.name} `);
    setBody(before + body.slice(caret));
    setMentions((x) => (x.some((y) => y.id === m.id) ? x : [...x, m]));
    setMq(null);
    window.setTimeout(() => ta.current?.focus(), 0);
  };
  const send = async () => {
    const used = mentions.filter((m) => body.includes(`@${m.name}`));
    try {
      const c = await api.post<Comment & { notified: string[] }>(`${url}/comments`, { body, internal, mentions: used.map((m) => m.id) });
      setComments((x) => [c, ...(x ?? [])]);
      setBody("");
      setMentions([]);
      toast(c.notified.length ? `Commentaire ajouté · ${c.notified.join(", ")} notifié(s)` : "Commentaire ajouté");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Envoi impossible.", true);
    }
  };
  const renderBody = (s: string) =>
    s.split(/(@[\p{L}][\p{L}\w.'-]*(?:\s[\p{L}][\p{L}\w.'-]*)?)/u).map((part, i) =>
      part.startsWith("@") && p.team.some((m) => part.startsWith(`@${m.name}`)) ? <b key={i} className="ad-mention">{part}</b> : <span key={i}>{part}</span>);

  if (!t) return null;
  const late = !!t.due && t.status !== "done" && t.due < new Date().toISOString().slice(0, 10);
  const stages = [...new Set([...p.phases, ...p.tasks.map((x) => x.phase).filter(Boolean)])];
  const deps = t.dependsOn ?? [];

  return createPortal(
    <div className="ad-scrim" onClick={onClose}>
      <aside className="ad" role="dialog" aria-label={`Action ${t.id}`} onClick={(e) => e.stopPropagation()}>
        <header className="ad-h">
          <div className="ad-hl">
            <span className="mono faint">{t.id}</span>
            {saving ? <span className="ad-saving">Enregistrement…</span> : <span className="ad-saved">✓ Enregistré automatiquement</span>}
          </div>
          <div className="ad-hr">
            <button className="btn ghost sm" type="button" onClick={() => onDiscuss(t)}>💬 Discussion</button>
            <button className="btn ghost sm" type="button" onClick={() => onAlert(t)}>🚨 Alerte</button>
            {canEdit && <button className="btn ghost sm pj-del" type="button" title="Supprimer" onClick={() => onDelete(t)}>🗑</button>}
            <button className="icon-btn" type="button" aria-label="Fermer" onClick={onClose}>✕</button>
          </div>
        </header>
        <div className="ad-b">
          {canEdit ? (
            <textarea className="ad-title" rows={1} value={title} maxLength={300} onChange={(e) => setTitle(e.target.value)}
              onBlur={() => title.trim() && title !== t.title && save({ title: title.trim() })}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); (e.target as HTMLTextAreaElement).blur(); } }} />
          ) : (
            <h2 className="ad-title ro">{t.title}</h2>
          )}
          {late && <div className="ad-flag crit">⏰ En retard depuis le {fr(t.due)}</div>}
          {(t.blockedBy ?? 0) > 0 && <div className="ad-flag warn">🔗 En attente de {t.blockedBy} action(s) prérequise(s)</div>}
          {t.depConflict && <div className="ad-flag crit">⚠️ Conflit de dates avec une action prérequise</div>}

          <div className="ad-grid">
            <label>Statut
              <select className={`ta-status st-${t.status}`} disabled={!canEdit} value={t.status} onChange={(e) => save({ status: e.target.value })}>
                {p.statuses.map((s) => <option key={s.code} value={s.code}>{s.label}</option>)}
              </select>
            </label>
            <label>Responsable
              <select className="inp" disabled={!canEdit} value={t.owner?.id ?? ""} onChange={(e) => save({ owner: e.target.value ? Number(e.target.value) : null })}>
                <option value="">Non affectée</option>
                {p.team.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
              </select>
            </label>
            <label>Début
              <input className="inp" type="date" disabled={!canEdit} value={t.startDate ?? ""} onChange={(e) => save({ startDate: e.target.value || null })} />
            </label>
            <label>Échéance
              <input className={`inp${late ? " ad-late" : ""}`} type="date" disabled={!canEdit} value={t.due ?? ""} onChange={(e) => save({ due: e.target.value || null })} />
            </label>
            <label>Charge (h)
              <input className="inp num" type="number" min={0} step={0.5} disabled={!canEdit} defaultValue={t.est ? Number(t.est) : ""} key={`est-${t.est}`}
                onBlur={(e) => { const v = e.target.value === "" ? 0 : Number(e.target.value); if (v !== Number(t.est ?? 0)) save({ est: v }); }} />
            </label>
            <label>Priorité
              <select className="inp" disabled={!canEdit} value={t.prio} onChange={(e) => save({ prio: e.target.value })}>
                <option value="">—</option>
                {["Haute", "Moyenne", "Basse"].map((x) => <option key={x}>{x}</option>)}
              </select>
            </label>
            <label>Étape
              <input className="inp" list={`ad-stages-${t.id}`} disabled={!canEdit} defaultValue={t.phase} key={`ph-${t.phase}`}
                onBlur={(e) => e.target.value !== t.phase && save({ phase: e.target.value })} />
              <datalist id={`ad-stages-${t.id}`}>{stages.map((s) => <option key={s} value={s} />)}</datalist>
            </label>
            {(p.instances?.length ?? 0) > 0 && (
              <label>Portée
                <select className="inp" disabled={!canEdit} value={t.instance?.id ?? ""} onChange={(e) => save({ instance: e.target.value ? Number(e.target.value) : null })}>
                  <option value="">Globale</option>
                  {p.instances!.map((x) => <option key={x.id} value={x.id}>{x.isPilot ? "⭐ " : ""}{x.name}</option>)}
                </select>
              </label>
            )}
          </div>

          <section className="ad-sec">
            <h4>🔗 Dépendances</h4>
            {deps.length === 0 && <div className="faint" style={{ fontSize: 12.5 }}>Aucun prérequis.</div>}
            <div className="ad-deps">
              {deps.map((d) => (
                <span key={d.id} className={`ad-dep${d.status === "done" ? " ok" : ""}`}>
                  {d.status === "done" ? "✓" : "⏳"} {d.title}{d.projectName ? ` · ${d.projectName}` : ""}
                  {canEdit && <button type="button" aria-label={`Retirer ${d.title}`} onClick={() => save({ dependsOn: deps.filter((x) => x.id !== d.id).map((x) => x.id) }, "Dépendance retirée")}>×</button>}
                </span>
              ))}
            </div>
            {(t.successors?.length ?? 0) > 0 && <div className="faint" style={{ fontSize: 12.5 }}>↪ Bloque : {t.successors!.map((d) => d.title).join(", ")}</div>}
            {canEdit && (
              <div className="ad-depadd">
                <input className="inp" placeholder="+ Ajouter un prérequis (titre, référence ou projet)…" value={dq} onChange={(e) => setDq(e.target.value)} />
                {found.length > 0 && (
                  <ul className="te-found">
                    {found.filter((x) => !deps.some((d) => d.id === x.id)).map((x) => (
                      <li key={x.id}>
                        <button type="button" onClick={() => { save({ dependsOn: [...deps.map((d) => d.id), x.id] }, "Dépendance ajoutée"); setDq(""); setFound([]); }}>
                          <b>{x.title}</b> <small>{x.id} · {x.projectName} · {x.statusLabel}</small>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </section>

          <section className="ad-sec">
            <div className="ad-tabs">
              <button type="button" className={tab === "comments" ? "on" : ""} onClick={() => setTab("comments")}>💬 Commentaires {comments ? `(${comments.length})` : ""}</button>
              <button type="button" className={tab === "history" ? "on" : ""} onClick={() => setTab("history")}>🕘 Historique</button>
            </div>
            {tab === "comments" ? (
              <>
                <div className="ad-compose">
                  <textarea ref={ta} className="inp" rows={3} placeholder="Écrire un commentaire… tapez @ pour mentionner un membre de l’équipe"
                    value={body} onChange={(e) => onBody(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && body.trim()) { e.preventDefault(); void send(); } }} />
                  {mentionList.length > 0 && (
                    <ul className="ad-mlist">
                      {mentionList.map((m) => (
                        <li key={m.id}><button type="button" onMouseDown={(e) => { e.preventDefault(); pickMention(m); }}><span className="ta-av">{m.name.split(/\s+/).map((x) => x[0]).join("").slice(0, 2)}</span>{m.name}</button></li>
                      ))}
                    </ul>
                  )}
                  <div className="ad-crow">
                    <label className="ad-int"><input type="checkbox" checked={internal} onChange={(e) => setInternal(e.target.checked)} /> Interne (invisible du client)</label>
                    {mentions.filter((m) => body.includes(`@${m.name}`)).length > 0 && (
                      <span className="faint">Notifiera : {mentions.filter((m) => body.includes(`@${m.name}`)).map((m) => m.name).join(", ")}</span>
                    )}
                    <button className="btn primary sm" type="button" disabled={!body.trim()} onClick={() => void send()}>Commenter</button>
                  </div>
                </div>
                {comments === null ? <div className="faint">Chargement…</div> : comments.length === 0 ? (
                  <div className="faint" style={{ fontSize: 12.5 }}>Aucun commentaire. Soyez le premier à commenter.</div>
                ) : (
                  <ul className="ad-comments">
                    {comments.map((c) => (
                      <li key={c.id}>
                        <span className="ta-av">{c.author.split(/\s+/).map((x) => x[0]).join("").slice(0, 2).toUpperCase()}</span>
                        <div>
                          <div className="ad-ch"><b>{c.author}</b><small>{c.at}</small>{c.internal && <span className="ta-tag">interne</span>}</div>
                          <p>{renderBody(c.body)}</p>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            ) : history.length === 0 ? (
              <div className="faint" style={{ fontSize: 12.5 }}>Pas d’historique enregistré pour cette action.</div>
            ) : (
              <ul className="ad-hist">{history.slice().reverse().map((h, i) => <li key={i}><small>{h.at}</small> {h.text}</li>)}</ul>
            )}
          </section>
        </div>
      </aside>
    </div>,
    document.body,
  );
}
