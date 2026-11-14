/** Glisser-déposer de fichiers : zone de dépôt (clic ou glisser) et hook pour accepter un dépôt sur n'importe quel bloc. */
import { useRef, useState, type DragEvent, type ReactNode } from "react";

const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");

/** Accepte des fichiers glissés sur un élément : `bind` à étaler sur le bloc, `dragging` pour l'afficher en surbrillance. */
export function useFileDrop(onFiles: (files: File[]) => void, disabled = false) {
  const [dragging, setDragging] = useState(false);
  const depth = useRef(0);
  const bind = {
    onDragEnter: (e: DragEvent) => {
      if (disabled || !hasFiles(e)) return;
      e.preventDefault();
      depth.current += 1;
      setDragging(true);
    },
    onDragOver: (e: DragEvent) => {
      if (disabled || !hasFiles(e)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
    },
    onDragLeave: (e: DragEvent) => {
      if (disabled || !hasFiles(e)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setDragging(false);
    },
    onDrop: (e: DragEvent) => {
      if (disabled || !hasFiles(e)) return;
      e.preventDefault();
      depth.current = 0;
      setDragging(false);
      const files = Array.from(e.dataTransfer.files ?? []);
      if (files.length) onFiles(files);
    },
  };
  return { dragging, bind };
}

/** Zone « Glissez vos fichiers ici ou cliquez pour choisir ». */
export function DropZone({
  onFiles, multiple = false, accept, disabled = false, title, hint, files, icon = "📎", compact = false,
}: {
  onFiles: (files: File[]) => void; multiple?: boolean; accept?: string; disabled?: boolean; title?: ReactNode; hint?: ReactNode;
  files?: File[]; icon?: string; compact?: boolean;
}) {
  const { dragging, bind } = useFileDrop((fs) => onFiles(multiple ? fs : fs.slice(0, 1)), disabled);
  const input = useRef<HTMLInputElement>(null);
  const names = (files ?? []).map((f) => f.name);
  return (
    <label className={`dz${dragging ? " over" : ""}${compact ? " compact" : ""}${disabled ? " off" : ""}${names.length ? " has" : ""}`} {...bind}>
      <input ref={input} type="file" multiple={multiple} accept={accept} disabled={disabled}
        onChange={(e) => { const fs = Array.from(e.target.files ?? []); if (fs.length) onFiles(fs); e.target.value = ""; }} />
      <span className="dz-ic">{dragging ? "⬇️" : icon}</span>
      <span className="dz-txt">
        <b>{dragging ? "Déposez pour ajouter" : names.length ? names.length > 1 ? `${names.length} fichiers sélectionnés` : names[0] : title ?? "Glissez vos fichiers ici"}</b>
        <small>{names.length > 1 ? names.join(" · ") : hint ?? (multiple ? "ou cliquez pour choisir (plusieurs fichiers possibles)" : "ou cliquez pour choisir")}</small>
      </span>
    </label>
  );
}
