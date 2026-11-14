import { useState } from "react";

export type Proposal = {
  id: string; kind: string; icon: string; category: string; level: "crit" | "warn" | "info";
  title: string; why: string; effect: string; do: string; payload: Record<string, unknown>;
  edit: { owner?: number | null; due?: string };
  assistant?: string; validator?: string; assistantName?: string; validatorLabel?: string;
};
const ASSISTANT: Record<string, string> = { atlas: "🧭 Atlas", nova: "📐 Nova", orion: "🛠️ Orion", vega: "🧪 Vega", mercure: "💶 Mercure", lyra: "🤝 Lyra", maestro: "🎼 Maestro" };
const VALIDATOR: Record<string, string> = { pm: "chef de projet", tl: "tech lead", client: "client", admin: "administrateur", ai: "Orchestrateur IA", auto: "exécution directe" };
export type ReviewHistory = { id: string; title: string; decision: string; by: string; result: string; at: string };
type Member = { id: number; name: string };
type Edits = Record<string, { owner?: number | null; due?: string }>;

const LEVEL = { crit: "Urgent", warn: "Important", info: "À prévoir" } as const;

/** Propositions du Chef de projet IA, à valider par le chef de projet humain (travail en binôme). */
export function ReviewPanel({ proposals, team, busy, canDecide, onDecide }: {
  proposals: Proposal[]; team: Member[]; busy: boolean; canDecide: boolean;
  onDecide: (accept: string[], reject: string[], edits: Edits) => void;
}) {
  const [sel, setSel] = useState<Set<string>>(() => new Set(proposals.filter((p) => p.level !== "info").map((p) => p.id)));
  const [edits, setEdits] = useState<Edits>({});
  const [open, setOpen] = useState<string | null>(null);
  if (!proposals.length) return null;
  const toggle = (id: string) => setSel((s) => {
    const n = new Set(s);
    if (n.has(id)) n.delete(id);
    else n.add(id);
    return n;
  });
  const val = (p: Proposal) => ({ ...p.edit, ...(edits[p.id] ?? {}) });
  const set = (id: string, k: "owner" | "due", v: string) =>
    setEdits((e) => ({ ...e, [id]: { ...(e[id] ?? {}), [k]: k === "owner" ? (v ? Number(v) : null) : v } }));
  const ids = proposals.map((p) => p.id).filter((id) => sel.has(id));
  return (
    <div className="rv-panel">
      <div className="rv-head">
        <b>🤝 Propositions à valider ({proposals.length})</b>
        <button className="btn ghost sm" type="button" onClick={() => setSel(sel.size === proposals.length ? new Set() : new Set(proposals.map((p) => p.id)))}>
          {sel.size === proposals.length ? "Tout désélectionner" : "Tout sélectionner"}
        </button>
      </div>
      {proposals.map((p) => {
        const v = val(p);
        return (
          <div key={p.id} className={`rv-card rv-${p.level}${sel.has(p.id) ? " on" : ""}`}>
            <label className="rv-top">
              {canDecide && <input type="checkbox" checked={sel.has(p.id)} onChange={() => toggle(p.id)} />}
              <span className="rv-icon" aria-hidden="true">{p.icon}</span>
              <span className="rv-title">
                <b>{p.title}</b>
                <small>
                  <span className={`rv-lvl rv-lvl-${p.level}`}>{LEVEL[p.level]}</span> · {p.category}
                  {p.assistant ? ` · proposé par ${ASSISTANT[p.assistant] ?? p.assistant}` : ""}
                  {p.validator ? ` · validation : ${VALIDATOR[p.validator] ?? p.validator}` : ""}
                </small>
              </span>
              <button className="btn ghost sm" type="button" onClick={(e) => { e.preventDefault(); setOpen(open === p.id ? null : p.id); }}>
                {open === p.id ? "Masquer" : "Détails"}
              </button>
            </label>
            {open === p.id && (
              <div className="rv-detail">
                <div><span className="rv-k">Pourquoi</span> {p.why}</div>
                <div><span className="rv-k">Ce que je ferai</span> {p.effect}</div>
              </div>
            )}
            {canDecide && ("owner" in p.edit || "due" in p.edit) && (
              <div className="rv-edit">
                {"owner" in p.edit && (
                  <label>
                    Responsable
                    <select className="inp" value={v.owner ?? ""} onChange={(e) => set(p.id, "owner", e.target.value)}>
                      <option value="">Chef de projet</option>
                      {team.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
                    </select>
                  </label>
                )}
                {"due" in p.edit && (
                  <label>
                    Échéance
                    <input className="inp" type="date" value={v.due ?? ""} onChange={(e) => set(p.id, "due", e.target.value)} />
                  </label>
                )}
              </div>
            )}
          </div>
        );
      })}
      {canDecide ? (
        <div className="rv-foot">
          <button className="btn primary sm" type="button" disabled={busy || !ids.length} onClick={() => onDecide(ids, [], edits)}>
            ✔ Valider la sélection ({ids.length})
          </button>
          <button className="btn ghost sm" type="button" disabled={busy || !ids.length} onClick={() => onDecide([], ids, {})}>
            ✖ Écarter la sélection
          </button>
          <span className="muted" style={{ fontSize: 11.5 }}>Rien n’est exécuté sans votre validation.</span>
        </div>
      ) : (
        <div className="muted" style={{ fontSize: 12 }}>Seul le chef de projet valide ces propositions.</div>
      )}
    </div>
  );
}

/** Journal du binôme : décisions prises (validées, écartées, exécutées automatiquement). */
export function ReviewHistoryList({ items }: { items: ReviewHistory[] }) {
  const [open, setOpen] = useState(false);
  if (!items.length) return null;
  return (
    <div className="rv-hist">
      <button className="btn ghost sm" type="button" onClick={() => setOpen(!open)}>
        📒 Journal du binôme ({items.length}) {open ? "▲" : "▼"}
      </button>
      {open && (
        <ul>
          {items.map((h, i) => (
            <li key={i}>
              <b>{h.decision === "validée" ? "✅" : "✖"} {h.title}</b>
              <small>
                {h.decision} par {h.by} · {new Date(h.at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}
                {h.result ? ` · ${h.result}` : ""}
              </small>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
