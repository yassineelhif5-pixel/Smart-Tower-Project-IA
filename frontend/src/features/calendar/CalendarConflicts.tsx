import { Icon, Modal, Pill } from "../../components/ui";
import type { Conflict } from "../../types/collab";

export const CONFLICT_LABEL: Record<Conflict["type"], string> = {
  double_booking: "Double affectation",
  overload: "Surcharge",
  unassigned: "Sans responsable",
  dependency: "Dépendance",
  deadline: "Échéance du projet",
  late: "Retard",
};

export function suggestionText(c: Conflict) {
  const s = c.suggestion;
  if (!s) return null;
  if (s.action === "assign") return "Désigner un responsable";
  const f = (v?: string) =>
    v
      ? s.allDay
        ? new Date(`${v.slice(0, 10)}T12:00`).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" })
        : new Date(v).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
      : "";
  return `${s.action === "extend" ? "Allonger" : "Déplacer"} : ${f(s.start)} → ${f(s.end)}`;
}

/** Conflits détectés avant enregistrement : rien n'est modifié tant que l'utilisateur n'a pas choisi. */
export function ConflictDialog({
  conflicts,
  onConfirm,
  onApply,
  onCancel,
  busy,
}: {
  conflicts: Conflict[];
  onConfirm: () => void;
  onApply: (c: Conflict) => void;
  onCancel: () => void;
  busy: boolean;
}) {
  return (
    <Modal
      title="Conflits de planning"
      onClose={onCancel}
      footer={
        <>
          <button className="btn" onClick={onCancel} disabled={busy}>
            Annuler la modification
          </button>
          <button className="btn primary" onClick={onConfirm} disabled={busy}>
            Enregistrer malgré tout
          </button>
        </>
      }
    >
      <p className="muted" style={{ marginTop: 0 }}>
        Cette modification crée {conflicts.length > 1 ? `${conflicts.length} conflits` : "un conflit"}. Rien n'a été
        enregistré : choisissez une proposition, confirmez tel quel ou annulez.
      </p>
      <ul className="conflicts">
        {conflicts.map((c, i) => (
          <li key={i} className={c.severity}>
            <Icon name="alert" size={16} />
            <div>
              <div>
                <Pill tone={c.severity === "critical" ? "crit" : "warn"}>{CONFLICT_LABEL[c.type]}</Pill>{" "}
                <b>{c.title}</b>
              </div>
              <p>{c.explanation}</p>
              {c.suggestion && c.suggestion.action !== "assign" && (
                <button className="btn sm" onClick={() => onApply(c)} disabled={busy}>
                  Appliquer la proposition — {suggestionText(c)}
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </Modal>
  );
}
