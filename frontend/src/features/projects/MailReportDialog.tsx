import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import { api, API_BASE, ApiError } from "../../api/client";
import { useToast } from "../../components/ui";

type Module = { code: string; icon: string; label: string; help: string; available: boolean };
type Member = { name: string; email: string; role: string };
type DocRef = { id: string; name: string; project: string; size: number; type: string };
type Hist = {
  id: string; at: string; by: string; to: string[]; cc: string[]; subject: string; projects: string[]; modules: string[];
  attachments: string[]; mode: string; status: string; error?: string;
};
type Options = {
  modules: Module[]; defaults: string[]; members: Member[]; documents: DocRef[]; channel: boolean; subject: string;
  projects: { id: string; name: string; code: string }[]; history: Hist[];
};
type EvoPoint = { week: string; planned: number | null; real: number | null };

const EMAIL = /^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$/;
const size = (n: number) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} Mo` : `${Math.max(1, Math.round(n / 1024))} Ko`);
function cookie(name: string) {
  return document.cookie.split("; ").find((c) => c.startsWith(`${name}=`))?.split("=")[1];
}

/** SVG (chaîne ou élément) → PNG data URL, fond blanc. */
export async function svgToPng(svg: string | SVGSVGElement, width: number, height: number, scale = 2): Promise<string> {
  const xml = typeof svg === "string" ? svg : new XMLSerializer().serializeToString(svg);
  const img = new Image();
  img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(xml)}`;
  await new Promise((r, j) => ((img.onload = r), (img.onerror = j)));
  const c = document.createElement("canvas");
  c.width = width * scale;
  c.height = height * scale;
  const g = c.getContext("2d")!;
  g.fillStyle = "#fff";
  g.fillRect(0, 0, c.width, c.height);
  g.drawImage(img, 0, 0, c.width, c.height);
  return c.toDataURL("image/png");
}

/** Courbe d'évolution prévu / réel (SVG autonome, pour l'e-mail). */
export function evolutionSvg(points: EvoPoint[], title: string): string {
  const W = 720, H = 240, L = 40, R = 16, T = 34, B = 30;
  const n = Math.max(1, points.length - 1);
  const x = (i: number) => L + (i / n) * (W - L - R);
  const y = (v: number) => T + (1 - v / 100) * (H - T - B);
  const line = (k: "planned" | "real") =>
    points.map((p, i) => (p[k] == null ? null : `${x(i)},${y(p[k] as number)}`)).filter(Boolean).join(" ");
  const grid = [0, 25, 50, 75, 100].map((v) => `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="#e2e8f0"/><text x="${L - 6}" y="${y(v) + 4}" font-size="10" text-anchor="end" fill="#64748b">${v}%</text>`).join("");
  const step = Math.max(1, Math.ceil(points.length / 8));
  const labels = points.map((p, i) => (i % step === 0 ? `<text x="${x(i)}" y="${H - 10}" font-size="10" text-anchor="middle" fill="#64748b">${new Date(p.week).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" })}</text>` : "")).join("");
  const esc = (s: string) => s.replace(/[<&>]/g, (c) => ({ "<": "&lt;", "&": "&amp;", ">": "&gt;" })[c]!);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" font-family="Arial, sans-serif">
<rect width="${W}" height="${H}" fill="#fff"/><text x="${L}" y="18" font-size="13" font-weight="bold" fill="#0f172a">${esc(title)}</text>
<g><rect x="${W - 210}" y="8" width="12" height="4" fill="#94a3b8"/><text x="${W - 194}" y="14" font-size="11" fill="#475569">Prévu</text>
<rect x="${W - 140}" y="8" width="12" height="4" fill="#4f46e5"/><text x="${W - 124}" y="14" font-size="11" fill="#475569">Réel</text></g>
${grid}${labels}
<polyline points="${line("planned")}" fill="none" stroke="#94a3b8" stroke-width="2" stroke-dasharray="5 4"/>
<polyline points="${line("real")}" fill="none" stroke="#4f46e5" stroke-width="3"/>
${points.map((p, i) => (p.real == null ? "" : `<circle cx="${x(i)}" cy="${y(p.real)}" r="3" fill="#4f46e5"/>`)).join("")}
</svg>`;
}

/** Fenêtre « Envoyer le reporting par e-mail » : contenu, destinataires, pièces jointes, aperçu, historique. */
export function MailReportDialog({ projectIds, makeImages, onClose }: {
  projectIds: string[]; makeImages: () => Promise<Record<string, string>>; onClose: () => void;
}) {
  const toast = useToast();
  const [opt, setOpt] = useState<Options | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const [mods, setMods] = useState<string[]>([]);
  const [to, setTo] = useState<string[]>([]);
  const [cc, setCc] = useState<string[]>([]);
  const [toInput, setToInput] = useState("");
  const [ccInput, setCcInput] = useState("");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("Bonjour,\n\nVeuillez trouver ci-dessous l’état d’avancement du projet.\n\nCordialement,");
  const [att, setAtt] = useState<{ gantt: boolean; evolution: boolean; excel: string[]; documents: string[] }>({ gantt: false, evolution: false, excel: [], documents: [] });
  const [tab, setTab] = useState<"compose" | "preview" | "history">("compose");
  const [preview, setPreview] = useState("");
  const [images, setImages] = useState<Record<string, string> | null>(null);
  const [viewing, setViewing] = useState<string>("");

  useEffect(() => {
    api.get<Options>(`/mail-reports/options?ids=${projectIds.map(encodeURIComponent).join(",")}`).then((o) => {
      setOpt(o);
      setMods(o.defaults.filter((c) => o.modules.some((m) => m.code === c && m.available)));
      setSubject(o.subject);
    }, (e) => setErr(e instanceof ApiError ? e.message : "Chargement impossible."));
  }, [projectIds]);

  const imgs = async () => {
    if (images) return images;
    const r = await makeImages().catch(() => ({}));
    setImages(r);
    return r;
  };
  const addMail = (raw: string, list: string[], set: (v: string[]) => void, clear: () => void) => {
    const parts = raw.split(/[\s,;]+/).map((x) => x.trim()).filter(Boolean);
    const bad = parts.filter((p) => !EMAIL.test(p));
    if (bad.length) {
      setErr(`Adresse invalide : ${bad.join(", ")}`);
      return;
    }
    setErr("");
    set([...new Set([...list, ...parts])]);
    clear();
  };
  const body = async (mode: string) => {
    const pending = [toInput, ccInput];
    const toAll = [...to, ...pending[0].split(/[\s,;]+/).filter((x) => EMAIL.test(x))];
    const ccAll = [...cc, ...pending[1].split(/[\s,;]+/).filter((x) => EMAIL.test(x))];
    const images = await imgs();
    return { mode, projects: projectIds, modules: mods, to: toAll, cc: ccAll, subject, message, images, attach: att };
  };
  const doPreview = async () => {
    setBusy("Préparation de l’aperçu…");
    setErr("");
    try {
      const r = await api.post<{ html: string }>("/mail-reports", await body("preview"));
      setPreview(r.html);
      setTab("preview");
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Aperçu impossible.");
    } finally {
      setBusy("");
    }
  };
  const send = async () => {
    setBusy("Envoi de l’e-mail…");
    setErr("");
    try {
      const r = await api.post<Hist>("/mail-reports", await body("send"));
      toast(`E-mail envoyé à ${r.to.join(", ")}`);
      window.dispatchEvent(new Event("pct-alerts-changed"));
      onClose();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Envoi impossible.");
    } finally {
      setBusy("");
    }
  };
  const eml = async () => {
    setBusy("Préparation du brouillon…");
    setErr("");
    try {
      if (!cookie("csrftoken")) await fetch(`${API_BASE}/auth/csrf`, { credentials: "same-origin" });
      const r = await fetch(`${API_BASE}/mail-reports`, {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": decodeURIComponent(cookie("csrftoken") ?? "") },
        body: JSON.stringify(await body("eml")),
      });
      if (!r.ok) throw new ApiError(r.status, await r.json().catch(() => ({})));
      const blob = await r.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `reporting-${new Date().toISOString().slice(0, 10)}.eml`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      toast("Brouillon téléchargé : ouvrez-le pour l’envoyer depuis votre messagerie.");
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Préparation impossible.");
    } finally {
      setBusy("");
    }
  };
  const view = async (id: string) => {
    try {
      const m = await api.get<Hist & { html: string }>(`/mail-reports/${id}`);
      setViewing(m.html);
    } catch {
      setErr("E-mail introuvable.");
    }
  };

  const canSend = mods.length > 0 && (to.length > 0 || toInput.split(/[\s,;]+/).some((x) => EMAIL.test(x)));
  const docsByProject = useMemo(() => {
    const m = new Map<string, DocRef[]>();
    opt?.documents.forEach((d) => m.set(d.project, [...(m.get(d.project) ?? []), d]));
    return m;
  }, [opt]);

  return createPortal(
    <div className="scrim" onClick={() => !busy && onClose()}>
      <div className="modal mr-modal" role="dialog" aria-label="Envoyer le reporting par e-mail" onClick={(e) => e.stopPropagation()}>
        <div className="modal-h">
          <div>
            <h3 style={{ margin: 0 }}>✉️ Envoyer le reporting par e-mail</h3>
            <small className="faint">{opt?.projects.map((p) => p.name).join(" · ")}</small>
          </div>
          <button className="icon-btn" type="button" aria-label="Fermer" disabled={!!busy} onClick={onClose}>✕</button>
        </div>
        <div className="mr-tabs">
          {(["compose", "preview", "history"] as const).map((t) => (
            <button key={t} type="button" className={tab === t ? "on" : ""} onClick={() => (t === "preview" ? void doPreview() : setTab(t))}>
              {t === "compose" ? "1. Composer" : t === "preview" ? "2. Aperçu" : `Historique (${opt?.history.length ?? 0})`}
            </button>
          ))}
        </div>
        <div className="modal-b mr-body">
          {err && <div className="xi-err">⚠️ {err}</div>}
          {busy && <div className="xi-busy"><span className="xi-spin" />{busy}</div>}
          {!opt ? (
            !err && <div className="faint">Chargement…</div>
          ) : tab === "compose" ? (
            <div className="mr-grid">
              <section>
                <h4>📋 Que voulez-vous envoyer ?</h4>
                <div className="mr-tools">
                  <button className="btn ghost sm" type="button" onClick={() => setMods(opt.modules.filter((m) => m.available).map((m) => m.code))}>Tout</button>
                  <button className="btn ghost sm" type="button" onClick={() => setMods([])}>Rien</button>
                  <button className="btn ghost sm" type="button" onClick={() => setMods(opt.defaults)}>Par défaut</button>
                </div>
                <div className="mr-mods">
                  {opt.modules.map((m) => (
                    <label key={m.code} className={`mr-mod${mods.includes(m.code) ? " on" : ""}${m.available ? "" : " off"}`} title={m.available ? m.help : "Réservé aux profils autorisés à voir le budget"}>
                      <input type="checkbox" disabled={!m.available} checked={mods.includes(m.code)}
                        onChange={() => setMods((x) => (x.includes(m.code) ? x.filter((c) => c !== m.code) : [...x, m.code]))} />
                      <span className="mr-ic">{m.icon}</span>
                      <span><b>{m.label}</b><small>{m.help}</small></span>
                    </label>
                  ))}
                </div>
              </section>
              <section>
                <h4>👤 Destinataires</h4>
                <label className="mr-field">
                  À
                  <div className="mr-chips">
                    {to.map((x) => <span key={x} className="mr-chip">{x}<button type="button" aria-label={`Retirer ${x}`} onClick={() => setTo(to.filter((y) => y !== x))}>×</button></span>)}
                    <input placeholder="email@exemple.com (Entrée pour ajouter)" value={toInput} onChange={(e) => setToInput(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter" || e.key === "," || e.key === ";") { e.preventDefault(); addMail(toInput, to, setTo, () => setToInput("")); } }}
                      onBlur={() => toInput.trim() && addMail(toInput, to, setTo, () => setToInput(""))} />
                  </div>
                </label>
                <label className="mr-field">
                  Cc
                  <div className="mr-chips">
                    {cc.map((x) => <span key={x} className="mr-chip">{x}<button type="button" aria-label={`Retirer ${x}`} onClick={() => setCc(cc.filter((y) => y !== x))}>×</button></span>)}
                    <input placeholder="copie (facultatif)" value={ccInput} onChange={(e) => setCcInput(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter" || e.key === "," || e.key === ";") { e.preventDefault(); addMail(ccInput, cc, setCc, () => setCcInput("")); } }}
                      onBlur={() => ccInput.trim() && addMail(ccInput, cc, setCc, () => setCcInput(""))} />
                  </div>
                </label>
                {opt.members.length > 0 && (
                  <div className="mr-members">
                    <small className="faint">Membres du projet :</small>
                    {opt.members.map((m) => (
                      <button key={m.email} type="button" className={`mr-mem${to.includes(m.email) ? " on" : ""}`} title={m.email}
                        onClick={() => setTo(to.includes(m.email) ? to.filter((x) => x !== m.email) : [...to, m.email])}>
                        {to.includes(m.email) ? "✓ " : "+ "}{m.name}
                      </button>
                    ))}
                  </div>
                )}
                <label className="mr-field">
                  Objet
                  <input className="inp" maxLength={200} value={subject} onChange={(e) => setSubject(e.target.value)} />
                </label>
                <label className="mr-field">
                  Message d’introduction
                  <textarea className="inp" rows={4} value={message} onChange={(e) => setMessage(e.target.value)} />
                </label>
                <h4>📎 Pièces jointes</h4>
                <div className="mr-att">
                  <label><input type="checkbox" checked={att.gantt} onChange={(e) => setAtt({ ...att, gantt: e.target.checked })} /> 🗓️ Planning Gantt (image PNG)</label>
                  <label><input type="checkbox" checked={att.evolution} onChange={(e) => setAtt({ ...att, evolution: e.target.checked })} /> 📈 Courbe d’évolution (image PNG)</label>
                  {opt.projects.map((p) => (
                    <label key={p.id}>
                      <input type="checkbox" checked={att.excel.includes(p.id)}
                        onChange={() => setAtt({ ...att, excel: att.excel.includes(p.id) ? att.excel.filter((x) => x !== p.id) : [...att.excel, p.id] })} />
                      📊 Rapport Excel détaillé — {p.name}
                    </label>
                  ))}
                  {opt.projects.map((p) => (docsByProject.get(p.id) ?? []).length > 0 && (
                    <div key={`d${p.id}`} className="mr-docs">
                      <small className="faint">Documents — {p.name}</small>
                      {(docsByProject.get(p.id) ?? []).map((d) => (
                        <label key={d.id}>
                          <input type="checkbox" checked={att.documents.includes(d.id)}
                            onChange={() => setAtt({ ...att, documents: att.documents.includes(d.id) ? att.documents.filter((x) => x !== d.id) : [...att.documents, d.id] })} />
                          📄 {d.name} <span className="faint">({size(d.size)})</span>
                        </label>
                      ))}
                    </div>
                  ))}
                </div>
                {!opt.channel && (
                  <p className="mr-warn">
                    ⚠️ L’envoi direct n’est pas encore activé pour votre entreprise (Configuration › Notifications › canal e-mail).
                    Utilisez « Ouvrir dans ma messagerie » : le mail s’ouvre dans Outlook / Thunderbird, prêt à envoyer.
                  </p>
                )}
              </section>
            </div>
          ) : tab === "preview" ? (
            preview ? <iframe className="mr-preview" title="Aperçu de l’e-mail" srcDoc={preview} sandbox="" /> : <div className="faint">Aucun aperçu.</div>
          ) : viewing ? (
            <>
              <button className="btn ghost sm" type="button" onClick={() => setViewing("")}>← Retour à l’historique</button>
              <iframe className="mr-preview" title="E-mail envoyé" srcDoc={viewing} sandbox="" />
            </>
          ) : opt.history.length === 0 ? (
            <div className="empty">Aucun e-mail envoyé pour l’instant.</div>
          ) : (
            <ul className="mr-hist">
              {opt.history.map((h) => (
                <li key={h.id}>
                  <span className={`pill nodot ${h.status === "sent" ? "ok" : h.status === "failed" ? "crit" : "info"}`}>
                    {h.status === "sent" ? "Envoyé" : h.status === "failed" ? "Échec" : "Brouillon .eml"}
                  </span>
                  <div>
                    <b>{h.subject}</b>
                    <small>
                      {new Date(h.at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })} · par {h.by} · à {h.to.join(", ") || "—"}
                      {h.attachments.length ? ` · ${h.attachments.length} PJ` : ""}{h.error ? ` · ${h.error}` : ""}
                    </small>
                  </div>
                  <button className="btn ghost sm" type="button" onClick={() => void view(h.id)}>Voir</button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="modal-f">
          <span className="faint" style={{ marginRight: "auto", fontSize: 12.5 }}>{mods.length} rubrique(s) · {to.length} destinataire(s)</span>
          <button className="btn ghost" type="button" disabled={!!busy || !mods.length} onClick={() => void doPreview()}>👁 Aperçu</button>
          <button className="btn" type="button" disabled={!!busy || !mods.length} onClick={() => void eml()} title="Télécharge un brouillon .eml qui s’ouvre dans votre messagerie">
            ✉️ Ouvrir dans ma messagerie
          </button>
          <button className="btn primary" type="button" disabled={!!busy || !canSend || !opt?.channel} onClick={() => void send()}
            title={opt?.channel ? "Envoyer maintenant" : "Canal e-mail non activé"}>
            📨 Envoyer
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
