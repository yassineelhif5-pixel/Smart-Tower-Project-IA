import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "../../api/client";
import { ErrorNotice, Loading } from "../../components/ui";
import { evolutionSvg, MailReportDialog, svgToPng } from "./MailReportDialog";

type Summary = { id: string; code: string; name: string; client: { name: string } };
type Phase = {
  id: number; name: string; start: string | null; end: string | null; realEnd: string | null; status: string; statusLabel: string;
  progress: number; plannedProgress: number | null; owner: string | null; slipDays: number; lot?: boolean; late?: number;
};
type Act = { id: string; title: string; due: string | null; start: string | null; status: string; owner: string | null; phase: string; lateDays: number };
type Proj = {
  project: { id: string; code: string; name: string; client: string; pm: string | null; start: string | null; end: string | null; typeLabel: string };
  progress: { planned: number | null; real: number | null; gap: number | null };
  phases: Phase[]; lots: Phase[]; milestones: { title: string; date: string; status: string }[];
  tasks: { total: number; done: number; rate: number | null; late: number };
  evolution?: { week: string; planned: number | null; real: number | null }[];
  late: Act[]; lateCount: number; doing: Act[]; doingCount: number; span: { start: string | null; end: string | null };
};
type Data = { today: string; generatedAt: string; projects: Proj[] };

const COLORS = ["#4f46e5", "#0ea5e9", "#16a34a", "#d97706", "#db2777", "#7c3aed", "#0f766e", "#b91c1c"];
const PH = { done: "#22c55e", doing: "#3b82f6", late: "#e5484d", todo: "#94a3b8", skipped: "#cbd5e1" } as Record<string, string>;
const d = (s: string | null) => (s ? new Date(`${s}T00:00:00`) : null);
const fr = (s: string | null) => (s ? new Date(`${s}T00:00:00`).toLocaleDateString("fr-FR") : "—");
const DAY = 86400000;
const keyPhases = (p: Proj) => (p.phases.length ? p.phases : p.lots ?? []);
const real = (p: Proj) => p.progress.real ?? p.tasks.rate ?? 0;
export const COMPARE_KEY = "pct-compare-projects";
export function readCompare(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(COMPARE_KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}
export function writeCompare(ids: string[]) {
  try {
    localStorage.setItem(COMPARE_KEY, JSON.stringify(ids));
  } catch {
    /* stockage indisponible : sélection non mémorisée */
  }
}

/** Reporting multi-projets : planning macro comparé, actions en retard / en cours, phases clés ; export PDF / image. */
export function PortfolioReporting({ projects }: { projects: Summary[] }) {
  const [sel, setSel] = useState<string[]>(() => {
    const saved = readCompare().filter((id) => projects.some((p) => p.id === id));
    return saved.length ? saved : projects.slice(0, 2).map((p) => p.id);
  });
  const [q, setQ] = useState("");
  const [pickOpen, setPickOpen] = useState(true);
  const [mail, setMail] = useState(false);
  useEffect(() => writeCompare(sel), [sel]);
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<unknown>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!sel.length) {
      setData(null);
      return;
    }
    setData(null);
    api.get<Data>(`/projects-portfolio/report?ids=${sel.map(encodeURIComponent).join(",")}`).then(setData, setError);
  }, [sel]);

  useEffect(() => {
    if (data && sessionStorage.getItem("pct-open-mail")) {
      sessionStorage.removeItem("pct-open-mail");
      setMail(true);
    }
  }, [data]);

  const toggle = (id: string) => setSel((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  // Axe de temps commun.
  const axis = useMemo(() => {
    if (!data) return null;
    const dates: number[] = [];
    data.projects.forEach((p) => {
      [p.span.start, p.span.end].forEach((x) => x && dates.push(d(x)!.getTime()));
      keyPhases(p).forEach((ph) => [ph.start, ph.end, ph.realEnd].forEach((x) => x && dates.push(d(x)!.getTime())));
      p.milestones.forEach((m) => dates.push(d(m.date)!.getTime()));
    });
    const today = d(data.today)!.getTime();
    dates.push(today);
    let min = Math.min(...dates), max = Math.max(...dates);
    if (max - min < 30 * DAY) max = min + 30 * DAY;
    min -= 5 * DAY;
    max += 5 * DAY;
    return { min, max, today };
  }, [data]);

  if (error) return <ErrorNotice error={error as never} onRetry={() => setSel([...sel])} />;

  const W = 1100, L = 220, R = 20;
  const x = (t: number) => (axis ? L + ((t - axis.min) / (axis.max - axis.min)) * (W - L - R) : 0);
  // Lignes : une ligne projet + une ligne par phase.
  const rows: { kind: "project" | "phase"; p: Proj; ph?: Phase; color: string }[] = [];
  data?.projects.forEach((p, i) => {
    rows.push({ kind: "project", p, color: COLORS[i % COLORS.length] });
    keyPhases(p).forEach((ph) => rows.push({ kind: "phase", p, ph, color: COLORS[i % COLORS.length] }));
  });
  const RH = 26, TOP = 34;
  const H = TOP + rows.length * RH + 16;
  const months: { t: number; label: string }[] = [];
  if (axis) {
    const m = new Date(axis.min);
    m.setDate(1);
    m.setMonth(m.getMonth() + 1);
    while (m.getTime() < axis.max) {
      months.push({ t: m.getTime(), label: m.toLocaleDateString("fr-FR", { month: "short", year: "2-digit" }) });
      m.setMonth(m.getMonth() + 1);
    }
  }

  const exportPng = async () => {
    if (!svgRef.current || !data) return;
    const xml = new XMLSerializer().serializeToString(svgRef.current);
    const img = new Image();
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(xml)}`;
    await new Promise((r) => (img.onload = r));
    const colW = 520, lineH = 22;
    const blocks = data.projects.map((p) => 3 + Math.max(Math.min(p.late.length, 10), Math.min(p.doing.length, 10), Math.min(keyPhases(p).length, 10)) + 1);
    const listH = blocks.reduce((a, b) => a + b * lineH + 20, 0);
    const c = document.createElement("canvas");
    c.width = Math.max(W, colW * 3) + 40;
    c.height = 90 + H + 30 + listH;
    const g = c.getContext("2d")!;
    g.fillStyle = "#fff";
    g.fillRect(0, 0, c.width, c.height);
    g.fillStyle = "#0f172a";
    g.font = "bold 24px Inter, Arial";
    g.fillText("Reporting projets — planning macro", 20, 40);
    g.font = "14px Inter, Arial";
    g.fillStyle = "#64748b";
    g.fillText(`${data.projects.map((p) => p.project.name).join(" · ")} — au ${fr(data.today)}`, 20, 66);
    g.drawImage(img, 20, 90, W, H);
    let y = 90 + H + 40;
    const clip = (s: string, n = 58) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);
    data.projects.forEach((p, i) => {
      g.fillStyle = COLORS[i % COLORS.length];
      g.font = "bold 17px Inter, Arial";
      g.fillText(`${p.project.name} — réel ${real(p)} % / prévu ${p.progress.planned ?? "—"} %`, 20, y);
      y += lineH + 4;
      const cols: [string, string[]][] = [
        [`⛔ En retard (${p.lateCount})`, p.late.slice(0, 10).map((a) => `${clip(a.title)} · ${fr(a.due)} (+${a.lateDays} j)`)],
        [`🔄 En cours (${p.doingCount})`, p.doing.slice(0, 10).map((a) => `${clip(a.title)} · ${a.owner ?? "—"}`)],
        [`🎯 Phases clés (${keyPhases(p).length})`, keyPhases(p).slice(0, 10).map((ph) => `${clip(ph.name, 34)} · ${fr(ph.start)} → ${fr(ph.realEnd ?? ph.end)} · ${ph.progress} %`)],
      ];
      const y0 = y;
      cols.forEach(([title, items], k) => {
        let yy = y0;
        g.font = "bold 14px Inter, Arial";
        g.fillStyle = "#0f172a";
        g.fillText(title, 20 + k * colW, yy);
        g.font = "13px Inter, Arial";
        g.fillStyle = "#334155";
        (items.length ? items : ["—"]).forEach((t) => {
          yy += lineH;
          g.fillText(t, 20 + k * colW, yy);
        });
      });
      y = y0 + (Math.max(...cols.map(([, it]) => Math.max(1, it.length))) + 1) * lineH + 20;
    });
    const a = document.createElement("a");
    a.href = c.toDataURL("image/png");
    a.download = `reporting-projets-${data.today}.png`;
    a.click();
  };

  return (
    <div className="pf">
      <div className="pf-picker no-print">
        <div className="pf-pick-h">
          <button className="btn ghost sm" type="button" onClick={() => setPickOpen(!pickOpen)} aria-expanded={pickOpen}>
            {pickOpen ? "▾" : "▸"} <b>Projets à afficher / comparer</b> <span className="pill nodot">{sel.length} / {projects.length} sélectionné(s)</span>
          </button>
          <span className="pf-exp">
            <button className="btn sm" type="button" disabled={!data} onClick={() => window.print()}>🖨 Exporter en PDF</button>
            <button className="btn sm" type="button" disabled={!data} onClick={() => void exportPng()}>🖼 Exporter en image</button>
            <button className="btn primary sm" type="button" disabled={!data} onClick={() => setMail(true)}>✉️ Envoyer par e-mail</button>
          </span>
        </div>
        {pickOpen && (
          <>
            <div className="pf-pick-tools">
              <input className="inp sm" placeholder="Rechercher un projet…" value={q} onChange={(e) => setQ(e.target.value)} />
              <button className="btn ghost sm" type="button" onClick={() => setSel(projects.map((p) => p.id))}>Tout cocher</button>
              <button className="btn ghost sm" type="button" onClick={() => setSel([])}>Tout décocher</button>
            </div>
            <div className="pf-checks">
              {projects.filter((p) => !q.trim() || `${p.code} ${p.name} ${p.client.name}`.toLowerCase().includes(q.trim().toLowerCase())).map((p) => (
                <label key={p.id} className={`pf-check${sel.includes(p.id) ? " on" : ""}`}>
                  <input type="checkbox" checked={sel.includes(p.id)} onChange={() => toggle(p.id)} />
                  <span>
                    <b>{p.name}</b>
                    <small>{p.code} · {p.client.name}</small>
                  </span>
                </label>
              ))}
            </div>
          </>
        )}
      </div>

      {mail && data && (
        <MailReportDialog projectIds={data.projects.map((p) => p.project.id)} onClose={() => setMail(false)}
          makeImages={async () => {
            const out: Record<string, string> = {};
            if (svgRef.current) out.gantt = await svgToPng(svgRef.current, W, H);
            for (const p of data.projects) {
              if (p.evolution && p.evolution.length > 1) out[`evo-${p.project.id}`] = await svgToPng(evolutionSvg(p.evolution, `Évolution — ${p.project.name}`), 720, 240);
            }
            return out;
          }} />
      )}
      {!sel.length ? (
        <div className="empty">Sélectionnez au moins un projet.</div>
      ) : !data || !axis ? (
        <Loading />
      ) : (
        <div className="pf-report" id="pf-print">
          <div className="pf-head">
            <h2 className="sec">Planning macro — {data.projects.length} projet(s)</h2>
            <small className="faint">Situation au {fr(data.today)}</small>
          </div>

          <div className="pf-kpis">
            {data.projects.map((p, i) => (
              <div key={p.project.id} className="pf-kpi" style={{ borderTopColor: COLORS[i % COLORS.length] }}>
                <b>{p.project.name}</b>
                <small>{p.project.client} · {p.project.typeLabel}{p.project.pm ? ` · CP ${p.project.pm}` : ""}</small>
                <div className="pf-bar">
                  <i style={{ width: `${real(p)}%`, background: COLORS[i % COLORS.length] }} />
                  {p.progress.planned != null && <em style={{ left: `${p.progress.planned}%` }} title={`Prévu ${p.progress.planned} %`} />}
                </div>
                <div className="pf-nums">
                  <span>Réel <b>{real(p)} %</b></span>
                  <span>Prévu <b>{p.progress.planned ?? "—"} %</b></span>
                  <span className={p.lateCount ? "crit" : ""}>⛔ <b>{p.lateCount}</b> en retard</span>
                  <span>🔄 <b>{p.doingCount}</b> en cours</span>
                </div>
              </div>
            ))}
          </div>

          <div className="pf-gantt">
            <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} width="100%" xmlns="http://www.w3.org/2000/svg" fontFamily="Inter, Arial, sans-serif">
              <rect x="0" y="0" width={W} height={H} fill="#ffffff" />
              {months.map((m) => (
                <g key={m.t}>
                  <line x1={x(m.t)} x2={x(m.t)} y1={TOP - 6} y2={H - 10} stroke="#e2e8f0" />
                  <text x={x(m.t) + 3} y={TOP - 12} fontSize="11" fill="#64748b">{m.label}</text>
                </g>
              ))}
              {rows.map((r, i) => {
                const y = TOP + i * RH;
                if (r.kind === "project") {
                  const s = d(r.p.span.start)?.getTime(), e = d(r.p.span.end)?.getTime();
                  return (
                    <g key={`p${r.p.project.id}`}>
                      <rect x="0" y={y} width={W} height={RH} fill={`${r.color}12`} />
                      <text x="8" y={y + 17} fontSize="12.5" fontWeight="700" fill={r.color}>{r.p.project.name.slice(0, 28)}</text>
                      {s && e ? (
                        <>
                          <rect x={x(s)} y={y + 6} width={Math.max(4, x(e) - x(s))} height={RH - 12} rx="4" fill={r.color} opacity="0.25" />
                          <rect x={x(s)} y={y + 6} width={Math.max(0, (x(e) - x(s)) * (real(r.p) / 100))} height={RH - 12} rx="4" fill={r.color} />
                          <text x={Math.min(x(e) + 4, W - 40)} y={y + 17} fontSize="11" fill="#334155">{real(r.p)} %</text>
                        </>
                      ) : (
                        <>
                          <rect x={L} y={y + 6} width={W - L - R} height={RH - 12} rx="4" fill={r.color} opacity="0.12" stroke={r.color} strokeDasharray="4 3" />
                          <rect x={L} y={y + 6} width={(W - L - R) * (real(r.p) / 100)} height={RH - 12} rx="4" fill={r.color} opacity="0.85" />
                          <text x={L + 8} y={y + 17} fontSize="11" fill="#0f172a">{real(r.p)} % · dates du projet non renseignées</text>
                        </>
                      )}
                      {r.p.late.filter((a) => a.due).map((a) => (
                        <circle key={a.id} cx={x(d(a.due)!.getTime())} cy={y + RH / 2} r="4.5" fill="#e5484d" stroke="#fff" strokeWidth="1.5">
                          <title>{`En retard : ${a.title} (échéance ${fr(a.due)})`}</title>
                        </circle>
                      ))}
                      {r.p.milestones.map((m) => {
                        const t = d(m.date)!.getTime();
                        return <path key={m.title + m.date} d={`M${x(t)} ${y + 4} l6 9 l-6 9 l-6 -9 z`} fill="#0f172a"><title>{m.title}</title></path>;
                      })}
                    </g>
                  );
                }
                const ph = r.ph!;
                const s = d(ph.start)?.getTime(), e = d(ph.end)?.getTime(), re = d(ph.realEnd)?.getTime();
                const col = PH[ph.status] ?? "#94a3b8";
                return (
                  <g key={`ph${r.p.project.id}-${ph.id}`}>
                    <text x="20" y={y + 17} fontSize="11.5" fill="#334155">{ph.name.slice(0, 30)}</text>
                    {!(s && e) && (
                      <>
                        <rect x={L} y={y + 7} width={W - L - R} height={RH - 14} rx="3" fill={col} opacity="0.12" strokeDasharray="3 3" stroke={col} />
                        <rect x={L} y={y + 7} width={(W - L - R) * (ph.progress / 100)} height={RH - 14} rx="3" fill={col} opacity="0.8" />
                        <text x={W - R - 4} y={y + 17} fontSize="10.5" fill="#64748b" textAnchor="end">{ph.progress} % · sans dates</text>
                      </>
                    )}
                    {s && e && (
                      <>
                        <rect x={x(s)} y={y + 7} width={Math.max(3, x(e) - x(s))} height={RH - 14} rx="3" fill={col} opacity="0.25" />
                        <rect x={x(s)} y={y + 7} width={Math.max(0, (x(e) - x(s)) * (ph.progress / 100))} height={RH - 14} rx="3" fill={col} />
                        {re && re > e && <rect x={x(e)} y={y + 10} width={x(re) - x(e)} height={RH - 20} fill="#e5484d" opacity="0.5" />}
                        <text x={Math.max(x(e), re ? x(re) : 0) + 4} y={y + 17} fontSize="10.5" fill="#64748b">{ph.progress} %</text>
                      </>
                    )}
                  </g>
                );
              })}
              <line x1={x(axis.today)} x2={x(axis.today)} y1={TOP - 6} y2={H - 6} stroke="#e5484d" strokeWidth="2" strokeDasharray="4 3" />
              <text x={x(axis.today) + 4} y={H - 4} fontSize="10.5" fill="#e5484d">Aujourd’hui</text>
            </svg>
            <div className="pf-legend">
              <span><i style={{ background: PH.done }} /> Terminé</span>
              <span><i style={{ background: PH.doing }} /> En cours</span>
              <span><i style={{ background: PH.late }} /> En retard</span>
              <span><i style={{ background: PH.todo }} /> À venir</span>
              <span>◆ Jalon</span>
              <span><i style={{ background: "#e5484d", borderRadius: "50%", width: 9, height: 9 }} /> Action en retard (échéance)</span>
              <span><i style={{ background: "#e5484d", opacity: 0.5 }} /> Glissement</span>
            </div>
          </div>

          {data.projects.map((p, i) => (
            <div key={p.project.id} className="pf-proj" style={{ borderLeftColor: COLORS[i % COLORS.length] }}>
              <h3>
                {p.project.name} <small className="faint">({p.project.code})</small>
                <a className="btn ghost sm no-print" href={`#projets/${encodeURIComponent(p.project.id)}`}>Ouvrir →</a>
              </h3>
              <div className="pf-cols">
                <div>
                  <h4>⛔ Actions en retard ({p.lateCount})</h4>
                  {p.late.length === 0 ? <div className="faint">Aucune</div> : (
                    <ul>{p.late.map((a) => <li key={a.id}><b>{a.title}</b><small>{a.owner ?? "Non affectée"} · échéance {fr(a.due)} · <span className="crit">+{a.lateDays} j</span></small></li>)}</ul>
                  )}
                </div>
                <div>
                  <h4>🔄 Actions en cours ({p.doingCount})</h4>
                  {p.doing.length === 0 ? <div className="faint">Aucune</div> : (
                    <ul>{p.doing.map((a) => <li key={a.id}><b>{a.title}</b><small>{a.owner ?? "Non affectée"} · échéance {fr(a.due)}</small></li>)}</ul>
                  )}
                </div>
                <div>
                  <h4>🎯 {p.phases.length ? "Phases clés" : "Lots (déduits des actions)"} ({keyPhases(p).length})</h4>
                  {keyPhases(p).length === 0 ? <div className="faint">Pas de planning macro saisi</div> : (
                    <ul>{keyPhases(p).map((ph) => (
                      <li key={ph.id}>
                        <b><i className="pf-dot" style={{ background: PH[ph.status] ?? "#94a3b8" }} />{ph.name}</b>
                        <small>{ph.start || ph.end ? `${fr(ph.start)} → ${fr(ph.realEnd ?? ph.end)} · ` : "sans dates · "}{ph.statusLabel} · {ph.progress} %{ph.slipDays > 0 ? ` · glissement ${ph.slipDays} j` : ""}{ph.late ? ` · ${ph.late} en retard` : ""}</small>
                      </li>
                    ))}</ul>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
