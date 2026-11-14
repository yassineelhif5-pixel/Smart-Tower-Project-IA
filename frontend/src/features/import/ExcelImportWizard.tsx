import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { api, API_BASE, ApiError } from "../../api/client";
import { useFileDrop } from "../../components/DropZone";

type Col = { index: number; header: string; sample: string[]; field: string; confidence: number };
type Sheet = { name: string; rows: number; headerRow: number; columns: Col[]; role: string; roleConfidence: number; estimateUnit: string };
type SheetMap = { role: string; headerRow: number; estimateUnit: string; columns: Record<string, string>; strategy: string; projectName?: string };
type Options = { pmIsMe: boolean; client: { mode: "same" | "each"; code: string; perGroup: Record<string, string> } };
type Mapping = { sheets: Record<string, SheetMap>; targets?: Record<string, string>; merge?: { target: string; name: string } | null; hoursPerDay?: number; options?: Options;
  groupOptions?: Record<string, { updateOnly: boolean }> };
type Row = {
  title: string; ref?: string; ownerName: string | null; ownerRaw: string; status: string; due: string | null; estHours: number | null; phase: string;
  match: { id: string; title: string; how: string } | null; changes: string[];
};
type Group = {
  key: string; label: string; sheets: string[]; action: "create" | "update" | "skip"; target: { id: string; name: string; code: string } | null;
  newName: string; projectType?: string | null; actions: number; match: { how: string; score: number } | null; updateOnly: boolean;
  unchanged: number; ignored: number; toCreate: number; toUpdate: number; owners: string[]; unknownOwners: string[]; estHours: number; done: number; sample: Row[];
};
type Analysis = {
  file: string; sheets: Sheet[]; mapping: Mapping; groups: Group[]; fields: Record<string, string>; recommendations: string[];
  questions: string[]; canCreate: boolean; projects: { id: string; code: string; name: string }[];
  clients: { code: string; name: string }[]; defaultClient: string; me: string;
};
type Report = {
  project: string; projectId?: string; created?: boolean; actionsCreated?: number; actionsUpdated?: number; unknownOwners?: string[];
  error?: string; client?: string; pm?: string | null; rows?: number; projectType?: string | null;
  actionsUnchanged?: number; actionsSkipped?: number;
};
type Step = { key: string; label: string; state: "wait" | "run" | "ok" | "ko"; report?: Report };

const STATUS: Record<string, string> = { todo: "À faire", planned: "Planifiée", doing: "En cours", review: "En revue", blocked: "Bloquée", done: "Terminée" };

function cookie(name: string) {
  return document.cookie.split("; ").find((c) => c.startsWith(`${name}=`))?.split("=")[1];
}
async function send<T>(file: File, step: string, mapping?: Mapping, only?: string): Promise<T> {
  if (!cookie("csrftoken")) await fetch(`${API_BASE}/auth/csrf`, { credentials: "same-origin" });
  const fd = new FormData();
  fd.append("file", file);
  fd.append("step", step);
  if (mapping) fd.append("mapping", JSON.stringify(mapping));
  if (only) fd.append("only", only);
  const r = await fetch(`${API_BASE}/imports/excel`, {
    method: "POST", credentials: "same-origin", headers: { "X-CSRFToken": decodeURIComponent(cookie("csrftoken") ?? "") }, body: fd,
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(r.status, body);
  return body as T;
}

/** Bouton d'accueil « Importer depuis Excel ». */
type Job = {
  id: string; file: string; status: "running" | "done" | "partial" | "failed"; startedAt: string; endedAt: string | null;
  total: number; done: number; current: string | null; rows: number; ignoredRows: number; report: Report[];
};

/** Bouton d'accueil « Importer depuis Excel » + suivi des imports en arrière-plan. */
export function ExcelImportCard() {
  const [open, setOpen] = useState(false);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [recap, setRecap] = useState<Report[] | null>(null);
  const load = useCallback(() => {
    api.get<{ jobs: Job[] }>("/imports/excel/jobs").then((d) => {
      setJobs((prev) => {
        if (prev.some((j) => j.status === "running") && !d.jobs.some((j) => j.status === "running")) {
          window.dispatchEvent(new Event("pct-alerts-changed"));
        }
        return d.jobs;
      });
    }, () => undefined);
  }, []);
  useEffect(() => {
    load();
    window.addEventListener("pct-import-started", load);
    return () => window.removeEventListener("pct-import-started", load);
  }, [load]);
  const running = jobs.filter((j) => j.status === "running");
  useEffect(() => {
    if (!running.length) return;
    const t = window.setInterval(load, 3000);
    return () => window.clearInterval(t);
  }, [running.length, load]);
  const recent = jobs.filter((j) => j.status !== "running" && j.endedAt && Date.now() - new Date(j.endedAt).getTime() < 6 * 3600 * 1000).slice(0, 3);
  return (
    <>
      <button type="button" className="xi-card" onClick={() => setOpen(true)}>
        <span className="xi-ic">📥</span>
        <span>
          <b>Importer des projets et des actions depuis Excel</b>
          <small>L’Orchestrateur IA lit votre classeur, détecte les feuilles et vous propose le mappage. Vous validez avant toute création.</small>
        </span>
        <span className="xi-go">Importer →</span>
      </button>
      {[...running, ...recent].map((j) => (
        <div key={j.id} className={`xi-job ${j.status}`}>
          <span>{j.status === "running" ? <span className="xi-spin" /> : j.status === "done" ? "✅" : "⚠️"}</span>
          <div>
            <b>{j.status === "running" ? "Import en arrière-plan en cours" : j.status === "done" ? "Import terminé" : "Import terminé avec des erreurs"} — {j.file}</b>
            <small>
              {j.done}/{j.total} projet(s) {j.current ? `· en cours : ${j.current}` : ""}
              {j.status !== "running" && ` · ${j.report.reduce((n, r) => n + (r.actionsCreated ?? 0), 0)} action(s) créée(s), ${j.report.reduce((n, r) => n + (r.actionsUpdated ?? 0), 0)} mise(s) à jour`}
            </small>
            {j.status === "running" && <div className="xi-pbar"><i style={{ width: `${Math.round((j.done / Math.max(1, j.total)) * 100)}%` }} /></div>}
          </div>
          {j.status !== "running" && <button className="btn sm" type="button" onClick={() => setRecap(j.report)}>Récapitulatif</button>}
        </div>
      ))}
      {open && <ExcelImportWizard onClose={() => { setOpen(false); load(); }} />}
      {recap && <ImportRecap report={recap} onClose={() => setRecap(null)} onDone={() => setRecap(null)} />}
    </>
  );
}

export function ExcelImportWizard({ onClose }: { onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const xiDrop = useFileDrop((fs) => {
    const f = fs.find((x) => /\.(xlsx|xlsm|csv)$/i.test(x.name));
    if (f) setFile(f);
  });
  const [busy, setBusy] = useState<string>("");
  const [err, setErr] = useState("");
  const [a, setA] = useState<Analysis | null>(null);
  const [map, setMap] = useState<Mapping | null>(null);
  const [groups, setGroups] = useState<Group[]>([]);
  const [recos, setRecos] = useState<string[]>([]);
  const [stale, setStale] = useState(false);
  const [report, setReport] = useState<Report[] | null>(null);
  const [steps, setSteps] = useState<Step[] | null>(null);
  const [recap, setRecap] = useState(false);
  const [bg, setBg] = useState<Job | null>(null);

  const fail = (e: unknown) => setErr(e instanceof ApiError ? e.message : "Opération impossible.");
  const analyse = async () => {
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) {
      setErr(`Fichier trop volumineux (${(file.size / 1024 / 1024).toFixed(1)} Mo) : 10 Mo maximum.`);
      return;
    }
    setErr("");
    setBusy("🎼 Lecture du classeur, détection des feuilles et des colonnes…");
    try {
      const r = await send<Analysis>(file, "analyse");
      setA(r);
      setMap({ ...r.mapping, options: { pmIsMe: true, client: { mode: "same", code: r.defaultClient, perGroup: {} } } });
      setGroups(r.groups);
      setRecos(r.recommendations);
      setStale(false);
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };
  const preview = async (m = map) => {
    if (!file || !m) return;
    setBusy("🎼 Mise à jour du plan d’import…");
    try {
      const r = await send<{ groups: Group[]; recommendations: string[] }>(file, "preview", m);
      setGroups(r.groups);
      setRecos(r.recommendations);
      setStale(false);
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };
  const apply = async () => {
    if (!file || !map) return;
    const todo = groups.filter((g) => g.action !== "skip");
    const list: Step[] = todo.map((g) => ({ key: g.key, label: g.action === "update" && g.target ? g.target.name : g.newName, state: "wait" }));
    setSteps(list);
    setErr("");
    const out: Report[] = [];
    for (let i = 0; i < todo.length; i++) {
      list[i] = { ...list[i], state: "run" };
      setSteps([...list]);
      setBusy(`🎼 Import du projet ${i + 1}/${todo.length} : ${list[i].label}…`);
      try {
        const r = await send<{ report: Report[] }>(file, "apply", map, todo[i].key);
        const rep = r.report[0] ?? { project: list[i].label, error: "Aucune action importée." };
        out.push(rep);
        list[i] = { ...list[i], state: rep.error ? "ko" : "ok", report: rep };
      } catch (e) {
        const rep = { project: list[i].label, error: e instanceof ApiError ? e.message : "Erreur pendant l’import." };
        out.push(rep);
        list[i] = { ...list[i], state: "ko", report: rep };
      }
      setSteps([...list]);
    }
    setBusy("");
    setReport(out);
    setRecap(true);
  };
  const applyBackground = async () => {
    if (!file || !map) return;
    setErr("");
    setBusy("🎼 Lancement de l’import en arrière-plan…");
    try {
      const job = await send<Job>(file, "apply_bg", map);
      setBg(job);
      window.dispatchEvent(new Event("pct-import-started"));
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };
  const setOpt = (fn: (o: Options) => Options) => {
    if (!map?.options) return;
    setMap({ ...map, options: fn(structuredClone(map.options)) });
  };
  const edit = (fn: (m: Mapping) => Mapping) => {
    if (!map) return;
    setMap(fn(structuredClone(map)));
    setStale(true);
  };
  const setTarget = (key: string, v: string) => {
    if (!map) return;
    const m = structuredClone(map);
    m.targets = { ...(m.targets ?? {}), [key]: v };
    setMap(m);
    void preview(m);
  };

  return createPortal(
    <div className="scrim" onClick={() => !busy && onClose()}>
      <div className="modal xi-modal" role="dialog" aria-label="Import Excel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-h">
          <div>
            <h3 style={{ margin: 0 }}>📥 Import Excel assisté par l’Orchestrateur IA</h3>
            <small className="faint">{a ? a.file : "Projets, actions, estimations et affectations"}</small>
          </div>
          <button className="icon-btn" type="button" aria-label="Fermer" disabled={!!busy} onClick={onClose}>✕</button>
        </div>
        <div className="modal-b xi-body">
          {err && <div className="xi-err">⚠️ {err}</div>}
          {busy && <div className="xi-busy"><span className="xi-spin" />{busy}</div>}

          {steps && (
            <div className="xi-progress">
              <div className="xi-pbar"><i style={{ width: `${Math.round((steps.filter((x) => x.state === "ok" || x.state === "ko").length / steps.length) * 100)}%` }} /></div>
              <small>{steps.filter((x) => x.state === "ok" || x.state === "ko").length} / {steps.length} projet(s) traité(s)</small>
              <ul>
                {steps.map((x) => (
                  <li key={x.key} className={`xi-ps ${x.state}`}>
                    <span>{x.state === "wait" ? "⏳" : x.state === "run" ? <span className="xi-spin" /> : x.state === "ok" ? "✅" : "⚠️"}</span>
                    <b>{x.label}</b>
                    <small>
                      {x.state === "wait" && "en attente"}
                      {x.state === "run" && "import en cours…"}
                      {x.state === "ok" && `${x.report?.created ? "projet créé" : "projet mis à jour"} · ${x.report?.actionsCreated} action(s) créée(s), ${x.report?.actionsUpdated} mise(s) à jour`}
                      {x.state === "ko" && x.report?.error}
                    </small>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {bg && (
            <div className="xi-bg">
              <span className="xi-ic">🕒</span>
              <div>
                <b>Import lancé en arrière-plan</b>
                <p>
                  {bg.total} projet(s) et {bg.rows} ligne(s) sont en cours d’import. Vous pouvez fermer cette fenêtre et continuer à travailler :
                  vous serez notifié dans la cloche 🔔 (et par e-mail) dès la fin, avec le récapitulatif. L’avancement s’affiche aussi sur la page « Mes projets ».
                </p>
              </div>
            </div>
          )}
          {bg ? null : steps ? null : report ? (
            <div className="xi-report">
              <h4>✅ Import terminé</h4>
              {report.map((r, i) => (
                <div key={i} className={`xi-rep${r.error ? " ko" : ""}`}>
                  {r.error ? (
                    <span>⚠️ <b>{r.project}</b> : {r.error}</span>
                  ) : (
                    <>
                      <span>
                        <b>{r.project}</b> {r.created ? <span className="pill nodot ok">Nouveau projet</span> : <span className="pill nodot info">Mis à jour</span>}
                        <small> · {r.actionsCreated} action(s) créée(s), {r.actionsUpdated} mise(s) à jour
                          {r.unknownOwners?.length ? ` · à affecter : ${r.unknownOwners.join(", ")}` : ""}</small>
                      </span>
                      {r.projectId && <a className="btn sm" href={`#projets/${encodeURIComponent(r.projectId)}`} onClick={onClose}>Ouvrir</a>}
                    </>
                  )}
                </div>
              ))}
            </div>
          ) : !a ? (
            <div className="xi-step1">
              <p>Quel fichier voulez-vous importer ? Classeur Excel (.xlsx) ou CSV, une ou plusieurs feuilles, un ou plusieurs projets.</p>
              <label className={`xi-drop${xiDrop.dragging ? " over" : ""}`} {...xiDrop.bind}>
                <input type="file" accept=".xlsx,.xlsm,.csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
                <span className="xi-ic">📄</span>
                <b>{xiDrop.dragging ? "Déposez le fichier ici" : file ? file.name : "Glissez le classeur ici ou cliquez pour le choisir"}</b>
                <small>{file ? `${(file.size / 1024).toFixed(0)} Ko` : "10 Mo maximum"}</small>
              </label>
              <ol className="xi-how">
                <li>Maestro lit le classeur et détecte les feuilles (actions, projets, à ignorer).</li>
                <li>Il propose une matrice de mappage colonne → champ, que vous pouvez corriger.</li>
                <li>Il propose de créer des projets ou de tout regrouper dans un projet existant.</li>
                <li>Vous validez : les projets sont créés ou mis à jour avec actions, estimations et affectations.</li>
              </ol>
            </div>
          ) : (
            map && (
              <>
                <div className="xi-ai">
                  <b>🎼 Maestro — analyse du classeur</b>
                  <ul>{recos.map((r, i) => <li key={i}>{r}</li>)}</ul>
                  {a.questions.length > 0 && (
                    <>
                      <b>❓ Questions</b>
                      <ul>{a.questions.map((q, i) => <li key={i}>{q}</li>)}</ul>
                    </>
                  )}
                </div>

                <h4>1. Feuilles et matrice de mappage</h4>
                {a.sheets.map((s) => {
                  const sm = map.sheets[s.name];
                  return (
                    <div key={s.name} className={`xi-sheet${sm.role === "ignore" ? " off" : ""}`}>
                      <div className="xi-sh">
                        <b>📑 {s.name}</b> <small className="faint">{s.rows} ligne(s)</small>
                        <label>
                          Cette feuille contient
                          <select className="inp sm" value={sm.role} onChange={(e) => edit((m) => ((m.sheets[s.name].role = e.target.value), m))}>
                            <option value="actions">des actions / tâches</option>
                            <option value="projects">une liste de projets</option>
                            <option value="ignore">rien à importer (ignorer)</option>
                          </select>
                        </label>
                        {sm.role === "actions" && (
                          <>
                            <label>
                              Projet
                              <select className="inp sm" value={sm.strategy} onChange={(e) => edit((m) => ((m.sheets[s.name].strategy = e.target.value), m))}>
                                <option value="column">selon la colonne « Projet »</option>
                                <option value="sheet">un projet pour cette feuille</option>
                              </select>
                            </label>
                            <label>
                              Charge en
                              <select className="inp sm" value={sm.estimateUnit} onChange={(e) => edit((m) => ((m.sheets[s.name].estimateUnit = e.target.value), m))}>
                                <option value="d">jours</option>
                                <option value="h">heures</option>
                              </select>
                            </label>
                          </>
                        )}
                        <label>
                          En-tête ligne
                          <input className="inp sm num" type="number" min={1} style={{ width: 64 }} value={sm.headerRow + 1}
                            onChange={(e) => edit((m) => ((m.sheets[s.name].headerRow = Math.max(0, Number(e.target.value) - 1)), m))} />
                        </label>
                      </div>
                      {sm.role !== "ignore" && (
                        <div className="tbl-wrap">
                          <table className="tbl tight xi-map">
                            <thead><tr><th>Colonne du fichier</th><th>Exemples</th><th>Champ Smart Tower</th><th>Confiance IA</th></tr></thead>
                            <tbody>
                              {s.columns.map((c) => {
                                const f = sm.columns[String(c.index)] ?? "ignore";
                                return (
                                  <tr key={c.index} className={f === "ignore" ? "xi-ign" : ""}>
                                    <td><b>{c.header}</b></td>
                                    <td className="faint xi-sample">{c.sample.join(" · ") || "—"}</td>
                                    <td>
                                      <select className="inp sm" value={f} onChange={(e) => edit((m) => ((m.sheets[s.name].columns[String(c.index)] = e.target.value), m))}>
                                        {Object.entries(a.fields).filter(([k]) => (sm.role === "projects" ? k.startsWith("p_") || k === "ignore" || k === "description" : !k.startsWith("p_")))
                                          .map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                                      </select>
                                    </td>
                                    <td>{f === "ignore" ? "—" : <span className={`xi-conf ${c.confidence >= 75 ? "hi" : c.confidence >= 50 ? "md" : "lo"}`}>{c.field === f ? `${c.confidence} %` : "manuel"}</span>}</td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  );
                })}

                <h4>2. Projets cibles</h4>
                <label className="xi-merge">
                  <input type="checkbox" checked={!!map.merge}
                    onChange={(e) => { const m = structuredClone(map); m.merge = e.target.checked ? { target: "new", name: a.file.replace(/\.[^.]+$/, "") } : null; setMap(m); void preview(m); }} />
                  <span><b>Tout regrouper dans un seul projet</b> <small className="faint">(au lieu d’un projet par feuille / par valeur de la colonne Projet)</small></span>
                </label>
                {map.merge && (
                  <div className="xi-row">
                    <select className="inp sm" value={map.merge.target}
                      onChange={(e) => { const m = structuredClone(map); m.merge = { ...m.merge!, target: e.target.value }; setMap(m); void preview(m); }}>
                      {a.canCreate && <option value="new">Nouveau projet…</option>}
                      {a.projects.map((p) => <option key={p.id} value={p.id}>{p.code} · {p.name}</option>)}
                    </select>
                    {map.merge.target === "new" && (
                      <input className="inp sm" value={map.merge.name} placeholder="Nom du nouveau projet"
                        onChange={(e) => { const m = structuredClone(map); m.merge = { ...m.merge!, name: e.target.value }; setMap(m); setStale(true); }} />
                    )}
                  </div>
                )}
                {map.options && groups.some((g) => g.action === "create") && (
                  <div className="xi-opts">
                    <h4 style={{ margin: 0 }}>3. Responsabilité et client des nouveaux projets</h4>
                    <div className="xi-q">
                      <span>❓ Les nouveaux projets doivent-ils être placés sous votre responsabilité directe ({a.me} comme chef de projet) ?</span>
                      <label><input type="radio" name="xi-pm" checked={map.options.pmIsMe} onChange={() => setOpt((o) => ({ ...o, pmIsMe: true }))} /> Oui, je suis chef de projet</label>
                      <label><input type="radio" name="xi-pm" checked={!map.options.pmIsMe} onChange={() => setOpt((o) => ({ ...o, pmIsMe: false }))} /> Non, garder le chef de projet indiqué dans le fichier (ou aucun)</label>
                    </div>
                    {groups.filter((g) => g.action !== "skip").length > 1 ? (
                      <div className="xi-q">
                        <span>❓ Tous les projets appartiennent-ils au même client ?</span>
                        <label><input type="radio" name="xi-cl" checked={map.options.client.mode === "same"} onChange={() => setOpt((o) => ({ ...o, client: { ...o.client, mode: "same" } }))} /> Oui, le même client :</label>
                        {map.options.client.mode === "same" && (
                          <select className="inp sm" value={map.options.client.code} onChange={(e) => { const v = e.target.value; setOpt((o) => ({ ...o, client: { ...o.client, code: v } })); }}>
                            {a.clients.map((c) => <option key={c.code} value={c.code}>{c.name}{c.code === a.defaultClient ? " (client en cours)" : ""}</option>)}
                          </select>
                        )}
                        <label><input type="radio" name="xi-cl" checked={map.options.client.mode === "each"} onChange={() => setOpt((o) => ({ ...o, client: { ...o.client, mode: "each" } }))} /> Non, je choisis le client de chaque projet ci-dessous</label>
                      </div>
                    ) : (
                      <div className="xi-q">
                        <span>Client du projet :</span>
                        <select className="inp sm" value={map.options.client.code} onChange={(e) => { const v = e.target.value; setOpt((o) => ({ ...o, client: { ...o.client, mode: "same", code: v } })); }}>
                          {a.clients.map((c) => <option key={c.code} value={c.code}>{c.name}{c.code === a.defaultClient ? " (client en cours)" : ""}</option>)}
                        </select>
                      </div>
                    )}
                  </div>
                )}
                {stale && (
                  <div className="xi-stale">
                    Le mappage a changé. <button className="btn sm primary" type="button" disabled={!!busy} onClick={() => void preview()}>Recalculer le plan</button>
                  </div>
                )}
                <div className="xi-groups">
                  {groups.length === 0 && <div className="empty">Aucune action détectée avec ce mappage (vérifiez la colonne « Titre de l’action »).</div>}
                  {groups.map((g) => (
                    <div key={g.key} className={`xi-group ${g.action}`}>
                      <div className="xi-gh">
                        <span className="xi-gi">{g.action === "create" ? "🆕" : g.action === "update" ? "🔄" : "⏭"}</span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <b>{g.action === "update" && g.target ? g.target.name : g.newName}</b>
                          <small className="faint">source : {g.label} ({g.sheets.join(", ")}){g.projectType ? ` · type : ${g.projectType}` : ""}</small>
                        </div>
                        {!map.merge && (
                          <select className="inp sm" value={g.action === "skip" ? "skip" : g.action === "create" ? "new" : g.target?.id ?? ""} onChange={(e) => setTarget(g.key, e.target.value)}>
                            {a.canCreate && <option value="new">Créer un nouveau projet</option>}
                            {a.projects.map((p) => <option key={p.id} value={p.id}>Mettre à jour : {p.code} · {p.name}</option>)}
                            <option value="skip">Ne pas importer</option>
                          </select>
                        )}
                      </div>
                      {g.action !== "skip" && (
                        <>
                          {g.action === "update" && g.target && (
                            <div className="xi-match">
                              <span>🔗 Projet existant détecté : <b>{g.target.name}</b> ({g.match?.how ?? "correspondance"}) — les actions déjà créées sont reconnues et seront mises à jour.</span>
                              <label>
                                <input type="checkbox" checked={g.updateOnly}
                                  onChange={(e) => { const m = structuredClone(map); m.groupOptions = { ...(m.groupOptions ?? {}), [g.key]: { updateOnly: e.target.checked } }; setMap(m); void preview(m); }} />
                                Mettre à jour seulement les actions existantes (ne créer aucune nouvelle action)
                              </label>
                            </div>
                          )}
                          <div className="xi-kpis">
                            <span><b>{g.actions}</b> ligne(s)</span>
                            <span>🆕 <b>{g.toCreate}</b> à créer</span>
                            <span>🔄 <b>{g.toUpdate}</b> à mettre à jour</span>
                            {g.unchanged > 0 && <span>✓ <b>{g.unchanged}</b> déjà à jour</span>}
                            {g.ignored > 0 && <span>⏭ <b>{g.ignored}</b> ignorée(s)</span>}
                            <span><b>{g.estHours}</b> h estimées</span>
                            <span><b>{g.done}</b> déjà terminée(s)</span>
                          </div>
                          {g.action === "create" && map.options?.client.mode === "each" && (
                            <label className="xi-gcl">
                              Client :
                              <select className="inp sm" value={map.options.client.perGroup[g.key] ?? a.defaultClient}
                                onChange={(e) => { const v = e.target.value; setOpt((o) => ({ ...o, client: { ...o.client, perGroup: { ...o.client.perGroup, [g.key]: v } } })); }}>
                                {a.clients.map((c) => <option key={c.code} value={c.code}>{c.name}{c.code === a.defaultClient ? " (client en cours)" : ""}</option>)}
                              </select>
                            </label>
                          )}
                          {g.owners.length > 0 && <small>👤 Affectations reconnues : {g.owners.join(", ")}</small>}
                          {g.unknownOwners.length > 0 && <small className="xi-warn">⚠️ Responsables non reconnus (actions non affectées) : {g.unknownOwners.join(", ")}</small>}
                          <div className="xi-prev-wrap">
                          <table className="tbl tight xi-prev">
                            <tbody>
                              {g.sample.map((r, i) => (
                                <tr key={i}>
                                  <td className="xi-mt">
                                    {r.match ? (
                                      r.changes.length ? (
                                        <span className="xi-badge up" title={`Correspondance : ${r.match.how}`}>🔄 {r.match.id} · {r.match.how}<em>→ {r.changes.join(", ")}</em></span>
                                      ) : (
                                        <span className="xi-badge same" title={`Correspondance : ${r.match.how}`}>✓ {r.match.id} · déjà à jour</span>
                                      )
                                    ) : g.updateOnly ? (
                                      <span className="xi-badge skip">⏭ ignorée</span>
                                    ) : (
                                      <span className="xi-badge new">🆕 nouvelle</span>
                                    )}
                                  </td>
                                  <td>{r.title}{r.match && r.match.title !== r.title ? <small className="faint" style={{ display: "block" }}>existante : {r.match.title}</small> : null}</td>
                                  <td className="faint">{r.ownerName ?? (r.ownerRaw ? `${r.ownerRaw} ?` : "—")}</td>
                                  <td className="faint">{STATUS[r.status]}</td>
                                  <td className="faint">{r.due ? new Date(r.due).toLocaleDateString("fr-FR") : "—"}</td>
                                  <td className="faint r">{r.estHours != null ? `${r.estHours} h` : "—"}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          </div>
                          {g.actions > g.sample.length && <small className="faint">… et {g.actions - g.sample.length} autre(s) action(s)</small>}
                        </>
                      )}
                    </div>
                  ))}
                </div>
              </>
            )
          )}
        </div>
        <div className="modal-f">
          {bg ? (
            <button className="btn primary" type="button" onClick={onClose}>Fermer</button>
          ) : steps && !report ? (
            <span className="faint">Import en cours, ne fermez pas la fenêtre…</span>
          ) : report ? (
            <>
              <button className="btn ghost" type="button" onClick={() => setRecap(true)}>Voir le récapitulatif</button>
              <button className="btn primary" type="button" onClick={onClose}>Fermer</button>
            </>
          ) : !a ? (
            <>
              <button className="btn ghost" type="button" onClick={onClose}>Annuler</button>
              <button className="btn primary" type="button" disabled={!file || !!busy} onClick={analyse}>🎼 Analyser le fichier</button>
            </>
          ) : (
            <>
              <button className="btn ghost" type="button" disabled={!!busy} onClick={() => { setA(null); setMap(null); setGroups([]); }}>← Changer de fichier</button>
              <span className="xi-launch">Mappage validé ? Lancer l’import :</span>
              <button className="btn" type="button" disabled={!!busy || stale || !groups.some((g) => g.action !== "skip")} onClick={applyBackground}
                title="L’import tourne sur le serveur ; vous êtes notifié à la fin">
                🕒 En arrière-plan
              </button>
              <button className="btn primary" type="button" disabled={!!busy || stale || !groups.some((g) => g.action !== "skip")} onClick={apply}
                title="Suivre la progression projet par projet">
                ▶ Suivre en temps réel
              </button>
            </>
          )}
        </div>
      </div>
      {recap && report && <ImportRecap report={report} onClose={() => setRecap(false)} onDone={onClose} />}
    </div>,
    document.body,
  );
}

/** Récapitulatif de fin d'import : ce qui a été importé (ou non). */
function ImportRecap({ report, onClose, onDone }: { report: Report[]; onClose: () => void; onDone: () => void }) {
  const ok = report.filter((r) => !r.error);
  const ko = report.filter((r) => r.error);
  const sum = (f: (r: Report) => number) => ok.reduce((n, r) => n + f(r), 0);
  const unknown = [...new Set(ok.flatMap((r) => r.unknownOwners ?? []))];
  const full = ko.length === 0;
  return (
    <div className="scrim xi-recap-scrim" onClick={(e) => { e.stopPropagation(); onClose(); }}>
      <div className={`modal xi-recap ${full ? "ok" : "partial"}`} role="dialog" aria-label="Récapitulatif de l’import" onClick={(e) => e.stopPropagation()}>
        <div className="modal-h">
          <h3 style={{ margin: 0 }}>{full ? "✅ Import réussi" : ok.length ? "⚠️ Import partiel" : "❌ Import non effectué"}</h3>
          <button className="icon-btn" type="button" aria-label="Fermer" onClick={onClose}>✕</button>
        </div>
        <div className="modal-b">
          <p style={{ marginTop: 0 }}>
            {full
              ? "Tous les éléments validés ont bien été importés."
              : ok.length
                ? `${ok.length} projet(s) importé(s), ${ko.length} non importé(s).`
                : "Aucun élément n’a été importé."}
          </p>
          <div className="xi-totals">
            <div><b>{sum((r) => (r.created ? 1 : 0))}</b><small>projet(s) créé(s)</small></div>
            <div><b>{sum((r) => (r.created ? 0 : 1))}</b><small>projet(s) mis à jour</small></div>
            <div><b>{sum((r) => r.actionsCreated ?? 0)}</b><small>action(s) créée(s)</small></div>
            <div><b>{sum((r) => r.actionsUpdated ?? 0)}</b><small>action(s) mise(s) à jour</small></div>
            <div className={ko.length ? "ko" : ""}><b>{ko.length}</b><small>projet(s) en échec</small></div>
          </div>
          <table className="tbl tight">
            <tbody>
              {report.map((r, i) => (
                <tr key={i}>
                  <td>{r.error ? "⚠️" : "✅"}</td>
                  <td>
                    <b>{r.project}</b>
                    <small className="faint" style={{ display: "block" }}>
                      {r.error ?? `${r.created ? "Nouveau projet" : "Mis à jour"}${r.projectType ? ` (${r.projectType})` : ""} · client ${r.client ?? "—"} · chef de projet ${r.pm ?? "—"} · ${r.actionsCreated} créée(s), ${r.actionsUpdated} mise(s) à jour${r.actionsUnchanged ? `, ${r.actionsUnchanged} déjà à jour` : ""}${r.actionsSkipped ? `, ${r.actionsSkipped} ignorée(s)` : ""}`}
                    </small>
                  </td>
                  <td className="r">{r.projectId && <a className="btn sm" href={`#projets/${encodeURIComponent(r.projectId)}`} onClick={onDone}>Ouvrir</a>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {unknown.length > 0 && (
            <p className="xi-warn" style={{ fontSize: 13 }}>
              ⚠️ Responsables non reconnus (actions à affecter) : {unknown.join(", ")}
            </p>
          )}
        </div>
        <div className="modal-f">
          <button className="btn primary" type="button" onClick={onClose}>OK</button>
        </div>
      </div>
    </div>
  );
}
