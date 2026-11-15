// Panneau d'information d'un document : type, client, personne, dates, versions, historique (journal) et code technique.
import { useState } from "react";

import { api } from "../api/client";
import { useApi } from "../api/useApi";

type Info = { code: string; name: string; type: string; fields: [string, string][]; createdAt: string | null; updatedAt?: string | null;
  versions: { id: string; version: number; name: string; createdAt: string; by: string; code: string; current: boolean }[];
  events: { at: string; by: string; event: string; detail: string }[] };
const dt = (s?: string | null) => (s ? new Date(s).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");

export function DocInfoPanel({ docRef, onClose, onOpenVersion }: { docRef: string; onClose: () => void; onOpenVersion?: (id: string) => void }) {
  const r = useApi(() => api.get<Info>(`/client-space/doc-info?ref=${encodeURIComponent(docRef)}`), [docRef]);
  const [copied, setCopied] = useState(false);
  const d = r.data;
  const copy = () => { if (d) void navigator.clipboard?.writeText(d.code).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }); };
  return (
    <div className="scrim" onClick={onClose} style={{ zIndex: 1100 }}>
      <aside role="dialog" aria-label="Informations du document" onClick={(e) => e.stopPropagation()}
        style={{ position: "fixed", top: 0, right: 0, bottom: 0, width: "min(440px, 100%)", background: "var(--surface, #fff)", boxShadow: "-8px 0 30px rgba(15,23,42,.18)",
          display: "flex", flexDirection: "column" }}>
        <header style={{ padding: "14px 16px", borderBottom: "1px solid var(--line, #e2e8f0)", display: "flex", justifyContent: "space-between", gap: 8 }}>
          <div style={{ minWidth: 0 }}><div className="muted" style={{ fontSize: 12 }}>ℹ️ {d?.type ?? "Document"}</div><b style={{ wordBreak: "break-all" }}>{d?.name ?? "…"}</b></div>
          <button type="button" className="btn sm ghost" onClick={onClose} aria-label="Fermer">✕</button>
        </header>
        <div style={{ flex: 1, overflow: "auto", padding: "12px 16px" }}>
          {r.error ? <p className="muted">Informations indisponibles.</p> : !d ? <p className="muted">Chargement…</p> : (
            <>
              <table className="tbl tight"><tbody>
                {d.fields.map(([k, v]) => <tr key={k}><td className="muted" style={{ width: 120 }}>{k}</td><td>{v}</td></tr>)}
                <tr><td className="muted">Créé le</td><td>{dt(d.createdAt)}</td></tr>
                {d.updatedAt && <tr><td className="muted">Modifié le</td><td>{dt(d.updatedAt)}</td></tr>}
              </tbody></table>
              {d.versions.length > 1 && (
                <>
                  <h4 style={{ margin: "14px 0 6px" }}>Versions ({d.versions.length})</h4>
                  <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 4 }}>
                    {d.versions.map((v) => (
                      <li key={v.id} style={{ fontSize: 12, padding: "4px 6px", borderRadius: 6, background: v.current ? "var(--surface-2, #eef2ff)" : undefined }}>
                        <b>v{v.version}</b> · {dt(v.createdAt)}{v.by ? ` · ${v.by}` : ""}{v.current ? " · (ce document)" : ""}
                        {onOpenVersion && !v.current && <button type="button" className="btn sm ghost" style={{ marginLeft: 6 }} onClick={() => onOpenVersion(v.id)}>voir</button>}
                        <div className="muted" style={{ fontFamily: "monospace", fontSize: 11 }}>{v.code}</div>
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <h4 style={{ margin: "14px 0 6px" }}>Historique</h4>
              {d.events.length === 0 ? <p className="muted">Aucun événement enregistré.</p> : (
                <ol style={{ listStyle: "none", padding: 0, margin: 0, borderLeft: "2px solid var(--line, #e2e8f0)" }}>
                  {d.events.map((e, i) => (
                    <li key={i} style={{ padding: "4px 0 6px 10px", fontSize: 12 }}>
                      <b>{e.event}</b> <span className="muted">· {dt(e.at)} · {e.by}</span>
                      {e.detail && <div className="muted" style={{ wordBreak: "break-word" }}>{e.detail}</div>}
                    </li>
                  ))}
                </ol>
              )}
            </>
          )}
        </div>
        {d && (
          <footer style={{ padding: "10px 16px", borderTop: "1px solid var(--line, #e2e8f0)", background: "var(--surface-2, #f8fafc)" }}>
            <div className="muted" style={{ fontSize: 11 }}>Code technique</div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <code style={{ fontSize: 13, fontWeight: 600, wordBreak: "break-all", flex: 1 }}>{d.code}</code>
              <button type="button" className="btn sm" onClick={copy}>{copied ? "Copié ✓" : "Copier"}</button>
            </div>
          </footer>
        )}
      </aside>
    </div>
  );
}
