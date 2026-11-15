// Documentation de l'Espace client classée par projet : pour chaque projet, ses documents par catégorie
// (CRA, factures, commandes, rapports budgétaires, contrats…), recherchables et filtrables.
import { useMemo, useState } from "react";

import { API_BASE, api } from "../../api/client";
import { useApi } from "../../api/useApi";
import { DocInfoPanel } from "../../components/DocInfoPanel";
import { DocViewer } from "../../components/DocViewer";

type Item = { id: string; category: string; title: string; client: string; period: string; periodLabel: string; person: string; number?: string;
  version?: number; amount?: string | number | null; status?: string; date: string; projects: string[]; projectRefs: string[]; note?: string; craId?: string | null; code?: string; ref?: string; download: string | null };
type Proj = { code: string; name: string; client: string; status: string; count: number };
type Data = { items: Item[]; categories: { code: string; label: string; count: number }[]; projects: Proj[] };
const ICON: Record<string, string> = { cra: "📄", invoice: "🧾", order: "🛒", budget: "📊", contract: "📑", other: "📁" };
const eur = (v: Item["amount"]) => (v === null || v === undefined || v === "" ? "" : Number(v).toLocaleString("fr-FR", { style: "currency", currency: "EUR" }));

export function Library() {
  const r = useApi(() => api.get<Data>("/client-space/library"));
  const [proj, setProj] = useState("all");
  const [cat, setCat] = useState("all");
  const [q, setQ] = useState("");
  const [year, setYear] = useState("");
  const [closed, setClosed] = useState<Record<string, boolean>>({});
  const [allVersions, setAllVersions] = useState(false);
  const [view, setView] = useState<Item | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const items = r.data?.items ?? [];
  const cats = r.data?.categories ?? [];
  const years = useMemo(() => [...new Set(items.map((i) => (i.period || i.date || "").slice(0, 4)).filter(Boolean))].sort().reverse(), [items]);
  const vkey = (i: Item) => `${i.category}|${i.client}|${i.person}|${i.period}`;
  const latest = useMemo(() => {
    const m = new Map<string, number>();
    for (const i of items) if (i.version) m.set(vkey(i), Math.max(m.get(vkey(i)) ?? 0, i.version));
    return m;
  }, [items]);
  const match = (i: Item) => (allVersions || !i.version || latest.get(vkey(i)) === i.version) && (cat === "all" || i.category === cat) && (!year || (i.period || i.date).startsWith(year))
    && (!q || `${i.title} ${i.client} ${i.person} ${i.number ?? ""} ${i.projects.join(" ")}`.toLowerCase().includes(q.toLowerCase()));
  const projects = (r.data?.projects ?? []).filter((p) => proj === "all" || p.code === proj);
  if (!r.data) return <section className="cs-card"><p className="muted">Chargement…</p></section>;
  const toggle = (k: string) => setClosed({ ...closed, [k]: !closed[k] });
  return (
    <section className="cs-card" style={{ display: "grid", gridTemplateColumns: "minmax(180px, 240px) 1fr", gap: 16 }}>
      <nav aria-label="Projets" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <b style={{ marginBottom: 6 }}>📚 Documentation</b>
        <button type="button" className={`btn sm ${proj === "all" ? "primary" : "ghost"}`} style={{ display: "flex", justifyContent: "space-between" }} onClick={() => setProj("all")}>
          <span>🗂️ Tous les projets</span><span>{items.length}</span>
        </button>
        {r.data.projects.map((p) => (
          <button key={p.code} type="button" className={`btn sm ${proj === p.code ? "primary" : "ghost"}`} title={p.client}
            style={{ display: "flex", justifyContent: "space-between", textAlign: "left", gap: 6 }} onClick={() => setProj(p.code)}>
            <span>📁 {p.name}</span><span>{p.count}</span>
          </button>
        ))}
      </nav>
      <div>
        <div className="vb-bar" style={{ marginBottom: 8 }}>
          <input className="inp" style={{ flex: 1, minWidth: 200 }} placeholder="Rechercher (consultant, n°, client…)" aria-label="Rechercher" value={q} onChange={(e) => setQ(e.target.value)} />
          <select className="inp" style={{ width: "auto" }} aria-label="Année" value={year} onChange={(e) => setYear(e.target.value)}>
            <option value="">Toutes les années</option>{years.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
          <label className="vb-check"><input type="checkbox" checked={allVersions} onChange={(e) => setAllVersions(e.target.checked)} /> Versions précédentes</label>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 12 }}>
          {[{ code: "all", label: "Tous les types", count: items.length }, ...cats].map((c) => (
            <button key={c.code} type="button" className={`btn sm ${cat === c.code ? "primary" : ""}`} onClick={() => setCat(c.code)}>
              {ICON[c.code] ?? "🗂️"} {c.label} <span className="muted">({c.count})</span>
            </button>
          ))}
        </div>
        {projects.map((p) => {
          const docs = items.filter((i) => i.projectRefs.includes(p.code) && match(i));
          const byCat = cats.map((c) => [c, docs.filter((i) => i.category === c.code).sort((a, b) => (b.period || b.date).localeCompare(a.period || a.date))] as const)
            .filter(([, l]) => l.length);
          const open = !closed[p.code];
          return (
            <div key={p.code} className="vb-group" style={{ marginBottom: 12 }}>
              <button type="button" className="cra-node" style={{ width: "100%", display: "flex", justifyContent: "space-between" }} onClick={() => toggle(p.code)} aria-expanded={open}>
                <span>{open ? "▾" : "▸"} 📁 <b>{p.name}</b> <span className="muted">{p.code !== "_general" ? `${p.code} · ${p.client}` : "non rattachés à un projet"}</span></span>
                <span className="muted">{docs.length} document(s)</span>
              </button>
              {open && (byCat.length === 0 ? <p className="muted" style={{ margin: "4px 22px" }}>Aucun document.</p> : byCat.map(([c, list]) => (
                <div key={c.code} style={{ margin: "6px 0 10px 18px" }}>
                  <div style={{ fontWeight: 600, margin: "4px 0" }}>{ICON[c.code] ?? "📁"} {c.label} <span className="muted">({list.length})</span></div>
                  {c.code === "invoice" || c.code === "cra" ? <DocTree list={list} prefix={`${p.code}|${c.code}`} onView={setView} onInfo={setInfo} all={items} /> : (
                  <div className="tbl-wrap">
                    <table className="tbl tight">
                      <tbody>
                        {list.map((i) => (
                          <tr key={`${i.category}-${i.id}`}>
                            <td style={{ whiteSpace: "nowrap", textTransform: "capitalize", width: 130 }} className="muted">{i.periodLabel || "—"}</td>
                            <td><b>{i.title}</b><div className="muted" style={{ fontSize: 12 }}>
                              {[i.person, i.number && `n° ${i.number}`, i.version && i.version > 1 ? `v${i.version}` : "", i.status, i.note].filter(Boolean).join(" · ")}
                            </div></td>
                            <td className="r" style={{ whiteSpace: "nowrap" }}>{eur(i.amount)}</td>
                            <td style={{ whiteSpace: "nowrap", fontSize: 12 }} className="muted">{new Date(i.date).toLocaleDateString("fr-FR")}</td>
                            <td style={{ whiteSpace: "nowrap" }}>{i.download && <><button type="button" className="btn sm primary" onClick={() => setView(i)}>👁️ Voir</button> <a className="btn sm" href={`${API_BASE}${i.download}`}>Télécharger</a> </>}{i.ref && <button type="button" className="btn sm" title={`Informations et historique · ${i.code ?? ""}`} onClick={() => setInfo(i.ref!)}>ℹ️</button>}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  )}
                </div>
              )))}
            </div>
          );
        })}
        {projects.length === 0 && <p className="muted">Aucun document.</p>}
        {info && <DocInfoPanel docRef={info} onClose={() => setInfo(null)} onOpenVersion={(id) => setInfo(id)} />}
        {view && view.download && (
          <DocViewer title={view.title} url={view.download} docRef={view.ref} onClose={() => setView(null)}
            meta={[view.client, view.person, view.periodLabel, view.number && `n° ${view.number}`, view.version && `v${view.version}`, eur(view.amount)].filter(Boolean).join(" · ")} />
        )}
      </div>
    </section>
  );
}

const MONTHS = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"];

function DocRow({ i, onView, onInfo }: { i: Item; onView: (i: Item) => void; onInfo: (ref: string) => void }) {
  return (
    <div className="cra-leaf" style={{ justifyContent: "space-between" }}>
      <span style={{ minWidth: 0 }}>{ICON[i.category] ?? "📁"} {i.title}
        <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}> · {[i.number && `n° ${i.number}`, i.version && i.version > 1 ? `v${i.version}` : "", i.note, new Date(i.date).toLocaleDateString("fr-FR")].filter(Boolean).join(" · ")}</span>
      </span>
      <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
        <b style={{ whiteSpace: "nowrap" }}>{eur(i.amount)}</b>
        {i.download && <><button type="button" className="btn sm primary" onClick={() => onView(i)}>👁️ Voir</button><a className="btn sm" href={`${API_BASE}${i.download}`}>Télécharger</a></>}
        {i.ref && <button type="button" className="btn sm" title={`Informations et historique · ${i.code ?? ""}`} onClick={() => onInfo(i.ref!)}>ℹ️</button>}
      </span>
    </div>
  );
}

/** Arborescence Année › Mois › Utilisateur pour les factures et les CRA. */
function DocTree({ list, prefix, onView, onInfo, all }: { list: Item[]; prefix: string; onView: (i: Item) => void; onInfo: (ref: string) => void; all: Item[] }) {
  // Factures : le CRA correspondant (même personne, client et mois) est affiché juste en dessous.
  const craOf = (inv: Item) => all.find((x) => x.category === "cra" && x.id === inv.craId)
    ?? all.filter((x) => x.category === "cra" && x.person === inv.person && x.period === inv.period && x.client === inv.client)
      .sort((a, b) => (b.version ?? 0) - (a.version ?? 0))[0];
  const [st, setSt] = useState<Record<string, boolean>>({});
  const tree = new Map<string, Map<string, Map<string, Item[]>>>();
  for (const i of list) {
    const per = i.period || i.date.slice(0, 7);
    const y = per.slice(0, 4);
    if (!tree.has(y)) tree.set(y, new Map());
    const months = tree.get(y)!;
    if (!months.has(per)) months.set(per, new Map());
    const people = months.get(per)!;
    const who = i.person || "—";
    if (!people.has(who)) people.set(who, []);
    people.get(who)!.push(i);
  }
  const total = (xs: Item[]) => xs.reduce((a, x) => a + Number(x.amount ?? 0), 0);
  const node = (k: string, dflt: boolean) => st[k] ?? dflt;
  const flip = (k: string, dflt: boolean) => setSt({ ...st, [k]: !(st[k] ?? dflt) });
  const sumTxt = (xs: Item[]) => (xs.some((x) => x.amount !== null && x.amount !== undefined && x.amount !== "") ? ` · ${eur(total(xs))}` : "");
  return (
    <ul className="cra-tree">
      {[...tree.entries()].sort((a, b) => b[0].localeCompare(a[0])).map(([y, months], yi) => {
        const ky = `${prefix}|${y}`;
        const yItems = [...months.values()].flatMap((m) => [...m.values()].flat());
        return (
          <li key={y}>
            <button type="button" className="cra-node" onClick={() => flip(ky, yi === 0)}>{node(ky, yi === 0) ? "▾" : "▸"} 📅 <b>{y}</b> <span className="muted">({yItems.length}{sumTxt(yItems)})</span></button>
            {node(ky, yi === 0) && (
              <ul>
                {[...months.entries()].sort((a, b) => b[0].localeCompare(a[0])).map(([m, people]) => {
                  const km = `${ky}|${m}`;
                  const mItems = [...people.values()].flat();
                  return (
                    <li key={m}>
                      <button type="button" className="cra-node" onClick={() => flip(km, false)}>{node(km, false) ? "▾" : "▸"} 🗓️ {MONTHS[Number(m.slice(5, 7)) - 1] ?? m} <span className="muted">({mItems.length}{sumTxt(mItems)})</span></button>
                      {node(km, false) && (
                        <ul>
                          {[...people.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([who, docs]) => {
                            const kp = `${km}|${who}`;
                            return (
                              <li key={who}>
                                <button type="button" className="cra-node" onClick={() => flip(kp, true)}>{node(kp, true) ? "▾" : "▸"} 👤 <b>{who}</b> <span className="muted">({docs.length}{sumTxt(docs)})</span></button>
                                {node(kp, true) && <ul>{[...docs].sort((a, b) => (b.version ?? 0) - (a.version ?? 0)).map((i) => {
                                  const cra = i.category === "invoice" ? craOf(i) : undefined;
                                  return (
                                    <li key={i.id}>
                                      <DocRow i={i} onView={onView} onInfo={onInfo} />
                                      {i.category === "invoice" && (cra
                                        ? <div className="inv-cra"><span className="muted" style={{ fontSize: 11 }}>↳ CRA correspondant</span><DocRow i={cra} onView={onView} onInfo={onInfo} /></div>
                                        : <div className="inv-cra muted" style={{ fontSize: 12 }}>↳ CRA correspondant introuvable</div>)}
                                    </li>
                                  );
                                })}</ul>}
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </li>
        );
      })}
    </ul>
  );
}
