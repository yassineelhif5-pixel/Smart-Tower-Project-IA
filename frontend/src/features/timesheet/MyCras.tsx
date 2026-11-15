// Mes CRA : arborescence Projet › Mois › versions générées, avec téléchargement (PDF).
import { useMemo, useState } from "react";

import { API_BASE, api } from "../../api/client";
import { useApi } from "../../api/useApi";
import { DocInfoPanel } from "../../components/DocInfoPanel";
import { DocViewer } from "../../components/DocViewer";
import { Card, useAction } from "../../components/ui";

type Cra = { id: string; name: string; period: string; periodLabel: string; client: string; projects: { code: string; name: string }[]; version: number;
  latest: boolean; days: string | number | null; createdAt: string; generatedBy: string; approvers: string[]; format: string; noInvoice: string; download: string; code?: string };

export function MyCras() {
  const r = useApi(() => api.get<{ cras: Cra[] }>("/timesheets/my-cras"));
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [old, setOld] = useState(false);
  const [view, setView] = useState<Cra | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const { run, busy } = useAction();
  const regenerate = (c: Cra) => {
    if (!window.confirm(`Régénérer le CRA ${c.client} de ${c.periodLabel} ? Une nouvelle version (v${c.version + 1}) sera créée à partir des saisies validées ; la facture garde son numéro.`)) return;
    void run(() => api.post<{ version: number }>(`/timesheets/my-cras/${encodeURIComponent(c.id)}/regenerate`, {}), "CRA régénéré : nouvelle version disponible")
      .then(() => r.reload(), () => undefined);
  };
  const tree = useMemo(() => {
    const t = new Map<string, { name: string; months: Map<string, { label: string; items: Cra[] }> }>();
    for (const c of r.data?.cras ?? []) {
      if (!old && !c.latest) continue;
      for (const p of c.projects) {
        if (!t.has(p.code)) t.set(p.code, { name: p.name, months: new Map() });
        const months = t.get(p.code)!.months;
        if (!months.has(c.period)) months.set(c.period, { label: c.periodLabel, items: [] });
        months.get(c.period)!.items.push(c);
      }
    }
    return [...t.entries()].sort();
  }, [r.data, old]);
  const toggle = (k: string) => setOpen({ ...open, [k]: !(open[k] ?? true) });
  const isOpen = (k: string, dflt = true) => open[k] ?? dflt;
  if (!r.data) return null;
  return (
    <Card title="Mes CRA" sub="Vos comptes rendus d'activité générés, classés par projet puis par mois."
      extra={<label className="vb-check"><input type="checkbox" checked={old} onChange={(e) => setOld(e.target.checked)} /> Versions précédentes</label>}>
      {tree.length === 0 ? <p className="muted">Aucun CRA généré pour l'instant.</p> : (
        <ul className="cra-tree">
          {tree.map(([code, p]) => (
            <li key={code}>
              <button type="button" className="cra-node" onClick={() => toggle(code)} aria-expanded={isOpen(code)}>
                {isOpen(code) ? "▾" : "▸"} 📁 <b>{code}</b> <span className="muted">{p.name !== code ? p.name : ""} · {p.months.size} mois</span>
              </button>
              {isOpen(code) && (
                <ul>
                  {[...p.months.entries()].sort((a, b) => b[0].localeCompare(a[0])).map(([m, mo]) => {
                    const k = `${code}|${m}`;
                    return (
                      <li key={m}>
                        <button type="button" className="cra-node" onClick={() => toggle(k)} aria-expanded={isOpen(k, false)}>
                          {isOpen(k, false) ? "▾" : "▸"} 🗓️ <span style={{ textTransform: "capitalize" }}>{mo.label}</span> <span className="muted">({mo.items.length})</span>
                        </button>
                        {isOpen(k, false) && (
                          <ul>
                            {mo.items.map((c) => (
                              <li key={c.id} className="cra-leaf">
                                <span>{c.format === "pdf" ? "📕" : "📄"} {c.name}</span>
                                <span className="muted" style={{ fontSize: 12 }}>
                                  v{c.version}{c.latest ? "" : " (ancienne)"} · {c.client} · {Number(c.days ?? 0).toLocaleString("fr-FR")} j · généré le {new Date(c.createdAt).toLocaleDateString("fr-FR")}
                                  {c.generatedBy ? ` par ${c.generatedBy}` : ""}{c.approvers.length ? ` · validé par ${c.approvers.join(", ")}` : ""}{c.noInvoice ? " · sans facture" : ""}
                                </span>
                                <span style={{ display: "inline-flex", gap: 6 }}>
                                  <button type="button" className="btn sm primary" onClick={() => setView(c)}>👁️ Voir</button>
                                  <a className="btn sm" href={`${API_BASE}${c.download}`}>Télécharger</a>
                                  {c.latest && <button type="button" className="btn sm" disabled={busy} onClick={() => regenerate(c)}>↻ Régénérer</button>}
                                  <button type="button" className="btn sm" title={`Informations et historique · ${c.code ?? ""}`} onClick={() => setInfo(c.id)}>ℹ️</button>
                                </span>
                              </li>
                            ))}
                          </ul>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
      {info && <DocInfoPanel docRef={info} onClose={() => setInfo(null)} onOpenVersion={(id) => setInfo(id)} />}
      {view && (
        <DocViewer title={`CRA ${view.client} — ${view.periodLabel} (v${view.version})`} url={view.download} docRef={view.id} onClose={() => setView(null)}
          meta={`${Number(view.days ?? 0).toLocaleString("fr-FR")} j · généré le ${new Date(view.createdAt).toLocaleString("fr-FR")}${view.generatedBy ? ` par ${view.generatedBy}` : ""}${view.approvers.length ? ` · validé par ${view.approvers.join(", ")}` : ""}${view.noInvoice ? ` · ${view.noInvoice}` : ""}`} />
      )}
    </Card>
  );
}
