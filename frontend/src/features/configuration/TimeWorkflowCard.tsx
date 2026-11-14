// Administrateur : workflow de validation des temps par projet, dessiné comme un circuit
// (Saisie → Valideur 1 → … → Valideur final → Client → Validé), appliqué à un ou plusieurs projets.
import { useState } from "react";

import { api } from "../../api/client";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Loading, Pill, useAction } from "../../components/ui";

type Step = { kind: "pm" | "tl" | "user" | "admin"; user?: number };
type WF = { steps: Step[]; client: boolean };
type Data = {
  projects: { id: string; name: string; client: string; status: string; pm: string | null; tl: string | null; workflow: WF | null; chain: string[]; pending: Record<string, number> }[];
  users: { id: number; name: string; role: string }[];
  kinds: { code: Step["kind"]; label: string }[];
  defaultMode: string; defaultClient: boolean;
};

const node: React.CSSProperties = { minWidth: 150, padding: "10px 12px", borderRadius: 12, border: "2px solid var(--line-2)", background: "var(--card, #fff)", display: "flex", flexDirection: "column", gap: 6 };
const arrow = <span aria-hidden style={{ fontSize: 22, color: "var(--muted)", alignSelf: "center" }}>➜</span>;

export function TimeWorkflowCard() {
  const r = useApi(() => api.get<Data>("/timesheets/workflows"));
  const { run, busy } = useAction();
  const [sel, setSel] = useState<string[]>([]);
  const [wf, setWf] = useState<WF>({ steps: [{ kind: "pm" }], client: false });
  const [q, setQ] = useState("");
  if (r.error) return <ErrorNotice error={r.error} onRetry={r.reload} />;
  if (!r.data) return <Loading />;
  const d = r.data;
  const list = d.projects.filter((p) => !q.trim() || `${p.name} ${p.client}`.toLowerCase().includes(q.trim().toLowerCase()));
  const setStep = (i: number, st: Step) => setWf({ ...wf, steps: wf.steps.map((x, j) => (j === i ? st : x)) });
  const valid = wf.steps.length > 0 && wf.steps.every((s) => s.kind !== "user" || s.user);
  const apply = (workflow: WF | null) => void run(() => api.put<Data>("/timesheets/workflows", { projects: sel, workflow }),
    workflow ? `Workflow appliqué à ${sel.length} projet(s)` : `Circuit par défaut rétabli sur ${sel.length} projet(s)`).then((res) => res && r.setData(res), () => undefined);
  const load = (p: Data["projects"][number]) => { setSel([p.id]); setWf(p.workflow ?? { steps: [{ kind: "pm" }], client: d.defaultClient }); };
  return (
    <Card title="Workflow de validation par projet" sub={`Dessinez le circuit (qui valide en 1er, puis en final, puis le client éventuellement) et appliquez-le à un ou plusieurs projets. Sans workflow propre, un projet suit le circuit de l’entreprise : ${d.defaultMode}${d.defaultClient ? " puis le client" : ""}.`}>
      {/* Le dessin du circuit */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "stretch", padding: 12, borderRadius: 14, background: "color-mix(in srgb, var(--line) 30%, transparent)" }}>
        <div style={{ ...node, borderColor: "var(--accent)", minWidth: 110, justifyContent: "center" }}><b>✍️ Saisie</b><small className="muted">Collaborateur</small></div>
        {wf.steps.map((st, i) => (
          <div key={i} style={{ display: "flex", gap: 8 }}>
            {arrow}
            <div style={{ ...node, borderColor: i === wf.steps.length - 1 ? "var(--warn)" : "var(--line-2)" }}>
              <b>{i === wf.steps.length - 1 && wf.steps.length > 1 ? "🏁 Valideur final" : `👤 Valideur ${i + 1}`}</b>
              <select className="inp" aria-label={`Type du valideur ${i + 1}`} value={st.kind} onChange={(e) => setStep(i, { kind: e.target.value as Step["kind"] })}>
                {d.kinds.map((k) => <option key={k.code} value={k.code}>{k.label}</option>)}
              </select>
              {st.kind === "user" && (
                <select className="inp" aria-label={`Personne qui valide à l'étape ${i + 1}`} value={st.user ?? ""} onChange={(e) => setStep(i, { kind: "user", user: Number(e.target.value) || undefined })}>
                  <option value="">Choisir…</option>{d.users.map((u) => <option key={u.id} value={u.id}>{u.name} — {u.role}</option>)}
                </select>
              )}
              <div style={{ display: "flex", gap: 4 }}>
                <button type="button" className="btn sm ghost" disabled={i === 0} title="Avancer" onClick={() => { const s = [...wf.steps]; [s[i - 1], s[i]] = [s[i], s[i - 1]]; setWf({ ...wf, steps: s }); }}>◀</button>
                <button type="button" className="btn sm ghost" disabled={i === wf.steps.length - 1} title="Reculer" onClick={() => { const s = [...wf.steps]; [s[i + 1], s[i]] = [s[i], s[i + 1]]; setWf({ ...wf, steps: s }); }}>▶</button>
                <button type="button" className="btn sm ghost" disabled={wf.steps.length === 1} title="Supprimer l'étape" onClick={() => setWf({ ...wf, steps: wf.steps.filter((_, j) => j !== i) })}>✕</button>
              </div>
            </div>
          </div>
        ))}
        {wf.steps.length < 6 && <button type="button" className="btn sm" style={{ alignSelf: "center" }} onClick={() => setWf({ ...wf, steps: [...wf.steps, { kind: "admin" }] })}>+ Étape</button>}
        {arrow}
        <label style={{ ...node, minWidth: 120, cursor: "pointer", borderStyle: wf.client ? "solid" : "dashed", borderColor: wf.client ? "var(--info, var(--accent))" : "var(--line-2)", opacity: wf.client ? 1 : 0.6 }}>
          <b>🏢 Client</b>
          <span style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }}><input type="checkbox" checked={wf.client} onChange={(e) => setWf({ ...wf, client: e.target.checked })} /> Valide après</span>
        </label>
        {arrow}
        <div style={{ ...node, borderColor: "var(--ok)", minWidth: 110, justifyContent: "center" }}><b>✅ Validé</b><small className="muted">Budget, CRA, facture</small></div>
      </div>

      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", margin: "12px 0" }}>
        <b>{sel.length} projet(s) sélectionné(s)</b>
        <button type="button" className="btn primary sm" disabled={busy || !sel.length || !valid} onClick={() => apply(wf)}>Appliquer ce workflow</button>
        <button type="button" className="btn sm" disabled={busy || !sel.length} onClick={() => apply(null)}>Revenir au circuit de l’entreprise</button>
        {!valid && <small className="muted">Choisissez la personne de chaque étape « Personne désignée ».</small>}
        <input className="inp" style={{ maxWidth: 240, marginLeft: "auto" }} placeholder="Filtrer les projets…" aria-label="Filtrer les projets" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>

      <div className="tbl-wrap"><table className="tbl tight">
        <thead><tr>
          <th><input type="checkbox" aria-label="Tout sélectionner" checked={list.length > 0 && list.every((p) => sel.includes(p.id))}
            onChange={(e) => setSel(e.target.checked ? [...new Set([...sel, ...list.map((p) => p.id)])] : sel.filter((id) => !list.some((p) => p.id === id)))} /></th>
          <th>Projet</th><th>Client</th><th>Circuit actuel</th><th>En attente</th><th /></tr></thead>
        <tbody>{list.map((p) => (
          <tr key={p.id} style={{ background: sel.includes(p.id) ? "var(--accent-soft)" : undefined }}>
            <td><input type="checkbox" aria-label={`Sélectionner ${p.name}`} checked={sel.includes(p.id)} onChange={(e) => setSel(e.target.checked ? [...sel, p.id] : sel.filter((x) => x !== p.id))} /></td>
            <td><b>{p.name}</b>{p.status !== "active" && <small className="muted"> ({p.status === "closed" ? "clôturé" : "en pause"})</small>}</td>
            <td>{p.client}</td>
            <td>{p.workflow ? <span style={{ display: "inline-flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}>{p.chain.map((c, i) => <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>{i > 0 && "→"}<Pill tone={i === p.chain.length - 1 ? "acc" : "info"}>{c}</Pill></span>)}</span>
              : <span className="muted">Circuit de l’entreprise : {p.chain.join(" → ")}</span>}</td>
            <td>{Object.keys(p.pending).length ? Object.entries(p.pending).map(([s, n]) => <small key={s} style={{ display: "block" }}>{n} à l’étape {Number(s) + 1}</small>) : <span className="muted">—</span>}</td>
            <td><button type="button" className="btn sm ghost" onClick={() => load(p)}>Modifier</button></td>
          </tr>
        ))}</tbody>
      </table></div>
    </Card>
  );
}
