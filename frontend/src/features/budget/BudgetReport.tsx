// Rapport budgétaire automatique : consommation = heures saisies × TJM. Filtres période / personne / regroupement,
// graphiques (consommé et engagé par mois ou semaine, cumul face au budget), détail par personne et par tâche,
// saisies manquantes et relance. Le client voit la synthèse si le chef de projet l'a rendue visible.
import { useMemo, useState } from "react";

import { api, ApiError } from "../../api/client";
import { useApi } from "../../api/useApi";
import { ErrorNotice, Loading, useAction } from "../../components/ui";
import "./budget.css";

type Num = string | number | null;
type Point = { key: string; label: string; consumed: Num; engaged: Num; hours: Num; cumulative: Num };
type Report = {
  audience: "full" | "client";
  project: { id: string; code: string; name: string; start: string | null; end: string | null };
  group: "month" | "week";
  currency: string;
  hoursPerDay: Num;
  totals: { initial: Num; approved: Num; consumed: Num; engaged: Num; spent: Num; remaining: Num; rate: number | null; hours: Num; days: Num };
  period: { from: string | null; to: string | null; consumed: Num; engaged: Num; hours: Num; days: Num };
  forecast: { endDate: string; projected: Num; dailyBurn: Num; overrun: Num } | null;
  series: Point[];
  byPerson: { id: number; name: string; role: string; dailyRate: Num; hours: Num; days: Num; consumed: Num; engaged: Num; orderedDays?: Num; orderedAmount?: Num; remainingAmount?: Num }[];
  byTask: { id: string | null; title: string; hours?: Num; cost: Num }[];
  missingRates: string[];
  people?: { id: number; name: string }[];
  settings?: { clientVisible: boolean; canEdit: boolean; isAdmin: boolean; reminders: { enabled: boolean; lookbackDays: number; email: boolean } };
  missingTimesheets?: { user: string; userId: number; days: string[] }[];
  supplements: { amount: string; reason: string; by: string; role: string; at: string; before: string; after: string }[];
  canAddBudget: boolean;
  thresholds: number[];
  requests: BudgetRequest[];
  canRequest: boolean;
  canDecide: boolean;
  notice?: string;
  budgetMode?: "global" | "resource";
  orders?: DayOrder[];
  canOrder?: boolean;
  canChooseMode?: boolean;
  policy?: { mode: "continue" | "block"; graceDays: number; scope: "project" | "resource" | "both" };
  canSetPolicy?: boolean;
  team?: { id: number; name: string }[];
};
type DayOrder = {
  id: string; person: number; personName: string; days: string; rate: string; amount: string; note: string; by: string; byRole: string;
  at: string; status: "pending" | "approved" | "rejected"; decidedBy?: string; comment?: string;
};
type BudgetRequest = {
  id: string; amount: string | null; reason: string; by: string; at: string; status: "pending" | "approved" | "rejected";
  rate: number | null; spent: string; approved: string | null; decidedBy?: string; decidedAt?: string; granted?: string | null; comment?: string;
};

const n = (v: Num) => (v === null || v === undefined || v === "" ? 0 : Number(v));
const eur = (v: Num) => (v === null || v === undefined ? "—" : n(v).toLocaleString("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }));
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const day = (s: string) => new Date(`${s}T00:00:00`).toLocaleDateString("fr-FR", { weekday: "short", day: "2-digit", month: "2-digit" });

const PRESETS: { id: string; label: string; range: () => [string, string] }[] = [
  { id: "all", label: "Depuis le début", range: () => ["", ""] },
  { id: "month", label: "Mois en cours", range: () => { const t = new Date(); return [iso(new Date(t.getFullYear(), t.getMonth(), 1)), iso(t)]; } },
  { id: "prev", label: "Mois précédent", range: () => { const t = new Date(); return [iso(new Date(t.getFullYear(), t.getMonth() - 1, 1)), iso(new Date(t.getFullYear(), t.getMonth(), 0))]; } },
  { id: "3m", label: "3 derniers mois", range: () => { const t = new Date(); return [iso(new Date(t.getFullYear(), t.getMonth() - 2, 1)), iso(t)]; } },
  { id: "year", label: "Année en cours", range: () => { const t = new Date(); return [iso(new Date(t.getFullYear(), 0, 1)), iso(t)]; } },
  { id: "custom", label: "Personnalisée", range: () => ["", ""] },
];

export function BudgetReport({ projectId }: { projectId: string }) {
  const [preset, setPreset] = useState("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [person, setPerson] = useState("");
  const [group, setGroup] = useState<"month" | "week">("month");
  const [view, setView] = useState<"chart" | "table">("chart");
  const query = new URLSearchParams({ ...(from ? { from } : {}), ...(to ? { to } : {}), ...(person ? { person } : {}), group }).toString();
  const url = `/projects/${encodeURIComponent(projectId)}/budget-report`;
  const r = useApi(() => api.get<Report>(`${url}?${query}`), [url, query]);
  const { run, busy } = useAction();
  const [sent, setSent] = useState<string | null>(null);
  const [extra, setExtra] = useState<{ amount: string; reason: string } | null>(null);

  if (r.error instanceof ApiError && r.error.status === 403) return null;
  if (r.error) return <ErrorNotice error={r.error} onRetry={r.reload} />;
  if (!r.data) return <Loading label="Calcul du budget…" />;
  const d = r.data;
  const full = d.audience === "full";
  const t = d.totals;
  const over = t.rate !== null && t.rate > 100;
  const pick = (id: string) => {
    setPreset(id);
    if (id !== "custom") { const [a, b] = PRESETS.find((p) => p.id === id)!.range(); setFrom(a); setTo(b); }
  };
  const save = (body: Record<string, unknown>) => void run(() => api.put<Report>(url, body), "Paramètre enregistré").then(() => r.reload(), () => undefined);
  const addBudget = () => {
    if (!extra || !(Number(extra.amount) > 0)) return;
    void run(() => api.post<Report>(`${url}/supplement`, { amount: Number(extra.amount), reason: extra.reason }), "Budget supplémentaire ajouté")
      .then(() => { setExtra(null); r.reload(); }, () => undefined);
  };
  const remind = () => void run(() => api.post<{ missing: unknown[]; sent: { user: string; via: string }[] }>(`${url}/remind`), "Relances envoyées")
    .then((res) => res && setSent(res.sent.length ? res.sent.map((s) => `${s.user} (${s.via})`).join(", ") : "Personne à relancer : toutes les saisies sont faites."), () => undefined);
  const csv = () => {
    const rows = [["Période", "Consommé validé (€)", "Engagé à valider (€)", "Heures", "Cumul (€)"],
      ...d.series.map((s) => [s.label, n(s.consumed), n(s.engaged), n(s.hours), n(s.cumulative)])];
    if (full) rows.push([], ["Personne", "Profil", "TJM (€)", "Heures", "Jours", "Consommé (€)", "Engagé (€)"],
      ...d.byPerson.map((p) => [p.name, p.role, n(p.dailyRate), n(p.hours), n(p.days), n(p.consumed), n(p.engaged)]));
    const blob = new Blob(["﻿" + rows.map((x) => x.join(";")).join("\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `budget_${d.project.code}_${from || "debut"}_${to || "aujourdhui"}.csv`;
    a.click();
  };

  return (
    <section className="bud card" aria-label="Budget du projet">
      <header className="bud-h">
        <div>
          <h3>💶 Budget — consommation automatique</h3>
          <small>Calculée à chaque saisie de temps : heures × TJM du membre ({n(d.hoursPerDay)} h = 1 jour). Validé = consommé, à valider = engagé.</small>
        </div>
        <button type="button" className="btn sm" onClick={csv}>⬇ Export CSV</button>
      </header>

      <div className="bud-kpis">
        <Kpi label="Budget initial" value={eur(t.initial)} sub={t.approved !== null && n(t.approved) !== n(t.initial) ? `Budget validé : ${eur(t.approved)}` : "Budget validé du projet"} />
        <Kpi label="Consommé (validé)" value={eur(t.consumed)} sub={`${n(t.days)} j saisis au total`} tone="acc" />
        <Kpi label="Engagé (à valider)" value={eur(t.engaged)} sub="Temps saisis non encore validés" />
        <Kpi label="Reste" value={eur(t.remaining)} sub={t.rate !== null ? `${t.rate} % du budget utilisé` : "Budget non renseigné"} tone={over ? "crit" : t.rate !== null && t.rate > 80 ? "warn" : "ok"} />
        {d.forecast && <Kpi label="Projection à la fin" value={eur(d.forecast.projected)} sub={d.forecast.overrun ? `Dépassement prévu : ${eur(d.forecast.overrun)}` : `Rythme : ${eur(d.forecast.dailyBurn)} / jour`} tone={d.forecast.overrun ? "crit" : ""} />}
      </div>
      {t.approved !== null && (
        <div className="bud-gauge" title={`${t.rate ?? 0} %`}>
          <i className="c" style={{ width: `${Math.min(100, (n(t.consumed) / Math.max(1, n(t.approved))) * 100)}%` }} />
          <i className="e" style={{ width: `${Math.min(100, (n(t.engaged) / Math.max(1, n(t.approved))) * 100)}%` }} />
        </div>
      )}

      <BudgetRequests d={d} url={url} onDone={r.reload} />
      <DayOrders d={d} url={url} onDone={r.reload} />

      <div className="bud-extra">
        <div>
          <b>Budget supplémentaire</b>
          <small>Alerte automatique (notification + e-mail) au client et au chef de projet à {d.thresholds.join(" % puis ")} % du budget consommé.</small>
          {d.supplements.length > 0 && (
            <ul>
              {d.supplements.slice().reverse().map((x) => (
                <li key={x.at}><b>+{eur(x.amount)}</b> le {new Date(x.at).toLocaleDateString("fr-FR")} par {x.by}{x.role ? ` (${x.role})` : ""}{x.reason ? ` — ${x.reason}` : ""} <small>· {eur(x.before)} → {eur(x.after)}</small></li>
              ))}
            </ul>
          )}
        </div>
        {d.canAddBudget && (extra === null ? (
          <button type="button" className="btn sm primary" onClick={() => setExtra({ amount: "", reason: "" })}>➕ Ajouter un budget</button>
        ) : (
          <form className="bud-extra-form" onSubmit={(e) => { e.preventDefault(); addBudget(); }}>
            <input className="inp" type="number" min={1} step={100} placeholder="Montant (€)" aria-label="Montant du budget supplémentaire" autoFocus
              value={extra.amount} onChange={(e) => setExtra({ ...extra, amount: e.target.value })} />
            <input className="inp" placeholder="Motif (ex. avenant n°2, nouvelle fonctionnalité)" aria-label="Motif"
              value={extra.reason} onChange={(e) => setExtra({ ...extra, reason: e.target.value })} />
            <button className="btn sm primary" type="submit" disabled={busy || !(Number(extra.amount) > 0)}>Ajouter</button>
            <button className="btn sm" type="button" onClick={() => setExtra(null)}>Annuler</button>
          </form>
        ))}
      </div>

      <div className="bud-filters">
        <div className="bud-seg" role="group" aria-label="Période">
          {PRESETS.map((p) => <button key={p.id} type="button" className={preset === p.id ? "on" : ""} onClick={() => pick(p.id)}>{p.label}</button>)}
        </div>
        {preset === "custom" && (
          <span className="bud-dates">
            <label>Du <input className="inp" type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
            <label>au <input className="inp" type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
          </span>
        )}
        {full && d.people && (
          <select className="inp" aria-label="Personne" value={person} onChange={(e) => setPerson(e.target.value)}>
            <option value="">Toute l'équipe</option>
            {d.people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        )}
        <select className="inp" aria-label="Regroupement" value={group} onChange={(e) => setGroup(e.target.value as "month" | "week")}>
          <option value="month">Par mois</option>
          <option value="week">Par semaine</option>
        </select>
        <div className="bud-seg" role="group" aria-label="Affichage">
          <button type="button" className={view === "chart" ? "on" : ""} onClick={() => setView("chart")}>📊 Graphiques</button>
          <button type="button" className={view === "table" ? "on" : ""} onClick={() => setView("table")}>☰ Tableaux</button>
        </div>
      </div>
      <p className="bud-period">Sur la période : <b>{eur(n(d.period.consumed) + n(d.period.engaged))}</b> ({eur(d.period.consumed)} validés, {eur(d.period.engaged)} à valider) · {n(d.period.days)} j · {n(d.period.hours)} h</p>

      {d.series.length === 0 ? <p className="muted">Aucune saisie de temps sur cette période.</p> : view === "chart" ? (
        <div className="bud-charts">
          <div><h4>Dépenses par {group === "week" ? "semaine" : "mois"} et cumul face au budget</h4><SeriesChart points={d.series} budget={t.approved} /></div>
          {d.byPerson.length > 0 && <div><h4>Dépenses par personne</h4><Bars rows={d.byPerson.map((p) => ({ label: p.name, a: n(p.consumed), b: n(p.engaged), note: `${n(p.days)} j` }))} /></div>}
          {d.byTask.length > 0 && <div><h4>Dépenses par tâche</h4><Bars rows={d.byTask.slice(0, 8).map((x) => ({ label: x.title, a: n(x.cost), b: 0, note: x.hours !== undefined ? `${n(x.hours)} h` : "" }))} /></div>}
        </div>
      ) : (
        <div className="bud-tables">
          <table className="tbl">
            <thead><tr><th>{group === "week" ? "Semaine" : "Mois"}</th><th className="num">Consommé</th><th className="num">Engagé</th><th className="num">Heures</th><th className="num">Cumul</th></tr></thead>
            <tbody>{d.series.map((s) => <tr key={s.key}><td>{s.label}</td><td className="num">{eur(s.consumed)}</td><td className="num">{eur(s.engaged)}</td><td className="num">{n(s.hours)}</td><td className="num">{eur(s.cumulative)}</td></tr>)}</tbody>
          </table>
          {d.byPerson.length > 0 && (
            <table className="tbl">
              <thead><tr><th>Personne</th><th>Profil</th><th className="num">TJM</th><th className="num">Jours</th><th className="num">Consommé</th><th className="num">Engagé</th>{d.budgetMode === "resource" && <><th className="num">Jours commandés</th><th className="num">Reste</th></>}</tr></thead>
              <tbody>{d.byPerson.map((p) => <tr key={p.id}><td>{p.name}</td><td>{p.role}</td><td className="num">{p.dailyRate === null && !full ? "—" : p.dailyRate === null ? <span className="bud-warn">à renseigner</span> : eur(p.dailyRate)}</td><td className="num">{n(p.days)}</td><td className="num">{eur(p.consumed)}</td><td className="num">{eur(p.engaged)}</td>
                {d.budgetMode === "resource" && <><td className="num">{p.orderedDays == null ? "—" : `${n(p.orderedDays)} j`}</td><td className={`num ${p.remainingAmount != null && n(p.remainingAmount) < 0 ? "bud-warn" : ""}`}>{p.remainingAmount == null ? "—" : eur(p.remainingAmount)}</td></>}</tr>)}</tbody>
            </table>
          )}
          <table className="tbl">
            <thead><tr><th>Tâche</th>{full && <th className="num">Heures</th>}<th className="num">Coût</th></tr></thead>
            <tbody>{d.byTask.map((x) => <tr key={x.id ?? "-"}><td>{x.title}</td>{full && <td className="num">{n(x.hours ?? 0)}</td>}<td className="num">{eur(x.cost)}</td></tr>)}</tbody>
          </table>
        </div>
      )}

      {full && d.missingRates.length > 0 && <p className="bud-alert">⚠ TJM manquant pour {d.missingRates.join(", ")} : leurs heures ne sont pas valorisées (Projet → Équipe → TJM).</p>}

      {full && d.missingTimesheets && (
        <div className={`bud-missing ${d.missingTimesheets.length ? "warn" : "ok"}`}>
          <div>
            <b>{d.missingTimesheets.length ? `⏰ ${d.missingTimesheets.length} membre(s) sans saisie de temps` : "✅ Toutes les saisies des derniers jours ouvrés sont faites"}</b>
            {d.missingTimesheets.map((m) => <small key={m.userId}>{m.user} : {m.days.map(day).join(", ")}</small>)}
            <small className="muted">Relance automatique chaque jour ouvré {d.settings?.reminders.enabled ? `(notification${d.settings.reminders.email ? " + e-mail" : ""}, ${d.settings.reminders.lookbackDays} derniers jours ouvrés)` : "désactivée"}.</small>
            {sent && <small className="bud-sent">Relancé : {sent}</small>}
          </div>
          {d.settings?.canEdit && <button type="button" className="btn sm primary" disabled={busy} onClick={remind}>📨 Relancer maintenant</button>}
        </div>
      )}

      {full && d.settings?.canEdit && (
        <div className="bud-settings">
          {d.canSetPolicy && d.policy && (
            <div className="bud-policy">
              <b>Budget consommé :</b>
              <select className="inp" aria-label="Comportement en cas de dépassement" value={d.policy.mode} disabled={busy}
                onChange={(e) => void run(() => api.put<Report>(`${url}/policy`, { mode: e.target.value }), "Politique enregistrée").then(() => r.reload(), () => undefined)}>
                <option value="continue">la saisie continue</option>
                <option value="block">la saisie est bloquée</option>
              </select>
              {d.policy.mode === "block" && (<>
                <span>après</span>
                <input className="inp bud-num" type="number" min={0} max={365} aria-label="Délai de grâce en jours" defaultValue={d.policy.graceDays}
                  onBlur={(e) => void run(() => api.put<Report>(`${url}/policy`, { graceDays: Number(e.target.value) }), "Délai enregistré").then(() => r.reload(), () => undefined)} />
                <span>jour(s) de grâce, pour</span>
                <select className="inp" aria-label="Portée" value={d.policy.scope} disabled={busy}
                  onChange={(e) => void run(() => api.put<Report>(`${url}/policy`, { scope: e.target.value }), "Politique enregistrée").then(() => r.reload(), () => undefined)}>
                  <option value="both">le projet et chaque ressource</option>
                  <option value="project">le projet entier</option>
                  <option value="resource">chaque ressource (jours commandés)</option>
                </select>
              </>)}
            </div>
          )}
          <label><input type="checkbox" checked={d.settings.clientVisible} disabled={busy} onChange={(e) => save({ clientVisible: e.target.checked })} /> Budget visible du client dans son reporting (synthèse et évolution, sans TJM ni coût par personne)</label>
          {d.settings.isAdmin && (
            <>
              <label><input type="checkbox" checked={d.settings.reminders.enabled} disabled={busy} onChange={(e) => save({ reminders: { enabled: e.target.checked } })} /> Relances automatiques de saisie</label>
              <label><input type="checkbox" checked={d.settings.reminders.email} disabled={busy} onChange={(e) => save({ reminders: { email: e.target.checked } })} /> Aussi par e-mail</label>
              <label>Contrôler les <input className="inp bud-num" type="number" min={1} max={20} value={d.settings.reminders.lookbackDays} onChange={(e) => save({ reminders: { lookbackDays: Number(e.target.value) } })} /> derniers jours ouvrés</label>
            </>
          )}
        </div>
      )}
    </section>
  );
}

function Kpi({ label, value, sub, tone = "" }: { label: string; value: string; sub: string; tone?: string }) {
  return <div className={`bud-kpi ${tone}`}><label>{label}</label><strong>{value}</strong><small>{sub}</small></div>;
}

/** Barres empilées consommé / engagé par période + courbe du cumul et ligne du budget validé. */
function SeriesChart({ points, budget }: { points: Point[]; budget: Num }) {
  const W = 720, H = 270, L = 64, R = 72, T = 22, B = 44;
  const maxBar = Math.max(1, ...points.map((p) => n(p.consumed) + n(p.engaged)));
  const maxCum = Math.max(1, n(budget), ...points.map((p) => n(p.cumulative)));
  const bw = (W - L - R) / points.length;
  const yBar = (v: number) => T + (H - T - B) * (1 - v / maxBar);
  const yCum = (v: number) => T + (H - T - B) * (1 - v / maxCum);
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  const line = points.map((p, i) => `${i ? "L" : "M"}${L + bw * i + bw / 2} ${yCum(n(p.cumulative))}`).join(" ");
  const every = Math.ceil(points.length / 12);
  return (
    <svg className="bud-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Dépenses par période et cumul">
      {ticks.map((k) => <g key={k}><line x1={L} x2={W - R} y1={yBar(maxBar * k)} y2={yBar(maxBar * k)} className="grid" />
        <text x={L - 6} y={yBar(maxBar * k) + 4} textAnchor="end" className="ax">{eur(maxBar * k)}</text>
        <text x={W - R + 6} y={yCum(maxCum * k) + 4} className="ax ax-cum">{eur(maxCum * k)}</text></g>)}
      <text x={L - 6} y={12} textAnchor="end" className="ax">Par période</text>
      <text x={W - R + 6} y={12} className="ax ax-cum">Cumul</text>
      {points.map((p, i) => {
        const x = L + bw * i + bw * 0.18, w = bw * 0.64;
        const c = n(p.consumed), e = n(p.engaged);
        return (
          <g key={p.key}>
            <rect x={x} y={yBar(c)} width={w} height={Math.max(0, yBar(0) - yBar(c))} className="c" rx="3"><title>{`${p.label} : ${eur(c)} validés`}</title></rect>
            <rect x={x} y={yBar(c + e)} width={w} height={Math.max(0, yBar(c) - yBar(c + e))} className="e" rx="3"><title>{`${p.label} : ${eur(e)} à valider`}</title></rect>
            {i % every === 0 && <text x={x + w / 2} y={H - B + 16} textAnchor="middle" className="ax">{p.label}</text>}
          </g>
        );
      })}
      {n(budget) > 0 && <g><line x1={L} x2={W - R} y1={yCum(n(budget))} y2={yCum(n(budget))} className="bdg" />
        <text x={W - R - 4} y={yCum(n(budget)) + 14} textAnchor="end" className="bdg-t">Budget validé {eur(budget)}</text></g>}
      <path d={line} className="cum" />
      {points.map((p, i) => <circle key={p.key} cx={L + bw * i + bw / 2} cy={yCum(n(p.cumulative))} r="3.5" className="cum-d"><title>{`Cumul fin ${p.label} : ${eur(p.cumulative)}`}</title></circle>)}
      <g className="leg" transform={`translate(${L}, ${H - 12})`}>
        <rect width="10" height="10" className="c" /><text x="14" y="9">Consommé (validé)</text>
        <rect x="140" width="10" height="10" className="e" /><text x="154" y="9">Engagé (à valider)</text>
        <line x1="290" x2="306" y1="5" y2="5" className="cum" /><text x="310" y="9">Cumul (axe de droite)</text>
        <line x1="430" x2="446" y1="5" y2="5" className="bdg" /><text x="450" y="9">Budget validé</text>
      </g>
    </svg>
  );
}

function Bars({ rows }: { rows: { label: string; a: number; b: number; note: string }[] }) {
  const max = useMemo(() => Math.max(1, ...rows.map((r) => r.a + r.b)), [rows]);
  return (
    <div className="bud-bars">
      {rows.map((r) => (
        <div key={r.label} className="bud-bar">
          <span title={r.label}>{r.label}</span>
          <div><i className="c" style={{ width: `${(r.a / max) * 100}%` }} /><i className="e" style={{ width: `${(r.b / max) * 100}%` }} /></div>
          <b>{eur(r.a + r.b)}</b><small>{r.note}</small>
        </div>
      ))}
    </div>
  );
}

/** Demande de budget : le chef de projet la soumet au client ; le client accepte (montant accordé) ou refuse (motif). */
function BudgetRequests({ d, url, onDone }: { d: Report; url: string; onDone: () => void }) {
  const { run, busy } = useAction();
  const [form, setForm] = useState<{ amount: string; reason: string } | null>(null);
  const [answer, setAnswer] = useState<{ amount: string; comment: string } | null>(null);
  const [notice, setNotice] = useState("");
  const pending = d.requests.find((x) => x.status === "pending");
  const rate = d.totals.rate ?? 0;
  const suggest = d.canRequest && !pending && d.totals.approved !== null && rate >= (d.thresholds[0] ?? 80);
  if (!d.canRequest && !d.canDecide && d.requests.length === 0) return null;
  if (!pending && !suggest && !d.canRequest && d.requests.length === 0) return null;
  const send = () => form && void run(() => api.post<Report>(`${url}/requests`, { amount: form.amount ? Number(form.amount) : null, reason: form.reason }), "Demande envoyée au client")
    .then((res) => { setForm(null); setNotice(res?.notice ?? ""); onDone(); }, () => undefined);
  const decide = (decision: "approved" | "rejected") => pending && answer && void run(() => api.post<Report>(`${url}/requests/${pending.id}/decision`,
    { decision, amount: decision === "approved" ? Number(answer.amount) : null, comment: answer.comment }), decision === "approved" ? "Budget accordé" : "Demande refusée")
    .then(() => { setAnswer(null); onDone(); }, () => undefined);
  return (
    <div className={`bud-req ${pending ? "pending" : suggest ? "suggest" : ""}`}>
      <div className="bud-req-main">
        <b>📨 Demandes de budget supplémentaire</b>
        {pending ? (
          <>
            <p>Demande de <b>{pending.by}</b> le {new Date(pending.at).toLocaleDateString("fr-FR")}{pending.amount ? <> : <b>{eur(pending.amount)}</b></> : ""}. Motif : {pending.reason}
              <small> · budget consommé alors à {pending.rate ?? "—"} %</small></p>
            {d.canDecide ? (answer === null ? (
              <div className="bud-req-btns">
                <button type="button" className="btn sm primary" onClick={() => setAnswer({ amount: pending.amount ?? "", comment: "" })}>Répondre</button>
              </div>
            ) : (
              <form className="bud-extra-form" onSubmit={(e) => { e.preventDefault(); decide("approved"); }}>
                <input className="inp" type="number" min={1} step={100} placeholder="Budget accordé (€)" aria-label="Budget accordé" autoFocus
                  value={answer.amount} onChange={(e) => setAnswer({ ...answer, amount: e.target.value })} />
                <input className="inp" placeholder="Commentaire (obligatoire en cas de refus)" aria-label="Commentaire"
                  value={answer.comment} onChange={(e) => setAnswer({ ...answer, comment: e.target.value })} />
                <button className="btn sm primary" type="submit" disabled={busy || !(Number(answer.amount) > 0)}>✔ Accepter et ajouter</button>
                <button className="btn sm" type="button" disabled={busy || !answer.comment.trim()} onClick={() => decide("rejected")}>✖ Refuser</button>
                <button className="btn sm" type="button" onClick={() => setAnswer(null)}>Annuler</button>
              </form>
            )) : <small>En attente de la réponse du client.</small>}
          </>
        ) : suggest ? (
          <p>Le budget est consommé à <b>{rate} %</b>. Demandez au client un budget supplémentaire : il sera prévenu par notification et e-mail, et l'acceptera en saisissant le montant.</p>
        ) : <small>Aucune demande en cours.</small>}
        {notice && <small className="bud-sent">{notice}</small>}
        {d.requests.filter((x) => x.status !== "pending").slice(0, 3).map((x) => (
          <small key={x.id}>{x.status === "approved" ? "✔" : "✖"} {new Date(x.at).toLocaleDateString("fr-FR")} · {x.by} → {x.decidedBy} : {x.status === "approved" ? `accordé ${eur(x.granted ?? null)}` : `refusé (${x.comment})`}</small>
        ))}
      </div>
      {d.canRequest && !pending && (form === null ? (
        <button type="button" className={`btn sm ${suggest ? "primary" : ""}`} onClick={() => setForm({ amount: "", reason: "" })}>Demander un budget au client</button>
      ) : (
        <form className="bud-extra-form" onSubmit={(e) => { e.preventDefault(); send(); }}>
          <input className="inp" type="number" min={0} step={100} placeholder="Montant souhaité (€, facultatif)" aria-label="Montant souhaité"
            value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
          <input className="inp" placeholder="Motif (obligatoire)" aria-label="Motif de la demande" autoFocus
            value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
          <button className="btn sm primary" type="submit" disabled={busy || !form.reason.trim()}>Envoyer au client</button>
          <button className="btn sm" type="button" onClick={() => setForm(null)}>Annuler</button>
        </form>
      ))}
    </div>
  );
}

/** Commandes de jours par consultant et choix du mode de budget (global ou par ressource). */
function DayOrders({ d, url, onDone }: { d: Report; url: string; onDone: () => void }) {
  const { run, busy } = useAction();
  const [form, setForm] = useState<{ person: string; days: string; note: string } | null>(null);
  const [reject, setReject] = useState<{ id: string; comment: string } | null>(null);
  const orders = d.orders ?? [];
  if (!d.canOrder && !d.canChooseMode && orders.length === 0) return null;
  const isClient = d.audience === "client" || (d.canChooseMode && !d.settings?.canEdit);
  const send = () => form && void run(() => api.post<Report>(`${url}/orders`, { person: Number(form.person), days: Number(form.days), note: form.note }),
    isClient ? "Commande validée et ajoutée au budget" : "Commande envoyée au client pour validation").then(() => { setForm(null); onDone(); }, () => undefined);
  const decide = (id: string, decision: "approved" | "rejected", comment = "") => void run(() => api.post<Report>(`${url}/orders/${id}/decision`, { decision, comment }),
    decision === "approved" ? "Commande validée" : "Commande refusée").then(() => { setReject(null); onDone(); }, () => undefined);
  const canDecide = d.canChooseMode;
  return (
    <div className="bud-orders">
      <div className="bud-orders-h">
        <b>🗓️ Commandes de jours</b>
        <div className="bud-mode" role="group" aria-label="Mode de budget">
          <span>Budget :</span>
          {(["global", "resource"] as const).map((m) => (
            <button key={m} type="button" className={`btn sm ${d.budgetMode === m ? "primary" : ""}`} disabled={!d.canChooseMode || busy}
              title={d.canChooseMode ? "Choix du client" : "Choisi par le client"}
              onClick={() => void run(() => api.put<Report>(url, { budgetMode: m }), "Mode de budget enregistré").then(onDone, () => undefined)}>
              {m === "global" ? "Global (toute l'équipe)" : "Par ressource"}
            </button>
          ))}
        </div>
      </div>
      <small>{d.budgetMode === "resource" ? "Chaque membre consomme les jours commandés pour lui ; le reste par personne apparaît dans le détail." : "Un budget unique pour toute l'équipe ; les commandes validées s'y ajoutent."}
        {" "}Les commandes du commercial ou du chef de projet sont validées par le client ; celles du client sont validées d'office.</small>
      {orders.length > 0 && (
        <table className="tbl">
          <thead><tr><th>Date</th><th>Ressource</th><th className="num">Jours</th><th className="num">Montant HT</th><th>Par</th><th>Statut</th></tr></thead>
          <tbody>{orders.map((o) => (
            <tr key={o.id}>
              <td>{new Date(o.at).toLocaleDateString("fr-FR")}</td><td>{o.personName}{o.note ? <small> · {o.note}</small> : null}</td>
              <td className="num">{n(o.days)}</td><td className="num">{eur(o.amount)}</td><td>{o.by}{o.byRole ? <small> ({o.byRole})</small> : null}</td>
              <td>{o.status === "pending" ? (canDecide ? (reject?.id === o.id ? (
                <span className="bud-inline">
                  <input className="inp" placeholder="Motif du refus" aria-label="Motif du refus" autoFocus value={reject.comment} onChange={(e) => setReject({ ...reject, comment: e.target.value })} />
                  <button type="button" className="btn sm" disabled={busy || !reject.comment.trim()} onClick={() => decide(o.id, "rejected", reject.comment)}>Refuser</button>
                  <button type="button" className="btn sm" onClick={() => setReject(null)}>Annuler</button>
                </span>
              ) : (
                <span className="bud-inline">
                  <button type="button" className="btn sm primary" disabled={busy} onClick={() => decide(o.id, "approved")}>✔ Valider</button>
                  <button type="button" className="btn sm" disabled={busy} onClick={() => setReject({ id: o.id, comment: "" })}>✖</button>
                </span>
              )) : <span className="bud-chip pending">À valider par le client</span>)
                : o.status === "approved" ? <span className="bud-chip ok">Validée{o.decidedBy ? ` · ${o.decidedBy}` : ""}</span>
                : <span className="bud-chip ko" title={o.comment}>Refusée</span>}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      {d.canOrder && (form === null ? (
        <button type="button" className="btn sm" onClick={() => setForm({ person: String(d.team?.[0]?.id ?? ""), days: "", note: "" })}>+ Commander des jours</button>
      ) : (
        <form className="bud-extra-form" onSubmit={(e) => { e.preventDefault(); send(); }}>
          <select className="inp" aria-label="Consultant" value={form.person} onChange={(e) => setForm({ ...form, person: e.target.value })}>
            {(d.team ?? []).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
          <input className="inp bud-num" type="number" min={0.5} step={0.5} placeholder="Jours" aria-label="Nombre de jours" autoFocus
            value={form.days} onChange={(e) => setForm({ ...form, days: e.target.value })} />
          <input className="inp" placeholder="Note (facultatif)" aria-label="Note" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
          <button className="btn sm primary" type="submit" disabled={busy || !form.person || !(Number(form.days) > 0)}>{isClient ? "Commander" : "Envoyer au client"}</button>
          <button className="btn sm" type="button" onClick={() => setForm(null)}>Annuler</button>
        </form>
      ))}
    </div>
  );
}
