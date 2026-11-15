// Visionneuse de documents en fenêtre : PDF affiché tel quel, Word (.docx) converti en aperçu HTML par le serveur.
import { useEffect, useState, type ReactNode } from "react";

import { API_BASE } from "../api/client";
import { DocInfoPanel } from "./DocInfoPanel";
import { Modal } from "./ui";

export function DocViewer({ title, url, meta, onClose, docRef }: { title: string; url: string; meta?: ReactNode; onClose: () => void; docRef?: string }) {
  const [info, setInfo] = useState(false);
  const [state, setState] = useState<{ kind: "loading" | "pdf" | "html" | "none" | "error"; src?: string; html?: string }>({ kind: "loading" });
  useEffect(() => {
    let blobUrl: string | null = null;
    const sep = url.includes("?") ? "&" : "?";
    (async () => {
      try {
        const p = await fetch(`${API_BASE}${url}${sep}preview=1`, { credentials: "include" });
        if (!p.ok) throw new Error(String(p.status));
        const info = (await p.json()) as { kind: string; html?: string };
        if (info.kind === "pdf") {
          const b = await (await fetch(`${API_BASE}${url}`, { credentials: "include" })).blob();
          blobUrl = URL.createObjectURL(new Blob([b], { type: "application/pdf" }));
          setState({ kind: "pdf", src: blobUrl });
        } else if (info.kind === "html") setState({ kind: "html", html: info.html });
        else setState({ kind: "none" });
      } catch {
        setState({ kind: "error" });
      }
    })();
    return () => { if (blobUrl) URL.revokeObjectURL(blobUrl); };
  }, [url]);
  const frame = { width: "100%", height: "72vh", border: "1px solid var(--line, #e2e8f0)", borderRadius: 8, background: "#fff" } as const;
  return (
    <Modal wide title={title} onClose={onClose}
      footer={<>{docRef && <button type="button" className="btn" onClick={() => setInfo(true)}>ℹ️ Historique</button>}<a className="btn" href={`${API_BASE}${url}`}>Télécharger</a><button type="button" className="btn primary" onClick={onClose}>Fermer</button></>}>
      {meta && <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>{meta}</div>}
      {state.kind === "loading" && <p className="muted">Chargement de l'aperçu…</p>}
      {state.kind === "error" && <p className="muted">Impossible d'afficher ce document.</p>}
      {state.kind === "none" && <p className="muted">Aperçu indisponible pour ce format : téléchargez le document.</p>}
      {state.kind === "pdf" && <iframe title="Aperçu du document" src={state.src} style={frame} />}
      {state.kind === "html" && <iframe title="Aperçu du document" sandbox="" srcDoc={state.html} style={frame} />}
      {info && docRef && <DocInfoPanel docRef={docRef} onClose={() => setInfo(false)} />}
      {state.kind === "html" && <p className="muted" style={{ fontSize: 11, marginTop: 6 }}>Aperçu simplifié d'un document Word : la mise en page exacte est dans le fichier téléchargé.</p>}
    </Modal>
  );
}
