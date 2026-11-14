import { createPortal } from "react-dom";
import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";

import { api, ApiError } from "../../api/client";
import { ReviewHistoryList, ReviewPanel, type Proposal, type ReviewHistory } from "./ReviewPanel";
import { MyQuestions, TeamQuestions, type AiQuestion } from "./QuestionsPanel";

type Suggestion = { intent: string; label: string };
type Mission = { code: string; icon: string; label: string; help: string; acts: boolean };
type Reply = {
  intent: string; reply: string; mode: string; suggestions: Suggestion[];
  confirm?: { intent: string; label: string; payload: Record<string, unknown> };
  form?: "task" | "automate" | "alert"; team?: { id: number; name: string }[];
  proposals?: Proposal[]; pending?: Proposal[]; history?: ReviewHistory[]; reviewAt?: string | null;
  questions?: AiQuestion[]; teamQuestions?: AiQuestion[]; autoDone?: { title: string; result: string }[];
  automation?: { enabled: boolean; everyDays: number };
  recommendations?: { level: string; text: string; mission: string }[];
};
type Msg = { from: "me" | "bot"; text: string; data?: Reply };
export type AssistantMe = {
  allowed: boolean; mode: "auto" | "semi" | "off"; modeLabel?: string; persona?: string; pitch?: string; missions?: Mission[]; llm?: boolean;
};

let cached: Promise<AssistantMe> | null = null;
/** Profil d'assistant de l'utilisateur (chargé une fois par session). */
export function loadAssistant() {
  cached ??= api.get<AssistantMe>("/assistant/me").catch(() => ({ allowed: false, mode: "off" as const }));
  return cached;
}

/** Rendu sûr d'un markdown simple (gras, italique, listes) sans HTML injecté. */
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|_[^_]+_)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <b key={i}>{part.slice(2, -2)}</b>
      : part.startsWith("_") && part.endsWith("_") && part.length > 2 ? <i key={i}>{part.slice(1, -1)}</i>
      : <Fragment key={i}>{part}</Fragment>,
  );
}
function Markdown({ text }: { text: string }) {
  const lines = text.split("\n");
  const out: ReactNode[] = [];
  let list: ReactNode[] = [];
  const flush = () => {
    if (list.length) out.push(<ul key={`u${out.length}`}>{list}</ul>);
    list = [];
  };
  lines.forEach((l, i) => {
    const m = l.match(/^\s*(?:[-•]|\d+\.)\s+(.*)$/);
    if (m) list.push(<li key={i}>{inline(m[1])}</li>);
    else {
      flush();
      if (l.trim()) out.push(<p key={i}>{inline(l)}</p>);
    }
  });
  flush();
  return <>{out}</>;
}

const MODE_BADGE = { auto: "⚡ Automatique", semi: "🤝 Semi-automatique", off: "" } as const;

/** Bouton ✨ à placer à côté du nom d'un projet : ouvre l'assistant IA du profil de l'utilisateur. */
export function AssistantButton({ projectId, projectName, autoOpen = false, onClose }: {
  projectId: string; projectName: string; autoOpen?: boolean; onClose?: () => void;
}) {
  const [me, setMe] = useState<AssistantMe | null>(null);
  const [open, setOpen] = useState(autoOpen);
  useEffect(() => {
    void loadAssistant().then(setMe);
  }, []);
  if (!me?.allowed) return null;
  return (
    <>
      <button className="as-btn" type="button" title={`${me.persona} · ${me.modeLabel}`} onClick={() => setOpen(true)}>
        ✨ <span>{me.persona}</span>
      </button>
      {open && <AssistantPopup me={me} projectId={projectId} projectName={projectName} onClose={() => (setOpen(false), onClose?.())} />}
    </>
  );
}

function AssistantPopup({ me, projectId, projectName, onClose }: { me: AssistantMe; projectId: string; projectName: string; onClose: () => void }) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [recos, setRecos] = useState<Reply["recommendations"] | null>(null);
  const [intro, setIntro] = useState<Reply | null>(null);
  const [alertForm, setAlertForm] = useState({ title: "", message: "", level: "warning" });
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [task, setTask] = useState({ title: "", owner: "", due: "" });
  const [auto, setAuto] = useState({ everyDays: 2 });
  const end = useRef<HTMLDivElement>(null);
  const missions = me.missions ?? [];

  useEffect(() => {
    api.post<Reply>(`/projects/${encodeURIComponent(projectId)}/assistant`, { intent: "intro" }).then((r) => (setRecos(r.recommendations ?? []), setIntro(r)), () => setRecos([]));
  }, [projectId]);
  useEffect(() => {
    if (msgs.length) end.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs]);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  const ask = async (body: Record<string, unknown>, label: string) => {
    setMsgs((m) => [...m, { from: "me", text: label }]);
    setBusy(true);
    try {
      const r = await api.post<Reply>(`/projects/${encodeURIComponent(projectId)}/assistant`, body);
      setMsgs((m) => [...m, { from: "bot", text: r.reply, data: r }]);
    } catch (e) {
      setMsgs((m) => [...m, { from: "bot", text: e instanceof ApiError ? `⚠️ ${e.message}` : "⚠️ L’assistant est indisponible." }]);
    } finally {
      setBusy(false);
    }
  };
  const mission = (code: string) => {
    const m = missions.find((x) => x.code === code);
    void ask({ intent: code, ai: code === "report" }, m ? m.label : code);
  };
  const canDecide = missions.some((m) => m.code === "review");
  const decide = (accept: string[], reject: string[], edits: Record<string, unknown>) =>
    void ask({ intent: "review_decide", accept, reject, edits },
      accept.length ? `Je valide ${accept.length} proposition(s)` : `J’écarte ${reject.length} proposition(s)`);
  const lastReview = msgs.map((m, i) => (m.data?.proposals ? i : -1)).reduce((a, b) => Math.max(a, b), -1);
  const send = () => {
    const t = text.trim();
    if (!t) return;
    setText("");
    void ask({ text: t, ai: true }, t);
  };

  return createPortal(
    <div className="scrim" onClick={onClose}>
      <section className="as-modal" role="dialog" aria-label={me.persona} onClick={(e) => e.stopPropagation()}>
        <header className="as-head">
          <div className="as-avatar" aria-hidden="true">✨</div>
          <div>
            <b>{me.persona}</b>
            <small>
              {projectName} · <span className={`as-mode as-mode-${me.mode}`}>{MODE_BADGE[me.mode]}</span>
              {me.llm ? " · IA Claude" : ""}
            </small>
          </div>
          <button className="icon-btn" type="button" aria-label="Fermer" onClick={onClose}>
            ✕
          </button>
        </header>
        <div className="as-body">
          {msgs.length === 0 && (
            <div className="as-intro">
              <p className="as-pitch">{me.pitch}</p>
              <p className="muted as-modetext">
                {me.mode === "auto"
                  ? "Mode automatique : je joue pleinement le rôle de chef de projet. À chaque passage, je fais la revue du projet, je questionne l’équipe, je relance et j’alerte ; je vous soumets les décisions (affectations, replanifications, nouvelles actions) pour validation."
                  : "Mode semi-automatique : nous travaillons en binôme. Je fais la revue du projet, je vous propose des actions détaillées et motivées ; vous les ajustez et les validez avant exécution."}
              </p>
              {intro?.questions && intro.questions.length > 0 && <MyQuestions projectId={projectId} questions={intro.questions} />}
              {intro?.autoDone && intro.autoDone.length > 0 && (
                <div className="as-autodone">
                  <b>🤖 Je viens de passer sur le projet et j’ai mené {intro.autoDone.length} action(s) :</b>
                  <ul>{intro.autoDone.map((d, i) => <li key={i}>{d.result}</li>)}</ul>
                </div>
              )}
              {intro?.pending && intro.pending.length > 0 && (
                <>
                  <h4>🤝 Mes propositions en attente de votre validation</h4>
                  <p className="muted" style={{ margin: "0 0 8px", fontSize: 12.5 }}>
                    Issues de ma dernière revue{intro.reviewAt ? ` (${new Date(intro.reviewAt).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })})` : ""}.
                    <button className="btn ghost sm" type="button" disabled={busy} style={{ marginLeft: 6 }} onClick={() => mission("review")}>Actualiser la revue</button>
                  </p>
                  <ReviewPanel proposals={intro.pending} team={intro.team ?? []} busy={busy} canDecide={canDecide} onDecide={decide} />
                </>
              )}
              {intro && !intro.pending?.length && missions.some((m) => m.code === "review") && (
                <div className="as-review-cta">
                  <span>🧭 Je peux passer tout le projet en revue (actions, charge, planning, budget, documents, alertes) et vous proposer un plan d’actions.</span>
                  <button className="btn primary sm" type="button" disabled={busy} onClick={() => mission("review")}>Lancer la revue</button>
                </div>
              )}
              <h4>💡 Mes recommandations</h4>
              {!recos ? (
                <div className="muted">Analyse du projet…</div>
              ) : (
                <ul className="as-recos">
                  {recos.map((r, i) => (
                    <li key={i} className={`as-reco as-${r.level}`}>
                      <span>{r.text}</span>
                      {missions.some((m) => m.code === r.mission) && (
                        <button className="btn ghost sm" type="button" disabled={busy} onClick={() => mission(r.mission)}>
                          Y aller →
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {intro?.teamQuestions && <TeamQuestions items={intro.teamQuestions} />}
              {intro?.history && <ReviewHistoryList items={intro.history} />}
              <h4>🎯 Que dois-je faire ?</h4>
              <div className="as-missions">
                {missions.map((m) => (
                  <button key={m.code} className="as-mission" type="button" disabled={busy} onClick={() => mission(m.code)}>
                    <span className="as-mi">{m.icon}</span>
                    <b>{m.label}</b>
                    <small>{m.help}</small>
                    {m.acts && <em>{me.mode === "auto" ? "exécution directe" : "avec validation"}</em>}
                  </button>
                ))}
              </div>
            </div>
          )}
          {msgs.map((m, i) => (
            <div key={i} className={`as-msg as-${m.from}`}>
              {m.from === "bot" ? <Markdown text={m.text} /> : m.text}
              {m.data?.confirm && (
                <div className="as-actions">
                  <button className="btn primary sm" type="button" disabled={busy}
                    onClick={() => ask({ intent: m.data!.confirm!.intent, ...m.data!.confirm!.payload, confirm: true }, m.data!.confirm!.label)}>
                    ✔ {m.data.confirm.label}
                  </button>
                  <span className="muted" style={{ fontSize: 11.5 }}>Validation humaine requise</span>
                </div>
              )}
              {m.data?.form === "task" && (
                <div className="as-form">
                  <input className="inp" placeholder={m.data.intent === "request" ? "Votre demande" : "Titre de l’action"} value={task.title} onChange={(e) => setTask({ ...task, title: e.target.value })} />
                  <div className="as-row">
                    {(m.data.team ?? []).length > 0 && (
                      <select className="inp" value={task.owner} onChange={(e) => setTask({ ...task, owner: e.target.value })}>
                        <option value="">Chef de projet</option>
                        {(m.data.team ?? []).map((t) => (
                          <option key={t.id} value={t.id}>
                            {t.name}
                          </option>
                        ))}
                      </select>
                    )}
                    <input className="inp" type="date" value={task.due} onChange={(e) => setTask({ ...task, due: e.target.value })} />
                  </div>
                  <button className="btn primary sm" type="button" disabled={busy || !task.title.trim()}
                    onClick={() => (ask({ intent: m.data!.intent, ...task, owner: task.owner ? Number(task.owner) : null }, `« ${task.title} »`), setTask({ title: "", owner: "", due: "" }))}>
                    {me.mode === "auto" ? "Créer" : "Proposer"}
                  </button>
                </div>
              )}
              {i === lastReview && m.data?.proposals && (
                <ReviewPanel key={i} proposals={m.data.proposals} team={m.data.team ?? []} busy={busy} canDecide={canDecide} onDecide={decide} />
              )}
              {m.data?.history && i === msgs.length - 1 && <ReviewHistoryList items={m.data.history} />}
              {m.data?.form === "alert" && (
                <div className="as-form">
                  <input className="inp" placeholder="Titre de l’alerte" maxLength={150} value={alertForm.title} onChange={(e) => setAlertForm({ ...alertForm, title: e.target.value })} />
                  <textarea className="inp" rows={3} placeholder="Message (contexte, impact, aide attendue)" value={alertForm.message} onChange={(e) => setAlertForm({ ...alertForm, message: e.target.value })} />
                  <div className="as-row">
                    <select className="inp" value={alertForm.level} onChange={(e) => setAlertForm({ ...alertForm, level: e.target.value })}>
                      <option value="info">🔔 Information</option>
                      <option value="warning">⚠️ Attention</option>
                      <option value="critical">🚨 Critique</option>
                    </select>
                    <button className="btn primary sm" type="button" disabled={busy || !alertForm.title.trim()}
                      onClick={() => (ask({ intent: "alert", ...alertForm }, `Alerte « ${alertForm.title} »`), setAlertForm({ title: "", message: "", level: "warning" }))}>
                      {me.mode === "auto" ? "Lancer" : "Proposer"}
                    </button>
                  </div>
                </div>
              )}
              {m.data?.form === "automate" && (
                <div className="as-form">
                  <label className="as-row" style={{ alignItems: "center" }}>
                    Relancer les retards tous les
                    <input className="inp num" type="number" min={1} max={14} style={{ width: 64 }} value={auto.everyDays} onChange={(e) => setAuto({ everyDays: Number(e.target.value) })} />
                    jour(s)
                  </label>
                  <div className="as-row">
                    <button className="btn primary sm" type="button" disabled={busy} onClick={() => ask({ intent: "automate", enabled: true, everyDays: auto.everyDays }, `Activer tous les ${auto.everyDays} j`)}>
                      Activer
                    </button>
                    {m.data.automation?.enabled && (
                      <button className="btn sm" type="button" disabled={busy} onClick={() => ask({ intent: "automate", enabled: false }, "Désactiver")}>
                        Désactiver
                      </button>
                    )}
                  </div>
                </div>
              )}
              {m.data?.suggestions?.length ? (
                <div className="as-actions">
                  {m.data.suggestions.filter((sg) => missions.some((x) => x.code === sg.intent)).map((sg) => (
                    <button key={sg.intent + sg.label} className="btn ghost sm" type="button" disabled={busy} onClick={() => mission(sg.intent)}>
                      {sg.label}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          ))}
          {busy && <div className="as-msg as-bot as-typing">L’assistant réfléchit…</div>}
          <div ref={end} />
        </div>
        {msgs.length > 0 && (
          <div className="as-quick">
            {missions.map((m) => (
              <button key={m.code} className="as-chip" type="button" disabled={busy} onClick={() => mission(m.code)}>
                {m.icon} {m.label}
              </button>
            ))}
          </div>
        )}
        <form className="as-input" onSubmit={(e) => (e.preventDefault(), send())}>
          <input className="inp" placeholder="Demandez-moi quelque chose sur ce projet…" value={text} maxLength={1500} onChange={(e) => setText(e.target.value)} />
          <button className="btn primary" type="submit" disabled={busy || !text.trim()} aria-label="Envoyer">
            ➤
          </button>
        </form>
      </section>
    </div>,
    document.body,
  );
}
