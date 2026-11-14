import { useState } from "react";

import { assistantApi } from "../api/endpoints";
import { useAction } from "./ui";

type Message = { from: "thor" | "you"; text: string };

/** Chat d'aide de bas de page. Les contrôles d'accès sont revérifiés par l'API à chaque question. */
export function HelpChat() {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([{ from: "thor", text: "Bonjour, je suis THOR. Je peux vous guider dans Control Tower selon les droits de votre profil." }]);
  const { run, busy } = useAction();
  const send = () => {
    const text = question.trim();
    if (!text || busy) return;
    setQuestion("");
    setMessages((rows) => [...rows, { from: "you", text }]);
    void run(() => assistantApi.ask(text), "").then((result) => {
      if (result) setMessages((rows) => [...rows, { from: "thor", text: result.answer }]);
    }, (error: unknown) => setMessages((rows) => [...rows, { from: "thor", text: error instanceof Error ? error.message : "Le chat est momentanément indisponible." }]));
  };
  return <>
    {open && <section aria-label="Chat d'aide THOR" style={{ position: "fixed", right: 22, bottom: 88, zIndex: 1000, width: "min(360px, calc(100vw - 28px))", height: 430, background: "var(--panel, #fff)", border: "1px solid var(--line, #dce3ed)", borderRadius: 16, boxShadow: "0 16px 50px #10213b30", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <header style={{ padding: "14px 16px", color: "white", background: "linear-gradient(120deg,#1e3a8a,#2563eb)" }}><b>THOR · Aide Control Tower</b><button aria-label="Fermer le chat" onClick={() => setOpen(false)} style={{ float: "right", color: "white", border: 0, background: "transparent", cursor: "pointer" }}>✕</button><small style={{ display: "block", opacity: .8 }}>Réponses limitées aux droits de votre profil</small></header>
      <div aria-live="polite" style={{ flex: 1, overflowY: "auto", padding: 12, display: "flex", flexDirection: "column", gap: 10 }}>
        {messages.map((message, index) => <div key={index} style={{ alignSelf: message.from === "you" ? "flex-end" : "flex-start", maxWidth: "88%", padding: "9px 11px", borderRadius: 12, background: message.from === "you" ? "#e7efff" : "#f1f4f8", fontSize: 13, whiteSpace: "pre-wrap" }}>{message.text}</div>)}
      </div>
      <form onSubmit={(event) => { event.preventDefault(); send(); }} style={{ display: "flex", gap: 8, padding: 10, borderTop: "1px solid #e5eaf1" }}>
        <input aria-label="Votre question" className="inp" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Posez votre question…" maxLength={1200} />
        <button className="btn primary" disabled={busy || !question.trim()} aria-label="Envoyer">➤</button>
      </form>
    </section>}
    <button onClick={() => setOpen((value) => !value)} aria-expanded={open} aria-label={open ? "Fermer le chat THOR" : "Ouvrir le chat THOR"} style={{ position: "fixed", right: 22, bottom: 20, zIndex: 1001, border: 0, borderRadius: 28, padding: "12px 18px", color: "white", background: "linear-gradient(120deg,#1e3a8a,#2563eb)", boxShadow: "0 8px 26px #1e3a8a55", cursor: "pointer", fontWeight: 700 }}>⚡ THOR · Aide</button>
  </>;
}
