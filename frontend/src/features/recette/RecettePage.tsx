// Module Recette : user stories de test, bugs liés et discussions. Interface pensée pour le testeur :
// un tableau par projet, des boutons de statut en un clic et une discussion sur chaque US ou bug.
import { useEffect, useMemo, useState, type FormEvent } from "react";

import { api, ApiError } from "../../api/client";
import { useApi } from "../../api/useApi";
import { Card, ErrorNotice, Loading, Modal, PageHead, Tabs, useAction } from "../../components/ui";

type Opt = { code: string; label: string };
type Member = { id: number; name: string; role: string };
export type Story = {
  id: number; code: string; title: string; description: string; acceptance: string; scenario: string; expected: string; feature: string;
  priority: string; priorityLabel: string; status: string; statusLabel: string; tester: number | null; testerName: string | null;
  createdBy: string | null; createdAt: string; testedAt: string | null; testedBy: string | null; openBugs: number; bugs: number; comments?: number;
};
export type Bug = {
  id: number; code: string; story: number; storyCode: string; storyTitle: string; title: string; description: string; steps: string; resolution: string;
  severity: string; severityLabel: string; status: string; statusLabel: string; open: boolean; assignee: number | null; assigneeName: string | null;
  reporter: number | null; reportedBy: string | null; createdAt: string; closedAt: string | null; comments?: number;
};
type Board = {
  project: { id: number; code: string; name: string }; stories: Story[]; bugs: Bug[]; members: Member[]; me: number;
  perms: { manage: boolean; report: boolean; assign: boolean }; priorities: Opt[]; storyStatuses: Opt[]; bugStatuses: Opt[];
};
type ProjectRow = { id: number; code: string; name: string; stories: number; byStatus: Record<string, number>; openBugs: number };

const PRIO_TONE: Record<string, string> = { bloquante: "crit", critique: "crit", majeure: "warn", mineure: "info", autre: "" };
const STORY_TONE: Record<string, string> = { a_tester: "", en_test: "info", validee: "ok", echec: "crit", a_retester: "acc", bloquee: "warn" };
const BUG_TONE: Record<string, string> = { nouveau: "crit", assigne: "warn", en_cours: "info", cloture: "ok", rejete: "", rouvert: "crit" };
const pill = (tone: string, text: string) => <span className={`pill ${tone}`}>{text}</span>;
const fmt = (d: string | null) => (d ? new Date(d).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "");

export function RecettePage() {
  const projects = useApi(() => api.get<{ projects: ProjectRow[]; perms: { manage: boolean } }>("/recette/projects"));
  const initial = Number(window.location.hash.split("/")[1]) || null;
  const [projectId, setProjectId] = useState<number | null>(initial);
  useEffect(() => {
    if (!projectId && projects.data?.projects.length) setProjectId(projects.data.projects[0].id);
  }, [projects.data, projectId]);
  useEffect(() => {
    if (projectId) window.history.replaceState(null, "", `#recette/${projectId}`);
  }, [projectId]);

  if (projects.error) return <div className="page"><ErrorNotice error={projects.error} onRetry={projects.reload} /></div>;
  if (!projects.data) return <div className="page"><Loading /></div>;
  const list = projects.data.projects;
  return (
    <div className="page">
      <PageHead eyebrow="Qualité" title="Recette" sub="User stories de test, bugs et discussions : suivez la recette de vos projets."
        right={list.length > 0 && (
          <select className="inp" aria-label="Projet" value={projectId ?? ""} onChange={(e) => setProjectId(Number(e.target.value))} style={{ minWidth: 240 }}>
            {list.map((p) => <option key={p.id} value={p.id}>{p.code} · {p.name}{p.openBugs ? ` (${p.openBugs} bug${p.openBugs > 1 ? "s" : ""})` : ""}</option>)}
          </select>
        )} />
      {list.length === 0 ? <Card title="Aucun projet">Vous n’êtes affecté à aucun projet.</Card> : projectId && <ProjectBoard key={projectId} projectId={projectId} onChanged={projects.reload} />}
    </div>
  );
}

function ProjectBoard({ projectId, onChanged }: { projectId: number; onChanged: () => void }) {
  const board = useApi(() => api.get<Board>(`/recette/board?project=${projectId}`), [projectId]);
  const [tab, setTab] = useState<"stories" | "bugs">("stories");
  const [mine, setMine] = useState(false);
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [openStory, setOpenStory] = useState<number | null>(null);
  const [openBug, setOpenBug] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const reload = () => { board.reload(); onChanged(); };

  const b = board.data;
  const stories = useMemo(() => (b?.stories ?? []).filter((s) =>
    (!mine || s.tester === b?.me) && (!statusFilter || s.status === statusFilter) &&
    (!q || `${s.code} ${s.title} ${s.feature}`.toLowerCase().includes(q.toLowerCase()))), [b, mine, statusFilter, q]);
  const bugs = useMemo(() => (b?.bugs ?? []).filter((x) =>
    (!mine || x.assignee === b?.me || x.reporter === b?.me) && (!statusFilter || x.status === statusFilter || (statusFilter === "open" && x.open)) &&
    (!q || `${x.code} ${x.title} ${x.storyCode}`.toLowerCase().includes(q.toLowerCase()))), [b, mine, statusFilter, q]);

  if (board.error) return <ErrorNotice error={board.error} onRetry={board.reload} />;
  if (!b) return <Loading />;
  const count = (st: string) => b.stories.filter((s) => s.status === st).length;
  const openBugs = b.bugs.filter((x) => x.open);
  const total = b.stories.length || 1;
  const story = b.stories.find((s) => s.id === openStory) ?? null;
  const bug = b.bugs.find((x) => x.id === openBug) ?? null;

  return (
    <>
      <div className="rec-kpis">
        {b.storyStatuses.map((s) => (
          <button key={s.code} type="button" className={`rec-kpi ${STORY_TONE[s.code]}${tab === "stories" && statusFilter === s.code ? " on" : ""}`}
            onClick={() => { setTab("stories"); setStatusFilter(statusFilter === s.code ? "" : s.code); }}>
            <b>{count(s.code)}</b><span>{s.label}</span>
          </button>
        ))}
        <button type="button" className={`rec-kpi crit${tab === "bugs" && statusFilter === "open" ? " on" : ""}`}
          onClick={() => { setTab("bugs"); setStatusFilter(statusFilter === "open" ? "" : "open"); }}>
          <b>{openBugs.length}</b><span>Bugs ouverts{openBugs.some((x) => ["bloquante", "critique"].includes(x.severity)) ? ` · ${openBugs.filter((x) => ["bloquante", "critique"].includes(x.severity)).length} critiques` : ""}</span>
        </button>
      </div>
      <div className="rec-progress" title="Avancement de la recette">
        <span className="ok" style={{ width: `${(count("validee") / total) * 100}%` }} />
        <span className="crit" style={{ width: `${(count("echec") / total) * 100}%` }} />
        <span className="acc" style={{ width: `${(count("a_retester") / total) * 100}%` }} />
      </div>

      <Card title="" sub="">
        <div className="rec-toolbar">
          <Tabs<"stories" | "bugs"> tabs={[["stories", `User stories (${b.stories.length})`], ["bugs", `Bugs (${b.bugs.length})`]]} value={tab}
            onChange={(t) => { setTab(t); setStatusFilter(""); }} />
          <div className="rec-filters">
            <input className="inp" placeholder="Rechercher…" value={q} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 200 }} />
            <select className="inp" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} aria-label="Statut" style={{ maxWidth: 180 }}>
              <option value="">Tous les statuts</option>
              {tab === "bugs" && <option value="open">Ouverts</option>}
              {(tab === "stories" ? b.storyStatuses : b.bugStatuses).map((s) => <option key={s.code} value={s.code}>{s.label}</option>)}
            </select>
            <label className="rec-mine"><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> {tab === "stories" ? "Mes tests" : "Mes bugs"}</label>
            {tab === "stories" && b.perms.manage && <button type="button" className="btn primary sm" onClick={() => setCreating(true)}>+ Nouvelle US</button>}
          </div>
        </div>

        {tab === "stories" ? (
          stories.length === 0 ? <p className="muted">Aucune user story{b.stories.length ? " pour ce filtre" : " : créez la première US de test"}.</p> : (
            <div className="tbl-wrap"><table className="tbl tight rec-table">
              <thead><tr><th>US</th><th>Titre</th><th>Priorité</th><th>Statut</th><th>Testeur</th><th>Bugs</th><th>Test rapide</th></tr></thead>
              <tbody>{stories.map((s) => (
                <tr key={s.id} onClick={() => setOpenStory(s.id)} className="rec-row">
                  <td className="mono">{s.code}</td>
                  <td><b>{s.title}</b>{s.feature && <small className="muted" style={{ display: "block" }}>{s.feature}</small>}</td>
                  <td>{pill(PRIO_TONE[s.priority] ?? "", s.priorityLabel)}</td>
                  <td>{pill(STORY_TONE[s.status] ?? "", s.statusLabel)}</td>
                  <td>{s.testerName ?? <span className="muted">—</span>}</td>
                  <td>{s.openBugs ? <span className="t-crit">{s.openBugs} ouvert{s.openBugs > 1 ? "s" : ""}</span> : s.bugs ? <span className="muted">{s.bugs} clos</span> : "—"}
                    {s.comments ? <small className="muted"> · 💬 {s.comments}</small> : null}</td>
                  <td onClick={(e) => e.stopPropagation()}>{b.perms.manage && <QuickStatus story={s} onDone={reload} />}</td>
                </tr>
              ))}</tbody>
            </table></div>
          )
        ) : (
          bugs.length === 0 ? <p className="muted">Aucun bug{b.bugs.length ? " pour ce filtre" : ""}.</p> : (
            <div className="tbl-wrap"><table className="tbl tight rec-table">
              <thead><tr><th>Bug</th><th>Titre</th><th>US</th><th>Sévérité</th><th>Statut</th><th>Affecté à</th><th>Déclaré</th></tr></thead>
              <tbody>{bugs.map((x) => (
                <tr key={x.id} onClick={() => setOpenBug(x.id)} className="rec-row">
                  <td className="mono">{x.code}</td>
                  <td><b>{x.title}</b>{x.comments ? <small className="muted"> · 💬 {x.comments}</small> : null}</td>
                  <td className="mono" title={x.storyTitle}>{x.storyCode}</td>
                  <td>{pill(PRIO_TONE[x.severity] ?? "", x.severityLabel)}</td>
                  <td>{pill(BUG_TONE[x.status] ?? "", x.statusLabel)}</td>
                  <td>{x.assigneeName ?? <span className="t-crit">Non affecté</span>}</td>
                  <td><small>{fmt(x.createdAt)}<br /><span className="muted">{x.reportedBy}</span></small></td>
                </tr>
              ))}</tbody>
            </table></div>
          )
        )}
      </Card>

      {creating && <StoryForm board={b} onClose={() => setCreating(false)} onSaved={(s) => { setCreating(false); reload(); setOpenStory(s.id); }} />}
      {story && <StoryModal board={b} story={story} onClose={() => setOpenStory(null)} onChanged={reload} onOpenBug={(id) => { setOpenStory(null); setOpenBug(id); }} />}
      {bug && <BugModal board={b} bug={bug} onClose={() => setOpenBug(null)} onChanged={reload} onOpenStory={(id) => { setOpenBug(null); setOpenStory(id); }} />}
    </>
  );
}

function QuickStatus({ story, onDone }: { story: Story; onDone: () => void }) {
  const { run, busy } = useAction();
  const set = (status: string) => void run(() => api.post(`/recette/stories/${story.id}/status`, { status }), "Statut mis à jour").then(onDone, () => undefined);
  return (
    <div className="btns" style={{ flexWrap: "nowrap" }}>
      {story.status !== "en_test" && story.status !== "validee" && <button className="btn ghost sm" title="Commencer le test" disabled={busy} onClick={() => set("en_test")}>▶</button>}
      <button className="btn ghost sm" title={story.openBugs ? "Bugs encore ouverts" : "Validée (OK)"} disabled={busy || story.status === "validee" || story.openBugs > 0} onClick={() => set("validee")}>✅</button>
      <button className="btn ghost sm" title="En échec (KO)" disabled={busy || story.status === "echec"} onClick={() => set("echec")}>❌</button>
    </div>
  );
}

function StoryForm({ board, story, onClose, onSaved }: { board: Board; story?: Story; onClose: () => void; onSaved: (s: Story) => void }) {
  const [f, setF] = useState({
    title: story?.title ?? "", feature: story?.feature ?? "", priority: story?.priority ?? "majeure", tester: story?.tester ? String(story.tester) : "",
    description: story?.description ?? "", acceptance: story?.acceptance ?? "", scenario: story?.scenario ?? "", expected: story?.expected ?? "",
  });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const submit = async (e?: FormEvent) => {
    e?.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const body = { ...f, tester: f.tester ? Number(f.tester) : null, project: board.project.id };
      onSaved(story ? await api.patch<Story>(`/recette/stories/${story.id}`, body) : await api.post<Story>("/recette/stories", body));
    } catch (x) {
      setErr(x instanceof ApiError ? x.message : "Enregistrement impossible.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title={story ? `Modifier ${story.code}` : "Nouvelle user story de test"} onClose={onClose} wide
      footer={<><button className="btn" onClick={onClose}>Annuler</button><button className="btn primary" disabled={busy || !f.title.trim()} onClick={() => void submit()}>{busy ? "Enregistrement…" : "Enregistrer"}</button></>}>
      <form onSubmit={submit} className="rec-form">
        <label className="span2">Titre<input className="inp" value={f.title} onChange={set("title")} placeholder="Ex. Connexion avec un compte Google" required /></label>
        <label>Lot / fonctionnalité<input className="inp" value={f.feature} onChange={set("feature")} placeholder="Ex. Authentification" /></label>
        <label>Priorité<select className="inp" value={f.priority} onChange={set("priority")}>{board.priorities.map((p) => <option key={p.code} value={p.code}>{p.label}</option>)}</select></label>
        <label>Testeur<select className="inp" value={f.tester} onChange={set("tester")}><option value="">Non attribué</option>{board.members.map((m) => <option key={m.id} value={m.id}>{m.name} · {m.role}</option>)}</select></label>
        <label className="span2">Description (en tant que… je veux… afin de…)<textarea className="inp" rows={3} value={f.description} onChange={set("description")} /></label>
        <label className="span2">Critères d’acceptation<textarea className="inp" rows={3} value={f.acceptance} onChange={set("acceptance")} placeholder={"- …\n- …"} /></label>
        <label>Étapes de test<textarea className="inp" rows={4} value={f.scenario} onChange={set("scenario")} placeholder={"1. …\n2. …"} /></label>
        <label>Résultat attendu<textarea className="inp" rows={4} value={f.expected} onChange={set("expected")} /></label>
        {err && <div className="callout warn span2" role="alert"><b>{err}</b></div>}
      </form>
    </Modal>
  );
}

function Text({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return <div className="rec-text"><span className="muted">{label}</span><p>{value}</p></div>;
}

function StoryModal({ board, story, onClose, onChanged, onOpenBug }: { board: Board; story: Story; onClose: () => void; onChanged: () => void; onOpenBug: (id: number) => void }) {
  const { run, busy } = useAction();
  const [edit, setEdit] = useState(false);
  const [reporting, setReporting] = useState(false);
  const [note, setNote] = useState("");
  const [threadKey, setThreadKey] = useState(0);
  const bugs = board.bugs.filter((x) => x.story === story.id);
  const setStatus = (status: string) =>
    void run(() => api.post(`/recette/stories/${story.id}/status`, { status, comment: note }), "Statut mis à jour")
      .then(() => { setNote(""); onChanged(); setThreadKey((k) => k + 1); }, () => undefined);
  if (edit) return <StoryForm board={board} story={story} onClose={() => setEdit(false)} onSaved={() => { setEdit(false); onChanged(); }} />;
  return (
    <Modal title={`${story.code} · ${story.title}`} onClose={onClose} wide>
      <div className="rec-detail">
        <div className="rec-main">
          <div className="rec-meta">
            {pill(STORY_TONE[story.status] ?? "", story.statusLabel)} {pill(PRIO_TONE[story.priority] ?? "", story.priorityLabel)}
            {story.feature && <span className="muted">· {story.feature}</span>}
            <span className="muted">· testeur : {story.testerName ?? "non attribué"}</span>
            {story.testedAt && <span className="muted">· testé le {fmt(story.testedAt)} par {story.testedBy}</span>}
          </div>
          {board.perms.manage && (
            <div className="rec-status-bar">
              <input className="inp" placeholder="Commentaire du test (facultatif)" value={note} onChange={(e) => setNote(e.target.value)} />
              <div className="btns">
                <button className="btn sm" disabled={busy || story.status === "en_test"} onClick={() => setStatus("en_test")}>▶ En test</button>
                <button className="btn sm ok" disabled={busy || story.status === "validee" || story.openBugs > 0} title={story.openBugs ? "Des bugs sont encore ouverts" : ""} onClick={() => setStatus("validee")}>✅ Validée</button>
                <button className="btn sm crit" disabled={busy || story.status === "echec"} onClick={() => setStatus("echec")}>❌ En échec</button>
                <button className="btn sm" disabled={busy || story.status === "bloquee"} onClick={() => setStatus("bloquee")}>⏸ Bloquée</button>
                <button className="btn ghost sm" onClick={() => setEdit(true)}>✏️ Modifier</button>
              </div>
            </div>
          )}
          <Text label="Description" value={story.description} />
          <Text label="Critères d’acceptation" value={story.acceptance} />
          <div className="grid g2" style={{ gap: 10 }}><Text label="Étapes de test" value={story.scenario} /><Text label="Résultat attendu" value={story.expected} /></div>

          <div className="rec-section">
            <div className="rec-section-h"><b>🐞 Bugs liés ({bugs.length})</b>
              {board.perms.report && !reporting && <button className="btn sm crit" onClick={() => setReporting(true)}>+ Déclarer un bug</button>}</div>
            {reporting && <BugForm board={board} storyId={story.id} onCancel={() => setReporting(false)} onSaved={() => { setReporting(false); onChanged(); setThreadKey((k) => k + 1); }} />}
            {bugs.length === 0 ? <p className="muted" style={{ margin: 0 }}>Aucun bug déclaré.</p> : bugs.map((x) => (
              <button key={x.id} type="button" className="rec-bug-line" onClick={() => onOpenBug(x.id)}>
                <span className="mono">{x.code}</span> <b>{x.title}</b> {pill(PRIO_TONE[x.severity] ?? "", x.severityLabel)} {pill(BUG_TONE[x.status] ?? "", x.statusLabel)}
                <span className="muted"> · {x.assigneeName ?? "non affecté"}</span>
              </button>
            ))}
          </div>
        </div>
        <Thread key={threadKey} target={{ story: story.id }} />
      </div>
    </Modal>
  );
}

function BugForm({ board, storyId, onCancel, onSaved }: { board: Board; storyId: number; onCancel: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ title: "", severity: "majeure", assignee: "", description: "", steps: "" });
  const { run, busy } = useAction();
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <div className="rec-form rec-bug-form">
      <label className="span2">Titre du bug<input className="inp" value={f.title} onChange={set("title")} placeholder="Ex. Message d’erreur après validation du formulaire" /></label>
      <label>Sévérité<select className="inp" value={f.severity} onChange={set("severity")}>{board.priorities.map((p) => <option key={p.code} value={p.code}>{p.label}</option>)}</select></label>
      <label>Affecter à (consultant, développeur, tech lead…)<select className="inp" value={f.assignee} onChange={set("assignee")}><option value="">Plus tard</option>{board.members.map((m) => <option key={m.id} value={m.id}>{m.name} · {m.role}</option>)}</select></label>
      <label>Constat<textarea className="inp" rows={3} value={f.description} onChange={set("description")} /></label>
      <label>Étapes pour reproduire<textarea className="inp" rows={3} value={f.steps} onChange={set("steps")} placeholder={"1. …\n2. …"} /></label>
      <div className="btns span2">
        <button className="btn crit sm" disabled={busy || !f.title.trim()} onClick={() => void run(() => api.post("/recette/bugs", { ...f, story: storyId, assignee: f.assignee ? Number(f.assignee) : null }), "Bug déclaré : l’US passe en échec").then(onSaved, () => undefined)}>Déclarer le bug</button>
        <button className="btn ghost sm" onClick={onCancel}>Annuler</button>
      </div>
    </div>
  );
}

function BugModal({ board, bug, onClose, onChanged, onOpenStory }: { board: Board; bug: Bug; onClose: () => void; onChanged: () => void; onOpenStory: (id: number) => void }) {
  const { run, busy } = useAction();
  const [note, setNote] = useState("");
  const [resolution, setResolution] = useState(bug.resolution);
  const [threadKey, setThreadKey] = useState(0);
  const isAssignee = bug.assignee === board.me;
  const manager = board.perms.report;
  const patch = (body: Record<string, unknown>, msg: string) =>
    void run(() => api.patch(`/recette/bugs/${bug.id}`, { ...body, comment: note }), msg).then(() => { setNote(""); onChanged(); setThreadKey((k) => k + 1); }, () => undefined);
  const statusBtn = (code: string, label: string, cls = "") =>
    <button key={code} className={`btn sm ${cls}`} disabled={busy || bug.status === code} onClick={() => patch({ status: code, resolution }, `Bug ${label.toLowerCase()}`)}>{label}</button>;
  return (
    <Modal title={`${bug.code} · ${bug.title}`} onClose={onClose} wide>
      <div className="rec-detail">
        <div className="rec-main">
          <div className="rec-meta">
            {pill(BUG_TONE[bug.status] ?? "", bug.statusLabel)} {pill(PRIO_TONE[bug.severity] ?? "", bug.severityLabel)}
            <button type="button" className="auth-link-inline" onClick={() => onOpenStory(bug.story)}>{bug.storyCode} · {bug.storyTitle}</button>
            <span className="muted">· déclaré par {bug.reportedBy} le {fmt(bug.createdAt)}</span>
          </div>
          <div className="grid g2" style={{ gap: 10 }}>
            <label className="rec-inline">Affecté à
              <select className="inp" disabled={!manager || busy} value={bug.assignee ?? ""} onChange={(e) => patch({ assignee: e.target.value ? Number(e.target.value) : null }, "Bug affecté")}>
                <option value="">Non affecté</option>{board.members.map((m) => <option key={m.id} value={m.id}>{m.name} · {m.role}</option>)}
              </select></label>
            <label className="rec-inline">Sévérité
              <select className="inp" disabled={!manager || busy} value={bug.severity} onChange={(e) => patch({ severity: e.target.value }, "Sévérité modifiée")}>
                {board.priorities.map((p) => <option key={p.code} value={p.code}>{p.label}</option>)}
              </select></label>
          </div>
          <Text label="Constat" value={bug.description} />
          <Text label="Étapes pour reproduire" value={bug.steps} />
          {(manager || isAssignee) && (
            <div className="rec-section">
              <label className="rec-inline">Correction / résolution
                <textarea className="inp" rows={2} value={resolution} onChange={(e) => setResolution(e.target.value)} placeholder="Ce qui a été corrigé, version livrée…" /></label>
              <input className="inp" placeholder="Commentaire (facultatif)" value={note} onChange={(e) => setNote(e.target.value)} />
              <div className="btns">
                {statusBtn("en_cours", "En cours")}
                {statusBtn("cloture", "✅ Clôturer", "ok")}
                {manager && statusBtn("rejete", "Rejeter")}
                {manager && (bug.status === "cloture" || bug.status === "rejete") && statusBtn("rouvert", "↺ Rouvrir", "crit")}
              </div>
              <small className="muted">À la clôture du dernier bug ouvert, l’US {bug.storyCode} passe automatiquement « Prête à retester ».</small>
            </div>
          )}
          {!manager && !isAssignee && bug.resolution && <Text label="Résolution" value={bug.resolution} />}
        </div>
        <Thread key={threadKey} target={{ bug: bug.id }} />
      </div>
    </Modal>
  );
}

type Comment = { id: number; author: string; authorId: number | null; body: string; kind: string; createdAt: string };

function Thread({ target }: { target: { story?: number; bug?: number } }) {
  const qs = target.bug ? `bug=${target.bug}` : `story=${target.story}`;
  const r = useApi(() => api.get<{ comments: Comment[] }>(`/recette/thread?${qs}`), [qs]);
  const [body, setBody] = useState("");
  const { run, busy } = useAction();
  const send = (e: FormEvent) => {
    e.preventDefault();
    void run(() => api.post("/recette/thread", { ...target, body }), "Message envoyé").then(() => { setBody(""); r.reload(); }, () => undefined);
  };
  return (
    <aside className="rec-thread">
      <b>💬 Discussion</b>
      <div className="rec-thread-list">
        {!r.data ? <Loading /> : r.data.comments.length === 0 ? <p className="muted">Aucun message. Posez une question ou partagez une précision.</p> :
          r.data.comments.map((c) => c.kind === "event"
            ? <div key={c.id} className="rec-event">• {c.body} <span className="muted">— {c.author}, {fmt(c.createdAt)}</span></div>
            : <div key={c.id} className="rec-msg"><div className="rec-msg-h"><b>{c.author}</b> <span className="muted">{fmt(c.createdAt)}</span></div><p>{c.body}</p></div>)}
      </div>
      <form onSubmit={send} className="rec-thread-form">
        <textarea className="inp" rows={2} placeholder="Écrire un message…" value={body} onChange={(e) => setBody(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && body.trim()) send(e as unknown as FormEvent); }} />
        <button className="btn primary sm" disabled={busy || !body.trim()}>Envoyer</button>
      </form>
    </aside>
  );
}
