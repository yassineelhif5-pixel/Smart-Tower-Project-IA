import { useState } from "react";

import { api } from "../../api/client";
import { useAction } from "../../components/ui";

export type AiQuestion = {
  id: string; task: string; taskTitle: string; kind: string; to: number; toName: string; question: string; by: string;
  at: string; status: "open" | "answered"; answer: string; answeredAt: string | null; answeredBy?: string;
  newDue: string | null; progress: number | null; blocked: boolean;
};

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "");

/** Formulaire de réponse à une question du Chef de projet IA. */
export function QuestionAnswer({ projectId, q, onDone }: { projectId: string; q: AiQuestion; onDone?: (q: AiQuestion) => void }) {
  const { run, busy } = useAction();
  const [f, setF] = useState({ answer: "", newDue: "", progress: "", blocked: q.kind === "blocked" });
  const send = () =>
    run(() => api.post<AiQuestion>(`/projects/${encodeURIComponent(projectId)}/questions`, { id: q.id, ...f, progress: f.progress || null, newDue: f.newDue || null }),
      "Réponse envoyée au chef de projet").then((r) => r && onDone?.(r), () => undefined);
  return (
    <div className="qa-form">
      <textarea className="inp" rows={3} placeholder="Votre réponse (avancement, difficultés, besoin d’aide…)" value={f.answer}
        onChange={(e) => setF({ ...f, answer: e.target.value })} />
      <div className="qa-row">
        <label>
          Nouvelle date de fin
          <input className="inp" type="date" value={f.newDue} onChange={(e) => setF({ ...f, newDue: e.target.value })} />
        </label>
        <label>
          Avancement (%)
          <input className="inp num" type="number" min={0} max={100} value={f.progress} onChange={(e) => setF({ ...f, progress: e.target.value })} />
        </label>
        <label className="qa-check">
          <input type="checkbox" checked={f.blocked} onChange={(e) => setF({ ...f, blocked: e.target.checked })} /> Je suis bloqué
        </label>
      </div>
      <button className="btn primary sm" type="button" disabled={busy || (!f.answer.trim() && !f.newDue)} onClick={send}>
        Répondre
      </button>
    </div>
  );
}

/** Questions qui me sont adressées par le Chef de projet IA. */
export function MyQuestions({ projectId, questions }: { projectId: string; questions: AiQuestion[] }) {
  const [done, setDone] = useState<Record<string, boolean>>({});
  const open = questions.filter((q) => !done[q.id]);
  if (!questions.length) return null;
  return (
    <div className="qa-box">
      <h4>❓ Le Chef de projet IA vous pose {questions.length > 1 ? `${questions.length} questions` : "une question"}</h4>
      {open.length === 0 && <div className="muted" style={{ fontSize: 13 }}>Merci, vos réponses ont été transmises au chef de projet. ✅</div>}
      {open.map((q) => (
        <div key={q.id} className="qa-item">
          <div className="qa-q">
            <b>{q.taskTitle}</b>
            <p>{q.question}</p>
            <small className="faint">{q.by} · {when(q.at)}</small>
          </div>
          <QuestionAnswer projectId={projectId} q={q} onDone={() => setDone((d) => ({ ...d, [q.id]: true }))} />
        </div>
      ))}
    </div>
  );
}

/** Vue chef de projet : questions posées à l'équipe et réponses reçues. */
export function TeamQuestions({ items }: { items: AiQuestion[] }) {
  const [open, setOpen] = useState(false);
  if (!items.length) return null;
  const waiting = items.filter((q) => q.status === "open").length;
  return (
    <div className="rv-hist">
      <button className="btn ghost sm" type="button" onClick={() => setOpen(!open)}>
        💬 Questions à l’équipe ({items.length}{waiting ? `, ${waiting} sans réponse` : ""}) {open ? "▲" : "▼"}
      </button>
      {open && (
        <ul>
          {items.map((q) => (
            <li key={q.id}>
              <b>{q.status === "open" ? "⏳" : "💬"} {q.toName} · {q.taskTitle}</b>
              <small>Question : {q.question}</small>
              {q.status === "answered" ? (
                <small className="qa-ans">
                  Réponse ({when(q.answeredAt)}) : {q.answer || "—"}
                  {q.newDue ? ` · nouvelle date ${new Date(q.newDue).toLocaleDateString("fr-FR")}` : ""}
                  {q.progress != null ? ` · ${q.progress} %` : ""}
                  {q.blocked ? " · bloqué" : ""}
                </small>
              ) : (
                <small>En attente de réponse depuis le {when(q.at)}</small>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
