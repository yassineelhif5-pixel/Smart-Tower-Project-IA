/** Comptes rendus de réunion : dépôt par tous les profils (glisser-déposer), lecture / OCR, puis validation de ce qui a été lu. */
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { api, API_BASE, ApiError } from "../../api/client";
import { DropZone } from "../../components/DropZone";
import { useToast } from "../../components/ui";
import { fetchDocBlob, isOcrable, ocrFile, uploadProjectFile } from "../files/fileTools";

type Person = { id: number; name: string; role?: string };
type MAction = {
  key: string; title: string; ownerId: number | null; ownerName: string | null; ownerRaw: string; ownerIsMember: boolean;
  due: string | null; status: string | null; source: string; confidence: number; mode: "create" | "update"; include: boolean;
  existingId?: string; existingTitle?: string; existingDue?: string | null; existingStatus?: string;
};
type Analysis = {
  meeting: { title: string; date: string | null; type: string; participants: Person[]; external: string[]; nextMeeting: string | null };
  agenda: string[]; decisions: string[]; risks: string[]; notes: string; actions: MAction[]; warnings: string[]; lines: number;
  document: { id: string; name: string; ext: string }; members: Person[]; canCreate: boolean; validator: string;
  previous?: { at: string; by: string; created: string[]; updated: string[]; proposed: number } | null;
};
type Applied = {
  createdActions: { id: string; title: string }[]; updatedActions: { id: string; title: string }[]; proposedTitles: string[];
  decisions: number; meeting: string | null; notifiedOwners: number; validator: string | null;
};
export type MinutesDoc = { id: string; name: string; ext: string; extraction?: { minutes?: { created?: string[]; updated?: string[]; proposed?: number } } & Record<string, unknown> };

const STATUSES = [["todo", "À faire"], ["doing", "En cours"], ["blocked", "Bloquée"], ["done", "Terminée"]];

/** Carte « Compte rendu de réunion » de l'onglet Documents (visible par tous les profils). */
export function MinutesCard({ projectId, internal, onUploaded }: { projectId: string; internal: boolean; onUploaded: () => void }) {
  const toast = useToast();
  const [files, setFiles] = useState<File[]>([]);
  const [runOcr, setRunOcr] = useState(true);
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState("");
  const [review, setReview] = useState<{ doc: MinutesDoc; file: File | null } | null>(null);

  const upload = async () => {
    const queue = [...files];
    let last: { doc: MinutesDoc; file: File } | null = null;
    try {
      for (const [i, f] of queue.entries()) {
        setBusy(queue.length > 1 ? `Dépôt ${i + 1}/${queue.length} : ${f.name}…` : `Dépôt de ${f.name}…`);
        const d = await uploadProjectFile(projectId, f, { type: "minutes", clientVisible: visible ? "1" : "0" });
        last = { doc: d as MinutesDoc, file: f };
      }
      toast(queue.length > 1 ? `${queue.length} comptes rendus déposés` : "Compte rendu déposé");
      setFiles([]);
      onUploaded();
      if (runOcr && last) setReview(last);
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Dépôt impossible", true);
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="mn-card">
      <div className="mn-head">
        <span className="mn-ic">📝</span>
        <div>
          <b>Compte rendu de réunion</b>
          <small>Tous les membres du projet peuvent déposer un CR (Word, PDF, PowerPoint, texte, photo ou scan).
            Smart Tower peut ensuite le lire (OCR si besoin) et vous proposer les décisions et actions à valider.</small>
        </div>
      </div>
      <DropZone multiple icon="📝" files={files} disabled={!!busy} onFiles={setFiles}
        title="Glissez le compte rendu ici" hint="ou cliquez pour choisir · 10 Mo max. par fichier"
        accept=".pdf,.doc,.docx,.odt,.ppt,.pptx,.txt,.md,.png,.jpg,.jpeg,.webp,.tif,.tiff,.bmp" />
      <div className="mn-opts">
        <label className="pj-check">
          <input type="checkbox" checked={runOcr} onChange={(e) => setRunOcr(e.target.checked)} />
          Lire le CR après le dépôt (OCR) et me proposer les actions à valider
        </label>
        {internal && (
          <label className="pj-check">
            <input type="checkbox" checked={visible} onChange={(e) => setVisible(e.target.checked)} /> Visible par le client
          </label>
        )}
        <span style={{ flex: 1 }} />
        {files.length > 0 && <button className="btn ghost sm" type="button" disabled={!!busy} onClick={() => setFiles([])}>Retirer</button>}
        <button className="btn primary" type="button" disabled={!files.length || !!busy} onClick={() => void upload()}>
          {busy ? "Dépôt…" : runOcr ? "Déposer et lire" : "Déposer"}
        </button>
      </div>
      {busy && <div className="muted" style={{ fontSize: 12.5 }}>{busy}</div>}
      {review && (
        <MinutesDialog projectId={projectId} doc={review.doc} file={review.file}
          onClose={() => setReview(null)} onDone={() => { setReview(null); onUploaded(); }} />
      )}
    </div>
  );
}

/** Lecture puis validation d'un CR déposé. `file` : fichier local (évite de le retélécharger pour l'OCR). */
export function MinutesDialog({ projectId, doc, file, onClose, onDone }: {
  projectId: string; doc: MinutesDoc; file?: File | null; onClose: () => void; onDone: () => void;
}) {
  const toast = useToast();
  const base = `/projects/${encodeURIComponent(projectId)}/minutes/${encodeURIComponent(doc.id)}`;
  const [step, setStep] = useState<"read" | "check" | "done">("read");
  const [progress, setProgress] = useState("Lecture du compte rendu…");
  const [a, setA] = useState<Analysis | null>(null);
  const [text, setText] = useState("");
  const [textSource, setTextSource] = useState("");
  const [showText, setShowText] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<Applied | null>(null);
  const [newDecision, setNewDecision] = useState("");
  const [extName, setExtName] = useState("");

  const analyse = async (ocrText?: string, source?: string) => {
    const r = await api.post<Analysis>(`${base}/analyse`, ocrText ? { ocrText, source } : {});
    setA(r);
    setStep("check");
  };

  const runOcr = async () => {
    setStep("read");
    setError("");
    try {
      const blob = file ?? (await fetchDocBlob(projectId, doc.id));
      const t = await ocrFile(blob, doc.name.includes(".") ? doc.name : `${doc.name}.${doc.ext}`, setProgress);
      setText(t);
      setTextSource("OCR (Tesseract)");
      setShowText(true); // l'utilisateur contrôle d'abord le texte reconnu
      setProgress("Analyse du texte reconnu…");
      await analyse(t);
    } catch (e) {
      setError(e instanceof Error ? e.message : "OCR impossible");
      setStep("check");
    }
  };

  // 1. Lecture : texte du fichier ; s'il est vide (scan, photo, PDF image), OCR dans le navigateur.
  useEffect(() => {
    let off = false;
    (async () => {
      try {
        const t = await api.get<{ text: string; extraction: { source?: string } }>(
          `/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(doc.id)}?text=1`);
        if (off) return;
        setText(t.text);
        setTextSource(t.extraction?.source ?? "texte du fichier");
        if (t.text.trim().length < 40 && isOcrable(`${doc.name}.${doc.ext}`)) {
          await runOcr();
        } else {
          await analyse();
        }
      } catch (e) {
        if (!off) {
          setError(e instanceof ApiError ? e.message : "Lecture impossible");
          setStep("check");
        }
      }
    })();
    return () => { off = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc.id]);

  const upd = (key: string, patch: Partial<MAction>) => a && setA({ ...a, actions: a.actions.map((x) => (x.key === key ? { ...x, ...patch } : x)) });
  const kept = a?.actions.filter((x) => x.include && x.title.trim()) ?? [];

  const apply = async () => {
    if (!a) return;
    setSaving(true);
    try {
      const r = await api.post<Applied>(`${base}/apply`, {
        meeting: {
          title: a.meeting.title, date: a.meeting.date, type: a.meeting.type, nextMeeting: a.meeting.nextMeeting,
          participants: a.meeting.participants.map((p) => p.id), external: a.meeting.external,
        },
        agenda: a.agenda, decisions: a.decisions, risks: a.risks, notes: a.notes,
        actions: a.actions.map((x) => ({
          title: x.title, owner: x.ownerId, due: x.due, status: x.status, include: x.include, mode: x.mode,
          existingId: x.existingId, existingTitle: x.existingTitle, source: x.source,
        })),
      });
      setResult(r);
      setStep("done");
      window.dispatchEvent(new Event("pct-alerts-changed"));
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Enregistrement impossible", true);
    } finally {
      setSaving(false);
    }
  };

  const list = (field: "decisions" | "risks" | "agenda", label: string, icon: string) => a && (
    <section className="mn-sec">
      <h4>{icon} {label} <span className="faint">({a[field].length})</span></h4>
      {a[field].length === 0 && <div className="faint" style={{ fontSize: 12.5 }}>Aucun élément repéré.</div>}
      {a[field].map((d, i) => (
        <div key={i} className="mn-li">
          <input className="inp" value={d} onChange={(e) => setA({ ...a, [field]: a[field].map((x, j) => (j === i ? e.target.value : x)) })} />
          <button className="btn ghost sm" type="button" title="Retirer" onClick={() => setA({ ...a, [field]: a[field].filter((_, j) => j !== i) })}>✕</button>
        </div>
      ))}
      {field === "decisions" && (
        <form className="mn-li" onSubmit={(e) => { e.preventDefault(); if (newDecision.trim()) { setA({ ...a, decisions: [...a.decisions, newDecision.trim()] }); setNewDecision(""); } }}>
          <input className="inp" placeholder="+ Ajouter une décision…" value={newDecision} onChange={(e) => setNewDecision(e.target.value)} />
        </form>
      )}
    </section>
  );

  return createPortal(
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && !saving && onClose()}>
      <div className="modal mn-modal" role="dialog" aria-label="Lecture du compte rendu">
        <header className="mn-top">
          <div>
            <small className="faint">Compte rendu de réunion</small>
            <h3>{doc.name}</h3>
          </div>
          <ol className="mn-steps">
            <li className={step === "read" ? "on" : "ok"}>1. Lecture</li>
            <li className={step === "check" ? "on" : step === "done" ? "ok" : ""}>2. Vérification</li>
            <li className={step === "done" ? "on" : ""}>3. Enregistré</li>
          </ol>
          <button className="btn ghost sm" type="button" onClick={onClose} disabled={saving}>✕</button>
        </header>

        <div className="mn-body">
          {step === "read" && (
            <div className="mn-wait"><span className="spinner" /> {progress}</div>
          )}

          {step === "check" && (
            <>
              {error && <div className="mn-warn">⚠️ {error}</div>}
              {a?.previous && (
                <div className="mn-info">Ce CR a déjà été traité le {new Date(a.previous.at).toLocaleString("fr-FR")} par {a.previous.by}
                  {" "}({a.previous.created.length} action(s) créée(s)). Une nouvelle validation crée une nouvelle réunion ; les actions déjà suivies sont proposées en mise à jour.</div>
              )}
              {a?.warnings.map((w) => <div key={w} className="mn-warn">⚠️ {w}</div>)}

              <section className="mn-sec mn-text">
                <h4>
                  🔎 Texte lu <span className="faint">({textSource || "—"}, {text.split(/\s+/).filter(Boolean).length} mots)</span>
                  <span style={{ flex: 1 }} />
                  <button className="btn ghost sm" type="button" onClick={() => setShowText(!showText)}>{showText ? "Masquer" : "Vérifier / corriger le texte"}</button>
                  {isOcrable(`${doc.name}.${doc.ext}`) && (
                    <button className="btn sm" type="button" onClick={() => void runOcr()}>🔁 Relancer l'OCR</button>
                  )}
                </h4>
                {showText && (
                  <>
                    <textarea className="inp mn-raw" value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
                    <div className="mn-li" style={{ justifyContent: "flex-end" }}>
                      <small className="faint" style={{ flex: 1 }}>Corrigez les erreurs de lecture puis relancez l'analyse : les propositions ci-dessous seront recalculées.</small>
                      <button className="btn sm primary" type="button" onClick={() => { setStep("read"); setProgress("Analyse du texte corrigé…"); setTextSource("texte vérifié"); void analyse(text, "Texte vérifié par l'utilisateur").catch(() => setStep("check")); }}>
                        Analyser ce texte
                      </button>
                    </div>
                  </>
                )}
              </section>

              {a && (
                <>
                  <section className="mn-sec">
                    <h4>📅 Réunion</h4>
                    <div className="mn-grid">
                      <label>Titre<input className="inp" value={a.meeting.title} onChange={(e) => setA({ ...a, meeting: { ...a.meeting, title: e.target.value } })} /></label>
                      <label>Type<input className="inp" value={a.meeting.type} onChange={(e) => setA({ ...a, meeting: { ...a.meeting, type: e.target.value } })} /></label>
                      <label>Date<input className="inp" type="date" value={a.meeting.date ?? ""} onChange={(e) => setA({ ...a, meeting: { ...a.meeting, date: e.target.value || null } })} /></label>
                      <label>Prochaine réunion<input className="inp" type="date" value={a.meeting.nextMeeting ?? ""} onChange={(e) => setA({ ...a, meeting: { ...a.meeting, nextMeeting: e.target.value || null } })} /></label>
                    </div>
                    <div className="mn-people">
                      <small className="faint">Participants :</small>
                      {a.members.map((m) => {
                        const on = a.meeting.participants.some((p) => p.id === m.id);
                        return (
                          <button key={m.id} type="button" className={`mn-chip${on ? " on" : ""}`}
                            onClick={() => setA({ ...a, meeting: { ...a.meeting, participants: on ? a.meeting.participants.filter((p) => p.id !== m.id) : [...a.meeting.participants, m] } })}>
                            {on ? "✓ " : ""}{m.name}
                          </button>
                        );
                      })}
                      {a.meeting.participants.filter((p) => !a.members.some((m) => m.id === p.id)).map((p) => (
                        <span key={p.id} className="mn-chip on">✓ {p.name}</span>
                      ))}
                      {a.meeting.external.map((x) => (
                        <button key={x} type="button" className="mn-chip ext" title="Participant externe : cliquer pour retirer"
                          onClick={() => setA({ ...a, meeting: { ...a.meeting, external: a.meeting.external.filter((y) => y !== x) } })}>{x} ✕</button>
                      ))}
                      <form onSubmit={(e) => { e.preventDefault(); if (extName.trim()) { setA({ ...a, meeting: { ...a.meeting, external: [...a.meeting.external, extName.trim()] } }); setExtName(""); } }}>
                        <input className="inp mn-ext" placeholder="+ externe" value={extName} onChange={(e) => setExtName(e.target.value)} />
                      </form>
                    </div>
                  </section>

                  {list("decisions", "Décisions", "✅")}

                  <section className="mn-sec">
                    <h4>
                      📌 Actions <span className="faint">({kept.length} retenue(s) sur {a.actions.length})</span>
                      <span style={{ flex: 1 }} />
                      <button className="btn ghost sm" type="button"
                        onClick={() => setA({ ...a, actions: [...a.actions, { key: `n${Date.now()}`, title: "", ownerId: null, ownerName: null, ownerRaw: "", ownerIsMember: false, due: null, status: null, source: "", confidence: 100, mode: "create", include: true }] })}>
                        + Ajouter une action
                      </button>
                    </h4>
                    {a.actions.length === 0 ? (
                      <div className="faint" style={{ fontSize: 12.5 }}>Aucune action repérée. Ajoutez-les à la main si besoin.</div>
                    ) : (
                      <div className="mn-actions">
                        {a.actions.map((x) => (
                          <div key={x.key} className={`mn-act${x.include ? "" : " off"}`}>
                            <input type="checkbox" checked={x.include} aria-label="Retenir cette action" onChange={(e) => upd(x.key, { include: e.target.checked })} />
                            <div className="mn-act-main">
                              <input className="inp" value={x.title} placeholder="Libellé de l'action" onChange={(e) => upd(x.key, { title: e.target.value })} />
                              <div className="mn-act-meta">
                                {x.mode === "update" ? (
                                  <span className="pill nodot info" title={x.existingTitle}>Mise à jour de {x.existingId}</span>
                                ) : (
                                  <span className="pill nodot ok">Nouvelle</span>
                                )}
                                {x.source && <span className="faint mn-src" title={x.source}>« {x.source.length > 90 ? `${x.source.slice(0, 90)}…` : x.source} »</span>}
                                {x.confidence < 70 && <span className="pill nodot warn" title="Responsable ou échéance non trouvés">à vérifier</span>}
                              </div>
                            </div>
                            <select className="inp" value={x.ownerId ?? ""} aria-label="Responsable" onChange={(e) => upd(x.key, { ownerId: e.target.value ? Number(e.target.value) : null })}>
                              <option value="">{x.ownerRaw ? `? ${x.ownerRaw}` : "Non affectée"}</option>
                              {a.members.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
                              {x.ownerId && !a.members.some((m) => m.id === x.ownerId) && <option value={x.ownerId}>{x.ownerName} (hors projet)</option>}
                            </select>
                            <input className="inp" type="date" value={x.due ?? ""} aria-label="Échéance" onChange={(e) => upd(x.key, { due: e.target.value || null })} />
                            <select className="inp" value={x.status ?? ""} aria-label="Statut" onChange={(e) => upd(x.key, { status: e.target.value || null })}>
                              <option value="">{x.mode === "update" ? "Statut inchangé" : "À faire"}</option>
                              {STATUSES.map(([c, l]) => <option key={c} value={c}>{l}</option>)}
                            </select>
                          </div>
                        ))}
                      </div>
                    )}
                  </section>

                  {list("risks", "Risques / points de vigilance", "⚠️")}
                  {a.agenda.length > 0 && list("agenda", "Ordre du jour", "🗒️")}

                  <section className="mn-sec">
                    <h4>📝 Notes de réunion</h4>
                    <textarea className="inp" rows={4} value={a.notes} onChange={(e) => setA({ ...a, notes: e.target.value })} />
                  </section>
                </>
              )}
            </>
          )}

          {step === "done" && result && (
            <div className="mn-done">
              <div className="mn-done-ic">✅</div>
              <h3>Compte rendu enregistré</h3>
              <ul>
                <li>Réunion enregistrée{result.meeting ? ` (${result.meeting})` : ""} avec {result.decisions} décision(s).</li>
                {result.createdActions.length > 0 && <li>{result.createdActions.length} action(s) créée(s) : {result.createdActions.map((t) => t.id).join(", ")}.</li>}
                {result.updatedActions.length > 0 && <li>{result.updatedActions.length} action(s) mise(s) à jour : {result.updatedActions.map((t) => t.id).join(", ")}.</li>}
                {result.proposedTitles.length > 0 && <li>{result.proposedTitles.length} action(s) envoyée(s) à {result.validator ?? "le chef de projet"} pour validation.</li>}
                {result.notifiedOwners > 0 && <li>{result.notifiedOwners} responsable(s) notifié(s).</li>}
              </ul>
            </div>
          )}
        </div>

        <footer className="mn-foot">
          {step === "check" && a ? (
            <>
              <a className="btn ghost sm" href={`${API_BASE}/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(doc.id)}?inline=1`} target="_blank" rel="noreferrer">Ouvrir le CR</a>
              <span style={{ flex: 1 }} />
              <button className="btn" type="button" onClick={onClose} disabled={saving}>Plus tard</button>
              <button className="btn primary" type="button" disabled={saving} onClick={() => void apply()}>
                {saving ? "Enregistrement…" : a.canCreate
                  ? `Valider${kept.length ? ` et enregistrer ${kept.length} action(s)` : " le compte rendu"}`
                  : `Envoyer à ${a.validator} pour validation`}
              </button>
            </>
          ) : step === "done" ? (
            <button className="btn primary" type="button" onClick={onDone}>Fermer</button>
          ) : (
            <button className="btn" type="button" onClick={onClose}>Annuler</button>
          )}
        </footer>
      </div>
    </div>,
    document.body,
  );
}
