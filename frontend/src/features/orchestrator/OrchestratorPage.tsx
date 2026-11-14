import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import { api, ApiError } from "../../api/client";
import { ErrorNotice, Loading, useAction } from "../../components/ui";
import { ReviewPanel, type Proposal } from "../assistant/ReviewPanel";

type Mate = {
  code: string; name: string; role: string; avatar: string; color: string; mission: string; enabled: boolean; mode: "auto" | "semi";
  stats: { actions: number; proposals: number; last: string | null }; pending: number;
};
type Pending = Proposal & { validator: string; validatorLabel: string; assistantName?: string; canValidate: boolean };
type Entry = { id: string; at: string; kind: string; actor: string; assistant: string | null; text: string };
type Overview = {
  licensed: boolean; maxMode: string; canConfigure: boolean; roster: Mate[]; circuits: Record<string, string>;
  categories: Record<string, string>; validators: Record<string, string>; pending: Pending[]; journal: Entry[];
  team: { id: number; name: string }[]; lastCycle: string | null; done?: { title: string; result: string }[];
};

const KIND = {
  proposition: ["💡", "Proposition"], validation: ["✅", "Validation"], refus: ["✖", "Refus"], execution: ["⚙️", "Exécution"],
  question: ["❓", "Question"], reponse: ["💬", "Réponse"], correction: ["✏️", "Correction"], modification: ["🛠", "Paramétrage"],
  cycle: ["🎼", "Orchestration"],
} as Record<string, [string, string]>;
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");

/** Orchestrateur IA du projet : équipe d'assistants, circuits de validation, propositions et fil des échanges. */
export function OrchestratorPage({ projectId, projectName }: { projectId: string; projectName: string }) {
  const url = `/projects/${encodeURIComponent(projectId)}/orchestrator`;
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [settings, setSettings] = useState(false);
  const [kind, setKind] = useState("");
  const [who, setWho] = useState("");
  const [last, setLast] = useState<{ title: string; result: string }[] | null>(null);
  const { run, busy } = useAction();
  const load = useCallback(() => {
    api.get<Overview>(url).then((d) => (setData(d), setError(null)), setError);
  }, [url]);
  useEffect(load, [load]);

  const journal = useMemo(
    () => (data?.journal ?? []).filter((e) => (!kind || e.kind === kind) && (!who || e.assistant === who)),
    [data, kind, who],
  );
  if (error) return <ErrorNotice error={error instanceof ApiError ? error : new ApiError(500, {})} onRetry={load} />;
  if (!data) return <Loading />;
  const mine = data.pending.filter((p) => p.canValidate);
  const others = data.pending.filter((p) => !p.canValidate);
  const names = Object.fromEntries(data.roster.map((m) => [m.code, m]));
  const orchestrate = () =>
    run(() => api.post<Overview>(url, { action: "run" }), "Orchestration terminée").then((d) => d && (setData(d), setLast(d.done ?? [])), () => undefined);
  const decide = (accept: string[], reject: string[], edits: Record<string, unknown>) =>
    run(() => api.post<Overview>(url, { action: "decide", accept, reject, edits }), accept.length ? "Propositions validées" : "Propositions écartées")
      .then((d) => d && (setData(d), setLast(d.done ?? [])), () => undefined);

  return (
    <div className="page orc">
      <div>
        <a className="lnk" href={`#projets/${encodeURIComponent(projectId)}`}>← {projectName}</a>
      </div>
      <div className="ph">
        <div>
          <div className="eyebrow">Assistants IA · {data.maxMode === "auto" ? "licence jusqu’au mode automatique" : "licence semi-automatique"}</div>
          <h1 className="pj-title">
            🎼 Orchestrateur IA
            {data.canConfigure && (
              <button className="pj-gear" type="button" title="Paramétrer les assistants et les circuits de validation" aria-label="Paramètres" onClick={() => setSettings(true)}>
                ⚙
              </button>
            )}
          </h1>
          <p>Maestro coordonne les assistants IA et les humains du projet, applique les circuits de validation et trace chaque échange.</p>
        </div>
        <div className="btns">
          <span className="faint" style={{ fontSize: 12.5 }}>Dernier passage : {when(data.lastCycle)}</span>
          <button className="btn primary" type="button" disabled={busy} onClick={orchestrate}>
            {busy ? "Orchestration…" : "▶ Lancer l’orchestration"}
          </button>
        </div>
      </div>

      {last && last.length > 0 && (
        <div className="as-autodone">
          <b>🎼 Actions menées par les assistants :</b>
          <ul>{last.map((d, i) => <li key={i}>{d.result}</li>)}</ul>
        </div>
      )}

      <section>
        <h2 className="sec">Équipe IA du projet</h2>
        <div className="orc-team">
          {data.roster.map((m) => (
            <div key={m.code} className={`orc-mate${m.enabled ? "" : " off"}`} style={{ ["--mate" as string]: m.color }}>
              <div className="orc-av">{m.avatar}</div>
              <div className="orc-id">
                <b>{m.name}</b>
                <small>{m.role}</small>
              </div>
              <span className={`pill nodot ${m.enabled ? (m.mode === "auto" ? "ok" : "info") : ""}`}>
                {m.enabled ? (m.mode === "auto" ? "⚡ Automatique" : "🤝 Semi-auto") : "Non affecté"}
              </span>
              <p>{m.mission}</p>
              <div className="orc-stats">
                <span><b>{m.stats.proposals}</b> proposition(s)</span>
                <span><b>{m.stats.actions}</b> action(s)</span>
                <span><b>{m.pending}</b> en attente</span>
              </div>
              <small className="faint">Dernière activité : {when(m.stats.last)}</small>
            </div>
          ))}
        </div>
      </section>

      <section className="orc-cols">
        <div className="card orc-card">
          <h2 className="sec">À valider par vous ({mine.length})</h2>
          {mine.length === 0 ? (
            <div className="empty">Aucune proposition n’attend votre validation.</div>
          ) : (
            <ReviewPanel key={mine.map((p) => p.id).join()} proposals={mine} team={data.team} busy={busy} canDecide onDecide={decide} />
          )}
          {others.length > 0 && (
            <>
              <h3 className="orc-sub">En attente d’autres validateurs ({others.length})</h3>
              <ul className="orc-others">
                {others.map((p) => (
                  <li key={p.id}>
                    <span>{p.icon}</span>
                    <span>
                      <b>{p.title}</b>
                      <small>{p.assistantName} · à valider par : {p.validatorLabel}</small>
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>

        <div className="card orc-card">
          <div className="orc-jh">
            <h2 className="sec">Fil d’orchestration</h2>
            <div className="btns">
              <select className="inp sm" aria-label="Type" value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="">Tous les échanges</option>
                {Object.entries(KIND).map(([k, [i, l]]) => <option key={k} value={k}>{i} {l}</option>)}
              </select>
              <select className="inp sm" aria-label="Assistant" value={who} onChange={(e) => setWho(e.target.value)}>
                <option value="">Tous les assistants</option>
                {data.roster.map((m) => <option key={m.code} value={m.code}>{m.avatar} {m.name}</option>)}
              </select>
            </div>
          </div>
          {journal.length === 0 ? (
            <div className="empty">Aucun échange pour l’instant. Lancez l’orchestration pour démarrer.</div>
          ) : (
            <ol className="orc-feed">
              {journal.map((e) => {
                const m = e.assistant ? names[e.assistant] : null;
                const [icon, label] = KIND[e.kind] ?? ["•", e.kind];
                return (
                  <li key={e.id} className={`orc-ev orc-${e.kind}`}>
                    <span className="orc-dot" style={m ? { background: m.color } : undefined}>{m?.avatar ?? "👤"}</span>
                    <div>
                      <div className="orc-evh">
                        <b>{e.actor}</b> <span className="pill nodot">{icon} {label}</span>
                        <small className="faint">{when(e.at)}</small>
                      </div>
                      <p>{e.text}</p>
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      </section>

      {settings && data.canConfigure && (
        <OrchestratorSettings data={data} onClose={() => setSettings(false)}
          onSave={(body) => run(() => api.put<Overview>(url, body), "Paramétrage enregistré").then((d) => d && (setData(d), setSettings(false)), () => undefined)} busy={busy} />
      )}
    </div>
  );
}

function OrchestratorSettings({ data, onClose, onSave, busy }: {
  data: Overview; onClose: () => void; onSave: (b: unknown) => void; busy: boolean;
}) {
  const [team, setTeam] = useState(() => Object.fromEntries(data.roster.map((m) => [m.code, { enabled: m.enabled, mode: m.mode }])));
  const [circuits, setCircuits] = useState({ ...data.circuits });
  return createPortal(
    <div className="scrim" onClick={onClose}>
      <div className="modal orc-modal" role="dialog" aria-label="Paramètres de l’orchestration" onClick={(e) => e.stopPropagation()}>
        <div className="modal-h">
          <h3>⚙ Assistants du projet et circuits de validation</h3>
          <button className="icon-btn" type="button" aria-label="Fermer" onClick={onClose}>✕</button>
        </div>
        <div className="modal-b">
          <h4 style={{ marginTop: 0 }}>Assistants affectés au projet</h4>
          <p className="muted" style={{ fontSize: 12.5, marginTop: 0 }}>
            Les assistants IA sont des ressources du projet : choisissez ceux qui travaillent sur ce projet et leur mode
            {data.maxMode !== "auto" ? " (votre licence est limitée au mode semi-automatique)" : ""}.
          </p>
          <table className="tbl tight">
            <tbody>
              {data.roster.map((m) => (
                <tr key={m.code}>
                  <td>
                    <label className="pj-check">
                      <input type="checkbox" checked={team[m.code].enabled} onChange={(e) => setTeam({ ...team, [m.code]: { ...team[m.code], enabled: e.target.checked } })} />
                      <span>{m.avatar} <b>{m.name}</b> <small className="faint">· {m.role}</small></span>
                    </label>
                  </td>
                  <td className="r">
                    <select className="inp sm" value={team[m.code].mode} disabled={!team[m.code].enabled}
                      onChange={(e) => setTeam({ ...team, [m.code]: { ...team[m.code], mode: e.target.value as "auto" | "semi" } })}>
                      <option value="semi">🤝 Semi-automatique</option>
                      {data.maxMode === "auto" && <option value="auto">⚡ Automatique</option>}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <h4>Circuits de validation</h4>
          <p className="muted" style={{ fontSize: 12.5, marginTop: 0 }}>
            Pour chaque type de décision, qui valide ? Un assistant en semi-automatique soumet toujours ses propositions à un humain.
          </p>
          <table className="tbl tight">
            <tbody>
              {Object.entries(data.categories).map(([k, label]) => (
                <tr key={k}>
                  <td>{label}</td>
                  <td className="r">
                    <select className="inp sm" value={circuits[k]} onChange={(e) => setCircuits({ ...circuits, [k]: e.target.value })}>
                      {Object.entries(data.validators).map(([v, vl]) => <option key={v} value={v}>{vl}</option>)}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="modal-f">
          <button className="btn ghost" type="button" onClick={onClose}>Annuler</button>
          <button className="btn primary" type="button" disabled={busy} onClick={() => onSave({ assistants: team, circuits })}>Enregistrer</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
