import { createPortal } from "react-dom";
import { WeeklyRecapCard } from "../features/notifications/WeeklyRecapCard";
import { Fragment, useEffect, useState } from "react";

import { api, API_BASE, ApiError } from "../api/client";
import { discussionApi } from "../api/collab";
import { AssistantButton } from "../features/assistant/ProjectAssistant";
import { AlertButton, AlertDialog, UserAlertsStrip } from "../features/projects/ProjectAlerts";
import { OrchestratorPage } from "../features/orchestrator/OrchestratorPage";
import { AiCallPage } from "../features/aicall/AiCallPage";
import { ExcelImportCard } from "../features/import/ExcelImportWizard";
import { MyTaskDialog, TaskBoard, useMyTask } from "../features/projects/MyTasks";
import { PortfolioReporting, readCompare, writeCompare } from "../features/projects/PortfolioReporting";
import { RequiredDocs } from "../features/projects/RequiredDocs";
import { TeamWorkload } from "../features/projects/TeamWorkload";
import { MigrationTab } from "../features/projects/MigrationTab";
import { ActionDrawer } from "../features/projects/ActionDrawer";
import { loadAssistant } from "../features/assistant/ProjectAssistant";
import { useApi } from "../api/useApi";
import { Card, ErrorNotice, Field, Loading, PageHead, useAction, useToast } from "../components/ui";
import { DocViewer } from "../features/projects/DocViewer";
import { DropZone } from "../components/DropZone";
import { TeamStructureButton, TeamStructureDialog } from "../features/projects/TeamStructure";
import { MinutesCard, MinutesDialog, type MinutesDoc } from "../features/projects/MinutesDialog";
import type { Me } from "../types/api";

type Person = { id: number; name: string; role: string };
type ProjectSummary = {
  id: string; code: string; name: string; client: { code: string; name: string }; method: string; progress: number; canEdit?: boolean;
  status?: "active" | "paused" | "closed"; statusLabel?: string; closedAt?: string | null; endDate?: string | null;
};
const PJ_FILTER_KEY = "pct-projects-filter";
const PJ_CLIENT_KEY = "pct-projects-client";
type DepRef = { id: string; title: string; status: string; statusLabel: string; due: string | null; project: string; projectName: string | null };
type Task = {
  id: string; title: string; status: string; statusLabel: string; owner: Person | null;
  due: string | null; startDate: string | null; prio: string; phase: string; est: string | null;
  dependsOn?: DepRef[]; successors?: DepRef[]; blockedBy?: number; depConflict?: boolean; instance?: { id: number; name: string } | null;
  doneAt?: string | null; spent?: string | null; type?: string; ticket?: string; extOwner?: string; incidentDate?: string | null; us?: { id: string; title: string; sprint: number | null } | null;
  extension?: { due: string; reason: string; by: string; from: string | null } | null;
};
type ProjRef = { id: string; code: string; name: string; progress?: number; endDate?: string | null; startDate?: string | null };
type Member = Person & { canEdit: boolean; isPm: boolean; isTl: boolean; openTasks: number; dailyRate?: string | null };
type Budget = {
  budget: string | null; consumed: string; pending: string; remaining: string | null; rate: number | null; hoursPerDay: string;
  rows: { user: string; dailyRate: string | null; hoursApproved: string; hoursPending: string; daysApproved: string; cost: string; engaged: string }[];
  missingRates: string[];
};
type Doc = {
  id: string; name: string; ext: string; type: string; typeLabel: string; description: string; size: number | null;
  version: number; uploadedBy: string | null; uploadedAt: string | null; clientVisible: boolean; hasFile: boolean;
  extraction?: Extraction; notified?: number; mailed?: number;
};
type Workspace = {
  id: string; code: string; name: string; client: { code: string; name: string }; method: string;
  description: string; startDate: string | null; endDate: string | null; progress: number;
  pm: Person | null; tl: Person | null;
  rights: {
    isPm: boolean; isTl: boolean; canManageTeam: boolean; canManageTasks: boolean; canCreateTasks?: boolean; canEditInfo: boolean;
    canEditType: boolean; canSeeMoney: boolean; canManageDocs: boolean;
  };
  team: Member[]; tasks: Task[]; statuses: { code: string; label: string }[]; counts: Record<string, number>;
  candidates?: Person[];
  projectType: string; projectTypeLabel: string; baseProject: { id: string; code: string; name: string } | null; baseVersion: string;
  targetVersion: string;
  projectTypes: { code: string; label: string }[]; natures?: string[]; natureChoices?: { code: string; label: string }[]; otherProjects?: { id: string; code: string; name: string }[];
  methodology: { kind: string; label: string; features: string[] };
  docTypes: { code: string; label: string }[];
  phases: string[];
  budget?: Budget;
  parent?: ProjRef | null; children?: ProjRef[]; dependsOn?: ProjRef[]; dependents?: ProjRef[]; linkProjects?: ProjRef[];
  instances?: { id: number; name: string; isPilot: boolean }[];
  status?: "active" | "paused" | "closed"; statusLabel?: string; closedAt?: string | null;
};

const projectsApi = {
  list: () => api.get<ProjectSummary[]>("/projects"),
  get: (id: string) => api.get<Workspace>(`/projects/${encodeURIComponent(id)}/workspace`),
  update: (id: string, body: Record<string, unknown>) => api.patch<Workspace>(`/projects/${encodeURIComponent(id)}/workspace`, body),
  addMember: (id: string, user: number, canEdit: boolean) => api.post<Workspace>(`/projects/${encodeURIComponent(id)}/team`, { user, canEdit }),
  removeMember: (id: string, user: number) => api.delete<Workspace>(`/projects/${encodeURIComponent(id)}/team/${user}`),
  addTask: (id: string, body: Record<string, unknown>) => api.post<Workspace>(`/projects/${encodeURIComponent(id)}/tasks`, body),
  updateTask: (id: string, task: string, body: Record<string, unknown>) =>
    api.patch<Workspace>(`/projects/${encodeURIComponent(id)}/tasks/${encodeURIComponent(task)}`, body),
  deleteTask: (id: string, task: string) => api.delete<Workspace>(`/projects/${encodeURIComponent(id)}/tasks/${encodeURIComponent(task)}`),
  remove: (id: string, code: string) => api.delete<{ deleted: string; actions: number }>(`/projects/${encodeURIComponent(id)}/workspace?confirm=${encodeURIComponent(code)}`),
  setRate: (id: string, user: number, dailyRate: number | null) =>
    api.post<Workspace>(`/projects/${encodeURIComponent(id)}/team`, { user, dailyRate }),
  documents: (id: string) =>
    api.get<{ types: { code: string; label: string }[]; canManage: boolean; internal?: boolean; documents: Doc[] }>(`/projects/${encodeURIComponent(id)}/documents`),
  updateDoc: (id: string, doc: string, body: Record<string, unknown>) =>
    api.patch<Doc>(`/projects/${encodeURIComponent(id)}/documents/${encodeURIComponent(doc)}`, body),
  deleteDoc: (id: string, doc: string) => api.delete<void>(`/projects/${encodeURIComponent(id)}/documents/${encodeURIComponent(doc)}`),
};

function readCookie(name: string) {
  return document.cookie.split("; ").find((c) => c.startsWith(`${name}=`))?.split("=")[1];
}

/** Dépôt d'un fichier (multipart) : le client JSON de l'application ne gère pas les fichiers. */
async function uploadDoc(id: string, form: FormData): Promise<Doc> {
  if (!readCookie("csrftoken")) await fetch(`${API_BASE}/auth/csrf`, { credentials: "same-origin" });
  const r = await fetch(`${API_BASE}/projects/${encodeURIComponent(id)}/documents`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRFToken": decodeURIComponent(readCookie("csrftoken") ?? "") },
    body: form,
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(r.status, body);
  return body as Doc;
}

const money = (v: string | number | null | undefined) =>
  v === null || v === undefined || v === "" ? "—" : Number(v).toLocaleString("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const fileSize = (n: number | null) => (n === null ? "—" : n > 1048576 ? `${(n / 1048576).toFixed(1)} Mo` : `${Math.max(1, Math.round(n / 1024))} Ko`);

const frDate = (iso: string | null) => (iso ? new Date(`${iso}T00:00:00`).toLocaleDateString("fr-FR") : "—");
const initials = (name: string) => name.split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase();

function selectedId() {
  const [, id] = window.location.hash.replace("#", "").split("/");
  return id ? decodeURIComponent(id) : null;
}
const wantsConfig = () => window.location.hash.replace("#", "").split("/")[2] === "config";
const wantsAi = () => window.location.hash.replace("#", "").split("/")[2] === "ia";
type AiState = { allowed: boolean; mode?: string; persona?: string; projects: Record<string, { pending: number; urgent: number; lastReview: string | null; actions: number }> };

export function ProjectsPage({ me }: { me: Me }) {
  const [id, setId] = useState<string | null>(selectedId);
  const [sub, setSub] = useState(() => window.location.hash.replace("#", "").split("/")[2] ?? "");
  useEffect(() => {
    const onHash = () => (setId(selectedId()), setSub(window.location.hash.replace("#", "").split("/")[2] ?? ""));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  if (id === "reporting") return <PortfolioPage me={me} />;
  if (id === "charge") return (
    <div className="page">
      <div><a className="lnk" href="#projets">← Mes projets</a></div>
      <PageHead eyebrow={me.tenant?.name ?? ""} title="Charge de l’équipe"
        sub="Charge de chaque membre de vos projets, cumulée sur tous les projets de l’entreprise, semaine par semaine. Cliquez sur une personne pour voir la répartition par projet." />
      <TeamWorkload />
    </div>
  );
  return id ? <ProjectDetail me={me} id={id} sub={sub} /> : <ProjectList me={me} />;
}

function PortfolioPage({ me }: { me: Me }) {
  const list = useApi(projectsApi.list);
  return (
    <div className="page">
      <div className="no-print">
        <a className="lnk" href="#projets">← Mes projets</a>
      </div>
      <PageHead eyebrow={me.tenant?.name ?? ""} title="Reporting projets"
        sub="Comparez le planning macro de plusieurs projets : avancement réel / prévu, actions en retard, actions en cours et phases clés. Export PDF ou image." />
      {list.error ? <ErrorNotice error={list.error} onRetry={list.reload} /> : !list.data ? <Loading /> : <PortfolioReporting projects={list.data} />}
    </div>
  );
}

function ProjectList({ me }: { me: Me }) {
  const list = useApi(projectsApi.list);
  const [ai, setAi] = useState<AiState | null>(null);
  const [cmp, setCmp] = useState<string[]>(readCompare);
  const [pf, setPf] = useState<"open" | "closed" | "all">(() => {
    try { const v = localStorage.getItem(PJ_FILTER_KEY); return v === "closed" || v === "all" ? v : "open"; } catch { return "open"; }
  });
  const choosePf = (v: "open" | "closed" | "all") => { setPf(v); try { localStorage.setItem(PJ_FILTER_KEY, v); } catch { /* */ } };
  const [cf, setCf] = useState<string>(() => { try { return localStorage.getItem(PJ_CLIENT_KEY) ?? ""; } catch { return ""; } });
  const chooseCf = (v: string) => { setCf(v); try { localStorage.setItem(PJ_CLIENT_KEY, v); } catch { /* */ } };
  const [teamOf, setTeamOf] = useState<string | null>(null);
  const isClosed = (p: ProjectSummary) => p.status === "closed";
  const clients = [...new Map((list.data ?? []).filter((p) => p.client?.code).map((p) => [p.client.code, p.client.name])).entries()].sort((x, y) => x[1].localeCompare(y[1]));
  const byClient = (list.data ?? []).filter((p) => !cf || p.client?.code === cf);
  const shownProjects = byClient.filter((p) => (pf === "all" ? true : pf === "closed" ? isClosed(p) : !isClosed(p)));
  const toggleCmp = (id: string) => setCmp((c) => { const n = c.includes(id) ? c.filter((x) => x !== id) : [...c, id]; writeCompare(n); return n; });
  useEffect(() => {
    api.get<AiState>("/assistant/projects").then(setAi, () => setAi(null));
  }, []);
  if (list.error) return <ErrorNotice error={list.error} onRetry={list.reload} />;
  return (
    <div className="page">
      <PageHead eyebrow={me.tenant?.name ?? ""} title="Mes projets" sub="Les projets qui vous sont affectés. Ouvrez un projet pour gérer son équipe et ses tâches."
        right={<div className="btns"><a className="btn" href="#projets/charge">👥 Charge équipe</a><a className="btn" href="#projets/reporting">📊 Reporting projets</a></div>} />
      {me.excelImportEnabled && <ExcelImportCard />}
      {!list.data ? (
        <Loading />
      ) : list.data.length === 0 ? (
        <Card title="Aucun projet">
          <div className="empty">Aucun projet ne vous est affecté. Un administrateur peut vous affecter à un projet dans Paramétrage.</div>
        </Card>
      ) : (
        <>
        <div className="pj-filterbar">
          <div className="seg">
            {([["open", "En cours"], ["closed", "Clôturés"], ["all", "Tous"]] as const).map(([k, l]) => (
              <button key={k} type="button" className={pf === k ? "on" : ""} onClick={() => choosePf(k)}>
                {l} <em>{byClient.filter((p) => (k === "all" ? true : k === "closed" ? isClosed(p) : !isClosed(p))).length}</em>
              </button>
            ))}
          </div>
          {clients.length > 1 && (
            <label className="pj-client-filter">
              🏢
              <select className="inp" value={cf} aria-label="Filtrer par client" onChange={(e) => chooseCf(e.target.value)}>
                <option value="">Tous les clients ({clients.length})</option>
                {clients.map(([code, name]) => (
                  <option key={code} value={code}>{name} ({(list.data ?? []).filter((p) => p.client?.code === code).length})</option>
                ))}
              </select>
              {cf && <button type="button" className="btn ghost sm" onClick={() => chooseCf("")}>✕</button>}
            </label>
          )}
        </div>
        {teamOf && <TeamStructureDialog projectId={teamOf} onClose={() => setTeamOf(null)} />}
        {shownProjects.length === 0 && (
          <div className="empty">{cf && byClient.length === 0 ? "Aucun projet pour ce client." : pf === "closed" ? "Aucun projet clôturé." : "Aucun projet en cours. Affichez « Clôturés » ou « Tous » pour retrouver les autres."}</div>
        )}
        {cmp.filter((id) => list.data?.some((p) => p.id === id)).length > 0 && (
          <div className="pj-cmpbar">
            <span>☑ {cmp.filter((id) => list.data?.some((p) => p.id === id)).length} projet(s) coché(s)</span>
            <a className="btn primary sm" href="#projets/reporting">📊 Afficher / comparer dans le reporting</a>
            <button className="btn ghost sm" type="button" onClick={() => { setCmp([]); writeCompare([]); }}>Tout décocher</button>
          </div>
        )}
        <div className="pj-grid">
          {shownProjects.map((p) => (
            <a key={p.id} className={`card pj-card${isClosed(p) ? " closed" : ""}`} href={`#projets/${encodeURIComponent(p.id)}`}>
              <div className="pj-card-top">
                <label className="pj-cmp" title="Cocher pour afficher / comparer dans le reporting projets" onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" checked={cmp.includes(p.id)} onChange={() => toggleCmp(p.id)} onClick={(e) => e.stopPropagation()} />
                </label>
                <span className="mono pj-code">{p.code}</span>
                {p.method && <span className="pill nodot">{p.method}</span>}
                <button type="button" className="pj-team" title="Structure de l’équipe"
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); setTeamOf(p.id); }}>👥</button>
                {p.status && p.status !== "active" && <span className={`pill nodot pj-st-${p.status}`}>{p.status === "closed" ? "🔒 Clôturé" : "⏸ En pause"}</span>}
                {ai?.allowed && (
                  <button type="button" className={`pj-ai${ai.projects[p.id]?.urgent ? " urgent" : ""}`}
                    title={`${ai.persona ?? "Assistant IA"} · ${ai.mode === "auto" ? "automatique" : "semi-automatique"}${ai.projects[p.id]?.lastReview ? ` · dernière revue le ${new Date(ai.projects[p.id].lastReview as string).toLocaleDateString("fr-FR")}` : ""}`}
                    onClick={(e) => { e.preventDefault(); e.stopPropagation(); window.location.hash = `#projets/${encodeURIComponent(p.id)}/ia`; }}>
                    ✨ IA
                    {ai.projects[p.id]?.pending ? <span className="pj-ai-n">{ai.projects[p.id].pending}</span> : null}
                  </button>
                )}
              </div>
              <b>{p.name}</b>
              <small>{p.client.name}</small>
              <div className="bar" aria-label={`Avancement ${p.progress} %`}>
                <i style={{ width: `${p.progress}%` }} />
              </div>
              <span className="pj-open">Ouvrir →</span>
            </a>
          ))}
        </div>
        </>
      )}
    </div>
  );
}

function ProjectDetail({ me, id, sub }: { me: Me; id: string; sub: string }) {
  const ws = useApi(() => projectsApi.get(id), [id]);
  const [aiOn, setAiOn] = useState(false);
  useEffect(() => {
    void loadAssistant().then((a) => setAiOn(a.allowed));
  }, []);
  const [tab, setTab] = useState<"team" | "tasks" | "migration" | "docs" | "budget" | "info">("team");
  const [config, setConfig] = useState(wantsConfig);
  if (ws.error) return <ErrorNotice error={ws.error} onRetry={ws.reload} />;
  if (!ws.data) return <Loading />;
  const p = ws.data;
  if (sub === "orchestrateur") return <OrchestratorPage projectId={p.id} projectName={p.name} />;
  if (sub === "appel-ia") return <AiCallPage projectId={p.id} projectName={p.name} />;
  const set = (next?: Workspace) => next && ws.setData(next);
  const role = p.rights.isPm ? "Chef de projet" : p.rights.isTl ? "Tech Lead" : null;
  const canConfig = p.rights.canEditInfo || p.rights.canEditType;
  const versions = p.baseVersion || p.targetVersion ? ` (${p.baseVersion || "—"} → ${p.targetVersion || "—"})` : "";

  return (
    <div className="page">
      <div>
        <a className="lnk" href="#projets">
          ← Mes projets
        </a>
      </div>
      <div className="ph">
        <div>
          <div className="eyebrow">
            {p.code} · {p.client.name}
          </div>
          <h1 className="pj-title">
            {p.name}
            {p.status && p.status !== "active" && <span className={`pill nodot pj-st-${p.status}`}>{p.status === "closed" ? `🔒 Clôturé${p.closedAt ? ` le ${frDate(p.closedAt)}` : ""}` : "⏸ En pause"}</span>}
            <AssistantButton projectId={p.id} projectName={p.name} autoOpen={wantsAi()}
              onClose={() => wantsAi() && window.history.replaceState(null, "", `#projets/${encodeURIComponent(p.id)}`)} />
            {canConfig && (
              <button className="pj-gear" type="button" title="Paramètres du projet" aria-label="Paramètres du projet" onClick={() => setConfig(true)}>
                ⚙
              </button>
            )}
          </h1>
          <p>
            {[p.projectTypeLabel + versions, p.methodology.label || p.method, p.startDate || p.endDate ? `${frDate(p.startDate)} → ${frDate(p.endDate)}` : "", role ? `Vous êtes ${role}` : ""]
              .filter(Boolean)
              .join(" · ")}
          </p>
          {(p.natures?.length ?? 0) > 0 && (
            <div className="pj-natures">
              {p.natures!.map((c) => <span key={c} className="pj-nature on">{p.natureChoices?.find((n) => n.code === c)?.label ?? c}</span>)}
            </div>
          )}
          {(p.parent || (p.children?.length ?? 0) > 0 || (p.dependsOn?.length ?? 0) > 0 || (p.dependents?.length ?? 0) > 0) && (
            <div className="pj-links-rel">
              {p.parent && <span>🧬 Sous-projet de <a href={`#projets/${encodeURIComponent(p.parent.id)}`}>{p.parent.name}</a></span>}
              {(p.children?.length ?? 0) > 0 && <span>🌿 Sous-projets : {p.children!.map((c, i) => <Fragment key={c.id}>{i ? ", " : ""}<a href={`#projets/${encodeURIComponent(c.id)}`}>{c.name}</a></Fragment>)}</span>}
              {(p.dependsOn?.length ?? 0) > 0 && <span>⛓ Dépend de : {p.dependsOn!.map((c, i) => <Fragment key={c.id}>{i ? ", " : ""}<a href={`#projets/${encodeURIComponent(c.id)}`}>{c.name}</a>{c.progress != null ? ` (${c.progress} %)` : ""}</Fragment>)}</span>}
              {(p.dependents?.length ?? 0) > 0 && <span>↪ Prérequis pour : {p.dependents!.map((c, i) => <Fragment key={c.id}>{i ? ", " : ""}<a href={`#projets/${encodeURIComponent(c.id)}`}>{c.name}</a></Fragment>)}</span>}
            </div>
          )}
        </div>
        <div className="pj-head-r">
          <div className="btns">
            {aiOn && (
              <a className="orc-btn" href={`#projets/${encodeURIComponent(p.id)}/orchestrateur`} title="Équipe d’assistants IA, circuits de validation et fil des échanges">
                🎼 Orchestrateur IA
              </a>
            )}
            {aiOn && (
              <a className="orc-btn ac-call-btn" href={`#projets/${encodeURIComponent(p.id)}/appel-ia`} title="Appel audio ou vidéo avec les assistants IA : ils rédigent la documentation en direct">
                📞 Appel IA
              </a>
            )}
            <button className="btn sm" type="button" title="Envoyer l’état d’avancement du projet par e-mail"
              onClick={() => { writeCompare([p.id]); try { sessionStorage.setItem("pct-open-mail", "1"); } catch { /* */ } window.location.hash = "#projets/reporting"; }}>
              ✉️ Envoyer par e-mail
            </button>
            <TeamStructureButton projectId={p.id} />
            <AlertButton projectId={p.id} actions={p.tasks.filter((t) => t.status !== "done").map((t) => ({ id: t.id, title: t.title }))} />
          </div>
          <MethodLinks p={p} />
        </div>
      </div>
      {config && canConfig && (
        <ProjectSettings
          p={p}
          canDelete={p.rights.isPm || me.isAdmin}
          onClose={() => {
            setConfig(false);
            if (wantsConfig()) window.history.replaceState(null, "", `#projets/${encodeURIComponent(p.id)}`);
          }}
          onSaved={(w) => {
            set(w);
            setConfig(false);
          }}
        />
      )}
      <div className="kpis pj-kpis">
        <div className="kpi">
          <label>Équipe</label>
          <strong>{p.team.length}</strong>
          <small>personne{p.team.length > 1 ? "s" : ""}</small>
        </div>
        <div className="kpi">
          <label>Tâches ouvertes</label>
          <strong>{p.tasks.filter((t) => t.status !== "done").length}</strong>
          <small>{p.tasks.filter((t) => !t.owner && t.status !== "done").length} non affectée(s)</small>
        </div>
        <div className={`kpi${p.counts.blocked ? " crit" : ""}`}>
          <label>Bloquées</label>
          <strong>{p.counts.blocked ?? 0}</strong>
          <small>à débloquer</small>
        </div>
        <div className="kpi ok">
          <label>Terminées</label>
          <strong>{p.counts.done ?? 0}</strong>
          <small>sur {p.tasks.length}</small>
        </div>
      </div>
      <UserAlertsStrip projectId={p.id} />
      <div className="tabs" role="tablist">
        {(
          [
            ["team", `Équipe (${p.team.length})`],
            ["tasks", `Actions (${p.tasks.length})`],
            ...(p.projectType === "migration" ? ([["migration", `🔁 Migration${p.instances?.length ? ` (${p.instances.length})` : ""}`]] as const) : []),
            ["docs", "Documents"],
            ...(p.rights.canSeeMoney ? ([["budget", "Budget"]] as const) : []),
            ["info", "Informations"],
          ] as [typeof tab, string][]
        ).map(([k, label]) => (
          <button key={k} type="button" role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>
            {label}
          </button>
        ))}
      </div>
      {tab === "team" && <TeamTab me={me} p={p} onChange={set} />}
      {tab === "tasks" && <TasksTab p={p} me={me} onChange={set} />}
      {tab === "docs" && <DocsTab p={p} />}
      {tab === "budget" && p.rights.canSeeMoney && <BudgetTab p={p} onChange={set} />}
      {tab === "info" && <InfoTab p={p} onChange={set} />}
      {tab === "info" && <WeeklyRecapCard projectId={p.id} />}
      {tab === "migration" && p.projectType === "migration" && <MigrationTab projectId={p.id} tasks={p.tasks} onTasksChanged={ws.reload} />}
    </div>
  );
}

function TeamTab({ me, p, onChange }: { me: Me; p: Workspace; onChange: (w?: Workspace) => void }) {
  const { run, busy } = useAction();
  const [user, setUser] = useState("");
  const [canEdit, setCanEdit] = useState(false);
  const add = () =>
    run(() => projectsApi.addMember(p.id, Number(user), canEdit), "Ressource affectée au projet").then((w) => {
      onChange(w);
      setUser("");
      setCanEdit(false);
    }, () => undefined);
  const remove = (m: Member) =>
    run(() => projectsApi.removeMember(p.id, m.id), `${m.name} retiré(e) du projet`).then(onChange, () => undefined);
  const [replace, setReplace] = useState<Member | null>(null);
  const canReplace = p.rights.isPm || p.rights.isTl || me.isAdmin;
  const toggleEdit = (m: Member) =>
    run(() => projectsApi.addMember(p.id, m.id, !m.canEdit), "Accès mis à jour").then(onChange, () => undefined);

  return (
    <Card
      title="Équipe du projet"
      sub={p.rights.canManageTeam ? "Affectez les ressources : elles verront le projet et pourront recevoir des tâches." : "Membres affectés au projet."}
    >
      {p.rights.canManageTeam && (
        <div className="pj-add">
          <Field id="pj-user" label="Ajouter une ressource">
            <select id="pj-user" className="inp" value={user} onChange={(e) => setUser(e.target.value)}>
              <option value="">{p.candidates?.length ? "Choisir un collaborateur…" : "Tous les collaborateurs sont déjà affectés"}</option>
              {p.candidates?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} · {c.role}
                </option>
              ))}
            </select>
          </Field>
          <label className="pj-check">
            <input type="checkbox" checked={canEdit} onChange={(e) => setCanEdit(e.target.checked)} /> Peut modifier le projet
          </label>
          <button className="btn primary" type="button" disabled={busy || !user} onClick={add}>
            Affecter
          </button>
        </div>
      )}
      {p.team.length === 0 ? (
        <div className="empty">Personne n’est encore affecté à ce projet.</div>
      ) : (
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>Personne</th>
                <th>Profil</th>
                <th>Rôle sur le projet</th>
                <th className="r">Tâches ouvertes</th>
                {p.rights.canSeeMoney && <th className="r">TJM (€)</th>}
                <th>Accès</th>
                {p.rights.canManageTeam && <th />}
              </tr>
            </thead>
            <tbody>
              {p.team.map((m) => (
                <tr key={m.id}>
                  <td>
                    <span className="pj-person">
                      <span className="av sm" style={{ background: "var(--av1)" }}>
                        {initials(m.name)}
                      </span>
                      {m.name}
                      {m.id === me.id && <span className="faint"> (vous)</span>}
                    </span>
                  </td>
                  <td className="muted">{m.role}</td>
                  <td>
                    {m.isPm && <span className="pill acc nodot">Chef de projet</span>}
                    {m.isTl && <span className="pill info nodot">Tech Lead</span>}
                    {!m.isPm && !m.isTl && <span className="faint">Membre</span>}
                  </td>
                  <td className="r">{m.openTasks}{canReplace && m.openTasks > 0 && (
                    <button className="btn ghost sm" type="button" style={{ marginLeft: 6 }} title="Confier ses actions à un remplaçant (absence)" onClick={() => setReplace(m)}>🔁 Remplacer</button>
                  )}</td>
                  {p.rights.canSeeMoney && (
                    <td className="r">
                      <input
                        className="inp num pj-rate"
                        type="number"
                        min={0}
                        step={10}
                        placeholder="—"
                        aria-label={`TJM de ${m.name}`}
                        defaultValue={m.dailyRate ? Number(m.dailyRate) : ""}
                        disabled={busy}
                        onBlur={(e) => {
                          const v = e.target.value === "" ? null : Number(e.target.value);
                          if (v !== (m.dailyRate ? Number(m.dailyRate) : null))
                            run(() => projectsApi.setRate(p.id, m.id, v), "TJM enregistré").then(onChange, () => undefined);
                        }}
                      />
                    </td>
                  )}
                  <td>
                    {p.rights.canManageTeam && !m.isPm && !m.isTl ? (
                      <button className="btn ghost sm" type="button" disabled={busy} onClick={() => toggleEdit(m)} title="Changer l’accès">
                        {m.canEdit ? "Écriture" : "Lecture"}
                      </button>
                    ) : (
                      <span className="muted">{m.canEdit ? "Écriture" : "Lecture"}</span>
                    )}
                  </td>
                  {p.rights.canManageTeam && (
                    <td className="r">
                      {!m.isPm && !m.isTl && (
                        <button className="btn ghost sm" type="button" disabled={busy} onClick={() => remove(m)}>
                          Retirer
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {replace && <ReassignDialog p={p} from={replace} onClose={() => setReplace(null)} onDone={onChange} />}
    </Card>
  );
}

/** Remplacement : le CP, le TL ou l'admin confie une, plusieurs ou toutes les actions ouvertes d'une personne à un remplaçant. */
function ReassignDialog({ p, from, onClose, onDone }: { p: Workspace; from: Member; onClose: () => void; onDone: (w?: Workspace) => void }) {
  const { run, busy } = useAction();
  const open = p.tasks.filter((t) => t.owner?.id === from.id && t.status !== "done");
  const [to, setTo] = useState("");
  const [sel, setSel] = useState<string[]>(open.map((t) => t.id));
  const go = () => run(() => api.post<Workspace & { moved: number }>(`/projects/${encodeURIComponent(p.id)}/tasks-reassign`, { from: from.id, to: Number(to), tasks: sel }),
    `${sel.length} action(s) confiée(s) au remplaçant`).then((w) => { onDone(w); onClose(); }, () => undefined);
  return (
    <div className="scrim" onClick={onClose}>
      <div className="modal" role="dialog" aria-label="Confier les actions à un remplaçant" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 560 }}>
        <div className="modal-h"><h3>🔁 Remplacer {from.name}</h3><button className="icon-btn" type="button" aria-label="Fermer" onClick={onClose}>✕</button></div>
        <div className="modal-b" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {open.length === 0 ? <p className="muted">{from.name} n’a aucune action ouverte sur ce projet.</p> : (<>
            <label>Remplaçant
              <select className="inp" value={to} onChange={(e) => setTo(e.target.value)}>
                <option value="">Choisir un membre de l’équipe…</option>
                {p.team.filter((m) => m.id !== from.id).map((m) => <option key={m.id} value={m.id}>{m.name} — {m.openTasks} action(s) ouverte(s)</option>)}
              </select>
            </label>
            <label style={{ display: "flex", gap: 8, alignItems: "center", fontWeight: 700 }}>
              <input type="checkbox" checked={sel.length === open.length} onChange={(e) => setSel(e.target.checked ? open.map((t) => t.id) : [])} /> Toutes ses actions ouvertes ({open.length})
            </label>
            <div style={{ maxHeight: 260, overflowY: "auto", display: "flex", flexDirection: "column", gap: 4, paddingLeft: 6 }}>
              {open.map((t) => (
                <label key={t.id} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
                  <input type="checkbox" checked={sel.includes(t.id)} onChange={(e) => setSel(e.target.checked ? [...sel, t.id] : sel.filter((x) => x !== t.id))} />
                  <span className="mono faint">{t.id}</span> {t.title}{t.due ? <small className="muted"> · {frDate(t.due)}</small> : null}
                </label>
              ))}
            </div>
            <small className="muted">Le remplaçant et {from.name} sont prévenus ; chaque action garde la trace du remplacement.</small>
          </>)}
        </div>
        <div className="modal-f" style={{ display: "flex", gap: 8, justifyContent: "flex-end", padding: "12px 16px" }}>
          <button className="btn" type="button" onClick={onClose}>Annuler</button>
          <button className="btn primary" type="button" disabled={busy || !to || sel.length === 0} onClick={go}>Confier {sel.length} action(s)</button>
        </div>
      </div>
    </div>
  );
}

function TasksTab({ p, me, onChange }: { p: Workspace; me: Me; onChange: (w?: Workspace) => void }) {
  const { run, busy } = useAction();
  const edit = p.rights.canManageTasks;
  const canCreate = edit || !!p.rights.canCreateTasks;
  const my = useMyTask<Workspace>(p.id, onChange);
  const [dialog, setDialog] = useState<{ task: Task; mode: "done" | "extend" } | null>(null);
  const [layout, setLayoutState] = useState<"list" | "board">(() => { try { return localStorage.getItem("pct-tasks-layout") === "board" ? "board" : "list"; } catch { return "list"; } });
  const setLayout = (l: "list" | "board") => { setLayoutState(l); try { localStorage.setItem("pct-tasks-layout", l); } catch { /* */ } };
  const today = new Date().toISOString().slice(0, 10);
  const isLate = (t: Task) => !!t.due && t.status !== "done" && t.due < today;

  // Filtres (barre compacte)
  const [q, setQ] = useState("");
  const [view, setView] = useState<"mine" | "open" | "late" | "unassigned" | "all">(() => (p.rights.canManageTasks ? "open" : "mine"));
  const [st, setSt] = useState("");
  const [stage, setStage] = useState("");
  const [inst, setInst] = useState("");
  const [owner, setOwner] = useState("");
  const [depOnly, setDepOnly] = useState(false);
  const [group, setGroup] = useState<"status" | "phase" | "owner" | "none">(() => {
    try { const g = localStorage.getItem("pct-tasks-group"); return g === "phase" || g === "owner" || g === "none" ? g : "status"; } catch { return "status"; }
  });
  const chooseGroup = (g: typeof group) => { setGroup(g); try { localStorage.setItem("pct-tasks-group", g); } catch { /* */ } };
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ title: "", owner: "", due: "", est: "", phase: "", instance: "", type: "", ticket: "", extOwner: "", incidentDate: "" });
  const [menu, setMenu] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [discuss, setDiscuss] = useState<Task | null>(null);
  const [alertOn, setAlertOn] = useState<Task | null>(null);
  const [editing, setEditing] = useState<Task | null>(null);

  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [menu]);

  const stages = [...new Set([...p.phases, ...p.tasks.map((t) => t.phase).filter(Boolean)])];
  const counts = {
    mine: p.tasks.filter((t) => t.owner?.id === me.id && t.status !== "done").length,
    open: p.tasks.filter((t) => t.status !== "done").length,
    late: p.tasks.filter(isLate).length,
    unassigned: p.tasks.filter((t) => !t.owner && t.status !== "done").length,
    blocked: p.tasks.filter((t) => t.status === "blocked").length,
    done: p.tasks.filter((t) => t.status === "done").length,
    all: p.tasks.length,
  };
  const needle = q.trim().toLowerCase();
  const tasks = p.tasks
    .filter((t) => (st ? t.status === st : view === "mine" ? t.owner?.id === me.id && t.status !== "done" : view === "all" ? true : view === "late" ? isLate(t) : view === "unassigned" ? !t.owner && t.status !== "done" : t.status !== "done"))
    .filter((t) => (!stage ? true : stage === "__none" ? !t.phase : t.phase === stage))
    .filter((t) => (!inst ? true : inst === "__global" ? !t.instance : String(t.instance?.id) === inst))
    .filter((t) => (!owner ? true : owner === "__none" ? !t.owner : String(t.owner?.id) === owner))
    .filter((t) => !depOnly || (t.dependsOn?.length ?? 0) + (t.successors?.length ?? 0) > 0)
    .filter((t) => !needle || `${t.title} ${t.id} ${t.owner?.name ?? ""} ${t.phase}`.toLowerCase().includes(needle))
    .sort((a, b) => (a.due ?? "9999").localeCompare(b.due ?? "9999") || a.id.localeCompare(b.id, undefined, { numeric: true }));
  const activeFilters = [st, stage, inst, owner, depOnly ? "x" : "", needle].filter(Boolean).length;
  const reset = () => { setSt(""); setStage(""); setInst(""); setOwner(""); setDepOnly(false); setQ(""); };

  // Regroupement
  const statusOrder = p.statuses.map((s) => s.code);
  const groups: { key: string; label: string; items: Task[] }[] = [];
  if (group === "none") groups.push({ key: "all", label: "", items: tasks });
  else {
    const map = new Map<string, Task[]>();
    tasks.forEach((t) => {
      const k = group === "status" ? t.status : group === "phase" ? t.phase || "__none" : t.owner ? String(t.owner.id) : "__none";
      map.set(k, [...(map.get(k) ?? []), t]);
    });
    const keys = [...map.keys()].sort((a, b) =>
      group === "status" ? statusOrder.indexOf(a) - statusOrder.indexOf(b) : a === "__none" ? 1 : b === "__none" ? -1 : a.localeCompare(b));
    keys.forEach((k) => groups.push({
      key: k, items: map.get(k)!,
      label: group === "status" ? p.statuses.find((s) => s.code === k)?.label ?? k
        : group === "phase" ? (k === "__none" ? "Sans étape" : k)
        : k === "__none" ? "Non affectées" : p.team.find((m) => String(m.id) === k)?.name ?? map.get(k)![0].owner?.name ?? "—",
    }));
  }

  const add = () =>
    run(() => projectsApi.addTask(p.id, {
      title: form.title, owner: form.owner ? Number(form.owner) : null, due: form.due, est: form.est || 0, phase: form.phase,
      ...(form.instance ? { instance: Number(form.instance) } : {}),
      ...(form.type === "infra" ? { type: "infra", ticket: form.ticket, extOwner: form.extOwner, incidentDate: form.incidentDate || null } : {}),
    }), "Action créée").then((w) => {
      onChange(w);
      setForm({ title: "", owner: "", due: "", est: "", phase: form.phase, instance: form.instance, type: form.type, ticket: "", extOwner: "", incidentDate: "" });
    }, () => undefined);
  const patch = (t: Task, body: Record<string, unknown>) => run(() => projectsApi.updateTask(p.id, t.id, body)).then(onChange, () => undefined);
  const dueLabel = (t: Task) => {
    if (!t.due) return { text: "Sans échéance", cls: "none" };
    const days = Math.round((new Date(`${t.due}T00:00:00`).getTime() - new Date(`${today}T00:00:00`).getTime()) / 86400000);
    if (t.status === "done") return { text: frDate(t.due), cls: "done" };
    if (days < 0) return { text: `${frDate(t.due)} · ${-days} j de retard`, cls: "late" };
    if (days === 0) return { text: "Aujourd’hui", cls: "soon" };
    if (days <= 3) return { text: `${frDate(t.due)} · dans ${days} j`, cls: "soon" };
    return { text: frDate(t.due), cls: "" };
  };
  const initials = (n: string) => n.split(/\s+/).map((x) => x[0]).join("").slice(0, 2).toUpperCase();

  return (
    <Card
      title="Actions"
      sub={`${counts.open} ouverte(s) · ${counts.done} terminée(s)${counts.late ? ` · ${counts.late} en retard` : ""}`}
      extra={canCreate ? <button className="btn primary sm" type="button" onClick={() => setAdding(!adding)}>{adding ? "Fermer" : "+ Nouvelle action"}</button> : undefined}
    >
      {adding && canCreate && (
        <div className="ta-add">
          <input className="inp ta-add-title" maxLength={300} autoFocus placeholder="Titre de l’action — Entrée pour créer" value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })} onKeyDown={(e) => { if (e.key === "Enter" && form.title.trim()) add(); }} />
          <select className="inp" aria-label="Type de tâche" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
            <option value="">Tâche projet</option>
            <option value="infra">🛠 Infra / autre équipe</option>
          </select>
          {form.type === "infra" && (<>
            <input className="inp" placeholder="N° de ticket" aria-label="Numéro de ticket" maxLength={60} value={form.ticket} onChange={(e) => setForm({ ...form, ticket: e.target.value })} />
            <input className="inp" placeholder="Personne ou groupe en charge *" aria-label="Personne ou groupe en charge" maxLength={120} value={form.extOwner} onChange={(e) => setForm({ ...form, extOwner: e.target.value })} />
            <input className="inp" type="date" title="Date de l’incident ou de la demande" aria-label="Date de l'incident ou de la demande" value={form.incidentDate} onChange={(e) => setForm({ ...form, incidentDate: e.target.value })} />
          </>)}
          <select className="inp" aria-label="Responsable" value={form.owner} onChange={(e) => setForm({ ...form, owner: e.target.value })}>
            <option value="">Non affectée</option>
            {p.team.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
          {stages.length > 0 && (
            <select className="inp" aria-label="Étape" value={form.phase} onChange={(e) => setForm({ ...form, phase: e.target.value })}>
              <option value="">Étape —</option>
              {stages.map((ph) => <option key={ph} value={ph}>{ph}</option>)}
            </select>
          )}
          {(p.instances?.length ?? 0) > 0 && (
            <select className="inp" aria-label="Portée" value={form.instance} onChange={(e) => setForm({ ...form, instance: e.target.value })}>
              <option value="">Globale</option>
              {p.instances!.map((x) => <option key={x.id} value={x.id}>{x.isPilot ? "⭐ " : ""}{x.name}</option>)}
            </select>
          )}
          <input className="inp" type="date" aria-label="Échéance" value={form.due} onChange={(e) => setForm({ ...form, due: e.target.value })} />
          <input className="inp num ta-est" type="number" min={0} step={0.5} placeholder="Charge (h)" aria-label="Charge" value={form.est} onChange={(e) => setForm({ ...form, est: e.target.value })} />
          <button className="btn primary" type="button" disabled={busy || !form.title.trim() || (form.type === "infra" && !form.extOwner.trim() && !form.owner)} onClick={add}>Créer</button>
        </div>
      )}

      <div className="ta-views">
        {([["mine", "🙋 Mes actions", counts.mine], ["open", "Ouvertes", counts.open], ["late", "En retard", counts.late], ["unassigned", "Non affectées", counts.unassigned], ["all", "Toutes", counts.all]] as const).map(([k, l, n]) => (
          <button key={k} type="button" className={`ta-view${view === k && !st ? " on" : ""}${k === "late" && n ? " crit" : ""}`} onClick={() => { setView(k); setSt(""); }}>
            {l}<em>{n}</em>
          </button>
        ))}
        <span className="ta-spacer" />
        <div className="seg" role="tablist" aria-label="Affichage des actions">
          <button type="button" role="tab" aria-selected={layout === "list"} className={layout === "list" ? "on" : ""} onClick={() => setLayout("list")}>☰ Liste</button>
          <button type="button" role="tab" aria-selected={layout === "board"} className={layout === "board" ? "on" : ""} onClick={() => setLayout("board")}>▦ Tableau</button>
        </div>
      </div>
      {dialog && <MyTaskDialog task={dialog.task} mode={dialog.mode} onClose={() => setDialog(null)}
        onDone={(d, sp) => { if (edit) patch(dialog.task, { status: "done", doneAt: d, spent: sp }); else void my.status(dialog.task, "done", d, sp); setDialog(null); }}
        onExtend={(due, reason) => { void my.extend(dialog.task, due, reason); setDialog(null); }} />}
      {layout === "board" && <TaskBoard<Workspace> p={p} meId={me.id} canManage={edit} onChange={onChange} onOpen={(id) => setOpenId(id)} patch={(t, body) => patch(t as Task, body)} />}

      <div className="ta-toolbar">
        <input className="inp ta-search" placeholder="🔍 Rechercher une action, une référence, un responsable…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select className={`inp ta-f${st ? " on" : ""}`} aria-label="Statut" value={st} onChange={(e) => setSt(e.target.value)}>
          <option value="">Tous les statuts</option>
          {p.statuses.map((x) => <option key={x.code} value={x.code}>{x.label} ({p.tasks.filter((t) => t.status === x.code).length})</option>)}
        </select>
        {stages.length > 0 && (
          <select className={`inp ta-f${stage ? " on" : ""}`} aria-label="Étape" value={stage} onChange={(e) => setStage(e.target.value)}>
            <option value="">Toutes les étapes</option>
            {stages.map((x) => <option key={x} value={x}>{x}</option>)}
            <option value="__none">Sans étape</option>
          </select>
        )}
        <select className={`inp ta-f${owner ? " on" : ""}`} aria-label="Responsable" value={owner} onChange={(e) => setOwner(e.target.value)}>
          <option value="">Tous les responsables</option>
          {p.team.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          <option value="__none">Non affectées</option>
        </select>
        {(p.instances?.length ?? 0) > 0 && (
          <select className={`inp ta-f${inst ? " on" : ""}`} aria-label="Instance" value={inst} onChange={(e) => setInst(e.target.value)}>
            <option value="">Toutes les instances</option>
            <option value="__global">🌐 Globales</option>
            {p.instances!.map((x) => <option key={x.id} value={x.id}>{x.isPilot ? "⭐ " : ""}{x.name}</option>)}
          </select>
        )}
        <label className="ta-check"><input type="checkbox" checked={depOnly} onChange={(e) => setDepOnly(e.target.checked)} /> Avec dépendances</label>
        <span className="ta-spacer" />
        <label className="ta-group">Grouper par
          <select className="inp" value={group} onChange={(e) => chooseGroup(e.target.value as typeof group)}>
            <option value="status">Statut</option>
            <option value="phase">Étape</option>
            <option value="owner">Responsable</option>
            <option value="none">Aucun</option>
          </select>
        </label>
      </div>
      {activeFilters > 0 && (
        <div className="ta-active">{tasks.length} action(s) affichée(s) · {activeFilters} filtre(s) actif(s) <button className="btn ghost sm" type="button" onClick={reset}>Effacer les filtres</button></div>
      )}

      {discuss && <DiscussDialog p={p} task={discuss} onClose={() => setDiscuss(null)} />}
      {editing && <TaskEditDialog p={p} task={editing} onClose={() => setEditing(null)} onSaved={(w) => { onChange(w); setEditing(null); }} />}
      {alertOn && <AlertDialog projectId={p.id} action={{ id: alertOn.id, title: alertOn.title }} onClose={() => setAlertOn(null)} />}
      {openId && (
        <ActionDrawer p={p} taskId={openId} canEdit={edit} meId={me.id} onChanged={(w) => onChange(w)} onClose={() => setOpenId(null)}
          onDiscuss={(t) => { setOpenId(null); setDiscuss(p.tasks.find((x) => x.id === t.id) ?? null); }}
          onAlert={(t) => { setOpenId(null); setAlertOn(p.tasks.find((x) => x.id === t.id) ?? null); }}
          onDelete={(t) => { if (window.confirm(`Supprimer définitivement l’action « ${t.title} » (${t.id}) ?`)) run(() => projectsApi.deleteTask(p.id, t.id), "Action supprimée").then((w) => { onChange(w); setOpenId(null); }, () => undefined); }} />
      )}

      {layout === "board" ? null : tasks.length === 0 ? (
        <div className="empty">{view === "mine" && p.tasks.length ? "Aucune action ouverte ne vous est affectée. Prenez une action « Non affectée » avec 🙋 M’affecter." : p.tasks.length ? "Aucune action ne correspond aux filtres." : "Aucune action pour l’instant."}</div>
      ) : (
        <div className="ta-list">
          <div className="ta-head">
            <span>Action</span><span>Responsable</span><span>Échéance</span><span>Statut</span><span className="r">Charge</span><span />
          </div>
          {groups.map((g) => (
            <div key={g.key} className="ta-group-block">
              {group !== "none" && (
                <div className={`ta-gh${group === "status" ? ` st-${g.key}` : ""}`}>
                  {group === "status" && <i className={`ta-dot st-${g.key}`} />}
                  <b>{g.label}</b><em>{g.items.length}</em>
                </div>
              )}
              {g.items.map((t) => {
                const due = dueLabel(t);
                return (
                  <div key={t.id} className={`ta-row${isLate(t) ? " late" : ""}${t.status === "done" ? " done" : ""}`} onClick={() => setOpenId(t.id)} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter") setOpenId(t.id); }}>
                    <div className="ta-main">
                      <span className={`ta-dot st-${t.status}`} title={t.statusLabel} />
                      <div className="ta-txt">
                        <b title={t.title}>{t.title}</b>
                        <div className="ta-meta">
                          <span className="mono">{t.id}</span>
                          {t.phase && group !== "phase" && <span className="ta-tag">{t.phase}</span>}
                          {t.instance && <span className="ta-tag inst">🔁 {t.instance.name}</span>}
                          {(t.dependsOn?.length ?? 0) > 0 && (
                            <span className={`ta-tag ${t.blockedBy ? "warn" : ""}`} title={`Dépend de : ${t.dependsOn!.map((d) => `${d.title}${d.projectName ? ` (${d.projectName})` : ""}`).join(", ")}`}>
                              🔗 {t.blockedBy ? `attend ${t.blockedBy} action(s)` : `${t.dependsOn!.length} prérequis ✓`}
                            </span>
                          )}
                          {(t.successors?.length ?? 0) > 0 && <span className="ta-tag" title={`Bloque : ${t.successors!.map((d) => d.title).join(", ")}`}>↪ bloque {t.successors!.length}</span>}
                          {t.depConflict && <span className="ta-tag crit">⚠️ conflit de dates</span>}
                          {t.type === "infra" && <span className="ta-tag warn" title={`Date de l’incident / demande : ${t.incidentDate ? frDate(t.incidentDate) : "—"}`}>🛠 Infra{t.ticket ? ` · #${t.ticket}` : ""}{t.extOwner ? ` · ${t.extOwner}` : ""}</span>}
                          {t.us && <span className="ta-tag" title={t.us.title}>📘 {t.us.id}</span>}
                          {t.extension && <span className="ta-tag warn" title={t.extension.reason}>⏳ délai demandé → {frDate(t.extension.due)}</span>}
                          {t.status === "done" && t.doneAt && <span className="ta-tag">✅ réalisée le {frDate(t.doneAt)}</span>}
                        </div>
                      </div>
                    </div>
                    <div className="ta-owner" onClick={(e) => e.stopPropagation()}>
                      {edit ? (
                        <select className="ta-plain" value={t.owner?.id ?? ""} disabled={busy} aria-label="Responsable"
                          onChange={(e) => patch(t, { owner: e.target.value ? Number(e.target.value) : null })}>
                          <option value="">— Non affectée</option>
                          {p.team.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
                        </select>
                      ) : t.owner?.id !== me.id && t.status !== "done" ? (
                        <button type="button" className="btn sm" disabled={my.busy} title="Vous affecter cette action"
                          onClick={() => { if (!t.owner || window.confirm(`Cette action est affectée à ${t.owner.name}. Vous l’affecter ?`)) void my.claim(t); }}>🙋 M’affecter</button>
                      ) : null}

                      <span className={`ta-av${t.owner ? "" : " none"}`} aria-hidden="true">{t.owner ? initials(t.owner.name) : "?"}</span>
                      <span className="ta-oname">{t.owner?.name ?? (t.type === "infra" && t.extOwner ? `${t.extOwner} (externe)` : "Non affectée")}</span>
                    </div>
                    <div className={`ta-due ${due.cls}`}>{due.text}</div>
                    <div onClick={(e) => e.stopPropagation()}>
                      {edit ? (
                        <select className={`ta-status st-${t.status}`} value={t.status} disabled={busy} aria-label="Statut" onChange={(e) => (e.target.value === "done" ? setDialog({ task: t, mode: "done" }) : patch(t, { status: e.target.value }))}>
                          {p.statuses.map((s) => <option key={s.code} value={s.code}>{s.label}</option>)}
                        </select>
                      ) : t.owner?.id === me.id ? (
                        <select className={`ta-status st-${t.status}`} value={t.status} disabled={my.busy} aria-label="Statut de mon action"
                          onChange={(e) => (e.target.value === "done" ? setDialog({ task: t, mode: "done" }) : void my.status(t, e.target.value))}>
                          {p.statuses.map((s) => <option key={s.code} value={s.code}>{s.label}</option>)}
                        </select>
                      ) : (
                        <span className={`ta-status st-${t.status}`}>{t.statusLabel}</span>
                      )}
                    </div>
                    <div className="ta-est r">{t.est && Number(t.est) ? `${Number(t.est)} h` : "—"}</div>
                    <div className="ta-menu" onClick={(e) => e.stopPropagation()}>
                      <button className="ta-more" type="button" aria-label={`Actions sur ${t.title}`} onClick={(e) => { e.stopPropagation(); setMenu(menu === t.id ? null : t.id); }}>⋯</button>
                      {menu === t.id && (
                        <div className="ta-pop" role="menu">
                          <button type="button" onClick={() => { setMenu(null); setOpenId(t.id); }}>📝 Ouvrir la fiche</button>
                          {edit && <button type="button" onClick={() => { setMenu(null); setEditing(t); }}>✏️ Modifier (formulaire)</button>}
                          <button type="button" onClick={() => { setMenu(null); setDiscuss(t); }}>💬 Discuter</button>
                          <button type="button" onClick={() => { setMenu(null); setOpenId(t.id); }}>💬 Commenter</button>
                          {t.owner?.id === me.id && t.status !== "done" && <button type="button" onClick={() => { setMenu(null); setDialog({ task: t, mode: "extend" }); }}>⏳ Demander un délai</button>}
                          {!edit && t.owner?.id === me.id && t.status !== "done" && <button type="button" onClick={() => { setMenu(null); setDialog({ task: t, mode: "done" }); }}>✅ Marquer terminée</button>}
                          {edit && t.extension && <button type="button" onClick={() => { setMenu(null); void my.decide(t, "approved"); }}>✅ Accorder le délai ({frDate(t.extension.due)})</button>}
                          {edit && t.extension && <button type="button" onClick={() => { setMenu(null); const c = window.prompt("Motif du refus ?") ?? ""; if (c) void my.decide(t, "rejected", c); }}>✖ Refuser le délai</button>}
                          <button type="button" onClick={() => { setMenu(null); setAlertOn(t); }}>🚨 Lancer une alerte</button>
                          {edit && t.status !== "done" && <button type="button" onClick={() => { setMenu(null); setDialog({ task: t, mode: "done" }); }}>✅ Marquer terminée</button>}
                          {edit && (
                            <button type="button" className="danger" onClick={() => { setMenu(null); if (window.confirm(`Supprimer définitivement l’action « ${t.title} » (${t.id}) ?`)) run(() => projectsApi.deleteTask(p.id, t.id), "Action supprimée").then(onChange, () => undefined); }}>
                              🗑 Supprimer
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function InfoTab({ p, onChange }: { p: Workspace; onChange: (w?: Workspace) => void }) {
  const { run, busy } = useAction();
  const [form, setForm] = useState({ method: p.method, startDate: p.startDate ?? "", endDate: p.endDate ?? "", description: p.description });
  const [type, setType] = useState({ projectType: p.projectType, baseProject: p.baseProject?.id ?? "", baseVersion: p.baseVersion, targetVersion: p.targetVersion });
  const edit = p.rights.canEditInfo;
  const typeChanged = type.projectType !== p.projectType || type.baseProject !== (p.baseProject?.id ?? "") || type.baseVersion !== p.baseVersion || type.targetVersion !== p.targetVersion;
  return (
    <>
    <Card title="Type de projet" sub="Nouveau projet, évolution ou amélioration d’un projet existant. Modifiable par le client, le chef de projet ou un administrateur.">
      <div className="frow">
        <Field id="pt-type" label="Type">
          <select id="pt-type" className="inp" disabled={!p.rights.canEditType} value={type.projectType} onChange={(e) => setType({ ...type, projectType: e.target.value })}>
            {p.projectTypes.map((t) => (
              <option key={t.code} value={t.code}>
                {t.label}
              </option>
            ))}
          </select>
        </Field>
        {type.projectType !== "new" && (
          <>
            <Field id="pt-base" label="Projet existant concerné">
              <select id="pt-base" className="inp" disabled={!p.rights.canEditType} value={type.baseProject} onChange={(e) => setType({ ...type, baseProject: e.target.value })}>
                <option value="">{p.baseProject ? p.baseProject.name : "Non précisé"}</option>
                {(p.otherProjects ?? []).filter((o) => o.id !== p.baseProject?.id).map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.code} — {o.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field id="pt-version" label="Version source">
              <input id="pt-version" className="inp" maxLength={40} placeholder="Ex. v2.3" disabled={!p.rights.canEditType} value={type.baseVersion} onChange={(e) => setType({ ...type, baseVersion: e.target.value })} />
            </Field>
            <Field id="pt-target" label="Version cible">
              <input id="pt-target" className="inp" maxLength={40} placeholder="Ex. v3.0" disabled={!p.rights.canEditType} value={type.targetVersion} onChange={(e) => setType({ ...type, targetVersion: e.target.value })} />
            </Field>
          </>
        )}
      </div>
      {p.rights.canEditType && typeChanged && (
        <div className="btns" style={{ marginTop: 12, justifyContent: "flex-end" }}>
          <button className="btn primary" type="button" disabled={busy}
            onClick={() => run(() => projectsApi.update(p.id, { ...type, baseProject: type.baseProject || null }), "Type de projet enregistré").then(onChange, () => undefined)}>
            Enregistrer le type
          </button>
        </div>
      )}
    </Card>
    <Card title="Informations du projet" sub={edit ? "Le chef de projet peut ajuster le cadrage du projet." : undefined}>
      <div className="frow">
        <Field id="pi-client" label="Client">
          <input id="pi-client" className="inp" value={p.client.name} disabled />
        </Field>
        <Field id="pi-pm" label="Chef de projet">
          <input id="pi-pm" className="inp" value={p.pm?.name ?? "Non affecté"} disabled />
        </Field>
        <Field id="pi-tl" label="Tech Lead">
          <input id="pi-tl" className="inp" value={p.tl?.name ?? "Non affecté"} disabled />
        </Field>
      </div>
      <div className="frow">
        <Field id="pi-method" label="Méthode">
          <select id="pi-method" className="inp" disabled={!edit} value={form.method} onChange={(e) => setForm({ ...form, method: e.target.value })}>
            <option value="">Non précisée</option>
            {["Scrum", "Cycle en V", "Kanban", "Hybride", "Régie"].map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </Field>
        <Field id="pi-start" label="Début">
          <input id="pi-start" className="inp" type="date" disabled={!edit} value={form.startDate} onChange={(e) => setForm({ ...form, startDate: e.target.value })} />
        </Field>
        <Field id="pi-end" label="Fin">
          <input id="pi-end" className="inp" type="date" disabled={!edit} value={form.endDate} onChange={(e) => setForm({ ...form, endDate: e.target.value })} />
        </Field>
      </div>
      <Field id="pi-desc" label="Description">
        <textarea id="pi-desc" className="inp" rows={3} disabled={!edit} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
      </Field>
      {edit && (
        <div className="btns" style={{ marginTop: 12, justifyContent: "flex-end" }}>
          <button className="btn primary" type="button" disabled={busy} onClick={() => run(() => projectsApi.update(p.id, form), "Projet mis à jour").then(onChange, () => undefined)}>
            Enregistrer
          </button>
        </div>
      )}
      <p className="muted" style={{ fontSize: 12.5, marginTop: 12 }}>
        Le chef de projet et le Tech Lead se changent dans Paramétrage › Projets (administrateur).
      </p>
    </Card>
    </>
  );
}


/** Raccourcis adaptés à la méthodologie du projet (Scrum, Cycle en V, hybride…). */
function MethodLinks({ p }: { p: Workspace }) {
  const f = p.methodology.features;
  const go = (tab: string) => `#pilotage/${encodeURIComponent(p.id)}/${tab}`;
  const links: [string, string][] = [];
  if (f.includes("phases")) links.push([go("macro"), "Planning macro"]);
  if (f.includes("weekly")) links.push([go("goals"), "Objectifs de la semaine"]);
  if (f.includes("scrum")) links.push([go("backlog"), "Product Backlog"], [go("board"), "Sprint Board"]);
  if (f.includes("capacity")) links.push([go("capacity"), "Capacité"]);
  links.push([`#reporting/${encodeURIComponent(p.id)}`, "Reporting"]);
  return (
    <div className="pj-links">
      {links.map(([href, label]) => (
        <a key={href} className="btn sm" href={href}>
          {label}
        </a>
      ))}
    </div>
  );
}

function TaskEditDialog({ p, task, onClose, onSaved }: { p: Workspace; task: Task; onClose: () => void; onSaved: (w?: Workspace) => void }) {
  const { run, busy } = useAction();
  const [f, setF] = useState({
    title: task.title, owner: task.owner ? String(task.owner.id) : "", status: task.status, startDate: task.startDate ?? "",
    due: task.due ?? "", est: task.est ? String(Number(task.est)) : "", phase: task.phase, prio: task.prio,
    instance: task.instance ? String(task.instance.id) : "",
  });
  const [deps, setDeps] = useState<DepRef[]>(task.dependsOn ?? []);
  const [dq, setDq] = useState("");
  const [found, setFound] = useState<DepRef[]>([]);
  useEffect(() => {
    if (dq.trim().length < 2) {
      setFound([]);
      return;
    }
    const t = window.setTimeout(() => {
      api.get<DepRef[]>(`/actions-search?q=${encodeURIComponent(dq.trim())}`).then((r) => setFound(r.filter((x) => x.id !== task.id)), () => setFound([]));
    }, 300);
    return () => window.clearTimeout(t);
  }, [dq, task.id]);
  const save = () =>
    run(() => projectsApi.updateTask(p.id, task.id, {
      title: f.title, owner: f.owner ? Number(f.owner) : null, status: f.status, startDate: f.startDate || null, due: f.due || null,
      est: f.est === "" ? 0 : Number(f.est), phase: f.phase, prio: f.prio, dependsOn: deps.map((d) => d.id),
      ...((p.instances?.length ?? 0) > 0 ? { instance: f.instance ? Number(f.instance) : null } : {}),
    }), "Action modifiée").then(onSaved, () => undefined);
  return createPortal(
    <div className="scrim" onClick={onClose}>
      <div className="modal" role="dialog" aria-label="Modifier l’action" onClick={(e) => e.stopPropagation()}>
        <div className="modal-h">
          <h3>✏️ Modifier l’action {task.id}</h3>
          <button className="icon-btn" type="button" aria-label="Fermer" onClick={onClose}>✕</button>
        </div>
        <div className="modal-b" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Field id="te-title" label="Titre">
            <input id="te-title" className="inp" maxLength={300} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
          </Field>
          <div className="frow">
            <Field id="te-owner" label="Responsable">
              <select id="te-owner" className="inp" value={f.owner} onChange={(e) => setF({ ...f, owner: e.target.value })}>
                <option value="">Non affectée</option>
                {p.team.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
              </select>
            </Field>
            <Field id="te-status" label="Statut">
              <select id="te-status" className="inp" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>
                {p.statuses.map((x) => <option key={x.code} value={x.code}>{x.label}</option>)}
              </select>
            </Field>
          </div>
          <div className="frow">
            <Field id="te-start" label="Début">
              <input id="te-start" className="inp" type="date" value={f.startDate} onChange={(e) => setF({ ...f, startDate: e.target.value })} />
            </Field>
            <Field id="te-due" label="Échéance">
              <input id="te-due" className="inp" type="date" value={f.due} onChange={(e) => setF({ ...f, due: e.target.value })} />
            </Field>
            <Field id="te-est" label="Charge (h)">
              <input id="te-est" className="inp num" type="number" min={0} step={0.5} value={f.est} onChange={(e) => setF({ ...f, est: e.target.value })} />
            </Field>
          </div>
          <div className="frow">
            <Field id="te-phase" label="Étape / phase / lot">
              <input id="te-phase" className="inp" maxLength={60} value={f.phase} onChange={(e) => setF({ ...f, phase: e.target.value })} />
            </Field>
            {(p.instances?.length ?? 0) > 0 && (
              <Field id="te-inst" label="Portée (migration)">
                <select id="te-inst" className="inp" value={f.instance} onChange={(e) => setF({ ...f, instance: e.target.value })}>
                  <option value="">Globale au projet</option>
                  {p.instances!.map((x) => <option key={x.id} value={x.id}>{x.isPilot ? "⭐ " : ""}{x.name}</option>)}
                </select>
              </Field>
            )}
            <Field id="te-prio" label="Priorité">
              <select id="te-prio" className="inp" value={f.prio} onChange={(e) => setF({ ...f, prio: e.target.value })}>
                <option value="">—</option>
                {["Haute", "Moyenne", "Basse"].map((x) => <option key={x}>{x}</option>)}
              </select>
            </Field>
          </div>
          <div className="te-deps">
            <b>🔗 Dépend de (prédécesseurs)</b>
            <small className="faint">Cette action ne peut démarrer qu’après les actions ci-dessous — du même projet ou d’un autre projet.</small>
            {deps.length === 0 && <div className="faint" style={{ fontSize: 12.5 }}>Aucune dépendance.</div>}
            {deps.map((d) => (
              <span key={d.id} className="mr-chip">
                {d.status === "done" ? "✓ " : "⏳ "}{d.title}{d.projectName ? ` · ${d.projectName}` : ""}
                <button type="button" aria-label={`Retirer ${d.title}`} onClick={() => setDeps(deps.filter((x) => x.id !== d.id))}>×</button>
              </span>
            ))}
            <input className="inp" placeholder="Rechercher une action (titre, référence ou projet)…" value={dq} onChange={(e) => setDq(e.target.value)} />
            {found.length > 0 && (
              <ul className="te-found">
                {found.filter((x) => !deps.some((d) => d.id === x.id)).map((x) => (
                  <li key={x.id}>
                    <button type="button" onClick={() => { setDeps([...deps, x]); setDq(""); setFound([]); }}>
                      <b>{x.title}</b> <small>{x.id} · {x.projectName}{x.due ? ` · échéance ${new Date(x.due).toLocaleDateString("fr-FR")}` : ""} · {x.statusLabel}</small>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
        <div className="modal-f">
          <button className="btn ghost" type="button" onClick={onClose}>Annuler</button>
          <button className="btn primary" type="button" disabled={busy || !f.title.trim()} onClick={save}>Enregistrer</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function DiscussDialog({ p, task, onClose }: { p: Workspace; task: Task; onClose: () => void }) {
  const { run, busy } = useAction();
  const [title, setTitle] = useState(`Tâche ${task.id} · ${task.title}`.slice(0, 200));
  const [people, setPeople] = useState<number[]>(task.owner ? [task.owner.id] : []);
  const [message, setMessage] = useState("");
  const toggle = (id: number) => setPeople((l) => (l.includes(id) ? l.filter((x) => x !== id) : [...l, id]));
  const create = () =>
    run(
      () => discussionApi.create({ project: p.id, action: task.id, title, destination: "internal", participants: people, message }),
      "Discussion créée",
    ).then((d) => {
      if (d) window.location.hash = `#collaboration/${d.id}`;
    }, () => undefined);
  return (
    <div className="scrim" onClick={onClose}>
      <div className="modal" role="dialog" aria-label="Nouvelle discussion" onClick={(e) => e.stopPropagation()}>
        <div className="modal-h">
          <h3>Discussion sur la tâche</h3>
          <button className="icon-btn" type="button" aria-label="Fermer" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="modal-b" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Field id="dd-title" label="Sujet">
            <input id="dd-title" className="inp" maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <div>
            <div className="muted" style={{ fontSize: 12.5, marginBottom: 6 }}>Participants (membres de l’équipe)</div>
            <div className="ng-phases">
              {p.team.map((m) => (
                <label key={m.id} className={`chip-toggle${people.includes(m.id) ? " on" : ""}`}>
                  <input type="checkbox" checked={people.includes(m.id)} onChange={() => toggle(m.id)} />
                  {m.name}
                </label>
              ))}
            </div>
          </div>
          <Field id="dd-msg" label="Premier message">
            <textarea id="dd-msg" className="inp" rows={3} placeholder="Ex. Pouvez-vous préciser le besoin sur ce point ?" value={message} onChange={(e) => setMessage(e.target.value)} />
          </Field>
        </div>
        <div className="modal-f">
          <button className="btn ghost" type="button" onClick={onClose}>
            Annuler
          </button>
          <button className="btn primary" type="button" disabled={busy || !title.trim() || people.length === 0} onClick={create}>
            Créer la discussion
          </button>
        </div>
      </div>
    </div>
  );
}

/** OCR gratuit dans le navigateur (Tesseract.js, chargé à la demande) pour les images et scans. */
type TesseractLike = { recognize: (f: File, lang: string, o: { logger: (m: { status: string; progress: number }) => void }) => Promise<{ data: { text: string } }> };
let tesseract: Promise<TesseractLike> | null = null;
function loadTesseract(): Promise<TesseractLike> {
  tesseract ??= new Promise((resolve, reject) => {
    const w = window as unknown as { Tesseract?: TesseractLike };
    if (w.Tesseract) return resolve(w.Tesseract);
    const sc = document.createElement("script");
    sc.src = "https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js";
    sc.onload = () => (w.Tesseract ? resolve(w.Tesseract) : reject(new Error("OCR indisponible")));
    sc.onerror = () => reject(new Error("OCR indisponible (pas d’accès Internet ?)"));
    document.head.appendChild(sc);
  });
  return tesseract;
}

function DocsTab({ p }: { p: Workspace }) {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const docs = useApi(() => api.get<{ types: { code: string; label: string }[]; canManage: boolean; internal?: boolean; documents: Doc[] }>(
    `/projects/${encodeURIComponent(p.id)}/documents${query ? `?q=${encodeURIComponent(query)}` : ""}`), [p.id, query]);
  const { run, busy } = useAction();
  const [files, setFiles] = useState<File[]>([]);
  const [meta, setMeta] = useState({ type: "auto", title: "", description: "", clientVisible: false });
  const [minutes, setMinutes] = useState<MinutesDoc | null>(null);
  const [ocr, setOcr] = useState<string>("");
  const [last, setLast] = useState<Doc | null>(null);
  const [openDoc, setOpenDoc] = useState<string | null>(null);
  const [view, setView] = useState<Doc | null>(null);
  const toast = useToast();

  const upload = async () => {
    if (!files.length) return;
    let ok = 0;
    let lastDoc: Doc | null = null;
    for (const [i, file] of files.entries()) {
      const tag = files.length > 1 ? ` (${i + 1}/${files.length})` : "";
      let ocrText = "";
      if (file.type.startsWith("image/")) {
        try {
          setOcr(`Chargement de l’OCR…${tag}`);
          const T = await loadTesseract();
          const res = await T.recognize(file, "fra+eng", {
            logger: (m) => m.status === "recognizing text" && setOcr(`Lecture du texte (OCR)${tag}… ${Math.round(m.progress * 100)} %`),
          });
          ocrText = res.data.text;
        } catch {
          setOcr("OCR indisponible : le document est déposé sans lecture du texte.");
        }
      }
      const fd = new FormData();
      fd.append("file", file);
      fd.append("type", meta.type);
      // Le titre saisi ne s'applique que s'il n'y a qu'un fichier (sinon chaque document garde son nom).
      fd.append("title", files.length === 1 ? meta.title : "");
      fd.append("description", meta.description);
      fd.append("clientVisible", meta.clientVisible ? "1" : "0");
      if (ocrText) fd.append("ocrText", ocrText);
      setOcr(`Analyse de ${file.name}${tag}…`);
      const d = await run(() => uploadDoc(p.id, fd)).catch(() => undefined);
      if (d) {
        ok += 1;
        lastDoc = d;
      }
    }
    if (ok) {
      toast(ok > 1 ? `${ok} documents déposés` : `Document déposé${lastDoc?.notified ? ` · ${lastDoc.notified} membre(s) notifié(s)${lastDoc.mailed ? ` et ${lastDoc.mailed} e-mail(s)` : ""}` : ""}`);
      setLast(lastDoc);
      window.dispatchEvent(new Event("pct-alerts-changed"));
      setFiles([]);
      setMeta({ type: "auto", title: "", description: "", clientVisible: false });
      docs.reload();
    }
    setOcr("");
  };

  if (docs.error) return <ErrorNotice error={docs.error} onRetry={docs.reload} />;
  if (!docs.data) return <Loading />;
  const d = docs.data;
  const groups = d.types.map((t) => ({ ...t, docs: d.documents.filter((x) => (x.type || "other") === t.code) })).filter((g) => g.docs.length);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {view && <DocViewer projectId={p.id} doc={view} onClose={() => setView(null)} />}
      <RequiredDocs projectId={p.id} refreshKey={d.documents.length}
        onConsult={(docId) => { const x = d.documents.find((y) => y.id === docId); if (x) setView(x); }} />
      {minutes && <MinutesDialog projectId={p.id} doc={minutes} onClose={() => setMinutes(null)} onDone={() => { setMinutes(null); docs.reload(); }} />}
      <MinutesCard projectId={p.id} internal={d.internal !== false} onUploaded={docs.reload} />
      {d.canManage && (
        <Card title="Déposer un document" sub="Le texte est lu automatiquement (PDF, Word, Excel, PowerPoint ; OCR gratuit pour les images) et le type est proposé d’après les mots-clés.">
          <div className="pj-add">
            <div className="pj-drop">
              <DropZone multiple files={files} disabled={!!ocr} onFiles={setFiles} title="Glissez vos documents ici"
                hint="ou cliquez pour choisir · plusieurs fichiers possibles · 10 Mo max. par fichier" />
            </div>
            <Field id="doc-type" label="Type">
              <select id="doc-type" className="inp" value={meta.type} onChange={(e) => setMeta({ ...meta, type: e.target.value })}>
                <option value="auto">Détection automatique</option>
                {d.types.map((t) => (
                  <option key={t.code} value={t.code}>
                    {t.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field id="doc-title" label="Titre (facultatif)">
              <input id="doc-title" className="inp" maxLength={255} value={meta.title} onChange={(e) => setMeta({ ...meta, title: e.target.value })} />
            </Field>
            <label className="pj-check">
              <input type="checkbox" checked={meta.clientVisible} onChange={(e) => setMeta({ ...meta, clientVisible: e.target.checked })} /> Visible par le client
            </label>
            <button className="btn primary" type="button" disabled={busy || !files.length || !!ocr} onClick={upload}>
              {ocr ? "Analyse…" : files.length > 1 ? `Déposer ${files.length} fichiers` : "Déposer"}
            </button>
          </div>
          {ocr && <div className="muted" style={{ fontSize: 12.5 }}>{ocr}</div>}
          {last && <ExtractionSummary doc={last} />}
        </Card>
      )}
      <Card
        title="Documents du projet"
        sub={`${d.documents.length} document(s), classés par type`}
        extra={
          <form className="pj-search" onSubmit={(e) => { e.preventDefault(); setQuery(q.trim()); }}>
            <input className="inp" placeholder="Rechercher (nom ou contenu)…" value={q} onChange={(e) => setQ(e.target.value)} />
          </form>
        }
      >
        {groups.length === 0 ? (
          <div className="empty">{query ? "Aucun document ne correspond à la recherche." : "Aucun document pour l’instant."}</div>
        ) : (
          groups.map((g) => (
            <div key={g.code} className="doc-group">
              <h4>
                {g.label} <span className="faint">({g.docs.length})</span>
              </h4>
              <div className="tbl-wrap">
                <table className="tbl tight">
                  <tbody>
                    {g.docs.map((x) => (
                      <Fragment key={x.id}>
                        <tr>
                          <td className="cell-main">
                            <b>
                              {x.name} {x.version > 1 && <span className="pill nodot">v{x.version}</span>}
                            </b>
                            <small>
                              {x.ext.toUpperCase()} · {fileSize(x.size)} · {x.uploadedBy ?? "—"} · {frDate(x.uploadedAt)}
                              {x.extraction?.autoClassified && <> · classé automatiquement ({x.extraction.confidence} %)</>}
                              {(() => {
                                const m = (x.extraction as { minutes?: { created: string[]; updated: string[]; proposed: number; by: string } } | undefined)?.minutes;
                                return m ? <> · <span className="pill nodot ok">CR traité : {m.created.length} action(s) créée(s){m.updated.length ? `, ${m.updated.length} mise(s) à jour` : ""}{m.proposed ? `, ${m.proposed} proposée(s)` : ""}</span></> : null;
                              })()}
                            </small>
                          </td>
                          <td>{x.clientVisible ? <span className="pill info nodot">Visible client</span> : <span className="faint">Interne</span>}</td>
                          <td className="r">
                            <div className="btns" style={{ justifyContent: "flex-end" }}>
                              {x.extraction?.words ? (
                                <button className="btn ghost sm" type="button" onClick={() => setOpenDoc(openDoc === x.id ? null : x.id)}>
                                  {openDoc === x.id ? "Masquer" : "Infos extraites"}
                                </button>
                              ) : null}
                              {x.type === "minutes" && x.hasFile && (
                                <button className="btn sm" type="button" title="Lire le compte rendu (OCR si besoin) et valider décisions et actions"
                                  onClick={() => setMinutes(x as unknown as MinutesDoc)}>
                                  {(x.extraction as { minutes?: unknown } | undefined)?.minutes ? "📝 Relire le CR" : "📝 Lire le CR (OCR)"}
                                </button>
                              )}
                              <button className="btn primary sm" type="button" onClick={() => setView(x)}>
                                👁 Consulter
                              </button>
                              {x.hasFile && (
                                <a className="btn sm" href={`${API_BASE}/projects/${encodeURIComponent(p.id)}/documents/${encodeURIComponent(x.id)}`}>
                                  Télécharger
                                </a>
                              )}
                              {d.canManage && (
                                <select className="inp pj-inline" aria-label="Reclasser" value={x.type} disabled={busy}
                                  onChange={(e) => run(() => projectsApi.updateDoc(p.id, x.id, { type: e.target.value }), "Document reclassé").then(docs.reload, () => undefined)}>
                                  {d.types.map((t) => (
                                    <option key={t.code} value={t.code}>
                                      {t.label}
                                    </option>
                                  ))}
                                </select>
                              )}
                              {d.canManage && (
                                <button className="btn ghost sm" type="button" disabled={busy}
                                  onClick={() => window.confirm(`Supprimer « ${x.name} » ?`) && run(() => projectsApi.deleteDoc(p.id, x.id), "Document supprimé").then(docs.reload, () => undefined)}>
                                  Supprimer
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                        {openDoc === x.id && (
                          <tr>
                            <td colSpan={3}>
                              <ExtractionSummary doc={x} />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))
        )}
      </Card>
    </div>
  );
}

type Extraction = {
  source?: string; suggestedType?: string | null; suggestedTypeLabel?: string; confidence?: number; matchedKeywords?: string[];
  dates?: string[]; amounts?: string[]; emails?: string[]; phones?: string[]; references?: string[]; versions?: string[];
  words?: number; excerpt?: string; autoClassified?: boolean;
};

function ExtractionSummary({ doc }: { doc: Doc }) {
  const e = doc.extraction ?? {};
  const chips = (label: string, items?: string[]) =>
    items && items.length ? (
      <div className="ex-row">
        <span>{label}</span>
        {items.map((i) => (
          <code key={i}>{i}</code>
        ))}
      </div>
    ) : null;
  return (
    <div className="ex-box">
      <div className="ex-head">
        <b>{doc.name}</b> — lu par : {e.source ?? "—"} · {e.words ?? 0} mots
        {e.suggestedType && (
          <span className="pill acc nodot" style={{ marginLeft: 8 }}>
            Type détecté : {e.suggestedTypeLabel} ({e.confidence} %)
          </span>
        )}
      </div>
      {chips("Mots-clés", e.matchedKeywords)}
      {chips("Dates", e.dates)}
      {chips("Montants", e.amounts)}
      {chips("Références", e.references)}
      {chips("Versions", e.versions)}
      {chips("E-mails", e.emails)}
      {chips("Téléphones", e.phones)}
      {e.excerpt && <p className="muted ex-excerpt">« {e.excerpt}… »</p>}
    </div>
  );
}

function BudgetTab({ p, onChange }: { p: Workspace; onChange: (w?: Workspace) => void }) {
  const { run, busy } = useAction();
  const b = p.budget!;
  const [budget, setBudget] = useState(b.budget ? String(Number(b.budget)) : "");
  const canSet = p.rights.isPm || p.rights.canEditInfo;
  const pct = b.rate ?? 0;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="kpis pj-kpis">
        <div className="kpi">
          <label>Budget</label>
          <strong>{money(b.budget)}</strong>
          <small>validé</small>
        </div>
        <div className="kpi">
          <label>Consommé</label>
          <strong>{money(b.consumed)}</strong>
          <small>temps validés × TJM</small>
        </div>
        <div className="kpi warn">
          <label>Engagé</label>
          <strong>{money(b.pending)}</strong>
          <small>temps à valider</small>
        </div>
        <div className={`kpi${b.remaining !== null && Number(b.remaining) < 0 ? " crit" : " ok"}`}>
          <label>Reste</label>
          <strong>{money(b.remaining)}</strong>
          <small>{b.rate !== null ? `${b.rate} % consommé` : "budget à saisir"}</small>
        </div>
      </div>
      {b.budget && (
        <div className={`bar ${pct > 100 ? "crit" : pct > 85 ? "warn" : "ok"}`} style={{ height: 10 }}>
          <i style={{ width: `${Math.min(100, pct)}%` }} />
        </div>
      )}
      {b.missingRates.length > 0 && (
        <div className="callout warn">
          TJM manquant pour : <b>{b.missingRates.join(", ")}</b>. Leur temps n’est pas valorisé : saisissez leur TJM dans l’onglet Équipe.
        </div>
      )}
      <Card title="Consommation par membre" sub={`Jours = heures ÷ ${Number(b.hoursPerDay)} h. Seuls les temps validés sont consommés ; les temps à valider sont engagés.`}
        extra={canSet && (
          <div className="pj-search" style={{ display: "flex", gap: 8 }}>
            <input className="inp num" type="number" min={0} step={1000} placeholder="Budget (€)" value={budget} onChange={(e) => setBudget(e.target.value)} />
            <button className="btn primary sm" type="button" disabled={busy}
              onClick={() => run(() => projectsApi.update(p.id, { budget: budget === "" ? null : Number(budget) }), "Budget enregistré").then(onChange, () => undefined)}>
              Enregistrer le budget
            </button>
          </div>
        )}>
        {b.rows.length === 0 ? (
          <div className="empty">Aucun temps saisi sur ce projet pour l’instant.</div>
        ) : (
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Membre</th>
                  <th className="r">TJM</th>
                  <th className="r">Heures validées</th>
                  <th className="r">Jours</th>
                  <th className="r">Consommé</th>
                  <th className="r">Heures à valider</th>
                  <th className="r">Engagé</th>
                </tr>
              </thead>
              <tbody>
                {b.rows.map((r) => (
                  <tr key={r.user}>
                    <td>{r.user}</td>
                    <td className="r">{r.dailyRate ? money(r.dailyRate) : <span className="t-warn">à saisir</span>}</td>
                    <td className="r">{Number(r.hoursApproved)} h</td>
                    <td className="r">{Number(r.daysApproved)} j</td>
                    <td className="r">
                      <b>{money(r.cost)}</b>
                    </td>
                    <td className="r">{Number(r.hoursPending)} h</td>
                    <td className="r">{money(r.engaged)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}


/** Paramètres du projet (roue ⚙ à côté du nom) : type, versions, cadrage et budget. */
/** Lignes de saisie du projet : définies par le client ou l'administrateur, ajoutées au fil de l'eau. */
function ProjectLines({ projectId }: { projectId: string }) {
  type L = { id: string; label: string; code: string; active: boolean; entries: number; by?: string };
  const url = `/projects/${encodeURIComponent(projectId)}/timesheet-lines`;
  const r = useApi(() => api.get<{ lines: L[]; canManage: boolean; profiles: string[] }>(url), [url]);
  const { run, busy } = useAction();
  const [label, setLabel] = useState("");
  const [code, setCode] = useState("");
  if (!r.data) return null;
  const add = () => label.trim() && void run(() => api.post(url, { label, code }), "Ligne ajoutée").then(() => { setLabel(""); setCode(""); r.reload(); }, () => undefined);
  const toggle = (l: L) => void run(() => api.patch(url, { id: l.id, active: !l.active }), l.active ? "Ligne désactivée" : "Ligne réactivée").then(() => r.reload(), () => undefined);
  return (
    <fieldset className="pj-fs">
      <legend>Lignes de saisie des temps</legend>
      <small className="muted">Les collaborateurs des profils concernés ({r.data.profiles.join(", ") || "aucun"}) choisissent une de ces lignes pour imputer leur temps sur ce projet. {r.data.canManage ? "Ajoutez des lignes au fil de l’eau ; une ligne utilisée se désactive au lieu d’être supprimée." : "Lignes définies par le client ou l’administrateur."}</small>
      {r.data.lines.length > 0 ? (
        <ul className="pj-lines">
          {r.data.lines.map((l) => (
            <li key={l.id} className={l.active ? "" : "off"}>
              <b>{l.label}</b>{l.code && <code>{l.code}</code>}<small>{l.entries} saisie(s)</small>
              {r.data!.canManage && <button type="button" className="btn sm" disabled={busy} onClick={() => toggle(l)}>{l.active ? "Désactiver" : "Réactiver"}</button>}
            </li>
          ))}
        </ul>
      ) : <small>Aucune ligne : la saisie se fait directement sur le projet.</small>}
      {r.data.canManage && (
        <form className="frow" onSubmit={(e) => { e.preventDefault(); add(); }}>
          <input className="inp" placeholder="Nouvelle ligne (ex. Recette lot 2, Atelier, Run N2…)" aria-label="Libellé de la ligne" maxLength={80} value={label} onChange={(e) => setLabel(e.target.value)} />
          <input className="inp" style={{ maxWidth: 140 }} placeholder="Code (facultatif)" aria-label="Code de la ligne" maxLength={20} value={code} onChange={(e) => setCode(e.target.value)} />
          <button className="btn sm primary" type="submit" disabled={busy || !label.trim()}>+ Ajouter</button>
        </form>
      )}
    </fieldset>
  );
}

function ProjectSettings({ p, onClose, onSaved, canDelete }: { p: Workspace; onClose: () => void; onSaved: (w?: Workspace) => void; canDelete: boolean }) {
  const { run, busy } = useAction();
  const [confirmCode, setConfirmCode] = useState("");
  const [f, setF] = useState({
    name: p.name, status: p.status ?? "active", parent: p.parent?.id ?? "", dependsOn: (p.dependsOn ?? []).map((x) => x.id),
    projectType: p.projectType, natures: p.natures ?? [], baseProject: p.baseProject?.id ?? "", baseVersion: p.baseVersion, targetVersion: p.targetVersion,
    method: p.method, startDate: p.startDate ?? "", endDate: p.endDate ?? "", description: p.description,
    budget: p.budget?.budget ? String(Number(p.budget.budget)) : "",
  });
  const versioned = f.projectType !== "new";
  const save = () => {
    const body: Record<string, unknown> = {};
    if (p.rights.canEditType) Object.assign(body, { projectType: f.projectType, natures: f.natures, baseProject: f.baseProject || null, baseVersion: f.baseVersion, targetVersion: f.targetVersion });
    if (p.rights.canEditInfo) Object.assign(body, { name: f.name, status: f.status, parent: f.parent || null, dependsOn: f.dependsOn, method: f.method, startDate: f.startDate, endDate: f.endDate, description: f.description });
    if (p.rights.canSeeMoney && (p.rights.isPm || p.rights.canEditInfo)) body.budget = f.budget === "" ? null : Number(f.budget);
    return run(() => projectsApi.update(p.id, body), "Projet mis à jour").then(onSaved, () => undefined);
  };
  return (
    <div className="scrim" onClick={onClose}>
      <div className="modal pj-settings" role="dialog" aria-label="Paramètres du projet" onClick={(e) => e.stopPropagation()}>
        <div className="modal-h">
          <h3>⚙ Paramètres — {p.name}</h3>
          <button className="icon-btn" type="button" aria-label="Fermer" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="modal-b" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <fieldset disabled={!p.rights.canEditType} className="pj-fs">
            <legend>Nature du projet</legend>
            <div className="pj-natures" role="group" aria-label="Natures du projet (combinables)">
              <span>Le projet est (plusieurs choix possibles) :</span>
              {(p.natureChoices ?? []).map((n) => (
                <label key={n.code} className={`pj-nature ${f.natures.includes(n.code) ? "on" : ""}`}>
                  <input type="checkbox" checked={f.natures.includes(n.code)}
                    onChange={(e) => setF({ ...f, natures: e.target.checked ? [...f.natures, n.code] : f.natures.filter((x) => x !== n.code) })} />
                  {n.label}
                </label>
              ))}
            </div>
            <div className="frow">
              <Field id="ps-type" label="Type de projet">
                <select id="ps-type" className="inp" value={f.projectType} onChange={(e) => setF({ ...f, projectType: e.target.value })}>
                  {p.projectTypes.map((t) => (
                    <option key={t.code} value={t.code}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </Field>
              {versioned && (
                <Field id="ps-base" label="Produit / projet existant">
                  <select id="ps-base" className="inp" value={f.baseProject} onChange={(e) => setF({ ...f, baseProject: e.target.value })}>
                    <option value="">Non précisé</option>
                    {p.baseProject && !(p.otherProjects ?? []).some((o) => o.id === p.baseProject!.id) && (
                      <option value={p.baseProject.id}>{p.baseProject.name}</option>
                    )}
                    {(p.otherProjects ?? []).map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.code} — {o.name}
                      </option>
                    ))}
                  </select>
                </Field>
              )}
            </div>
            {versioned && (
              <div className="frow">
                <Field id="ps-src" label="Version source">
                  <input id="ps-src" className="inp" maxLength={40} placeholder="Ex. v2.3" value={f.baseVersion} onChange={(e) => setF({ ...f, baseVersion: e.target.value })} />
                </Field>
                <Field id="ps-tgt" label="Version cible">
                  <input id="ps-tgt" className="inp" maxLength={40} placeholder="Ex. v3.0" value={f.targetVersion} onChange={(e) => setF({ ...f, targetVersion: e.target.value })} />
                </Field>
              </div>
            )}
          </fieldset>
          <ProjectLines projectId={p.id} />
          <fieldset disabled={!p.rights.canEditInfo} className="pj-fs">
            <legend>Cadrage</legend>
            <div className="frow">
              <Field id="ps-name" label="Nom du projet">
                <input id="ps-name" className="inp" maxLength={200} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
              </Field>
              <Field id="ps-status" label="Statut du projet">
                <select id="ps-status" className="inp" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value as "active" | "paused" | "closed" })}>
                  <option value="active">▶ En cours</option>
                  <option value="paused">⏸ En pause</option>
                  <option value="closed">🔒 Clôturé</option>
                </select>
              </Field>
            </div>
            <div className="frow">
              <Field id="ps-method" label="Méthode">
                <select id="ps-method" className="inp" value={f.method} onChange={(e) => setF({ ...f, method: e.target.value })}>
                  <option value="">Non précisée</option>
                  {["Scrum", "Cycle en V", "Kanban", "Hybride", "Régie"].map((m) => (
                    <option key={m}>{m}</option>
                  ))}
                </select>
              </Field>
              <Field id="ps-start" label="Début">
                <input id="ps-start" className="inp" type="date" value={f.startDate} onChange={(e) => setF({ ...f, startDate: e.target.value })} />
              </Field>
              <Field id="ps-end" label="Fin">
                <input id="ps-end" className="inp" type="date" value={f.endDate} onChange={(e) => setF({ ...f, endDate: e.target.value })} />
              </Field>
            </div>
            <Field id="ps-desc" label="Description">
              <textarea id="ps-desc" className="inp" rows={2} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
            </Field>
          </fieldset>
          <fieldset disabled={!p.rights.canEditInfo} className="pj-fs">
            <legend>Liens avec d’autres projets</legend>
            <Field id="ps-parent" label="Projet parent (ce projet en est un sous-projet)">
              <select id="ps-parent" className="inp" value={f.parent} onChange={(e) => setF({ ...f, parent: e.target.value })}>
                <option value="">Aucun (projet autonome)</option>
                {(p.linkProjects ?? []).map((o) => <option key={o.id} value={o.id}>{o.code} — {o.name}</option>)}
              </select>
            </Field>
            <div className="ps-deps">
              <small className="faint">Ce projet dépend de (prérequis) :</small>
              <div className="ps-deplist">
                {(p.linkProjects ?? []).length === 0 && <span className="faint">Aucun autre projet.</span>}
                {(p.linkProjects ?? []).map((o) => (
                  <label key={o.id} className={`pf-check${f.dependsOn.includes(o.id) ? " on" : ""}`}>
                    <input type="checkbox" checked={f.dependsOn.includes(o.id)}
                      onChange={() => setF({ ...f, dependsOn: f.dependsOn.includes(o.id) ? f.dependsOn.filter((x) => x !== o.id) : [...f.dependsOn, o.id] })} />
                    <span><b>{o.name}</b><small>{o.code}</small></span>
                  </label>
                ))}
              </div>
            </div>
          </fieldset>
          {p.rights.canSeeMoney && (p.rights.isPm || p.rights.canEditInfo) && (
            <fieldset className="pj-fs">
              <legend>Budget</legend>
              <Field id="ps-budget" label="Budget validé (€)">
                <input id="ps-budget" className="inp num" type="number" min={0} step={1000} value={f.budget} onChange={(e) => setF({ ...f, budget: e.target.value })} />
              </Field>
            </fieldset>
          )}
          {canDelete && (
            <fieldset className="pj-fs pj-danger">
              <legend>Zone de danger</legend>
              <p style={{ margin: 0, fontSize: 13 }}>
                Supprimer définitivement le projet, ses {p.tasks.length} action(s), ses documents, son planning et les temps saisis. Cette opération est irréversible.
              </p>
              <div className="frow" style={{ alignItems: "flex-end" }}>
                <Field id="ps-del" label={`Pour confirmer, saisissez le code du projet : ${p.code}`}>
                  <input id="ps-del" className="inp" value={confirmCode} onChange={(e) => setConfirmCode(e.target.value)} placeholder={p.code} />
                </Field>
                <button className="btn danger" type="button" disabled={busy || confirmCode.trim().toUpperCase() !== p.code.toUpperCase()}
                  onClick={() => run(() => projectsApi.remove(p.id, confirmCode.trim()), "Projet supprimé").then((r) => { if (r) window.location.hash = "#projets"; }, () => undefined)}>
                  🗑 Supprimer le projet
                </button>
              </div>
            </fieldset>
          )}
          <p className="muted" style={{ fontSize: 12, margin: 0 }}>
            Le chef de projet et le Tech Lead se changent dans Paramétrage › Projets (administrateur). Les TJM se saisissent dans l’onglet Équipe.
          </p>
        </div>
        <div className="modal-f">
          <button className="btn ghost" type="button" onClick={onClose}>
            Annuler
          </button>
          <button className="btn primary" type="button" disabled={busy} onClick={save}>
            Enregistrer
          </button>
        </div>
      </div>
    </div>
  );
}
