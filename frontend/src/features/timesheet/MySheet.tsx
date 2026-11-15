// Feuille de temps par période : vues Jour / Semaine / Mois, saisie en brouillon (enregistrement automatique)
// par projet et par ligne de saisie, absences, contrôle de complétude et envoi en validation de la période.
import { useEffect, useMemo, useState } from "react";

import { api, ApiError } from "../../api/client";
import { ErrorNotice, Loading, useAction, useToast } from "../../components/ui";
import "./sheet.css";
import { SheetHistory } from "./SheetHistory";

type View = "day" | "week" | "month";
type Line = { id: string; label: string; code: string };
type SheetProject = { id: string; code: string; name: string; client: string; lines: Line[]; lineRequired: boolean };
type Status = "draft" | "pending" | "client" | "approved" | "rejected";
type Sheet = {
  unit: "hour" | "day"; full: number; hoursPerDay: number; from: string; to: string; approval: string;
  projects: SheetProject[];
  entries: { id: number; project: string; line: string; date: string; amount: number; status: Status; rejectReason?: string; editable?: boolean }[];
  absences: { id: number; kind: string; date: string; amount: number; status: "draft" | "submitted" }[];
  absenceKinds: { code: string; label: string }[];
  days: { date: string; working: boolean; holiday: string | null; total: number; complete: boolean; over: boolean }[];
  incomplete: string[]; drafts: number; canSubmit: boolean; gap: number; rejectedLeft: number;
  rejected: { id: number; project: string; date: string; amount: number; reason: string }[];
  sent?: { entries: number; absences: number; auto: boolean; gapDays?: number };
};

const STATUS: Record<string, string> = { draft: "Brouillon", pending: "En validation", client: "Chez le client", approved: "Validé", rejected: "Refusé", submitted: "Envoyée" };
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const parse = (s: string) => new Date(`${s}T00:00:00`);
const add = (d: Date, n: number) => { const r = new Date(d); r.setDate(r.getDate() + n); return r; };
const monday = (d: Date) => add(new Date(d.getFullYear(), d.getMonth(), d.getDate()), -((d.getDay() + 6) % 7));
const fmt = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/0$/, "").replace(".", ","));
const num = (v: string) => { const n = Number(String(v).replace(",", ".")); return Number.isFinite(n) && n >= 0 ? n : NaN; };

function rangeOf(view: View, anchor: Date): [Date, Date] {
  if (view === "day") return [anchor, anchor];
  if (view === "week") { const m = monday(anchor); return [m, add(m, 6)]; }
  return [new Date(anchor.getFullYear(), anchor.getMonth(), 1), new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0)];
}

export function MySheet() {
  const [view, setViewState] = useState<View>(() => { try { return (localStorage.getItem("pct.sheetView") as View) || "week"; } catch { return "week"; } });
  const [anchor, setAnchor] = useState(() => new Date());
  const [weekend, setWeekend] = useState(false);
  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [edit, setEdit] = useState<Record<string, string>>({});
  const [extraRows, setExtraRows] = useState<string[]>([]);
  const [pickProject, setPickProject] = useState("");
  const [extraAbs, setExtraAbs] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [history, setHistory] = useState(false);
  const { run, busy } = useAction();
  const toast = useToast();
  const [start, end] = rangeOf(view, anchor);
  const q = `from=${iso(start)}&to=${iso(end)}`;
  const setView = (v: View) => { setViewState(v); try { localStorage.setItem("pct.sheetView", v); } catch { /* préférence locale */ } };

  useEffect(() => {
    let live = true;
    setEdit({}); setError(null);
    api.get<Sheet>(`/timesheets/sheet?${q}`).then((s) => live && setSheet(s), (e) => live && setError(e));
    return () => { live = false; };
  }, [q]);

  const today = iso(new Date());
  const unit = sheet?.unit === "day" ? "j" : "h";
  const days = useMemo(() => (sheet?.days ?? []).filter((d) => view !== "month" && view !== "week" ? true : weekend || parse(d.date).getDay() % 6 !== 0 || d.total > 0), [sheet, view, weekend]);

  // Lignes affichées : projet sans ligne de saisie, ou couple projet + ligne déjà utilisé / ajouté.
  const rows = useMemo(() => {
    if (!sheet) return [] as { key: string; project: SheetProject; line: Line | null }[];
    const used = new Set([...sheet.entries.map((e) => `${e.project}|${e.line}`), ...extraRows]);
    const out: { key: string; project: SheetProject; line: Line | null }[] = [];
    for (const p of sheet.projects) {
      if (!p.lineRequired) out.push({ key: `${p.id}|`, project: p, line: null });
      else for (const l of p.lines) if (used.has(`${p.id}|${l.id}`)) out.push({ key: `${p.id}|${l.id}`, project: p, line: l });
    }
    // Saisies existantes hors lignes actives (ancienne saisie sans ligne, ligne désactivée) : affichées en lecture.
    for (const e of sheet.entries) {
      const key = `${e.project}|${e.line}`;
      if (out.some((r) => r.key === key)) continue;
      const p = sheet.projects.find((x) => x.id === e.project) ?? { id: e.project, code: e.project, name: e.project, client: "", lines: [], lineRequired: false };
      out.push({ key, project: p, line: { id: e.line, label: e.line ? "Ligne désactivée" : "Sans ligne", code: "" } });
    }
    return out;
  }, [sheet, extraRows]);
  const addable = (sheet?.projects ?? []).flatMap((p) => p.lines.filter((l) => !rows.some((r) => r.key === `${p.id}|${l.id}`)).map((l) => ({ key: `${p.id}|${l.id}`, label: `${p.name} › ${l.label}` })));
  const absRows = useMemo(() => {
    const set = new Set([...(sheet?.absences ?? []).map((a) => a.kind), ...extraAbs]);
    return (sheet?.absenceKinds ?? []).filter((k) => set.has(k.code));
  }, [sheet, extraAbs]);

  if (error) return <ErrorNotice error={error as ApiError} onRetry={() => setAnchor(new Date(anchor))} />;
  if (!sheet) return <Loading label="Chargement de la feuille de temps…" />;

  const entryOf = (key: string, date: string) => { const [p, l] = key.split("|"); return sheet.entries.find((e) => e.project === p && e.line === l && e.date === date); };
  const absOf = (kind: string, date: string) => sheet.absences.find((a) => a.kind === kind && a.date === date);
  const locked = (s?: string) => s === "pending" || s === "client" || s === "approved" || s === "submitted";
  const cellVal = (k: string, saved?: number) => (k in edit ? edit[k] : saved ? fmt(saved) : "");
  const rowTotal = (key: string) => days.reduce((s, d) => s + (entryOf(key, d.date)?.amount ?? 0), 0);
  const absTotal = (kind: string) => days.reduce((s, d) => s + (absOf(kind, d.date)?.amount ?? 0), 0);
  const periodTotal = days.reduce((s, d) => s + d.total, 0);
  const expected = sheet.days.filter((d) => d.working).length * sheet.full;
  const doneDays = sheet.days.filter((d) => d.working && d.complete).length;
  const workDays = sheet.days.filter((d) => d.working).length;

  const save = async (cells: { project: string; line: string; date: string; amount: number }[], absences: { kind: string; date: string; amount: number }[], keys: string[]) => {
    setSaving(true);
    try {
      const s = await api.put<Sheet>(`/timesheets/sheet?${q}`, { from: iso(start), to: iso(end), cells, absences });
      setSheet(s);
      setEdit((prev) => { const n = { ...prev }; keys.forEach((k) => delete n[k]); return n; });
    } catch (e) {
      toast(e instanceof Error ? e.message : "Enregistrement impossible", true);
    } finally {
      setSaving(false);
    }
  };
  const commitCell = (rowKey: string, date: string) => {
    const k = `e|${rowKey}|${date}`;
    if (!(k in edit)) return;
    const v = num(edit[k] || "0");
    if (Number.isNaN(v)) { toast("Durée invalide", true); return; }
    const [project, line] = rowKey.split("|");
    void save([{ project, line, date, amount: v }], [], [k]);
  };
  const commitAbs = (kind: string, date: string) => {
    const k = `a|${kind}|${date}`;
    if (!(k in edit)) return;
    const v = num(edit[k] || "0");
    if (Number.isNaN(v)) { toast("Durée invalide", true); return; }
    void save([], [{ kind, date, amount: v }], [k]);
  };
  const fillRow = (rowKey: string) => {
    const [project, line] = rowKey.split("|");
    const cells = sheet.days.filter((d) => d.working && !d.complete && !locked(entryOf(rowKey, d.date)?.status))
      .map((d) => ({ project, line, date: d.date, amount: (entryOf(rowKey, d.date)?.amount ?? 0) + (sheet.full - d.total) }));
    if (cells.length) void save(cells, [], []);
  };
  const submit = () => void run(() => api.post<Sheet>("/timesheets/sheet/submit", { from: iso(start), to: iso(end) }))
    .then((s) => { if (!s) return; setSheet(s); toast((s.sent?.auto ? "Période enregistrée et validée automatiquement" : `Période envoyée en validation (${s.sent?.entries ?? 0} saisie(s), ${s.sent?.absences ?? 0} absence(s))`) + (s.sent?.gapDays ? ` · ${s.sent.gapDays} jour(s) complété(s) en absence` : "")); }, () => undefined);

  const move = (dir: number) => setAnchor(view === "day" ? add(anchor, dir) : view === "week" ? add(anchor, 7 * dir) : new Date(anchor.getFullYear(), anchor.getMonth() + dir, 1));
  const label = view === "day" ? start.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long", year: "numeric" })
    : view === "week" ? `Semaine du ${start.toLocaleDateString("fr-FR", { day: "numeric", month: "long" })} au ${end.toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" })}`
    : start.toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
  const head = (d: Sheet["days"][number]) => {
    const dt = parse(d.date);
    return view === "month" ? <><small>{dt.toLocaleDateString("fr-FR", { weekday: "narrow" })}</small>{dt.getDate()}</>
      : <><small>{dt.toLocaleDateString("fr-FR", { weekday: "short" })}</small>{dt.getDate()}</>;
  };
  const input = (k: string, saved: number | undefined, status: string | undefined, onCommit: () => void, aria: string, off: boolean, editable?: boolean) => (
    locked(status) && !editable ? <span className={`sh-lock ${status}`} title={`${STATUS[status!]} · CRA généré : saisie figée`}>{fmt(saved ?? 0)}</span> : (
      <input className={`sh-in ${status === "rejected" ? "rej" : ""} ${status === "draft" ? "draft" : ""} ${locked(status) ? `sent ${status}` : ""}`} inputMode="decimal" placeholder={off ? "" : "·"} aria-label={aria}
        value={cellVal(k, saved)} onChange={(e) => setEdit({ ...edit, [k]: e.target.value })} onBlur={onCommit}
        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} title={locked(status) ? `${STATUS[status!]} — encore modifiable (CRA non généré) : la modifier la remettra en brouillon, à renvoyer.` : status === "rejected" ? `Refusé : ${sheet.entries.find((x) => `e|${x.project}|${x.line}|${x.date}` === k)?.rejectReason || "à corriger"}` : status ? STATUS[status] : undefined} />
    ));

  return (
    <section className="sh card" aria-label="Ma feuille de temps">
      {history && <SheetHistory onClose={() => setHistory(false)} onOpen={(p) => { setHistory(false); setView("month"); setAnchor(new Date(`${p}-01T00:00:00`)); }} />}
      <header className="sh-top">
        <div className="sh-seg" role="tablist" aria-label="Affichage">
          {(["day", "week", "month"] as const).map((v) => (
            <button key={v} type="button" role="tab" aria-selected={view === v} className={view === v ? "on" : ""} onClick={() => setView(v)}>
              {v === "day" ? "Jour" : v === "week" ? "Semaine" : "Mois"}
            </button>
          ))}
        </div>
        <div className="sh-nav">
          <button type="button" className="btn sm" aria-label="Période précédente" onClick={() => move(-1)}>‹</button>
          <button type="button" className="btn sm" onClick={() => setAnchor(new Date())}>Aujourd’hui</button>
          <button type="button" className="btn sm" aria-label="Période suivante" onClick={() => move(1)}>›</button>
          <h3>{label.charAt(0).toUpperCase() + label.slice(1)}</h3>
        </div>
        <button type="button" className="btn sm sh-histbtn" title="Historique de mes saisies, états, validations en attente et CRA" onClick={() => setHistory(true)}>🕘 Historique</button>
        {view !== "day" && <label className="sh-we"><input type="checkbox" checked={weekend} onChange={(e) => setWeekend(e.target.checked)} /> Week-end</label>}
      </header>

      <p className={`sh-note ${sheet.unit}`}>
        {sheet.unit === "day"
          ? <>📅 Saisie <b>en jours</b> : indiquez <b>1</b> pour une journée complète et <b>0,5</b> pour une demi-journée (présence ou absence).</>
          : <>⏱️ Saisie <b>en heures</b> : <b>1 journée = {fmt(sheet.hoursPerDay)} h</b>. Une demi-journée = {fmt(sheet.hoursPerDay / 2)} h.</>}
      </p>

      {sheet.rejected.length > 0 && (
        <div className="sh-rejected" role="alert">
          <b>⚠️ {sheet.rejected.length} saisie(s) refusée(s) à corriger puis renvoyer</b>
          {sheet.rejected.map((x) => (
            <div key={x.id}>• {new Date(`${x.date}T00:00:00`).toLocaleDateString("fr-FR", { weekday: "short", day: "2-digit", month: "2-digit" })} — {x.project} ({fmt(x.amount)} {unit}) : <i>{x.reason || "sans motif"}</i></div>
          ))}
          <small>Modifiez la case en rouge (nouvelle durée, ou 0 pour la supprimer), puis cliquez sur « Envoyer en validation ».</small>
        </div>
      )}

      <div className="sh-progress" aria-label="Complétude de la période">
        <div className="sh-bar"><i style={{ width: `${workDays ? (doneDays / workDays) * 100 : 100}%` }} /></div>
        <span><b>{doneDays}/{workDays}</b> jour(s) ouvré(s) complet(s) · {fmt(periodTotal)} / {fmt(expected)} {unit}{saving ? " · enregistrement…" : " · enregistré automatiquement"}</span>
      </div>

      <div className="sh-wrap">
        <table className={`sh-grid ${view}`}>
          <thead>
            <tr>
              <th className="sh-first">Projet · ligne</th>
              {days.map((d) => (
                <th key={d.date} className={`${d.date === today ? "today" : ""} ${!d.working ? "off" : ""} ${d.working ? (d.complete ? "ok" : "ko") : ""}`} title={d.holiday ?? undefined}>
                  {head(d)}{d.holiday && <em>férié</em>}
                </th>
              ))}
              <th className="sh-tot">Total</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key}>
                <td className="sh-first">
                  <b>{r.project.name}</b>
                  <small>{r.line ? <span className="sh-line">{r.line.label}</span> : r.project.client}</small>
                  {view !== "day" && !(r.project.lineRequired && !r.project.lines.some((l) => l.id === r.line?.id)) && <button type="button" className="sh-fill" title="Compléter les jours ouvrés restants sur cette ligne" onClick={() => fillRow(r.key)}>⇥</button>}
                </td>
                {days.map((d) => {
                  const e = entryOf(r.key, d.date);
                  return <td key={d.date} className={`${d.date === today ? "today" : ""} ${!d.working ? "off" : ""}`}>
                    {input(`e|${r.key}|${d.date}`, e?.amount, e?.status, () => commitCell(r.key, d.date), `${r.project.name}${r.line ? ` ${r.line.label}` : ""} ${d.date}`, !d.working, e?.editable)}
                  </td>;
                })}
                <td className="sh-tot">{rowTotal(r.key) ? `${fmt(rowTotal(r.key))} ${unit}` : "—"}</td>
              </tr>
            ))}
            {addable.length > 0 && (
              <tr className="sh-add">
                <td colSpan={days.length + 2}>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                    <b style={{ fontSize: 13 }}>+ Saisir sur :</b>
                    <select className="inp" style={{ maxWidth: 260 }} aria-label="Projet" value={pickProject} onChange={(e) => setPickProject(e.target.value)}>
                      <option value="">1. Choisir le projet…</option>
                      {[...new Map(addable.map((a) => [a.key.split("|")[0], a.label.split(" › ")[0]])).entries()].map(([id, name]) => <option key={id} value={id}>{name}</option>)}
                    </select>
                    <select className="inp" style={{ maxWidth: 300 }} aria-label="Ligne du projet" value="" disabled={!pickProject}
                      onChange={(e) => { if (e.target.value) { setExtraRows([...extraRows, e.target.value]); setPickProject(""); } }}>
                      <option value="">2. Choisir la ligne déclarée…</option>
                      {addable.filter((a) => a.key.startsWith(`${pickProject}|`)).map((a) => <option key={a.key} value={a.key}>{a.label.split(" › ")[1]}</option>)}
                    </select>
                    <small className="muted">Lignes définies par le client ou l’administrateur (Paramètres du projet → Lignes de saisie).</small>
                  </div>
                </td>
              </tr>
            )}
            <tr className="sh-sep"><td colSpan={days.length + 2}>Absences</td></tr>
            {absRows.map((k) => (
              <tr key={k.code} className="sh-abs">
                <td className="sh-first"><b>{k.label}</b></td>
                {days.map((d) => {
                  const a = absOf(k.code, d.date);
                  return <td key={d.date} className={`${d.date === today ? "today" : ""} ${!d.working ? "off" : ""}`}>
                    {input(`a|${k.code}|${d.date}`, a?.amount, a?.status, () => commitAbs(k.code, d.date), `${k.label} ${d.date}`, !d.working)}
                  </td>;
                })}
                <td className="sh-tot">{absTotal(k.code) ? `${fmt(absTotal(k.code))} ${unit}` : "—"}</td>
              </tr>
            ))}
            <tr className="sh-add">
              <td colSpan={days.length + 2}>
                <select className="inp" aria-label="Déclarer une absence" value="" onChange={(e) => e.target.value && setExtraAbs([...extraAbs, e.target.value])}>
                  <option value="">+ Déclarer une absence (congés, RTT, maladie, formation…)</option>
                  {sheet.absenceKinds.filter((k) => !absRows.some((r) => r.code === k.code)).map((k) => <option key={k.code} value={k.code}>{k.label}</option>)}
                </select>
              </td>
            </tr>
          </tbody>
          <tfoot>
            <tr>
              <td className="sh-first">Total du jour</td>
              {days.map((d) => (
                <td key={d.date} className={d.over ? "crit" : d.working ? (d.complete ? "ok" : "ko") : ""}>{d.total ? fmt(d.total) : d.working ? "0" : ""}{d.working && d.complete ? " ✓" : ""}</td>
              ))}
              <td className="sh-tot">{fmt(periodTotal)} {unit}</td>
            </tr>
          </tfoot>
        </table>
      </div>

      <footer className="sh-foot">
        <div className="sh-legend">
          <span className="sh-lock draft">Brouillon</span><span className="sh-lock pending">En validation</span>
          <span className="sh-lock approved">Validé</span><span className="sh-lock rejected">Refusé</span>
          <small>Une journée ouvrée est complète quand présence + absences = {fmt(sheet.full)} {unit}.</small>
        </div>
        {sheet.canSubmit ? (
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            {sheet.incomplete.length > 0 && <small className="sh-todo">{fmt(sheet.gap)} {unit} non saisi(es) sur {sheet.incomplete.length} jour(s) : ce temps sera déclaré en absence (« Absence / temps non saisi ») à l’envoi.</small>}
            <button type="button" className="btn primary" disabled={busy || saving} onClick={submit}>
              {sheet.approval === "auto" ? "Valider la période" : "📤 Envoyer en validation"}
            </button>
          </div>
        ) : sheet.rejectedLeft > 0 ? (
          <small className="sh-todo">Corrigez les {sheet.rejectedLeft} saisie(s) refusée(s) avant de renvoyer la période.</small>
        ) : sheet.incomplete.length ? (
          <small className="sh-todo">Encore {sheet.incomplete.length} jour(s) à compléter ({sheet.incomplete.slice(0, 4).map((d) => parse(d).toLocaleDateString("fr-FR", { weekday: "short", day: "numeric" })).join(", ")}{sheet.incomplete.length > 4 ? "…" : ""}) avant l’envoi en validation.</small>
        ) : <small className="sh-done">{sheet.entries.some((e) => e.status === "pending" || e.status === "client") ? "✓ Période complète et envoyée en validation." : sheet.entries.length ? "✓ Période complète et validée." : "✓ Période complète."}</small>}
      </footer>
    </section>
  );
}
