import { useEffect, useRef, useState } from "react";

import { ApiError } from "../../api/client";
import { calendarApi, discussionApi, teamsApi } from "../../api/collab";
import { useApi } from "../../api/useApi";
import { ErrorNotice, Field, fmtDate, Icon, Loading, Modal, Pill, useAction, useToast } from "../../components/ui";
import type { Destination, Discussion, DiscussionInput, Message, TeamsKind } from "../../types/collab";
import { DiscussionMessage } from "./DiscussionMessage";
import { useFileDrop } from "../../components/DropZone";
import { uploadProjectFile } from "../files/fileTools";

const newKey = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);

/** Discussions d'un projet (ou d'une action) : liste, fil de messages, rédaction, création. */
export function DiscussionPanel({
  project,
  action,
  initial,
  compact,
}: {
  project?: string;
  action?: string | null;
  initial?: number;
  compact?: boolean;
}) {
  const list = useApi(() => discussionApi.list({ project, action: action ?? undefined }), [project, action]);
  const [selected, setSelected] = useState<number | null>(initial ?? null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (selected == null && list.data?.length) setSelected(list.data[0].id);
  }, [list.data, selected]);
  useEffect(() => {
    if (initial) setSelected(initial);
  }, [initial]);

  if (list.error) return <ErrorNotice error={list.error} onRetry={list.reload} />;
  if (!list.data) return <Loading />;
  const current = list.data.find((d) => d.id === selected) ?? null;

  return (
    <div className={`disc ${compact ? "compact" : ""}`}>
      <aside className="disc-list" aria-label="Discussions">
        <button className="btn sm primary" onClick={() => setCreating(true)} disabled={!project}>
          <Icon name="plus" size={14} /> Nouvelle discussion
        </button>
        {!list.data.length && <p className="muted">Aucune discussion pour l'instant.</p>}
        {list.data.map((d) => (
          <button key={d.id} className={`disc-item ${d.id === selected ? "on" : ""}`} onClick={() => setSelected(d.id)}>
            <b>{d.title}</b>
            <small>
              {!project && `${d.project.code} · `}
              {d.destination === "internal" ? "Interne" : d.teamsKindLabel}
              {d.private ? " · privée" : ""} · {d.messageCount ?? 0} msg
            </small>
            {d.failedCount ? <Pill tone="crit">{d.failedCount} échec(s)</Pill> : null}
            {d.status === "archived" && <Pill tone="">Archivée</Pill>}
          </button>
        ))}
      </aside>
      {current ? (
        <Thread key={current.id} discussion={current} onChanged={list.reload} />
      ) : (
        <div className="empty">Sélectionnez ou créez une discussion.</div>
      )}
      {creating && project && (
        <NewDiscussion
          project={project}
          action={action ?? null}
          onClose={() => setCreating(false)}
          onCreated={(d) => {
            setCreating(false);
            list.reload();
            setSelected(d.id);
          }}
        />
      )}
    </div>
  );
}

function Thread({ discussion, onChanged }: { discussion: Discussion; onChanged: () => void }) {
  const messages = useApi(() => discussionApi.messages(discussion.id), [discussion.id]);
  const docs = useApi(() => discussionApi.documents(discussion.id), [discussion.id]);
  const [body, setBody] = useState("");
  const [replyTo, setReplyTo] = useState<Message | null>(null);
  const [mentions, setMentions] = useState<number[]>([]);
  const [attachments, setAttachments] = useState<string[]>([]);
  const [key, setKey] = useState(newKey);
  const { run, busy } = useAction();
  const toast = useToast();
  const end = useRef<HTMLDivElement>(null);
  const teams = discussion.destination !== "internal";
  const [uploading, setUploading] = useState("");
  const pick = useRef<HTMLInputElement>(null);

  // Pièces jointes glissées-déposées (ou choisies) : déposées dans les documents du projet puis jointes au message.
  const attachFiles = async (files: File[]) => {
    const added: string[] = [];
    for (const [i, f] of files.entries()) {
      setUploading(files.length > 1 ? `Envoi ${i + 1}/${files.length} : ${f.name}…` : `Envoi de ${f.name}…`);
      try {
        const d = await uploadProjectFile(discussion.project.id, f, { attachment: "1", type: "auto", clientVisible: teams ? "1" : "0" });
        added.push(d.id);
      } catch (e) {
        toast(e instanceof ApiError ? `${f.name} : ${e.message}` : `${f.name} : envoi impossible`, true);
      }
    }
    setUploading("");
    if (added.length) {
      docs.reload();
      setAttachments((cur) => [...new Set([...cur, ...added])]);
      toast(added.length > 1 ? `${added.length} pièces jointes ajoutées` : "Pièce jointe ajoutée");
    }
  };
  const drop = useFileDrop((fs) => void attachFiles(fs), !discussion.canPost || !!uploading);

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "nearest" });
  }, [messages.data?.length]);

  // Relecture périodique des réponses Teams (filet de sécurité des notifications Microsoft).
  useEffect(() => {
    if (!teams) return;
    const t = window.setInterval(() => messages.reload(), 30000);
    return () => window.clearInterval(t);
  }, [teams, messages]);

  const send = async () => {
    const text = body.trim();
    if (!text) return;
    try {
      await run(() =>
        discussionApi.post(discussion.id, {
          body: text,
          parent: replyTo?.id ?? null,
          mentions,
          attachments,
          clientKey: key,
        }),
      );
      setBody("");
      setReplyTo(null);
      setMentions([]);
      setAttachments([]);
      setKey(newKey());
      messages.reload();
      onChanged();
    } catch {
      /* message d'erreur déjà affiché ; le texte est conservé pour réessayer (même clé : pas de doublon) */
    }
  };

  const byId = new Map((messages.data ?? []).map((m) => [m.id, m]));
  return (
    <section className="disc-thread" aria-label={discussion.title}>
      <header className="disc-h">
        <div>
          <h3>{discussion.title}</h3>
          <small className="muted">
            {discussion.project.code}
            {discussion.action ? ` · ${discussion.action.title}` : ""} · {discussion.destinationLabel}
            {teams ? ` (${discussion.teamsKindLabel})` : ""} · {discussion.participants.map((p) => p.name).join(", ")}
          </small>
        </div>
        <div className="btns">
          <AiMembers discussion={discussion} onChanged={() => { messages.reload(); onChanged(); }} />
          {discussion.teamsUrl && (
            <a className="btn sm" href={discussion.teamsUrl} target="_blank" rel="noreferrer noopener">
              Ouvrir dans Teams
            </a>
          )}
          {teams && (
            <button
              className="btn sm"
              disabled={busy}
              onClick={() =>
                void run(() => discussionApi.synchronize(discussion.id)).then(
                  (c) => {
                    if (!c) return;
                    toast(
                      c.created || c.updated || c.deleted
                        ? `Synchronisé : ${c.created} nouveau(x), ${c.updated} modifié(s)`
                        : "Déjà à jour",
                    );
                    messages.reload();
                  },
                  () => undefined,
                )
              }
            >
              <Icon name="refresh" size={14} /> Synchroniser
            </button>
          )}
        </div>
      </header>
      {discussion.lastError && <div className="callout warn">{discussion.lastError}</div>}
      <div className="disc-msgs" role="log" aria-live="polite">
        {messages.error && <ErrorNotice error={messages.error} onRetry={messages.reload} />}
        {!messages.data && !messages.error && <Loading />}
        {messages.data?.length === 0 && <p className="muted">Aucun message. Lancez la discussion.</p>}
        {messages.data?.map((m) => (
          <DiscussionMessage
            key={m.id}
            message={m}
            parent={m.parent ? byId.get(m.parent) : undefined}
            showStatus={teams}
            onReply={setReplyTo}
            onChanged={() => {
              messages.reload();
              onChanged();
            }}
          />
        ))}
        <div ref={end} />
      </div>
      {discussion.canPost ? (
        <div className={`disc-compose dz-target${drop.dragging ? " over" : ""}`} {...drop.bind}>
          {drop.dragging && <div className="dz-overlay">⬇️ Déposez pour joindre au message</div>}
          {replyTo && (
            <div className="reply-to">
              Réponse à <b>{replyTo.author?.name ?? replyTo.externalAuthor}</b> : {replyTo.body.slice(0, 80)}
              <button className="icon-btn" aria-label="Annuler la réponse" onClick={() => setReplyTo(null)}>
                <Icon name="x" size={13} />
              </button>
            </div>
          )}
          <textarea
            className="inp"
            rows={3}
            placeholder={teams ? "Message (publié aussi dans Teams)…" : "Message interne…"}
            aria-label="Votre message"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void send();
            }}
          />
          <div className="disc-tools">
            <select
              className="inp"
              aria-label="Mentionner"
              value=""
              onChange={(e) => e.target.value && setMentions([...new Set([...mentions, Number(e.target.value)])])}
            >
              <option value="">@ Mentionner…</option>
              {discussion.participants.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <select
              className="inp"
              aria-label="Joindre un document du projet"
              value=""
              onChange={(e) => e.target.value && setAttachments([...new Set([...attachments, e.target.value])])}
            >
              <option value="">Joindre un document…</option>
              {(docs.data ?? []).map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
            <input ref={pick} type="file" multiple hidden onChange={(e) => { const fs = Array.from(e.target.files ?? []); e.target.value = ""; if (fs.length) void attachFiles(fs); }} />
            <button className="btn ghost" type="button" title="Joindre un fichier depuis l'ordinateur (ou glissez-le sur le message)"
              disabled={!!uploading} onClick={() => pick.current?.click()}>
              <Icon name="paperclip" size={14} /> Fichier
            </button>
            <button className="btn primary" disabled={busy || !body.trim()} onClick={() => void send()}>
              Envoyer
            </button>
          </div>
          {(mentions.length > 0 || attachments.length > 0) && (
            <div className="msg-meta">
              {mentions.map((id) => (
                <button key={id} className="mention" onClick={() => setMentions(mentions.filter((x) => x !== id))}>
                  @{discussion.participants.find((p) => p.id === id)?.name} ×
                </button>
              ))}
              {attachments.map((id) => (
                <button key={id} className="attach" onClick={() => setAttachments(attachments.filter((x) => x !== id))}>
                  <Icon name="paperclip" size={13} /> {docs.data?.find((d) => d.id === id)?.name} ×
                </button>
              ))}
            </div>
          )}
          <small className="muted">
            {uploading ? `${uploading} · ` : "Glissez des fichiers sur le message pour les joindre · "}Ctrl + Entrée pour envoyer. Dernière synchronisation : {fmtDate(discussion.lastSyncedAt)}
          </small>
        </div>
      ) : (
        <p className="muted">Lecture seule.</p>
      )}
    </section>
  );
}

/** Assistants IA de la discussion : le créateur en ajoute ; Maestro analyse la tâche et l'affecte à la bonne IA ou personne. */
function AiMembers({ discussion, onChanged }: { discussion: Discussion; onChanged: () => void }) {
  const ai = discussion.ai;
  const [open, setOpen] = useState(false);
  const { run, busy } = useAction();
  if (!ai || !ai.licensed) return null;
  const add = (code: string) =>
    void run(() => discussionApi.addAi(discussion.id, code), code === "maestro" ? "Maestro analyse la tâche…" : "Assistant ajouté").then(
      () => { setOpen(false); onChanged(); }, () => undefined);
  const remove = (code: string) => void run(() => discussionApi.removeAi(discussion.id, code), "Assistant retiré").then(onChanged, () => undefined);
  return (
    <div className="disc-ai">
      {ai.members.map((m) => (
        <span key={m.code} className="disc-ai-chip" style={{ ["--mate" as string]: m.color }} title={`${m.name} · ${m.role}`}>
          {m.avatar} {m.name}
          {ai.canManage && <button type="button" aria-label={`Retirer ${m.name}`} disabled={busy} onClick={() => remove(m.code)}>×</button>}
        </span>
      ))}
      {ai.canManage && ai.available.length > 0 && (
        <div className="disc-ai-add">
          <button type="button" className="btn sm" disabled={busy} onClick={() => setOpen(!open)} aria-expanded={open}>🤖 Ajouter une IA</button>
          {open && (
            <div className="disc-ai-menu" role="menu">
              {ai.available.map((m) => (
                <button key={m.code} type="button" role="menuitem" disabled={busy} onClick={() => add(m.code)} style={{ ["--mate" as string]: m.color }}>
                  <span className="disc-ai-ico">{m.avatar}</span>
                  <span><b>{m.name}</b> <small>{m.role}</small>
                    <em>{m.code === "maestro" ? "Analyse la tâche et l'affecte automatiquement à la bonne IA ou à la bonne personne." : m.mission}</em></span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function NewDiscussion({
  project,
  action,
  onClose,
  onCreated,
}: {
  project: string;
  action: string | null;
  onClose: () => void;
  onCreated: (d: Discussion) => void;
}) {
  const status = useApi(teamsApi.status);
  const people = useApi(() => calendarApi.people(project), [project]);
  const [form, setForm] = useState<DiscussionInput>({
    project,
    action,
    title: "",
    destination: "internal",
    teamsKind: "group",
    participants: [],
    message: "",
  });
  const [team, setTeam] = useState("");
  const teamsList = useApi(
    () =>
      form.destination !== "internal" && form.teamsKind === "channel" ? teamsApi.joinedTeams() : Promise.resolve([]),
    [form.destination, form.teamsKind],
  );
  const channels = useApi(() => (team ? teamsApi.channels(team) : Promise.resolve([])), [team]);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (patch: Partial<DiscussionInput>) => setForm((f) => ({ ...f, ...patch }));
  const s = status.data;
  const teamsReady = !!s?.configured && !!s?.linked;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      onCreated(
        await discussionApi.create({
          ...form,
          teamsKind: form.destination === "internal" ? "none" : form.teamsKind,
          teamId: form.teamsKind === "channel" ? team : undefined,
        }),
      );
    } catch (e) {
      if (e instanceof ApiError) setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Nouvelle discussion"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>
            Annuler
          </button>
          <button className="btn primary" onClick={() => void submit()} disabled={busy}>
            {busy ? "Création…" : "Créer"}
          </button>
        </>
      }
    >
      <div className="ev-form">
        {error && <ErrorNotice error={error} />}
        <Field id="d-title" label="Sujet">
          <input id="d-title" className="inp" value={form.title} onChange={(e) => set({ title: e.target.value })} />
        </Field>
        <fieldset className="radios">
          <legend>Destination</legend>
          {(
            [
              ["internal", "Interne PCT"],
              ["teams", "Microsoft Teams"],
              ["both", "PCT et Teams"],
            ] as [Destination, string][]
          ).map(([k, l]) => (
            <label key={k}>
              <input
                type="radio"
                name="dest"
                checked={form.destination === k}
                disabled={k !== "internal" && !teamsReady}
                onChange={() => set({ destination: k })}
              />{" "}
              {l}
            </label>
          ))}
        </fieldset>
        {!teamsReady && s && (
          <small className="muted">
            {!s.configured
              ? "Teams n'est pas activé par votre entreprise."
              : "Reliez votre compte Microsoft (page Collaboration) pour publier dans Teams."}
          </small>
        )}
        {form.destination !== "internal" && (
          <fieldset className="radios">
            <legend>Dans Teams</legend>
            {(
              [
                ["oneOnOne", "Conversation individuelle"],
                ["group", "Conversation de groupe"],
                ["channel", "Canal d'équipe"],
              ] as [TeamsKind, string][]
            ).map(([k, l]) => (
              <label key={k}>
                <input
                  type="radio"
                  name="kind"
                  checked={form.teamsKind === k}
                  disabled={k === "channel" && !s?.channels}
                  onChange={() => set({ teamsKind: k })}
                />{" "}
                {l}
              </label>
            ))}
          </fieldset>
        )}
        {form.destination !== "internal" && form.teamsKind === "channel" ? (
          <div className="grid g2">
            <Field id="d-team" label="Équipe">
              <select id="d-team" className="inp" value={team} onChange={(e) => setTeam(e.target.value)}>
                <option value="">Choisir…</option>
                {(teamsList.data ?? []).map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field id="d-channel" label="Canal">
              <select
                id="d-channel"
                className="inp"
                value={form.channelId ?? ""}
                onChange={(e) => set({ channelId: e.target.value })}
              >
                <option value="">Choisir…</option>
                {(channels.data ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        ) : (
          <Field id="d-people" label="Participants" hint="Seules les personnes ayant accès au projet sont proposées.">
            <div className="chips" id="d-people">
              {(people.data ?? []).map((p) => {
                const on = form.participants.includes(p.id);
                return (
                  <button
                    key={p.id}
                    type="button"
                    className={`chip ${on ? "on" : ""}`}
                    aria-pressed={on}
                    onClick={() =>
                      set({
                        participants: on ? form.participants.filter((x) => x !== p.id) : [...form.participants, p.id],
                      })
                    }
                  >
                    {p.name}
                  </button>
                );
              })}
            </div>
          </Field>
        )}
        <Field id="d-msg" label="Premier message (facultatif)">
          <textarea
            id="d-msg"
            className="inp"
            rows={3}
            value={form.message}
            onChange={(e) => set({ message: e.target.value })}
          />
        </Field>
      </div>
    </Modal>
  );
}
