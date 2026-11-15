// Historique des feuilles de temps : par personne et par mois, état actuel, en attente chez qui, lien vers le CRA.
import { useState } from "react";

import { api, API_BASE } from "../../api/client";
import { useApi } from "../../api/useApi";
import { ErrorNotice, Loading } from "../../components/ui";

type Row = {
  person: { id: number; name: string }; period: string; state: string; stateLabel: string;
  totals: Record<string, number>; total: number; absences: number;
  projects: { id: string; name: string; client: string }[];
  waiting: { who: string; role: string; step: string }[];
  cra: { id: string; name: string; client: string; version: number; days: string | null; createdAt: string; number?: string; generatedBy?: string; approvers?: string[] }[];
  timeline: { at: string; kind: "envoi" | "validation" | "refus" | "cra"; by: string; step: string; count: number; hours: number | string; reason: string }[];
  mine: boolean;
  periodLabel?: string | null;
  pipelines: { project: string; steps: { label: string; state: "done" | "current" | "todo"; count: number }[]; complete: boolean; next: string | null }[];
  lastValidation: { by: string; at: string; status: string } | null;
};
type History = { scope: "own" | "team" | "all"; unit: "hour" | "day"; rows: Row[]; people: [number, string][] };

const SCOPE = { own: "Vos feuilles", team: "Vos feuilles et celles de votre équipe", all: "Toutes les feuilles de l’entreprise" };
const STATUS_ORDER: [string, string][] = [["approved", "Validé"], ["client", "Chez le client"], ["pending", "En validation"], ["draft", "Brouillon"], ["rejected", "Refusé"]];
const month = (p: string) => { const s = new Date(`${p}-01T00:00:00`).toLocaleDateString("fr-FR", { month: "long", year: "numeric" }); return s.charAt(0).toUpperCase() + s.slice(1); };
const fmt = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/0$/, "").replace(".", ","));

export function SheetHistory({ onClose, onOpen }: { onClose: () => void; onOpen: (period: string) => void }) {
  const [person, setPerson] = useState("");
  const [months, setMonths] = useState(6);
  const [group, setGroup] = useState<"month" | "week">("month");
  const [openTl, setOpenTl] = useState<string | null>(null);
  const r = useApi(() => api.get<History>(`/timesheets/history?months=${months}&group=${group}${person ? `&person=${person}` : ""}`), [months, person, group]);
  const unit = r.data?.unit === "day" ? "j" : "h";
  const download = async (id: string, name: string) => {
    const res = await fetch(`${API_BASE}/timesheets/history/cra/${encodeURIComponent(id)}`, { credentials: "include" });
    if (!res.ok) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(await res.blob());
    a.download = /\.(docx|pdf)$/i.test(name) ? name : `${name}.pdf`;
    a.click();
  };
  return (
    <div className="scrim" onClick={onClose}>
      <aside className="sh-hist" role="dialog" aria-label="Historique des feuilles de temps" onClick={(e) => e.stopPropagation()}>
        <header>
          <div>
            <h3>🕘 Historique des feuilles de temps</h3>
            {r.data && <small>{SCOPE[r.data.scope]}</small>}
          </div>
          <button className="icon-btn" type="button" aria-label="Fermer" onClick={onClose}>✕</button>
        </header>
        <div className="sh-hist-f">
          {r.data && r.data.scope !== "own" && (
            <select className="inp" aria-label="Personne" value={person} onChange={(e) => setPerson(e.target.value)}>
              <option value="">Toutes les personnes</option>
              {r.data.people.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
            </select>
          )}
          <div className="sh-seg" role="tablist" aria-label="Regroupement">
            <button type="button" role="tab" aria-selected={group === "week"} className={group === "week" ? "on" : ""} onClick={() => setGroup("week")}>Par semaine</button>
            <button type="button" role="tab" aria-selected={group === "month"} className={group === "month" ? "on" : ""} onClick={() => setGroup("month")}>Par mois</button>
          </div>
          <select className="inp" aria-label="Période" value={months} onChange={(e) => setMonths(Number(e.target.value))}>
            <option value={3}>3 derniers mois</option><option value={6}>6 derniers mois</option><option value={12}>12 derniers mois</option>
          </select>
        </div>
        {r.error ? <ErrorNotice error={r.error} onRetry={r.reload} /> : !r.data ? <Loading /> : r.data.rows.length === 0 ? (
          <p className="muted">Aucune feuille de temps sur la période.</p>
        ) : (
          <ul className="sh-hist-list">
            {r.data.rows.map((x) => (
              <li key={`${x.person.id}-${x.period}`} className={`st-${x.state}`}>
                <div className="sh-hist-top">
                  <div>
                    <b>{x.periodLabel ?? month(x.period)}</b>{r.data!.scope !== "own" && <span className="sh-hist-who"> · {x.person.name}</span>}
                    <small>{x.projects.map((p) => p.name).join(", ")}</small>
                  </div>
                  <span className={`sh-lock ${x.state}`}>{x.stateLabel}</span>
                </div>
                <div className="sh-hist-nums">
                  <span><b>{fmt(x.total)} {unit}</b> saisis</span>
                  {x.absences > 0 && <span>{fmt(x.absences)} {unit} d’absence</span>}
                  {STATUS_ORDER.filter(([k]) => x.totals[k]).map(([k, l]) => <span key={k} className={`sh-hist-pill ${k}`}>{l} : {fmt(x.totals[k])} {unit}</span>)}
                </div>
                {x.pipelines.map((pl) => (
                  <div key={pl.project} className="sh-pipe">
                    {x.pipelines.length > 1 && <small className="muted">{pl.project}</small>}
                    <div className="sh-pipe-steps">
                      {pl.steps.map((st, i) => (
                        <span key={i} className={`sh-step ${st.state}`} title={st.count ? `${st.count} saisie(s) à cette étape` : undefined}>
                          {st.state === "done" ? "✓" : st.state === "current" ? "⏳" : "○"} {st.label}{st.state === "current" && st.count ? ` (${st.count})` : ""}
                        </span>
                      ))}
                    </div>
                    <small className={pl.complete ? "sh-done" : "muted"}>{pl.complete ? "✓ Circuit terminé : tout est validé." : `Prochaine étape : ${pl.next}`}</small>
                  </div>
                ))}
                {x.lastValidation && <small className="muted">Dernière validation : {x.lastValidation.by} le {new Date(x.lastValidation.at).toLocaleDateString("fr-FR")}</small>}
                {x.waiting.length > 0 && (
                  <div className="sh-hist-wait">
                    ⏳ En attente : {x.waiting.map((w, i) => <span key={i}><b>{w.who}</b>{w.role ? ` (${w.role})` : ""} — {w.step}{i < x.waiting.length - 1 ? " · " : ""}</span>)}
                  </div>
                )}
                {x.cra.map((c) => (
                  <div key={c.id} className="sh-cra">
                    📄 <b>CRA v{c.version}</b> — {c.client}{c.number ? ` · facture ${c.number}` : ""} · généré le {new Date(c.createdAt).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })} par {c.generatedBy || "automatique"}
                    {c.approvers?.length ? <> · <span className="sh-done">validé par {c.approvers.join(", ")}</span></> : null}
                  </div>
                ))}
                <button type="button" className="btn sm ghost" style={{ alignSelf: "flex-start" }} onClick={() => setOpenTl(openTl === `${x.person.id}-${x.period}` ? null : `${x.person.id}-${x.period}`)}>
                  {openTl === `${x.person.id}-${x.period}` ? "▾ Masquer l’historique complet" : `▸ Historique complet (${x.timeline.length})`}
                </button>
                {openTl === `${x.person.id}-${x.period}` && (
                  <ol className="sh-tl">
                    {x.timeline.length === 0 && <li className="muted">Aucun événement enregistré.</li>}
                    {x.timeline.map((ev, i) => (
                      <li key={i} className={`sh-tl-${ev.kind}`}>
                        <time>{ev.at ? new Date(ev.at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—"}</time>
                        <span>
                          {ev.kind === "envoi" ? <>📤 <b>Envoi en validation</b> {ev.step}{ev.reason ? <small className="muted"> · {ev.reason}</small> : null}</>
                            : ev.kind === "validation" ? <>✓ <b>{ev.by}</b> a validé{ev.step ? ` (${ev.step})` : ""} · {ev.count} saisie(s), {fmt(Number(ev.hours))} {unit}</>
                            : ev.kind === "refus" ? <>✖ <b>{ev.by}</b> a refusé{ev.step ? ` (${ev.step})` : ""} · {ev.count} saisie(s){ev.reason ? <> — <i>{ev.reason}</i></> : null}</>
                            : <>📄 <b>{ev.step}</b> généré par {ev.by || "automatique"}{ev.reason ? <small className="muted"> · {ev.reason}</small> : null}</>}
                        </span>
                      </li>
                    ))}
                  </ol>
                )}
                <div className="sh-hist-act">
                  {x.cra.length ? x.cra.map((c) => (
                    <button key={c.id} type="button" className="btn sm" onClick={() => void download(c.id, c.name)}>📄 CRA {c.client}{c.version > 1 ? ` (v${c.version})` : ""}</button>
                  )) : <small className="muted">{x.state === "approved" ? "CRA en cours de génération (à la validation complète du mois)." : "CRA disponible une fois le mois entièrement validé."}</small>}
                  {x.mine && <button type="button" className="btn sm ghost" onClick={() => onOpen(x.period)}>Ouvrir la feuille</button>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  );
}
