// Portail client : saisies et reporting par utilisateur, facturation par utilisateur et par mois,
// commandes (licences, modules, assistants IA, ressources) et récap par e-mail.
import { useState } from "react";

import { api, API_BASE } from "../../api/client";
import { useApi } from "../../api/useApi";
import { ErrorNotice, Field, Loading, Pill, useAction } from "../../components/ui";

type Num = string | number;
const n = (v: Num | null | undefined) => Number(v ?? 0);
const eur = (v: Num | null | undefined) => n(v).toLocaleString("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const fmt = (v: Num) => { const x = n(v); return Number.isInteger(x) ? String(x) : x.toFixed(2).replace(/0$/, "").replace(".", ","); };
const ST: Record<string, [string, "ok" | "warn" | "crit" | "info" | ""]> = {
  approved: ["Validé", "ok"], client: ["À valider par vous", "warn"], pending: ["En validation interne", "info"], rejected: ["Refusé", "crit"],
};
const month0 = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };

async function download(url: string, name: string) {
  const res = await fetch(`${API_BASE}${url}`, { credentials: "include" });
  if (!res.ok) return;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(await res.blob());
  a.download = name;
  a.click();
}

// ---------------------------------------------------------------- saisies et reporting par utilisateur
type TS = {
  projects: { id: string; code: string; name: string; client: string; status: string; statusLabel: string }[];
  selectedProjects: number;
  people: { id: number; name: string; role: string; hours: Num; days: Num; amount: Num; status: Record<string, Num>; projects: string[] }[];
  byProject: { id: string; name: string; days: Num; amount: Num }[];
  totals: { days: Num; amount: Num };
  rows: { id: number; date: string; personName: string; projectName: string; task: string; days: Num; hours: Num; status: string; approvedBy: string | null; amount: Num }[];
};

const PSTATUS: [string, string][] = [["all", "Tous les projets"], ["active", "Projets actifs (en cours)"], ["inactive", "Projets non actifs (pause, clôturés)"]];

export function PortalTimesheets() {
  const [pstatus, setPstatus] = useState("all");
  const [project, setProject] = useState("");
  const [person, setPerson] = useState("");
  const [month, setMonth] = useState(month0());
  const q = new URLSearchParams({ projectStatus: pstatus, ...(project ? { project } : {}), ...(person ? { person } : {}), ...(month ? { month } : {}) }).toString();
  const r = useApi(() => api.get<TS>(`/client-portal/timesheets?${q}`), [q]);
  const [detail, setDetail] = useState(false);
  if (r.error) return <ErrorNotice error={r.error} onRetry={r.reload} />;
  if (!r.data) return <Loading />;
  const d = r.data;
  const max = Math.max(1, ...d.people.map((p) => n(p.days)));
  return (
    <section className="cs-card">
      <div className="cs-filters" style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "end" }}>
        <Field id="pt-status" label="Statut des projets"><select id="pt-status" className="inp" value={pstatus} onChange={(e) => { setPstatus(e.target.value); setProject(""); }}>
          {PSTATUS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
        <Field id="pt-project" label="Projet"><select id="pt-project" className="inp" value={project} onChange={(e) => setProject(e.target.value)}>
          <option value="">{PSTATUS.find(([k]) => k === pstatus)?.[1]} ({d.projects.filter((p) => pstatus === "all" || (pstatus === "active") === (p.status === "active")).length})</option>
          {d.projects.filter((p) => pstatus === "all" || (pstatus === "active") === (p.status === "active")).map((p) => <option key={p.id} value={p.id}>{p.name}{p.status !== "active" ? ` — ${p.statusLabel}` : ""}</option>)}</select></Field>
        <Field id="pt-person" label="Utilisateur"><select id="pt-person" className="inp" value={person} onChange={(e) => setPerson(e.target.value)}>
          <option value="">Tous</option>{d.people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
        <Field id="pt-month" label="Mois"><input id="pt-month" className="inp" type="month" value={month} onChange={(e) => setMonth(e.target.value)} /></Field>
        <button type="button" className="btn sm ghost" onClick={() => setMonth("")}>Toute la période</button>
      </div>
      <div className="kpis" style={{ margin: "12px 0" }}>
        <div className="kpi"><label>Jours saisis</label><strong>{fmt(d.totals.days)} j</strong></div>
        <div className="kpi"><label>Montant (TJM)</label><strong>{eur(d.totals.amount)}</strong></div>
        <div className="kpi"><label>Utilisateurs</label><strong>{d.people.length}</strong></div>
        <div className="kpi"><label>Projets pris en compte</label><strong>{d.selectedProjects}</strong></div>
      </div>
      <h4>Total par utilisateur</h4>
      <div className="tbl-wrap"><table className="tbl tight">
        <thead><tr><th>Utilisateur</th><th>Projets</th><th>Jours</th><th className="r">Montant HT</th><th>État des saisies</th></tr></thead>
        <tbody>{d.people.map((p) => (
          <tr key={p.id}><td><b>{p.name}</b><small className="muted" style={{ display: "block" }}>{p.role}</small></td><td>{p.projects.join(", ")}</td>
            <td style={{ minWidth: 160 }}><div style={{ display: "flex", alignItems: "center", gap: 8 }}><div style={{ flex: 1, height: 8, background: "var(--line)", borderRadius: 4 }}><div style={{ width: `${(n(p.days) / max) * 100}%`, height: "100%", background: "var(--accent)", borderRadius: 4 }} /></div><b>{fmt(p.days)} j</b></div></td>
            <td className="r">{eur(p.amount)}</td>
            <td>{Object.entries(p.status).map(([s, v]) => <Pill key={s} tone={ST[s]?.[1] ?? ""}>{ST[s]?.[0] ?? s} : {fmt(v)} j</Pill>)}</td></tr>
        ))}{d.people.length === 0 && <tr><td colSpan={5} className="muted">Aucune saisie sur la période.</td></tr>}</tbody>
      </table></div>
      {d.byProject.length > 1 && (<>
        <h4>Total par projet</h4>
        <div className="tbl-wrap"><table className="tbl tight"><tbody>{d.byProject.map((p) => <tr key={p.id}><td>{p.name}</td><td className="r">{fmt(p.days)} j</td><td className="r">{eur(p.amount)}</td></tr>)}</tbody></table></div>
      </>)}
      <button type="button" className="btn sm" style={{ marginTop: 10 }} onClick={() => setDetail(!detail)}>{detail ? "Masquer" : "Voir"} toutes les saisies ({d.rows.length})</button>
      {detail && (
        <div className="tbl-wrap" style={{ marginTop: 8 }}><table className="tbl tight">
          <thead><tr><th>Date</th><th>Utilisateur</th><th>Projet</th><th>Tâche</th><th className="r">Jours</th><th>État</th></tr></thead>
          <tbody>{d.rows.map((x) => <tr key={x.id}><td>{new Date(`${x.date}T00:00:00`).toLocaleDateString("fr-FR")}</td><td>{x.personName}</td><td>{x.projectName}</td><td>{x.task || "—"}</td><td className="r">{fmt(x.days)}</td>
            <td><Pill tone={ST[x.status]?.[1] ?? ""}>{ST[x.status]?.[0] ?? x.status}</Pill>{x.approvedBy ? <small className="muted"> · {x.approvedBy}</small> : null}</td></tr>)}</tbody>
        </table></div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- facturation par utilisateur et par mois
type Doc = { id: string; name: string; number: string; ht: Num | null; ttc: Num | null; version: number } | null;
type Bill = { rows: { person: number; personName: string; period: string; periodLabel: string; days: Num; amount: Num; state: string; invoice: Doc; cra: Doc }[]; months: string[]; totals: Record<string, Num> };

export function PortalBilling() {
  const [months, setMonths] = useState(6);
  const [pstatus, setPstatus] = useState("all");
  const r = useApi(() => api.get<Bill>(`/client-portal/billing?months=${months}&projectStatus=${pstatus}`), [months, pstatus]);
  if (r.error) return <ErrorNotice error={r.error} onRetry={r.reload} />;
  if (!r.data) return <Loading />;
  const d = r.data;
  return (
    <section className="cs-card">
      <p className="muted">Montant au TJM des jours saisis, par utilisateur et par mois. Dès que vous validez le mois d’un utilisateur (onglet « Temps à valider »), sa facture et son CRA sont générés automatiquement.</p>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
        <select className="inp" style={{ maxWidth: 260 }} aria-label="Statut des projets" value={pstatus} onChange={(e) => setPstatus(e.target.value)}>
          {PSTATUS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <select className="inp" style={{ maxWidth: 200 }} aria-label="Période" value={months} onChange={(e) => setMonths(Number(e.target.value))}>
          <option value={3}>3 derniers mois</option><option value={6}>6 derniers mois</option><option value={12}>12 derniers mois</option>
        </select>
      </div>
      {d.months.map((m) => (
        <div key={m} style={{ marginBottom: 14 }}>
          <h4 style={{ display: "flex", justifyContent: "space-between" }}><span>{d.rows.find((x) => x.period === m)?.periodLabel}</span><span>{eur(d.totals[m])} HT</span></h4>
          <div className="tbl-wrap"><table className="tbl tight">
            <thead><tr><th>Utilisateur</th><th className="r">Jours</th><th className="r">Montant HT</th><th>État</th><th>Facture</th><th>CRA</th></tr></thead>
            <tbody>{d.rows.filter((x) => x.period === m).map((x) => (
              <tr key={`${x.person}-${x.period}`}><td><b>{x.personName}</b></td><td className="r">{fmt(x.days)}</td><td className="r">{eur(x.amount)}</td>
                <td><Pill tone={ST[x.state]?.[1] ?? ""}>{ST[x.state]?.[0] ?? x.state}</Pill></td>
                <td>{x.invoice ? <button type="button" className="btn sm" onClick={() => void download(`/client-space/documents/${x.invoice!.id}`, `${x.invoice!.name}`)}>🧾 {x.invoice.number || "Facture"} · {eur(x.invoice.ttc)} TTC</button> : <span className="muted">{x.state === "approved" ? "En cours de génération" : "Après validation"}</span>}</td>
                <td>{x.cra ? <button type="button" className="btn sm ghost" onClick={() => void download(`/client-space/documents/${x.cra!.id}`, `${x.cra!.name}`)}>📄 CRA</button> : "—"}</td></tr>
            ))}</tbody>
          </table></div>
        </div>
      ))}
      {d.months.length === 0 && <p className="muted">Aucune saisie facturable sur la période.</p>}
    </section>
  );
}

// ---------------------------------------------------------------- commandes
type Order = { id: string; kind: string; kindLabel: string; item: string; quantity: string; unit: string; projectNames: string[]; note: string; by: string; at: string; status: string; history: { at: string; by: string; to: string; comment: string }[] };
type Orders = { orders: Order[]; kinds: { code: string; label: string }[]; modules: { code: string; label: string }[]; assistants: { code: string; label: string }[]; projects: { id: string; name: string }[]; canDecide: boolean; isClient: boolean };
const OST: Record<string, [string, "ok" | "warn" | "crit" | "info" | ""]> = { pending: ["En attente", "warn"], accepted: ["Acceptée", "info"], delivered: ["Livrée", "ok"], rejected: ["Refusée", "crit"] };

export function PortalOrders() {
  const r = useApi(() => api.get<Orders>("/client-portal/orders"));
  const { run, busy } = useAction();
  const [f, setF] = useState({ kind: "licence", item: "", quantity: "1", projects: [] as string[], note: "" });
  if (r.error) return <ErrorNotice error={r.error} onRetry={r.reload} />;
  if (!r.data) return <Loading />;
  const d = r.data;
  const send = () => void run(() => api.post<Orders>("/client-portal/orders", { ...f, quantity: Number(f.quantity) }), "Commande envoyée")
    .then((res) => { if (res) { r.setData(res); setF({ ...f, item: "", note: "", quantity: "1" }); } }, () => undefined);
  const decide = (o: Order, status: string) => {
    const comment = status === "rejected" ? window.prompt("Motif du refus ?") ?? "" : "";
    if (status === "rejected" && !comment) return;
    void run(() => api.post<Orders>(`/client-portal/orders/${o.id}/decision`, { status, comment }), "Commande mise à jour").then((res) => res && r.setData(res), () => undefined);
  };
  const itemField = f.kind === "module" ? (
    <select className="inp" value={f.item} onChange={(e) => setF({ ...f, item: e.target.value })}><option value="">Choisir un module…</option>{d.modules.map((m) => <option key={m.code} value={m.label}>{m.label}</option>)}</select>
  ) : f.kind === "assistant" ? (
    <select className="inp" value={f.item} onChange={(e) => setF({ ...f, item: e.target.value })}><option value="">Choisir un assistant IA…</option>{d.assistants.map((a) => <option key={a.code} value={a.label}>{a.label}</option>)}</select>
  ) : f.kind === "resource" ? (
    <input className="inp" placeholder="Profil souhaité (ex. Développeur senior, Testeur, Architecte…)" value={f.item} onChange={(e) => setF({ ...f, item: e.target.value })} />
  ) : (
    <input className="inp" placeholder="Type de licence (facultatif : nominative, concurrente…)" value={f.item} onChange={(e) => setF({ ...f, item: e.target.value })} />
  );
  return (
    <section className="cs-card">
      <h4>Nouvelle commande</h4>
      <div className="grid g2">
        <Field id="po-kind" label="Je commande"><select id="po-kind" className="inp" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value, item: "" })}>{d.kinds.map((k) => <option key={k.code} value={k.code}>{k.label}</option>)}</select></Field>
        <Field id="po-item" label={f.kind === "module" ? "Module" : f.kind === "assistant" ? "Assistant IA" : f.kind === "resource" ? "Profil" : "Licence"}>{itemField}</Field>
        <Field id="po-qty" label={f.kind === "licence" ? "Nombre de licences" : f.kind === "assistant" ? "Durée (mois)" : f.kind === "resource" ? "Nombre de jours" : "Quantité"}>
          <input id="po-qty" className="inp" type="number" min={0.5} step={f.kind === "resource" ? 0.5 : 1} value={f.quantity} onChange={(e) => setF({ ...f, quantity: e.target.value })} /></Field>
        <Field id="po-note" label="Précisions"><input id="po-note" className="inp" placeholder="Date souhaitée, contexte…" value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></Field>
      </div>
      <div style={{ margin: "8px 0" }}><b>Pour le(s) projet(s) :</b>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 6 }}>{d.projects.map((p) => (
          <label key={p.id} style={{ display: "flex", gap: 6, alignItems: "center" }}><input type="checkbox" checked={f.projects.includes(p.id)}
            onChange={(e) => setF({ ...f, projects: e.target.checked ? [...f.projects, p.id] : f.projects.filter((x) => x !== p.id) })} /> {p.name}</label>
        ))}</div>
      </div>
      <button type="button" className="btn primary" disabled={busy || !f.projects.length || (f.kind !== "licence" && !f.item)} onClick={send}>Envoyer la commande</button>
      <h4 style={{ marginTop: 18 }}>Commandes</h4>
      <div className="tbl-wrap"><table className="tbl tight">
        <thead><tr><th>Date</th><th>Commande</th><th>Projets</th><th>Par</th><th>État</th>{d.canDecide && <th>Traitement</th>}</tr></thead>
        <tbody>{d.orders.map((o) => (
          <tr key={o.id}><td>{new Date(o.at).toLocaleDateString("fr-FR")}</td><td><b>{o.kindLabel}</b>{o.item ? ` — ${o.item}` : ""} × {fmt(o.quantity)} {o.unit}{o.note && <small className="muted" style={{ display: "block" }}>{o.note}</small>}</td>
            <td>{o.projectNames.join(", ")}</td><td>{o.by}</td>
            <td><Pill tone={OST[o.status]?.[1] ?? ""}>{OST[o.status]?.[0] ?? o.status}</Pill>{o.history.length > 0 && <small className="muted" style={{ display: "block" }}>{o.history[o.history.length - 1].by}{o.history[o.history.length - 1].comment ? ` : ${o.history[o.history.length - 1].comment}` : ""}</small>}</td>
            {d.canDecide && <td><div className="btns">
              {o.status === "pending" && <><button type="button" className="btn sm primary" disabled={busy} onClick={() => decide(o, "accepted")}>Accepter</button><button type="button" className="btn sm" disabled={busy} onClick={() => decide(o, "rejected")}>Refuser</button></>}
              {o.status === "accepted" && <button type="button" className="btn sm primary" disabled={busy} onClick={() => decide(o, "delivered")}>Marquer livrée</button>}
            </div></td>}</tr>
        ))}{d.orders.length === 0 && <tr><td colSpan={6} className="muted">Aucune commande.</td></tr>}</tbody>
      </table></div>
    </section>
  );
}

// ---------------------------------------------------------------- récap par e-mail
export function PortalRecap() {
  const projects = useApi(() => api.get<{ projects: { id: string; name: string }[] }>("/client-portal/orders"));
  const [sel, setSel] = useState<string[]>([]);
  const [month, setMonth] = useState(month0());
  const [to, setTo] = useState("");
  const [text, setText] = useState("");
  const [subject, setSubject] = useState("Récapitulatif projets — Control Tower");
  const [msg, setMsg] = useState("");
  const { run, busy } = useAction();
  if (!projects.data) return <Loading />;
  const preview = () => void run(() => api.get<{ text: string; to: string[] }>(`/client-portal/recap?projects=${sel.join(",")}&month=${month}`)).then((res) => {
    if (res) { setText(res.text); if (!to && res.to.length) setTo(res.to.join(", ")); }
  }, () => undefined);
  const send = () => void run(() => api.post<{ sent: boolean; reason?: string; to?: string[] }>("/client-portal/recap", { projects: sel, month, text, subject, to: to.split(/[,;\s]+/).filter(Boolean) }))
    .then((res) => res && setMsg(res.sent ? `✓ Récap envoyé à ${res.to?.join(", ")}.` : res.reason ?? "Non envoyé."), () => undefined);
  const mailto = `mailto:${encodeURIComponent(to.replace(/\s/g, ""))}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(text)}`;
  return (
    <section className="cs-card">
      <p className="muted">Composez un récapitulatif (budget, temps par utilisateur, tâches ouvertes et en retard) et envoyez-le par e-mail.</p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, margin: "6px 0 10px" }}>{projects.data.projects.map((p) => (
        <label key={p.id} style={{ display: "flex", gap: 6, alignItems: "center" }}><input type="checkbox" checked={sel.includes(p.id)} onChange={(e) => setSel(e.target.checked ? [...sel, p.id] : sel.filter((x) => x !== p.id))} /> {p.name}</label>
      ))}</div>
      <div className="grid g2">
        <Field id="rc-month" label="Mois des temps"><input id="rc-month" className="inp" type="month" value={month} onChange={(e) => setMonth(e.target.value)} /></Field>
        <Field id="rc-to" label="Destinataires (séparés par des virgules)"><input id="rc-to" className="inp" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
      </div>
      <Field id="rc-subject" label="Objet"><input id="rc-subject" className="inp" value={subject} onChange={(e) => setSubject(e.target.value)} /></Field>
      <button type="button" className="btn" disabled={busy} onClick={preview} style={{ margin: "8px 0" }}>Générer l’aperçu</button>
      {text && <>
        <Field id="rc-text" label="Contenu"><textarea id="rc-text" className="inp mono" rows={14} value={text} onChange={(e) => setText(e.target.value)} /></Field>
        <div className="btns" style={{ marginTop: 8 }}>
          <button type="button" className="btn primary" disabled={busy || !to.trim()} onClick={send}>✉ Envoyer le récap</button>
          <a className="btn" href={mailto}>Ouvrir dans ma messagerie</a>
        </div>
      </>}
      {msg && <div className="notice" style={{ marginTop: 8 }}>{msg}</div>}
    </section>
  );
}
