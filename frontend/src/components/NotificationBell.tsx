import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { api } from "../api/client";
import { DocViewer } from "../features/projects/DocViewer";
import { QuestionAnswer, type AiQuestion } from "../features/assistant/QuestionsPanel";
import { Icon } from "./ui";

type AlertDetail = {
  id: string; title: string; message: string; level: "info" | "warning" | "critical"; levelLabel: string;
  action: string | null; actionTitle: string | null; by: string; at: string; closed: boolean; closedBy?: string;
  notified: number; project: string;
};
type Item = {
  id: number; title: string; body: string; text: string; event: string; createdAt: string; read: boolean;
  project: string | null; ref: string | null; alert: AlertDetail | null; doc: string | null; question?: string | null; mail?: string | null;
};
type Alerts = { unread: number; items: Item[] };
type DocRow = { id: string; name: string; ext: string; typeLabel: string; version: number; hasFile: boolean; uploadedBy: string | null; uploadedAt: string | null; description: string };

export const ALERTS_CHANGED = "pct-alerts-changed";

const ago = (iso: string) => {
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "à l’instant";
  if (m < 60) return `il y a ${m} min`;
  const h = Math.round(m / 60);
  return h < 24 ? `il y a ${h} h` : new Date(iso).toLocaleDateString("fr-FR");
};
const full = (iso: string) => new Date(iso).toLocaleString("fr-FR", { dateStyle: "long", timeStyle: "short" });
const LEVEL_ICON = { info: "🔔", warning: "⚠️", critical: "🚨" } as const;
const icon = (n: Item) =>
  n.alert ? LEVEL_ICON[n.alert.level] : n.doc ? "📄" : n.question ? ""
    : /🚨|📄|⚠️|🔔/u.test(n.title) ? "" : /retard|bloquée|dépass/i.test(n.title) ? "⛔" : /glissement|surcharge|budget/i.test(n.title) ? "⚠️" : "🔔";
const cleanTitle = (t: string) => t.replace(/^\[[^\]]+\]\s*/, "");
const code = (t: string) => t.match(/^\[([^\]]+)\]/)?.[1] ?? "";

/** Détail d'une notification : alerte lancée par un membre, nouveau document ou alerte automatique. */
function NotificationDetail({ n, onClose }: { n: Item; onClose: () => void }) {
  const [doc, setDoc] = useState<DocRow | null | undefined>(undefined);
  const [viewing, setViewing] = useState(false);
  const [q, setQ] = useState<AiQuestion | null | undefined>(undefined);
  const [mailHtml, setMailHtml] = useState<string | null>(null);
  useEffect(() => {
    if (!n.mail) return;
    api.get<{ html: string }>(`/mail-reports/${encodeURIComponent(n.mail)}`).then((m) => setMailHtml(m.html), () => setMailHtml(""));
  }, [n.mail]);
  useEffect(() => {
    if (!n.question || !n.project) return;
    api.get<{ mine: AiQuestion[]; all: AiQuestion[] }>(`/projects/${encodeURIComponent(n.project)}/questions`)
      .then((d) => setQ([...d.mine, ...d.all].find((x) => x.id === n.question) ?? null), () => setQ(null));
  }, [n.question, n.project]);
  useEffect(() => {
    if (!n.doc || !n.project) return;
    api.get<{ documents: DocRow[] }>(`/projects/${encodeURIComponent(n.project)}/documents`)
      .then((d) => setDoc(d.documents.find((x) => x.id === n.doc) ?? null), () => setDoc(null));
  }, [n.doc, n.project]);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && !viewing && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose, viewing]);
  const a = n.alert;
  const go = (hash: string) => {
    window.location.hash = hash;
    onClose();
  };
  return createPortal(
    <div className="scrim" onClick={onClose}>
      <div style={n.mail ? { width: "min(860px, 95vw)" } : undefined} className={`modal nd-modal${a ? ` nd-${a.level}` : ""}`} role="dialog" aria-label="Détail de la notification" onClick={(e) => e.stopPropagation()}>
        <div className="modal-h">
          <div style={{ minWidth: 0 }}>
            <div className="eyebrow">{code(n.title)}{a ? " · Alerte projet" : n.doc ? " · Nouveau document" : n.question ? " · Question du Chef de projet IA" : " · Notification"}</div>
            <h3 style={{ margin: "4px 0 0" }}>
              {icon(n)} {a ? a.title : cleanTitle(n.title)}
            </h3>
          </div>
          <button className="icon-btn" type="button" aria-label="Fermer" onClick={onClose}>✕</button>
        </div>
        <div className="modal-b nd-body">
          {a ? (
            <>
              <div className="nd-tags">
                <span className={`pill nodot nd-lvl nd-lvl-${a.level}`}>{a.levelLabel}</span>
                <span className={`pill nodot ${a.closed ? "" : "warn"}`}>{a.closed ? `Clôturée${a.closedBy ? ` par ${a.closedBy}` : ""}` : "Ouverte"}</span>
              </div>
              <dl className="nd-dl">
                <dt>Concerne</dt>
                <dd>{a.action ? <>Action <b>{a.action}</b> · {a.actionTitle}</> : "Le projet en général"}</dd>
                <dt>Lancée par</dt>
                <dd>{a.by}</dd>
                <dt>Date</dt>
                <dd>{full(a.at)}</dd>
                <dt>Diffusion</dt>
                <dd>{a.notified} membre(s) notifié(s)</dd>
              </dl>
              <div className="nd-msg">{a.message || <span className="faint">Aucun message complémentaire.</span>}</div>
            </>
          ) : n.mail ? (
            <>
              <p style={{ marginTop: 0 }}>{n.text}</p>
              {mailHtml === null ? <div className="faint">Chargement de l’e-mail…</div> : mailHtml ? (
                <iframe title="E-mail envoyé" srcDoc={mailHtml} sandbox="" style={{ width: "100%", height: "55vh", border: "1px solid var(--line)", borderRadius: 12 }} />
              ) : <div className="faint">E-mail non disponible.</div>}
            </>
          ) : n.question ? (
            q === undefined ? (
              <div className="faint">Chargement de la question…</div>
            ) : q === null ? (
              <p style={{ marginTop: 0 }}>{n.text}</p>
            ) : (
              <>
                <dl className="nd-dl">
                  <dt>Action</dt>
                  <dd><b>{q.task}</b> · {q.taskTitle}</dd>
                  <dt>Posée par</dt>
                  <dd>{q.by}</dd>
                </dl>
                <div className="nd-msg">{q.question}</div>
                {q.status === "open" ? (
                  <div style={{ marginTop: 12 }}>
                    <QuestionAnswer projectId={n.project ?? ""} q={q} onDone={(r) => setQ(r)} />
                  </div>
                ) : (
                  <div className="nd-msg" style={{ marginTop: 10, background: "color-mix(in srgb, #22c55e 10%, transparent)" }}>
                    ✅ Réponse de {q.answeredBy ?? q.toName} : {q.answer || "—"}
                    {q.newDue ? ` · nouvelle date ${new Date(q.newDue).toLocaleDateString("fr-FR")}` : ""}
                    {q.progress != null ? ` · ${q.progress} %` : ""}
                    {q.blocked ? " · bloqué" : ""}
                  </div>
                )}
              </>
            )
          ) : n.doc ? (
            <>
              <p style={{ marginTop: 0 }}>{n.text}</p>
              {doc === undefined ? (
                <div className="faint">Chargement du document…</div>
              ) : doc === null ? (
                <div className="faint">Ce document n’est plus disponible (supprimé ou non visible pour vous).</div>
              ) : (
                <dl className="nd-dl">
                  <dt>Document</dt>
                  <dd><b>{doc.name}</b> · {doc.ext.toUpperCase()} · v{doc.version}</dd>
                  <dt>Type</dt>
                  <dd>{doc.typeLabel}</dd>
                  {doc.description && <><dt>Description</dt><dd>{doc.description}</dd></>}
                  <dt>Déposé par</dt>
                  <dd>{doc.uploadedBy ?? "—"}</dd>
                </dl>
              )}
            </>
          ) : (
            <p style={{ marginTop: 0, whiteSpace: "pre-wrap" }}>{n.text}</p>
          )}
          <div className="faint" style={{ fontSize: 12.5, marginTop: 12 }}>Reçue le {full(n.createdAt)}</div>
        </div>
        <div className="modal-f">
          {doc && <button className="btn primary" type="button" onClick={() => setViewing(true)}>👁 Consulter le document</button>}
          {n.project && (
            <button className={`btn${doc ? "" : " primary"}`} type="button" onClick={() => go(`#projets/${encodeURIComponent(n.project ?? "")}`)}>
              Ouvrir le projet →
            </button>
          )}
          <button className="btn ghost" type="button" onClick={onClose}>Fermer</button>
        </div>
      </div>
      {viewing && doc && n.project && (
        <div onClick={(e) => e.stopPropagation()}>
          <DocViewer projectId={n.project} doc={doc} onClose={() => setViewing(false)} />
        </div>
      )}
    </div>,
    document.body,
  );
}

/** Centre de notifications : alertes lancées par les membres, nouveaux documents, alertes automatiques des projets. */
export function NotificationBell() {
  const [data, setData] = useState<Alerts | null>(null);
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<Item | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const load = useCallback(() => {
    api.get<Alerts>("/me/alerts").then(setData, () => undefined);
  }, []);
  useEffect(() => {
    load();
    const t = window.setInterval(load, 60000);
    const onFocus = () => document.visibilityState === "visible" && load();
    window.addEventListener(ALERTS_CHANGED, load);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      window.clearInterval(t);
      window.removeEventListener(ALERTS_CHANGED, load);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [load]);
  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const markAll = () => api.post("/me/alerts", {}).then(load, () => undefined);
  const openItem = (n: Item) => {
    if (!n.read) void api.post("/me/alerts", { ids: [n.id] }).then(load, () => undefined);
    setDetail(n);
    setOpen(false);
  };
  const unread = data?.unread ?? 0;
  return (
    <div className="bell" ref={ref}>
      <button className="icon-btn" type="button" aria-label={`Notifications${unread ? ` (${unread} non lues)` : ""}`} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Icon name="bell" />
        {unread > 0 && <span className="badge">{unread > 99 ? "99+" : unread}</span>}
      </button>
      {open && (
        <div className="bell-pop" role="dialog" aria-label="Notifications">
          <div className="bell-h">
            <b>Notifications</b>
            {unread > 0 && (
              <button className="btn ghost sm" type="button" onClick={markAll}>
                Tout marquer comme lu
              </button>
            )}
          </div>
          {!data ? (
            <div className="bell-empty">Chargement…</div>
          ) : data.items.length === 0 ? (
            <div className="bell-empty">Aucune notification. Les alertes de vos projets, les nouveaux documents et les alertes lancées par l’équipe apparaîtront ici.</div>
          ) : (
            data.items.map((n) => (
              <button key={n.id} type="button" className={`bell-item${n.read ? "" : " unread"}${n.alert ? ` bell-al-${n.alert.level}` : ""}`} onClick={() => openItem(n)}>
                <span aria-hidden="true">{icon(n)}</span>
                <span>
                  <b>{n.title}</b>
                  <small className="bell-text">{n.alert?.message || n.text}</small>
                  <small>
                    {n.alert ? `${n.alert.levelLabel} · par ${n.alert.by}${n.alert.closed ? " · clôturée" : ""} · ` : ""}
                    {ago(n.createdAt)} · <span className="bell-more">Voir le détail</span>
                  </small>
                </span>
              </button>
            ))
          )}
        </div>
      )}
      {detail && <NotificationDetail n={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}
