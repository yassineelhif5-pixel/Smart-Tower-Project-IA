// Test SMTP détaillé : connexion, chiffrement, authentification (et envoi si adresse), avec le journal OK / KO
// et l'erreur exacte renvoyée par le serveur. Utilisé sous chaque configuration SMTP (admin, Pilote, plateforme).
import { useState } from "react";

import { api } from "../../api/client";
import { useApi } from "../../api/useApi";
import { useAction } from "../../components/ui";

type Hist = { at: string; ok: boolean; recipient: string; subject: string; error: string };
type Res = { ok: boolean; step: string; code: number | null; error: string; at: string; server: string; history: Hist[] };

export function SmtpTestPanel({ postUrl, getUrl, initial }: { postUrl: string; getUrl?: string; initial?: Hist[] }) {
  const h = useApi(() => (getUrl ? api.get<{ history: Hist[] }>(getUrl) : Promise.resolve({ history: initial ?? [] })), [getUrl]);
  const { run, busy } = useAction();
  const [to, setTo] = useState("");
  const [last, setLast] = useState<Res | null>(null);
  const [hist, setHist] = useState<Hist[] | null>(null);
  const list = hist ?? h.data?.history ?? initial ?? [];
  const go = (send: boolean) => void run(() => api.post<Res>(postUrl, send ? { to } : {})).then((r) => { if (r) { setLast(r); setHist(r.history); } }, () => undefined);
  return (
    <div style={{ border: "1px solid var(--line, #e2e8f0)", borderRadius: 10, padding: 12, marginTop: 10 }}>
      <b>🔌 Test SMTP et journal</b>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", margin: "8px 0" }}>
        <button type="button" className="btn sm" disabled={busy} onClick={() => go(false)}>Tester la connexion</button>
        <input className="inp" style={{ width: 240 }} placeholder="adresse pour un e-mail de test" aria-label="Adresse de test" value={to} onChange={(e) => setTo(e.target.value)} />
        <button type="button" className="btn sm primary" disabled={busy || !to.includes("@")} onClick={() => go(true)}>Tester et envoyer</button>
      </div>
      {last && (
        <div style={{ padding: "8px 10px", borderRadius: 8, marginBottom: 8, background: last.ok ? "#dcfce7" : "#fee2e2", color: last.ok ? "#166534" : "#991b1b", fontSize: 13 }}>
          {last.ok ? <>✅ <b>OK</b> — {last.server} · {last.step === "envoi" ? "connexion, authentification et envoi réussis" : "connexion et authentification réussies"}</>
            : <>❌ <b>Échec</b> à l'étape « {last.step} » — {last.server}{last.code ? ` · code ${last.code}` : ""}<div style={{ fontFamily: "monospace", fontSize: 12, marginTop: 4, wordBreak: "break-word" }}>{last.error}</div></>}
        </div>
      )}
      {list.length === 0 ? <p className="muted" style={{ fontSize: 12, margin: 0 }}>Aucun test enregistré.</p> : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 4, maxHeight: 220, overflow: "auto" }}>
          {list.map((x, i) => (
            <li key={i} style={{ fontSize: 12, borderLeft: `3px solid ${x.ok ? "#16a34a" : "#dc2626"}`, paddingLeft: 8 }}>
              <b style={{ color: x.ok ? "#15803d" : "#b91c1c" }}>{x.ok ? "OK" : "KO"}</b> · {new Date(x.at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "medium" })} · {x.recipient}
              <div className="muted">{x.subject}</div>
              {x.error && <div style={{ fontFamily: "monospace", color: "#b91c1c", wordBreak: "break-word" }}>{x.error}</div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
