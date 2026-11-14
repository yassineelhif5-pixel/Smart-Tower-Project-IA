import { createPortal } from "react-dom";
import { useEffect, useState } from "react";

import { api, API_BASE } from "../../api/client";

type ViewDoc = { id: string; name: string; ext: string; typeLabel: string; version: number; hasFile: boolean; uploadedBy: string | null; uploadedAt: string | null };
type TextResp = { text: string; description: string; extraction: { summary?: string; words?: number; pages?: number } };

const IMAGES = ["png", "jpg", "jpeg", "gif", "webp", "bmp"];
const NATIVE = ["pdf", "txt", "csv", "md"];

/** Fenêtre « Consulter le document » : aperçu dans l'application (PDF, images, texte) ou texte extrait (Word, Excel, PowerPoint…). */
export function DocViewer({ projectId, doc, onClose }: { projectId: string; doc: ViewDoc; onClose: () => void }) {
  const ext = (doc.ext || "").toLowerCase();
  const url = `${API_BASE}/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(doc.id)}`;
  const native = doc.hasFile && (IMAGES.includes(ext) || NATIVE.includes(ext));
  const [mode, setMode] = useState<"preview" | "text">(native ? "preview" : "text");
  const [text, setText] = useState<TextResp | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (mode !== "text" || text) return;
    api.get<TextResp>(`/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(doc.id)}?text=1`).then(setText, () => setError(true));
  }, [mode, text, projectId, doc.id]);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  return createPortal(
    <div className="scrim" onClick={onClose}>
      <div className="modal dv-modal" role="dialog" aria-label={`Consulter ${doc.name}`} onClick={(e) => e.stopPropagation()}>
        <div className="modal-h">
          <div style={{ minWidth: 0 }}>
            <h3 className="dv-title">📄 {doc.name}</h3>
            <small className="faint">
              {doc.typeLabel} · v{doc.version} · {ext.toUpperCase() || "—"}
              {doc.uploadedBy ? ` · ${doc.uploadedBy}` : ""}
              {doc.uploadedAt ? ` · ${new Date(doc.uploadedAt).toLocaleDateString("fr-FR")}` : ""}
            </small>
          </div>
          <div className="btns">
            {native && (
              <div className="seg" role="tablist">
                <button type="button" className={mode === "preview" ? "on" : ""} onClick={() => setMode("preview")}>Aperçu</button>
                <button type="button" className={mode === "text" ? "on" : ""} onClick={() => setMode("text")}>Texte extrait</button>
              </div>
            )}
            {doc.hasFile && (
              <>
                <a className="btn ghost sm" href={`${url}?inline=1`} target="_blank" rel="noopener noreferrer">Nouvel onglet</a>
                <a className="btn sm" href={url}>Télécharger</a>
              </>
            )}
            <button className="icon-btn" type="button" aria-label="Fermer" onClick={onClose}>✕</button>
          </div>
        </div>
        <div className="dv-body">
          {mode === "preview" && native ? (
            IMAGES.includes(ext) ? (
              <div className="dv-img"><img src={`${url}?inline=1`} alt={doc.name} /></div>
            ) : (
              <iframe className="dv-frame" title={doc.name} src={`${url}?inline=1`} />
            )
          ) : error ? (
            <div className="empty">Impossible de charger le contenu du document.</div>
          ) : !text ? (
            <div className="empty">Chargement du contenu…</div>
          ) : (
            <div className="dv-text">
              {!native && (
                <div className="dv-note">
                  Aperçu du contenu ({ext.toUpperCase()}) : le texte du document est affiché ci-dessous. Pour la mise en page d’origine, utilisez « Télécharger ».
                </div>
              )}
              {text.description && <p className="muted">{text.description}</p>}
              {text.text.trim() ? <pre>{text.text}</pre> : <div className="empty">Aucun texte lisible dans ce document.</div>}
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
