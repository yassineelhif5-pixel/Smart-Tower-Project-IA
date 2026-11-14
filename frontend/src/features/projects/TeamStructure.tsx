/** Structure de l'équipe d'un projet : organigramme (humains + assistants IA), charge en cours, absences et remplaçants. */
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { api, API_BASE, ApiError } from "../../api/client";
import { useToast } from "../../components/ui";

type Mini = { id: number; name: string; title: string; role: string; roleCode: string; internal: boolean; team: string; photo?: number | null };
type Load = { open: number; doing: number; blocked: number; late: number; done: number; share: number; allOpen: number; allProjects: number };
type Absence = { id: string; from: string; to: string; reason: string; upcoming: boolean; source: "declared" | "delegation"; replacement: Mini | null };
type Person = Mini & { position: "pm" | "tl" | "member" | "client"; side: "internal" | "client"; load: Load; email?: string; absence?: Absence; replacing: string[] };
type Ai = { code: string; name: string; role: string; avatar: string; color: string; mission: string; mode: string; modeLabel: string; pending: number; share: number };
type Data = {
  project: { id: string; code: string; name: string; client: { code: string; name: string } | null; status: string };
  totals: { open: number; unassigned: number; late: number; done: number; people: number; absent: number };
  people: Person[]; ai: Ai[]; aiLicensed: boolean; me: number; canManageAbsences: boolean; candidates: Mini[];
};

const fr = (d: string) => new Date(`${d}T00:00:00`).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" });
const GRADS = [["#6366f1", "#8b5cf6"], ["#0ea5e9", "#22d3ee"], ["#10b981", "#34d399"], ["#f59e0b", "#f97316"], ["#ec4899", "#f43f5e"],
  ["#14b8a6", "#0ea5e9"], ["#8b5cf6", "#d946ef"], ["#64748b", "#334155"]];
const initials = (n: string) => n.split(/\s+/).filter(Boolean).map((p) => p[0]).join("").slice(0, 2).toUpperCase();

export function Avatar({ p, size = 56, bump = 0 }: { p: Pick<Mini, "id" | "name" | "photo">; size?: number; bump?: number }) {
  const [broken, setBroken] = useState(false);
  const h = [...p.name].reduce((n, ch) => (n * 31 + ch.charCodeAt(0)) >>> 0, 7);
  const [a, b] = GRADS[h % GRADS.length];
  if (p.photo && !broken) {
    return <img className="ts-av" style={{ width: size, height: size }} alt={p.name} onError={() => setBroken(true)}
      src={`${API_BASE}/users/${p.id}/photo?v=${p.photo}${bump ? `-${bump}` : ""}`} />;
  }
  return (
    <span className="ts-av ts-av-txt" style={{ width: size, height: size, fontSize: size * 0.36, background: `linear-gradient(135deg, ${a}, ${b})` }}>
      {initials(p.name)}
    </span>
  );
}

/** Anneau de charge : part des actions en cours du projet portées par la personne. */
function Ring({ pct, size = 54, color }: { pct: number; size?: number; color?: string }) {
  const r = (size - 8) / 2;
  const c = 2 * Math.PI * r;
  const col = color ?? (pct >= 45 ? "#ef4444" : pct >= 25 ? "#f59e0b" : pct > 0 ? "#10b981" : "#cbd5e1");
  return (
    <svg className="ts-ring" width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-label={`Charge ${pct} %`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--line)" strokeWidth="6" />
      {pct > 0 && <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={col} strokeWidth="6" strokeLinecap="round"
        strokeDasharray={`${(c * Math.min(pct, 100)) / 100} ${c}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} />}
      <text x="50%" y="50%" dominantBaseline="central" textAnchor="middle" fontSize={size * 0.26} fontWeight="700" fill="currentColor">{pct}%</text>
    </svg>
  );
}

/** Photo redimensionnée (256 px, JPEG) avant envoi. */
async function resizeToDataUrl(file: File): Promise<string> {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise<HTMLImageElement>((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url; });
    const side = Math.min(img.width, img.height);
    const c = document.createElement("canvas");
    c.width = c.height = 256;
    c.getContext("2d")?.drawImage(img, (img.width - side) / 2, (img.height - side) / 2, side, side, 0, 0, 256, 256);
    return c.toDataURL("image/jpeg", 0.86);
  } finally {
    URL.revokeObjectURL(url);
  }
}

const POS_LABEL = { pm: "Chef de projet", tl: "Tech lead", member: "Équipe projet", client: "Côté client" };

function PersonCard({ p, me, featured, canRemove, onPhoto, onRemoveAbsence, bump }: {
  p: Person; me: boolean; featured?: boolean; canRemove: boolean; bump: number;
  onPhoto: () => void; onRemoveAbsence: (a: Absence) => void;
}) {
  const ab = p.absence;
  const away = ab && !ab.upcoming;
  return (
    <article className={`ts-card${featured ? " feat" : ""}${away ? " away" : ""}${me ? " me" : ""} side-${p.side}`}>
      <div className="ts-card-top">
        <button type="button" className="ts-av-wrap" title={me ? "Changer ma photo" : p.name} onClick={me ? onPhoto : undefined} disabled={!me}>
          <Avatar p={p} size={featured ? 64 : 52} bump={me ? bump : 0} />
          {away && <span className="ts-badge" title="Absent">🌴</span>}
          {me && <span className="ts-cam">📷</span>}
        </button>
        <div className="ts-id">
          <b title={p.email}>{p.name}{me && <span className="ts-me"> · vous</span>}</b>
          <small>{p.title || p.role}</small>
          <span className={`ts-pos pos-${p.position}`}>{POS_LABEL[p.position]}</span>
        </div>
        {p.side === "internal" || p.load.open > 0 ? <Ring pct={p.load.share} size={featured ? 60 : 52} /> : null}
      </div>
      {(p.side === "internal" || p.load.open > 0) && (
        <div className="ts-stats">
          <span><b>{p.load.open}</b> en cours</span>
          {p.load.doing > 0 && <span className="doing">{p.load.doing} démarrée(s)</span>}
          {p.load.late > 0 && <span className="late">⏰ {p.load.late} en retard</span>}
          {p.load.blocked > 0 && <span className="blk">⛔ {p.load.blocked} bloquée(s)</span>}
          {p.load.done > 0 && <span className="done">✓ {p.load.done} terminée(s)</span>}
        </div>
      )}
      {p.side === "internal" && p.load.allProjects > 0 && (
        <div className="ts-all" title="Actions en cours sur tous les projets actifs">
          <span>Tous projets</span>
          <i><em style={{ width: `${Math.min(100, p.load.allOpen * 5)}%` }} /></i>
          <small>{p.load.allOpen} action(s) · {p.load.allProjects} projet(s)</small>
        </div>
      )}
      {ab && (
        <div className={`ts-abs${ab.upcoming ? " soon" : ""}`}>
          <span>🌴 {ab.upcoming ? `Absent(e) du ${fr(ab.from)} au ${fr(ab.to)}` : `Absent(e) jusqu'au ${fr(ab.to)}`}{ab.reason ? ` · ${ab.reason}` : ""}</span>
          {ab.replacement ? (
            <span className="ts-rep"><Avatar p={ab.replacement} size={20} /> remplacé(e) par <b>{ab.replacement.name}</b></span>
          ) : (
            <span className="ts-rep none">Aucun remplaçant désigné</span>
          )}
          {canRemove && ab.source === "declared" && (
            <button type="button" className="ts-x" title="Retirer cette absence" onClick={() => onRemoveAbsence(ab)}>✕</button>
          )}
        </div>
      )}
      {p.replacing.length > 0 && <div className="ts-repl">🔁 Remplace {p.replacing.join(", ")}</div>}
    </article>
  );
}

function AiCard({ a }: { a: Ai }) {
  return (
    <article className="ts-card ts-ai-card" style={{ ["--ai" as string]: a.color }}>
      <div className="ts-card-top">
        <span className="ts-av ts-ai-av" style={{ background: `linear-gradient(135deg, ${a.color}, color-mix(in srgb, ${a.color} 55%, #fff))` }}>{a.avatar}</span>
        <div className="ts-id">
          <b>{a.name}</b>
          <small>{a.role}</small>
          <span className={`ts-pos pos-ai ${a.mode}`}>{a.modeLabel}</span>
        </div>
        <Ring pct={a.share} size={50} color={a.color} />
      </div>
      <p className="ts-mission">{a.mission}</p>
      <div className="ts-stats"><span><b>{a.pending}</b> proposition(s) en attente de validation</span></div>
    </article>
  );
}

function AbsenceForm({ data, onClose, onSaved }: { data: Data; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const internal = data.people.filter((p) => p.side === "internal");
  const allowed = data.canManageAbsences ? internal : internal.filter((p) => p.id === data.me);
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({ user: String(allowed[0]?.id ?? data.me), start: today, end: today, replacement: "", reason: "Congés" });
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      await api.post("/team-absences", { ...f, user: Number(f.user), replacement: f.replacement ? Number(f.replacement) : null, project: data.project.id });
      toast("Absence enregistrée" + (f.replacement ? " · le remplaçant est prévenu" : ""));
      onSaved();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Enregistrement impossible", true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="ts-form" role="dialog" aria-label="Déclarer une absence">
      <h4>🌴 Déclarer une absence</h4>
      <div className="ts-form-grid">
        <label>Personne
          <select className="inp" value={f.user} onChange={(e) => setF({ ...f, user: e.target.value, replacement: f.replacement === e.target.value ? "" : f.replacement })}>
            {allowed.map((p) => <option key={p.id} value={p.id}>{p.name}{p.id === data.me ? " (moi)" : ""}</option>)}
          </select>
        </label>
        <label>Du<input className="inp" type="date" value={f.start} onChange={(e) => setF({ ...f, start: e.target.value, end: f.end < e.target.value ? e.target.value : f.end })} /></label>
        <label>Au<input className="inp" type="date" value={f.end} min={f.start} onChange={(e) => setF({ ...f, end: e.target.value })} /></label>
        <label>Remplacé(e) par
          <select className="inp" value={f.replacement} onChange={(e) => setF({ ...f, replacement: e.target.value })}>
            <option value="">— Personne —</option>
            {data.candidates.filter((c) => String(c.id) !== f.user).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <label>Motif
          <select className="inp" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })}>
            {["Congés", "Maladie", "Formation", "Déplacement", "Mission sur un autre projet", "Autre"].map((r) => <option key={r}>{r}</option>)}
          </select>
        </label>
      </div>
      <div className="ts-form-foot">
        <small className="faint">Le remplaçant et la personne absente reçoivent une notification.</small>
        <span style={{ flex: 1 }} />
        <button className="btn ghost" type="button" onClick={onClose}>Annuler</button>
        <button className="btn primary" type="button" disabled={busy || !f.user} onClick={() => void save()}>Enregistrer</button>
      </div>
    </div>
  );
}

type Filter = "all" | "internal" | "client" | "ai";

/** Bouton « Structure de l'équipe » + fenêtre (accessible à tous les profils du projet). */
export function TeamStructureButton({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className="btn" type="button" onClick={() => setOpen(true)} title="Organigramme de l'équipe, charge en cours et absences">👥 Structure de l'équipe</button>
      {open && <TeamStructureDialog projectId={projectId} onClose={() => setOpen(false)} />}
    </>
  );
}

export function TeamStructureDialog({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const toast = useToast();
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");
  const [form, setForm] = useState(false);
  const [bump, setBump] = useState(0);
  const pick = useRef<HTMLInputElement>(null);

  const load = () => api.get<Data>(`/projects/${encodeURIComponent(projectId)}/team-structure`).then(setData, (e) => setError(e instanceof ApiError ? e.message : "Chargement impossible"));
  useEffect(() => {
    void load();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const people = useMemo(() => {
    const n = q.trim().toLowerCase();
    return (data?.people ?? []).filter((p) => (filter === "all" || (filter === "internal" && p.side === "internal") || (filter === "client" && p.side === "client"))
      && (!n || `${p.name} ${p.title} ${p.role}`.toLowerCase().includes(n)));
  }, [data, filter, q]);
  const ai = useMemo(() => (filter === "all" || filter === "ai" ? (data?.ai ?? []).filter((a) => !q.trim() || `${a.name} ${a.role}`.toLowerCase().includes(q.trim().toLowerCase())) : []), [data, filter, q]);

  const lead = people.filter((p) => p.position === "pm" || p.position === "tl");
  const team = people.filter((p) => p.position === "member");
  const client = people.filter((p) => p.position === "client");
  const groups = useMemo(() => {
    const m = new Map<string, Person[]>();
    team.forEach((p) => m.set(p.role || "Équipe", [...(m.get(p.role || "Équipe") ?? []), p]));
    return [...m.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [team]);

  const onPhoto = async (fs: FileList | null) => {
    const f = fs?.[0];
    if (!f) return;
    try {
      const image = await resizeToDataUrl(f);
      await api.put("/auth/photo", { image });
      toast("Photo de profil mise à jour");
      setBump(Date.now());
      void load();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Image illisible", true);
    }
  };
  const removeAbsence = async (a: Absence) => {
    if (!window.confirm("Retirer cette absence ?")) return;
    try {
      await api.delete(`/team-absences/${encodeURIComponent(a.id)}`);
      toast("Absence retirée");
      void load();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Suppression impossible", true);
    }
  };

  const card = (p: Person, featured = false) => (
    <PersonCard key={p.id} p={p} me={p.id === data?.me} featured={featured} bump={bump}
      canRemove={!!data && (data.canManageAbsences || p.id === data.me)}
      onPhoto={() => pick.current?.click()} onRemoveAbsence={(a) => void removeAbsence(a)} />
  );

  return createPortal(
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal ts-modal" role="dialog" aria-label="Structure de l'équipe">
        <input ref={pick} type="file" accept="image/*" hidden onChange={(e) => { void onPhoto(e.target.files); e.target.value = ""; }} />
        <header className="ts-head">
          <div className="ts-title">
            <small>Structure de l'équipe</small>
            <h3>{data?.project.name ?? "…"}</h3>
            {data?.project.client && <span className="ts-client-pill">🏢 {data.project.client.name}</span>}
          </div>
          <button className="btn ghost sm" type="button" onClick={onClose} aria-label="Fermer">✕</button>
        </header>
        {data && (
          <div className="ts-kpis">
            <div><b>{data.totals.people}</b><small>personnes</small></div>
            <div><b>{data.ai.length}</b><small>assistants IA</small></div>
            <div><b>{data.totals.open}</b><small>actions en cours</small></div>
            <div className={data.totals.late ? "warn" : ""}><b>{data.totals.late}</b><small>en retard</small></div>
            <div className={data.totals.unassigned ? "warn" : ""}><b>{data.totals.unassigned}</b><small>non affectées</small></div>
            <div className={data.totals.absent ? "abs" : ""}><b>{data.totals.absent}</b><small>absent(s)</small></div>
          </div>
        )}
        <div className="ts-bar">
          <div className="ts-chips" role="tablist">
            {([["all", "Toute l'équipe"], ["internal", "Interne"], ["client", "Côté client"], ["ai", "🤖 Équipe IA"]] as [Filter, string][]).map(([k, l]) => (
              <button key={k} type="button" role="tab" aria-selected={filter === k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>{l}</button>
            ))}
          </div>
          <input className="inp ts-search" placeholder="Rechercher une personne…" value={q} onChange={(e) => setQ(e.target.value)} />
          {data && <button className="btn sm" type="button" onClick={() => setForm(!form)}>🌴 Déclarer une absence</button>}
        </div>
        <div className="ts-body">
          {error && <div className="mn-warn">⚠️ {error}</div>}
          {!data && !error && <div className="mn-wait"><span className="spinner" /> Chargement de l'équipe…</div>}
          {data && form && <AbsenceForm data={data} onClose={() => setForm(false)} onSaved={() => { setForm(false); void load(); }} />}
          {data && (
            <div className="ts-org">
              {filter !== "ai" && (lead.length > 0 || client.length > 0) && (
                <section className="ts-level ts-top">
                  {lead.length > 0 && (
                    <div className="ts-col">
                      <h4>🧭 Pilotage</h4>
                      <div className="ts-lead">{lead.map((p) => card(p, true))}</div>
                    </div>
                  )}
                  {client.length > 0 && (
                    <div className="ts-col ts-client-col">
                      <h4>🏢 Côté client{data.project.client ? ` · ${data.project.client.name}` : ""}</h4>
                      <div className="ts-grid">{client.map((p) => card(p))}</div>
                    </div>
                  )}
                </section>
              )}
              {filter !== "ai" && groups.length > 0 && <div className="ts-link" aria-hidden />}
              {groups.map(([role, ps]) => (
                <section key={role} className="ts-level">
                  <h4>{role} <span className="faint">({ps.length})</span></h4>
                  <div className="ts-grid">{ps.map((p) => card(p))}</div>
                </section>
              ))}
              {(filter === "all" || filter === "ai") && (
                <section className="ts-level ts-ai">
                  <h4>🤖 Équipe IA <span className="faint">({ai.length})</span></h4>
                  {ai.length ? (
                    <div className="ts-grid">{ai.map((a) => <AiCard key={a.code} a={a} />)}</div>
                  ) : (
                    <div className="faint" style={{ fontSize: 13 }}>
                      {data.aiLicensed ? "Aucun assistant IA affecté à ce projet (Orchestrateur IA › assistants)." : "Les assistants IA ne sont pas inclus dans la licence de votre entreprise."}
                    </div>
                  )}
                </section>
              )}
              {people.length === 0 && ai.length === 0 && <div className="faint">Aucune personne ne correspond.</div>}
            </div>
          )}
        </div>
        <footer className="ts-foot">
          <small className="faint">Charge = part des {data?.totals.open ?? 0} actions en cours du projet portée par chaque personne (IA : part des propositions en attente).
            Cliquez sur votre photo pour la changer.</small>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
