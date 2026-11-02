import { useState } from "react";

import { discussionApi } from "../../api/collab";
import { fmtDate, Icon, Modal, Pill, useAction } from "../../components/ui";
import type { Message } from "../../types/collab";
import { initials } from "../calendar/calendarUtils";

const STATUS: Record<Message["publicationStatus"], [string, "ok" | "warn" | "crit" | "info" | ""]> = {
  internal: ["Interne", ""],
  pending: ["Envoi…", "info"],
  published: ["Publié dans Teams", "ok"],
  failed: ["Échec Teams", "crit"],
};

/** Un message : auteur, texte, mentions, pièces jointes, état de publication ; actions de l'auteur. */
export function DiscussionMessage({
  message,
  parent,
  onReply,
  onChanged,
  showStatus,
}: {
  message: Message;
  parent?: Message;
  onReply: (m: Message) => void;
  onChanged: () => void;
  showStatus: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(message.body);
  const [history, setHistory] = useState<{ at: string; body: string; deleted?: boolean }[] | null>(null);
  const { run, busy } = useAction();
  const m = message;
  const who = m.author?.name ?? m.externalAuthor ?? "Utilisateur Teams";

  if (m.kind === "system")
    return (
      <div className="msg-sys" role="note">
        {m.body} · {fmtDate(m.createdAt)}
      </div>
    );

  return (
    <article className={`msg ${m.mine ? "mine" : ""} ${m.deleted ? "deleted" : ""}`} aria-label={`Message de ${who}`}>
      <span className="av sm" aria-hidden="true">
        {initials(who)}
      </span>
      <div className="msg-b">
        <header>
          <b>{who}</b>
          {m.origin === "teams" && <Pill tone="info">Teams</Pill>}
          <time dateTime={m.createdAt}>{fmtDate(m.createdAt)}</time>
          {m.editedAt && !m.deleted && <span className="muted">· modifié</span>}
          {showStatus && m.origin === "pct" && !m.deleted && (
            <Pill tone={STATUS[m.publicationStatus][1]}>{STATUS[m.publicationStatus][0]}</Pill>
          )}
        </header>
        {parent && (
          <blockquote className="msg-quote">
            {parent.author?.name ?? parent.externalAuthor} :{" "}
            {parent.deleted ? "message supprimé" : parent.body.slice(0, 120)}
          </blockquote>
        )}
        {editing ? (
          <div className="msg-edit">
            <textarea
              className="inp"
              rows={3}
              value={text}
              aria-label="Modifier le message"
              onChange={(e) => setText(e.target.value)}
            />
            <div className="btns">
              <button className="btn sm" onClick={() => setEditing(false)}>
                Annuler
              </button>
              <button
                className="btn sm primary"
                disabled={busy || !text.trim()}
                onClick={() =>
                  void run(() => discussionApi.edit(m.id, text), "Message modifié").then(
                    () => {
                      setEditing(false);
                      onChanged();
                    },
                    () => undefined,
                  )
                }
              >
                Enregistrer
              </button>
            </div>
          </div>
        ) : (
          <p className="msg-t">{m.deleted ? <i className="muted">Message supprimé</i> : m.body}</p>
        )}
        {!m.deleted && (m.mentions.length > 0 || m.attachments.length > 0) && (
          <div className="msg-meta">
            {m.mentions.map((u) => (
              <span key={u.id} className="mention">
                @{u.name}
              </span>
            ))}
            {m.attachments.map((a) => (
              <span key={a.id} className="attach">
                <Icon name="paperclip" size={13} /> {a.name}
                {a.ext && !a.name.endsWith(a.ext) ? `.${a.ext}` : ""}
              </span>
            ))}
          </div>
        )}
        {m.publicationError && (
          <small className={m.publicationStatus === "failed" ? "t-crit" : "muted"}>{m.publicationError}</small>
        )}
        {!m.deleted && !editing && (
          <div className="msg-actions">
            <button className="link" onClick={() => onReply(m)}>
              <Icon name="reply" size={13} /> Répondre
            </button>
            {m.canEdit && (
              <button className="link" onClick={() => setEditing(true)}>
                <Icon name="edit" size={13} /> Modifier
              </button>
            )}
            {m.mine && m.kind === "message" && (
              <button
                className="link"
                onClick={() =>
                  window.confirm("Supprimer ce message ?") &&
                  void run(() => discussionApi.remove(m.id), "Message supprimé").then(onChanged, () => undefined)
                }
              >
                <Icon name="trash" size={13} /> Supprimer
              </button>
            )}
            {m.canRetry && (
              <button
                className="link"
                disabled={busy}
                onClick={() => void run(() => discussionApi.retry(m.id)).then(onChanged, () => undefined)}
              >
                <Icon name="refresh" size={13} /> Renvoyer dans Teams
              </button>
            )}
            {m.mine && m.historyCount > 0 && (
              <button
                className="link"
                onClick={() => void discussionApi.history(m.id).then((h) => setHistory(h.history))}
              >
                Historique ({m.historyCount})
              </button>
            )}
          </div>
        )}
      </div>
      {history && (
        <Modal title="Historique du message" onClose={() => setHistory(null)}>
          <ol className="plain">
            {history.map((h, i) => (
              <li key={i}>
                <small className="muted">
                  {fmtDate(h.at)}
                  {h.deleted ? " · supprimé" : ""}
                </small>
                <p>{h.body}</p>
              </li>
            ))}
          </ol>
        </Modal>
      )}
    </article>
  );
}
