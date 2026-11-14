// Appels IA : lancement d'un appel et salle d'échange (avatar 3D, voix, sous-titres, document rédigé en direct, cartes).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { API_BASE, ApiError } from "../../api/client";
import { ErrorNotice, Loading, useAction, useToast } from "../../components/ui";
import { ocrFile, uploadProjectFile } from "../files/fileTools";
import { aiCalls, type Call, type Card, type Lobby, type Mate, type Section, type Turn } from "./api";
import { Avatar, type AvatarState } from "./Avatar";
import { canListen, canSpeak, createListener, hush, speak } from "./voice";
import "./aicall.css";

const hashFor = (projectId: string, callId?: string) => `#projets/${encodeURIComponent(projectId)}/appel-ia${callId ? `/${callId}` : ""}`;
const hhmm = (iso: string) => new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
const docUrl = (projectId: string, docId: string) => `${API_BASE}/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(docId)}`;

const callFromHash = () => window.location.hash.replace("#", "").split("/")[3] ?? "";

/** #projets/<id>/appel-ia : lancement et historique ; #projets/<id>/appel-ia/<appel> : salle d'appel. */
export function AiCallPage({ projectId, projectName }: { projectId: string; projectName: string }) {
  const [callId, setCallId] = useState(callFromHash);
  useEffect(() => {
    const on = () => setCallId(callFromHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return callId ? <CallRoom key={callId} projectId={projectId} projectName={projectName} callId={callId} /> : <CallLobby projectId={projectId} projectName={projectName} />;
}

/* ------------------------------------------------------------------ lancement */
function CallLobby({ projectId, projectName }: { projectId: string; projectName: string }) {
  const [data, setData] = useState<Lobby | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [lead, setLead] = useState("nova");
  const [extra, setExtra] = useState<string[]>([]);
  const [mode, setMode] = useState<"audio" | "video">("audio");
  const [objective, setObjective] = useState("");
  const [title, setTitle] = useState("");
  const { run, busy } = useAction();
  const load = useCallback(() => {
    aiCalls.lobby(projectId).then((d) => {
      setData(d);
      setError(null);
      const first = d.assistants.find((a) => a.canLead && a.enabled);
      if (first) setLead((l) => (d.assistants.some((a) => a.code === l && a.canLead && a.enabled) ? l : first.code));
    }, setError);
  }, [projectId]);
  useEffect(load, [load]);
  if (error) return <div className="page"><a className="lnk" href={`#projets/${encodeURIComponent(projectId)}`}>← {projectName}</a><ErrorNotice error={error instanceof ApiError ? error : new ApiError(500, {})} onRetry={load} /></div>;
  if (!data) return <Loading />;
  const leads = data.assistants.filter((a) => a.canLead);
  const others = data.assistants.filter((a) => a.code !== "maestro" && a.code !== lead);
  const chosen = data.assistants.find((a) => a.code === lead);
  const start = () =>
    run(() => aiCalls.start(projectId, { lead, assistants: extra.filter((c) => c !== lead), mode, objective, docTitle: title }), "Appel lancé")
      .then((c) => c && (window.location.hash = hashFor(projectId, c.id)), () => undefined);

  return (
    <div className="page ac-lobby">
      <div><a className="lnk" href={`#projets/${encodeURIComponent(projectId)}`}>← {projectName}</a></div>
      <div className="ph">
        <div>
          <div className="eyebrow">Assistants IA · Maestro orchestre</div>
          <h1>📞 Appels IA</h1>
          <p>Échangez à la voix ou par écrit avec un assistant : il pose les questions, rédige le document en direct et le dépose, versionné, dans le projet.</p>
        </div>
      </div>
      <div className="ac-launch card">
        <h3>Qui rédige ?</h3>
        <div className="ac-pick">
          {leads.map((a) => (
            <button key={a.code} type="button" className={`ac-mate ${lead === a.code ? "on" : ""}`} disabled={!a.enabled}
              onClick={() => setLead(a.code)} style={{ ["--mate" as string]: a.color }} title={a.enabled ? a.mission : "Non activé sur ce projet (Orchestrateur IA → paramètres)"}>
              <span className="ac-mate-ico">{a.avatar}</span>
              <span><b>{a.name}</b><small>{a.role}</small><em>{a.enabled ? `Rédige : ${a.docLabel}` : "Non activé"}</em></span>
            </button>
          ))}
        </div>
        <h3>Assistants invités <small>(Maestro est toujours présent)</small></h3>
        <div className="ac-chips">
          {others.map((a) => (
            <label key={a.code} className={`ac-chip ${a.enabled ? "" : "off"}`} title={a.enabled ? a.mission : "Non activé sur ce projet"}>
              <input type="checkbox" disabled={!a.enabled} checked={extra.includes(a.code)}
                onChange={(e) => setExtra((x) => (e.target.checked ? [...x, a.code] : x.filter((c) => c !== a.code)))} />
              {a.avatar} {a.name} <small>{a.role}</small>
            </label>
          ))}
        </div>
        <div className="ac-row">
          <label className="ac-field"><span>Objectif de l'appel</span>
            <input value={objective} onChange={(e) => setObjective(e.target.value)} placeholder={chosen?.code === "nova" ? "Rédiger les spécifications du portail…" : "Définir l'architecture cible…"} />
          </label>
          <label className="ac-field"><span>Titre du document</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={`${chosen?.docLabel ?? "Document"} – ${projectName}`} />
          </label>
        </div>
        <div className="ac-row ac-row-end">
          <div className="ac-seg" role="group" aria-label="Type d'appel">
            <button type="button" className={mode === "audio" ? "on" : ""} onClick={() => setMode("audio")}>🎙 Audio</button>
            <button type="button" className={mode === "video" ? "on" : ""} onClick={() => setMode("video")}>🎥 Vidéo</button>
          </div>
          {data.hasSpecs && lead === "nova" && <span className="ac-hint">📎 Une expression de besoin est déjà déposée : Nova proposera de partir d'elle.</span>}
          <button type="button" className="btn primary ac-go" disabled={busy || !chosen?.enabled} onClick={start}>📞 Lancer l'appel</button>
        </div>
        {!canListen() && <p className="ac-hint">Votre navigateur ne gère pas la reconnaissance vocale : l'échange se fera par écrit (Chrome ou Edge recommandés).</p>}
      </div>

      <h3 className="ac-h3">Appels du projet</h3>
      {data.calls.length === 0 ? <p className="ac-hint">Aucun appel pour l'instant.</p> : (
        <div className="ac-history">
          {data.calls.map((c) => (
            <div key={c.id} className="ac-hist card">
              <div>
                <b>{c.docTitle}</b>
                <small>{c.leadName} · {new Date(c.startedAt).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })} · {c.duration} min · {c.turns} échanges · {c.organizer}</small>
              </div>
              <span className={`pill ${c.status === "live" ? "ok" : c.stopped ? "warn" : ""}`}>{c.status === "live" ? "En cours" : c.stopped ? "Arrêté sans document" : "Clôturé"}</span>
              {c.document && <a className="btn sm" href={docUrl(projectId, c.document.id)}>⬇ {c.document.name} v0.{c.document.version}</a>}
              <a className="btn sm" href={hashFor(projectId, c.id)}>{c.status === "live" ? "Rejoindre" : "Revoir"}</a>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ salle d'appel */
function CallRoom({ projectId, projectName, callId }: { projectId: string; projectName: string; callId: string }) {
  const toast = useToast();
  const [call, setCall] = useState<Call | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(0);
  const [speaker, setSpeaker] = useState<string | null>(null);
  const [caption, setCaption] = useState("");
  const [interim, setInterim] = useState("");
  const [micOn, setMicOn] = useState(false);
  const [voiceOn, setVoiceOn] = useState(canSpeak());
  const [camOn, setCamOn] = useState(false);
  const [text, setText] = useState("");
  const [ocr, setOcr] = useState("");
  const [confirmClose, setConfirmClose] = useState(false);
  const mouth = useRef(0);
  const spoken = useRef<Set<string>>(new Set());
  const queue = useRef<Turn[]>([]);
  const talking = useRef(false);
  const voiceRef = useRef(voiceOn);
  voiceRef.current = voiceOn;
  const outbox = useRef<string[]>([]);
  const sending = useRef(false);
  const listener = useRef<ReturnType<typeof createListener>>(null);
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const chat = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const first = useRef(true);

  /* --- voix des assistants : file d'attente des tours non encore prononcés --- */
  const pump = useCallback(() => {
    if (talking.current) return;
    const next = queue.current.shift();
    if (!next) { setSpeaker(null); return; }
    talking.current = true;
    setSpeaker(next.speaker);
    setCaption(next.text);
    const done = () => { talking.current = false; setTimeout(pump, 180); };
    if (!voiceRef.current) { setTimeout(done, Math.min(4500, 900 + next.text.length * 28)); return; }
    speak(next.text, next.speaker, { onStart: () => (mouth.current = 1), onWord: () => (mouth.current = 1), onEnd: done });
  }, []);

  const absorb = useCallback((c: Call) => {
    setCall(c);
    const fresh = c.turns.filter((t) => !spoken.current.has(t.id));
    fresh.forEach((t) => spoken.current.add(t.id));
    if (first.current) {
      first.current = false;
      // À l'ouverture d'un appel tout neuf, on prononce l'accueil ; sinon on ne relit pas l'historique.
      const young = Date.now() - new Date(c.startedAt).getTime() < 90_000;
      if (!young || c.status !== "live") return;
    }
    queue.current.push(...fresh.filter((t) => t.speaker !== "user" && t.kind !== "system"));
    pump();
  }, [pump]);

  const load = useCallback(() => aiCalls.get(projectId, callId).then(absorb, setError), [projectId, callId, absorb]);
  useEffect(() => { void load(); }, [load]);

  /* --- envoi séquentiel des actions (paroles, cartes, fichiers) --- */
  const act = useCallback(async (body: Record<string, unknown>) => {
    setPending((n) => n + 1);
    try {
      absorb(await aiCalls.act(projectId, callId, body));
    } catch (e) {
      if (e instanceof ApiError) toast(e.message, true);
    } finally {
      setPending((n) => n - 1);
    }
  }, [projectId, callId, absorb, toast]);

  const flush = useCallback(async () => {
    if (sending.current) return;
    sending.current = true;
    while (outbox.current.length) {
      const t = outbox.current.shift()!;
      await act({ action: "say", text: t });
    }
    sending.current = false;
  }, [act]);

  const send = useCallback((t: string) => {
    const clean = t.trim();
    if (!clean) return;
    hush();
    queue.current = [];
    talking.current = false;
    outbox.current.push(clean);
    void flush();
  }, [flush]);

  /* --- micro --- */
  useEffect(() => {
    listener.current = createListener({
      onFinal: (t) => { setInterim(""); if (!talking.current) send(t); },
      onInterim: (t) => setInterim(talking.current ? "" : t),
      onVoice: () => undefined,
      onState: (on, err) => { setMicOn(on); if (err) toast(err, true); },
    });
    return () => { listener.current?.stop(); hush(); };
  }, [send, toast]);
  const toggleMic = () => (micOn ? listener.current?.stop() : listener.current?.start());
  const takeFloor = () => { hush(); queue.current = []; talking.current = false; setSpeaker(null); if (!micOn) listener.current?.start(); };

  /* --- caméra (vidéo de soi ; la visio entre humains arrive au lot 3) --- */
  useEffect(() => {
    if (!camOn) { stream.current?.getTracks().forEach((t) => t.stop()); stream.current = null; return; }
    navigator.mediaDevices?.getUserMedia({ video: true }).then((s) => {
      stream.current = s;
      if (video.current) video.current.srcObject = s;
    }, () => { setCamOn(false); toast("Caméra indisponible ou refusée.", true); });
    return () => { stream.current?.getTracks().forEach((t) => t.stop()); };
  }, [camOn, toast]);

  /* --- synchronisation des autres participants --- */
  useEffect(() => {
    const id = setInterval(() => { if (!sending.current && !document.hidden && call?.status === "live") void load(); }, 5000);
    return () => clearInterval(id);
  }, [load, call?.status]);
  useEffect(() => { chat.current?.scrollTo({ top: chat.current.scrollHeight, behavior: "smooth" }); }, [call?.turns.length, interim]);

  const mates = useMemo(() => Object.fromEntries((call?.assistants ?? []).map((m) => [m.code, m])) as Record<string, Mate>, [call]);
  if (error) return <div className="page"><a className="lnk" href={hashFor(projectId)}>← Appels IA</a><ErrorNotice error={error instanceof ApiError ? error : new ApiError(500, {})} onRetry={load} /></div>;
  if (!call) return <Loading />;

  const live = call.status === "live";
  const star = mates[speaker && speaker !== "user" ? speaker : call.lead] ?? mates[call.lead];
  const stageState: AvatarState = speaker === star?.code ? "speaking" : pending ? "thinking" : interim || micOn ? "listening" : "idle";
  const open = call.cards.filter((c) => c.status === "open");
  const done = call.sections.filter((s) => s.status === "draft" || s.status === "done").length;

  const upload = async (f: File) => {
    try {
      let ocrText = "";
      if (f.type.startsWith("image/")) ocrText = await ocrFile(f, f.name, setOcr);
      setOcr("Dépôt du fichier…");
      const d = await uploadProjectFile(projectId, f, { type: "auto", ...(ocrText ? { ocrText } : {}) });
      setOcr("");
      await act({ action: "file", docId: d.id });
    } catch (e) {
      setOcr("");
      toast(e instanceof Error ? e.message : "Dépôt impossible.", true);
    }
  };

  return (
    <div className={`ac-room ${live ? "" : "ac-ended"}`}>
      <header className="ac-top">
        <a className="lnk" href={hashFor(projectId)}>← Appels IA · {projectName}</a>
        <div className="ac-title">
          <span className={`ac-dot ${live ? "on" : ""}`} />
          <b>{call.docTitle}</b>
          <small>{call.mode === "video" ? "🎥 Vidéo" : "🎙 Audio"} · {call.duration} min · {call.llm ? "Claude" : "moteur local"} · {call.promptVersion}</small>
        </div>
        <div className="ac-people">
          {call.participants.map((p) => <span key={p.id} className="ac-person" title={`${p.name} · ${p.role}`}>{p.name.split(" ").map((x) => x[0]).join("").slice(0, 2)}</span>)}
          {call.assistants.map((m) => <span key={m.code} className="ac-person ai" style={{ ["--mate" as string]: m.color }} title={`${m.name} · ${m.role}`}>{m.avatar}</span>)}
        </div>
      </header>

      <div className="ac-grid">
        <section className="ac-stage" style={{ ["--mate" as string]: star?.color ?? "#4f46e5" }}>
          <div className="ac-glow" />
          {star && <Avatar key={star.code} code={star.code} color={star.color} name={star.name} state={stageState} mouth={mouth} />}
          <div className="ac-nameplate"><b>{star?.name}</b><small>{star?.role}</small>
            <span className={`ac-state ac-state-${stageState}`}>{{ speaking: "parle", thinking: "réfléchit…", listening: "écoute", idle: "en attente" }[stageState]}</span>
          </div>
          <div className="ac-tiles">
            {call.assistants.filter((m) => m.code !== star?.code).map((m) => (
              <div key={m.code} className={`ac-tile ${speaker === m.code ? "talk" : ""}`} style={{ ["--mate" as string]: m.color }}>
                <Avatar code={m.code} color={m.color} name={m.name} state={speaker === m.code ? "speaking" : "idle"} mouth={mouth} size="tile" lite />
                <span>{m.name}</span>
              </div>
            ))}
            {call.mode === "video" && (
              <div className="ac-tile ac-me">
                {camOn ? <video ref={video} autoPlay muted playsInline /> : <span className="ac-me-off">📷</span>}
                <span>Vous</span>
              </div>
            )}
          </div>
          <div className="ac-caption" aria-live="polite">
            {interim ? <><b>Vous :</b> {interim}</> : caption ? <><b>{mates[speaker ?? ""]?.name ?? ""}</b> {caption}</> : <span className="ac-muted">Parlez ou écrivez : {mates[call.lead]?.name} vous écoute.</span>}
          </div>
          {live && (
            <div className="ac-controls">
              {canListen() && <button type="button" className={`ac-ctl ${micOn ? "on" : ""}`} onClick={toggleMic} title={micOn ? "Couper le micro" : "Activer le micro"}>{micOn ? "🎙" : "🎙️"}<span>{micOn ? "Micro actif" : "Micro coupé"}</span></button>}
              <button type="button" className="ac-ctl" onClick={takeFloor} title="Interrompre l'assistant et prendre la parole">✋<span>Prendre la parole</span></button>
              {canSpeak() && <button type="button" className={`ac-ctl ${voiceOn ? "on" : ""}`} onClick={() => { if (voiceOn) hush(); setVoiceOn(!voiceOn); }} title="Voix des assistants">{voiceOn ? "🔊" : "🔇"}<span>Voix IA</span></button>}
              {call.mode === "video" && <button type="button" className={`ac-ctl ${camOn ? "on" : ""}`} onClick={() => setCamOn(!camOn)}>📷<span>Caméra</span></button>}
              <button type="button" className="ac-ctl" onClick={() => fileInput.current?.click()} title="Déposer un document que l'assistant lira">📎<span>Document</span></button>
              <button type="button" className="ac-ctl" onClick={() => send("Où en est-on ? Fais-moi un récap.")}>🧾<span>Récap</span></button>
              <button type="button" className="ac-ctl end" onClick={() => setConfirmClose(true)}>⏹<span>Terminer</span></button>
              <input ref={fileInput} type="file" hidden accept=".pdf,.doc,.docx,.xlsx,.pptx,.txt,.md,.csv,image/*"
                onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void upload(f); }} />
            </div>
          )}
          {confirmClose && live && (
            <div className="ac-confirm">
              <span>Terminer l'appel : déposer « {call.docTitle} » en brouillon dans le projet, ou arrêter sans document ?</span>
              <button type="button" className="btn primary sm" onClick={() => { setConfirmClose(false); void act({ action: "close" }); }}>Clôturer et déposer</button>
              <button type="button" className="btn sm ac-stop" onClick={() => { setConfirmClose(false); hush(); queue.current = []; void act({ action: "stop" }); }}>Arrêter sans document</button>
              <button type="button" className="btn sm" onClick={() => setConfirmClose(false)}>Continuer l'appel</button>
            </div>
          )}
          {ocr && <div className="ac-ocr">🔎 {ocr}</div>}
        </section>

        <section className="ac-talk">
          <div className="ac-chat" ref={chat}>
            {call.turns.map((t) => <Bubble key={t.id} t={t} mate={mates[t.speaker]} />)}
            {pending > 0 && <div className="ac-typing"><i /><i /><i /> {mates[call.lead]?.name} réfléchit</div>}
          </div>
          {open.length > 0 && live && (
            <div className="ac-cards">
              {open.map((c) => <CardView key={c.id} card={c} mate={mates[c.by]} onAnswer={(optionId, txt) => act({ action: "card", cardId: c.id, optionId, text: txt })} />)}
            </div>
          )}
          {live ? (
            <form className="ac-input" onSubmit={(e) => { e.preventDefault(); send(text); setText(""); }}>
              <input value={text} onChange={(e) => { setText(e.target.value); if (e.target.value.length === 1) hush(); }}
                placeholder={micOn ? "Parlez, ou écrivez ici…" : "Écrivez votre réponse…"} aria-label="Message" />
              <button className="btn primary" type="submit" disabled={!text.trim()}>Envoyer</button>
            </form>
          ) : call.document ? (
            <div className="ac-final">
              ✅ Document déposé : <a href={docUrl(projectId, call.document.id)}>⬇ {call.document.name} (v0.{call.document.version})</a>
              <a className="btn sm" href={`#projets/${encodeURIComponent(projectId)}`}>Voir le projet</a>
            </div>
          ) : call.stopped && (
            <div className="ac-final ac-final-stop">
              ⏹ Appel arrêté sans document. L'échange et le brouillon restent consultables.
              <button type="button" className="btn sm primary" disabled={pending > 0} onClick={() => void act({ action: "generate" })}>Générer le document maintenant</button>
            </div>
          )}
          <p className="ac-tip">Astuce : avec des haut-parleurs, l'assistant ne vous écoute pas pendant qu'il parle. Cliquez ✋ pour l'interrompre. Dites « récap » pour faire le point, « suivant » pour passer une question.</p>
        </section>

        <aside className="ac-doc">
          <div className="ac-doc-head">
            <div><small>{call.docLabel} · rédigé par {mates[call.lead]?.name}</small><b>{call.docTitle}</b></div>
            <div className="ac-progress" title={`${done} / ${call.sections.length} sections`}><i style={{ width: `${(done / Math.max(1, call.sections.length)) * 100}%` }} /></div>
            <small>{done} / {call.sections.length} sections · {call.files.length} fichier(s) lu(s)</small>
          </div>
          <div className="ac-sections">
            {call.sections.map((s, i) => <SectionView key={s.key} s={s} current={call.cursor === i && live} editable={live}
              onSave={(content) => act({ action: "edit", key: s.key, content })} />)}
          </div>
        </aside>
      </div>
    </div>
  );
}

function Bubble({ t, mate }: { t: Turn; mate?: Mate }) {
  if (t.kind === "system") return <div className="ac-sys">{t.text}</div>;
  const me = t.speaker === "user";
  return (
    <div className={`ac-bubble ${me ? "me" : ""} ${t.kind === "file" ? "file" : ""}`} style={{ ["--mate" as string]: mate?.color ?? "#64748b" }}>
      <span className="ac-who">{me ? t.name.split(" ").map((x) => x[0]).join("").slice(0, 2) : mate?.avatar ?? "🤖"}</span>
      <div><small>{t.name} · {hhmm(t.at)}</small><p>{t.text}</p></div>
    </div>
  );
}

function CardView({ card, mate, onAnswer }: { card: Card; mate?: Mate; onAnswer: (optionId: string, text: string) => void }) {
  const [free, setFree] = useState<string | null>(null);
  return (
    <div className={`ac-card ac-card-${card.type}`} style={{ ["--mate" as string]: mate?.color ?? "#0f172a" }}>
      <small>{mate?.avatar} {mate?.name ?? card.by} · {card.type === "invite" ? "invitation" : card.type === "validation" ? "validation" : "choix"}</small>
      <p>{card.question}</p>
      <div className="ac-opts">
        {card.options.map((o) => (
          <button key={o.id} type="button" className={`ac-opt ${o.recommended ? "rec" : ""}`} title={o.hint}
            onClick={() => (o.label === "Je précise moi-même" ? setFree("") : onAnswer(o.id, ""))}>
            {o.recommended && <em>Recommandé</em>}{o.label}{o.hint && <small>{o.hint}</small>}
          </button>
        ))}
      </div>
      {free !== null && (
        <form className="ac-free" onSubmit={(e) => { e.preventDefault(); if (free.trim()) onAnswer(card.options.at(-1)?.id ?? "", free); }}>
          <input autoFocus value={free} onChange={(e) => setFree(e.target.value)} placeholder="Votre formulation mesurable…" />
          <button className="btn sm primary" type="submit">Valider</button>
        </form>
      )}
    </div>
  );
}

function SectionView({ s, current, editable, onSave }: { s: Section; current: boolean; editable: boolean; onSave: (c: string) => void }) {
  const [edit, setEdit] = useState<string | null>(null);
  const fresh = s.updatedAt && Date.now() - new Date(s.updatedAt).getTime() < 8000;
  return (
    <div className={`ac-sec ac-sec-${s.status} ${current ? "cur" : ""} ${fresh ? "fresh" : ""}`}>
      <div className="ac-sec-h">
        <b>{s.title}</b>
        {current && <span className="pill info">en cours</span>}
        {s.status === "skipped" && <span className="pill warn">à compléter</span>}
        {editable && edit === null && <button type="button" className="ac-edit" onClick={() => setEdit(s.content)} aria-label={`Modifier ${s.title}`}>✎</button>}
      </div>
      {edit !== null ? (
        <div className="ac-sec-edit">
          <textarea value={edit} onChange={(e) => setEdit(e.target.value)} rows={Math.min(14, Math.max(4, edit.split("\n").length + 1))} />
          <div><button type="button" className="btn sm primary" onClick={() => { onSave(edit); setEdit(null); }}>Enregistrer</button>
            <button type="button" className="btn sm" onClick={() => setEdit(null)}>Annuler</button></div>
        </div>
      ) : s.content ? <p>{s.content}</p> : <p className="ac-muted">{s.question ? "En attente de l'échange." : "Rempli automatiquement pendant l'appel."}</p>}
      {s.author && s.content && <small className="ac-by">{s.author}{s.updatedAt ? ` · ${hhmm(s.updatedAt)}` : ""}</small>}
    </div>
  );
}
